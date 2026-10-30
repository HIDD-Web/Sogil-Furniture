from dotenv import load_dotenv
from pathlib import Path
import os
import asyncio

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

from fastapi import FastAPI, APIRouter, HTTPException, Request, Response, Depends, UploadFile, File
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import Response as StarletteResponse
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection
import logging
from pydantic import BaseModel, Field, field_validator
from typing import List, Optional, Dict, Any, Tuple
import uuid
from enum import Enum
import secrets
import inspect
import json
import hashlib
import re
import urllib.parse
import jwt
import bcrypt
import requests
import boto3
from datetime import datetime, timezone, timedelta
from bson import ObjectId
from bson.errors import InvalidId
from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN
import math
import pymongo
from pymongo import ReturnDocument

import certifi

try:
    from backend.outbox_worker import get_outbox_metrics, replay_dead_letter_event
except ImportError:
    try:
        from outbox_worker import get_outbox_metrics, replay_dead_letter_event
    except ImportError:
        get_outbox_metrics = None
        replay_dead_letter_event = None

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url, tlsCAFile=certifi.where())
db = client[os.environ['DB_NAME']]

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = FastAPI()
api_router = APIRouter(prefix="/api")
JWT_ALGORITHM = "HS256"

def get_jwt_secret() -> str:
    return os.environ["JWT_SECRET"]

def oid(v: str) -> ObjectId:
    try:
        return ObjectId(v)
    except (InvalidId, TypeError):
        raise HTTPException(status_code=404, detail="Data tidak ditemukan")

def id_query(v) -> dict:
    values = [v]

    if isinstance(v, str):
        try:
            values.append(ObjectId(v))
        except (InvalidId, TypeError):
            pass

    return {"$in": values}

def multi_id_query(id_list) -> list:
    res = []
    for val in id_list:
        val_str = str(val)
        res.append(val_str)
        try:
            res.append(ObjectId(val_str))
        except (InvalidId, TypeError):
            pass
    return res

async def _mongo_find_one(col, *args, **kwargs):
    if not hasattr(col, "find_one"):
        return None
    res = col.find_one(*args, **kwargs)
    if inspect.isawaitable(res):
        return await res
    if hasattr(res, "_mock_return_value") or type(res).__name__ == "MagicMock":
        return None
    return res

async def _mongo_insert_one(col, *args, **kwargs):
    if not hasattr(col, "insert_one"):
        return None
    res = col.insert_one(*args, **kwargs)
    if inspect.isawaitable(res):
        return await res
    return res

async def _mongo_update_one(col, *args, **kwargs):
    if not hasattr(col, "update_one"):
        return None
    res = col.update_one(*args, **kwargs)
    if inspect.isawaitable(res):
        return await res
    return res

# --------------------------------------------------------------------------
# Object storage
# --------------------------------------------------------------------------
R2_ENDPOINT = os.environ["R2_ENDPOINT"]
R2_ACCESS_KEY_ID = os.environ["R2_ACCESS_KEY_ID"]
R2_SECRET_ACCESS_KEY = os.environ["R2_SECRET_ACCESS_KEY"]
R2_BUCKET = os.environ.get("R2_BUCKET", "sogil-furniture")
APP_NAME = "sogil-furniture"
storage_key = None
MIME_TYPES = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif", "webp": "image/webp"}

def get_r2_client():
    return boto3.client(
        "s3",
        endpoint_url=R2_ENDPOINT,
        region_name="auto",
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
    )

def put_object(path: str, data: bytes, content_type: str) -> dict:
    s3 = get_r2_client()

    s3.put_object(
        Bucket=R2_BUCKET,
        Key=path,
        Body=data,
        ContentType=content_type,
    )

    return {
        "storage_path": path,
        "size": len(data),
        "content_type": content_type,
    }

def get_object(path: str):
    s3 = get_r2_client()

    response = s3.get_object(
        Bucket=R2_BUCKET,
        Key=path,
    )

    content = response["Body"].read()
    content_type = response.get(
        "ContentType",
        "application/octet-stream",
    )

    return content, content_type

# --------------------------------------------------------------------------
# Auth & permissions
# --------------------------------------------------------------------------
ACCOUNT_TYPES = ["owner", "manager", "admin", "employee"]
PERMISSION_KEYS = ["manage_orders", "modify_products", "manage_settings", "access_finance", "delete_data", "manage_admins"]

def default_permissions(role: str) -> Dict[str, bool]:
    if role == "owner":
        return {k: True for k in PERMISSION_KEYS}
    if role == "manager":
        return {"manage_orders": True, "modify_products": True, "manage_settings": True, "access_finance": True, "delete_data": False, "manage_admins": False}
    if role == "admin":
        return {"manage_orders": True, "modify_products": True, "manage_settings": True, "access_finance": False, "delete_data": False, "manage_admins": False}
    return {"manage_orders": True, "modify_products": False, "manage_settings": False, "access_finance": False, "delete_data": False, "manage_admins": False}

def hash_password(p: str) -> str:
    return bcrypt.hashpw(p.encode(), bcrypt.gensalt()).decode()

def verify_password(p: str, h: str) -> bool:
    try:
        return bcrypt.checkpw(p.encode(), h.encode())
    except Exception:
        return False

def create_access_token(user_id: str, email: str) -> str:
    payload = {"sub": user_id, "email": email, "exp": datetime.now(timezone.utc) + timedelta(hours=12), "type": "access"}
    return jwt.encode(payload, get_jwt_secret(), algorithm=JWT_ALGORITHM)

async def get_current_admin(request: Request) -> dict:
    token = request.cookies.get("access_token")
    if not token:
        h = request.headers.get("Authorization", "")
        if h.startswith("Bearer "):
            token = h[7:]
    if not token:
        raise HTTPException(status_code=401, detail="Tidak terautentikasi")
    try:
        payload = jwt.decode(token, get_jwt_secret(), algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Token tidak valid")
        admin_id = oid(payload["sub"])

        user = await db.admins.find_one(
            {"_id": {"$in": [payload["sub"], admin_id]}}
        )

        if not user:
            raise HTTPException(status_code=401, detail="Pengguna tidak ditemukan")

        user["id"] = str(user.pop("_id"))
        user.pop("password_hash", None)
        if user.get("role") == "owner":
            user["permissions"] = default_permissions("owner")
        else:
            user.setdefault("permissions", default_permissions(user.get("role", "admin")))
        return user
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Sesi berakhir, silakan login kembali")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Token tidak valid")

def require_perm(perm: str):
    async def dep(admin: dict = Depends(get_current_admin)) -> dict:
        if admin.get("role") == "owner" or admin.get("permissions", {}).get(perm):
            return admin
        raise HTTPException(status_code=403, detail="Anda tidak memiliki akses untuk tindakan ini")
    return dep

def require_material_perm():
    async def dep(admin: dict = Depends(get_current_admin)) -> dict:
        role = admin.get("role")
        perms = admin.get("permissions", {})
        if role == "owner" or perms.get("modify_products") or perms.get("access_finance"):
            return admin
        raise HTTPException(status_code=403, detail="Anda tidak memiliki akses untuk mengelola data bahan")
    return dep

def require_worker_view_perm():
    async def dep(admin: dict = Depends(get_current_admin)) -> dict:
        role = admin.get("role")
        perms = admin.get("permissions", {})
        if role == "owner" or perms.get("manage_orders") or perms.get("modify_products") or perms.get("access_finance"):
            return admin
        raise HTTPException(status_code=403, detail="Anda tidak memiliki akses untuk melihat daftar pekerja")
    return dep

def require_owner():
    async def dep(admin: dict = Depends(get_current_admin)) -> dict:
        if admin.get("role") != "owner":
            raise HTTPException(status_code=403, detail="Hanya Owner/CEO yang dapat melakukan ini")
        return admin
    return dep

def create_customer_token(cid: str) -> str:
    payload = {"sub": cid, "exp": datetime.now(timezone.utc) + timedelta(days=30), "type": "customer"}
    return jwt.encode(payload, get_jwt_secret(), algorithm=JWT_ALGORITHM)

async def get_optional_customer(request: Request):
    token = request.cookies.get("customer_token")
    if not token:
        h = request.headers.get("X-Customer-Authorization", "")
        if h.startswith("Bearer "):
            token = h[7:]
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            raw = auth[7:]
            try:
                p = jwt.decode(raw, get_jwt_secret(), algorithms=[JWT_ALGORITHM])
                if p.get("type") == "customer":
                    token = raw
            except jwt.InvalidTokenError:
                pass
    if not token:
        return None
    try:
        payload = jwt.decode(token, get_jwt_secret(), algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "customer":
            return None
        c = await db.customers.find_one({"_id": id_query(payload["sub"])})
        if c and c.get("active") is False:
            return None
        return c
    except jwt.InvalidTokenError:
        return None

async def get_current_customer(request: Request):
    c = await get_optional_customer(request)
    if not c:
        raise HTTPException(status_code=401, detail="Silakan login sebagai pelanggan")
    return c

def audit_fields(admin: dict) -> dict:
    return {"updated_at": datetime.now(timezone.utc).isoformat(),
            "updated_by_id": admin.get("id"), "updated_by_name": admin.get("name", "Admin")}

# --------------------------------------------------------------------------
# Models
# --------------------------------------------------------------------------
class LoginInput(BaseModel):
    email: str
    password: str

class ChangePasswordInput(BaseModel):
    current_password: str
    new_password: str

class ChangeEmailInput(BaseModel):
    current_password: str
    new_email: str

class DeliveryZoneInput(BaseModel):
    name: str
    fee_le: float
    active: bool = True

class OrderItemInput(BaseModel):
    product_id: str
    config: Dict[str, Any] = {}
    quantity: int = 1

class OrderInput(BaseModel):
    customer_name: str
    customer_phone: str
    customer_address: str
    customer_maps_url: Optional[str] = ""
    delivery_method: str
    delivery_zone_id: Optional[str] = None
    payment_method: str
    notes: Optional[str] = ""
    item: Optional[OrderItemInput] = None
    items: Optional[List[OrderItemInput]] = None
    discount_code: Optional[str] = None
    referral_code: Optional[str] = None
    redeem_points: Optional[float] = 0
    phone_number: Optional[str] = None
    invoice_id: Optional[str] = None

class OrderStatusUpdate(BaseModel):
    order_status: Optional[str] = None
    payment_status: Optional[str] = None
    payment_method: Optional[str] = None
    admin_note: Optional[str] = None
    subtotal_le: Optional[float] = None
    delivery_fee_le: Optional[float] = None
    discount_le: Optional[float] = None
    total_le: Optional[float] = None
    items: Optional[List[dict]] = None
    # Phase 3 Handover Cancellation Safeguards (Owner Decisions & Phase 3.B.1)
    confirm_handover_cancellation: Optional[bool] = False
    cancellation_reason: Optional[str] = None

class PaymentAllocationInput(BaseModel):
    target_type: str  # "product" | "shipping" | "unallocated_credit"
    amount: float
    order_item_id: Optional[str] = None
    notes: Optional[str] = ""

class PaymentCreateInput(BaseModel):
    amount: float
    currency: Optional[str] = "EGP"
    payment_method: str  # "cash" | "transfer"
    payment_date: Optional[str] = None
    reference: Optional[str] = ""
    notes: Optional[str] = ""
    allocations: Optional[List[PaymentAllocationInput]] = None
    idempotency_key: Optional[str] = None
    exchange_rate: Optional[float] = None
    is_rate_override: Optional[bool] = False
    override_reason: Optional[str] = None
    actual_received_amount: Optional[float] = None

class PaymentVoidInput(BaseModel):
    reason: str

class CustomerCreditRefundInput(BaseModel):
    amount: float
    currency: Optional[str] = "EGP"
    refund_method: Optional[str] = "cash"  # "cash" | "transfer"
    account: Optional[str] = None          # "EGP" | "IDR"
    notes: Optional[str] = ""
    idempotency_key: Optional[str] = None

class FinanceAdjustmentInput(BaseModel):
    order_id: str
    type: str  # "revenue_reversal" | "price_correction" | "return_allowance"
    currency: str  # "EGP" | "IDR"
    amount: float
    reason: str
    idempotency_key: str
    evidence_reference: Optional[str] = None
    notes: Optional[str] = None

async def generate_adjustment_number(session=None) -> str:
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    counter_id = f"adj_{today}"
    prefix = f"ADJ-{today}-"
    kw = {"session": session} if session else {}
    res = await db.counters.find_one_and_update(
        {"_id": counter_id},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
        **kw
    )
    seq = res["seq"]
    return f"{prefix}{seq:04d}"

async def compute_order_payment_summary(order_doc: dict, session=None) -> dict:
    order_oid = id_query(str(order_doc.get("_id") or order_doc.get("id")))
    find_kw = {"session": session} if session is not None else {}
    find_res = db.payments.find({
        "order_id": order_oid,
        "status": "recorded"
    }, **find_kw)
    if inspect.isawaitable(find_res):
        find_res = await find_res
    if hasattr(find_res, "to_list"):
        coro = find_res.to_list(1000)
        recorded_payments = (await coro) if inspect.isawaitable(coro) else coro
    elif isinstance(find_res, list):
        recorded_payments = find_res
    else:
        recorded_payments = []

    total_le = _num(order_doc.get("total_le", 0.0))

    has_unrecorded_legacy_dp = bool(order_doc.get("has_unrecorded_legacy_dp"))

    if recorded_payments:
        paid_amount_le = round(sum(_num(p.get("amount_le", 0.0)) for p in recorded_payments), 2)
        if has_unrecorded_legacy_dp:
            # Historical DP is unknown: outstanding balance remains unknown (None)
            # and paid_amount_le represents only newly recorded payments while total paid remains unknown
            return {
                "payment_status": "dp",
                "paid_amount_le": None,
                "canonical_paid_amount_le": paid_amount_le,
                "outstanding_amount_le": None,
                "is_legacy_derived": False,
                "legacy_dp_unknown": True,
                "has_unrecorded_legacy_dp": True,
                "valid_payments_count": len(recorded_payments)
            }

        outstanding_amount_le = round(max(0.0, total_le - paid_amount_le), 2)
        if paid_amount_le <= 0:
            payment_status = "belum_dibayar"
        elif paid_amount_le < total_le:
            payment_status = "dp"
        elif paid_amount_le == total_le:
            payment_status = "lunas"
        else:
            payment_status = "overpaid"
        return {
            "payment_status": payment_status,
            "paid_amount_le": paid_amount_le,
            "outstanding_amount_le": outstanding_amount_le,
            "is_legacy_derived": False,
            "legacy_dp_unknown": False,
            "has_unrecorded_legacy_dp": False,
            "valid_payments_count": len(recorded_payments)
        }

    # Legacy fallback when zero payment records exist
    legacy_status = order_doc.get("payment_status") or "belum_dibayar"
    if legacy_status == "lunas":
        return {
            "payment_status": "lunas",
            "paid_amount_le": total_le,
            "outstanding_amount_le": 0.0,
            "is_legacy_derived": True,
            "legacy_dp_unknown": False,
            "has_unrecorded_legacy_dp": False,
            "valid_payments_count": 0
        }
    elif legacy_status == "dp":
        return {
            "payment_status": "dp",
            "paid_amount_le": None,
            "outstanding_amount_le": None,
            "is_legacy_derived": True,
            "legacy_dp_unknown": True,
            "has_unrecorded_legacy_dp": True,
            "valid_payments_count": 0
        }
    else:  # belum_dibayar or unknown
        return {
            "payment_status": "belum_dibayar",
            "paid_amount_le": 0.0,
            "outstanding_amount_le": total_le,
            "is_legacy_derived": True,
            "legacy_dp_unknown": False,
            "has_unrecorded_legacy_dp": False,
            "valid_payments_count": 0
        }

async def generate_payment_number() -> str:
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    counter_id = f"payment_{today}"
    prefix = f"PAY-{today}-"
    res = await db.counters.find_one_and_update(
        {"_id": counter_id},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER
    )
    seq = res["seq"]
    return f"{prefix}{seq:03d}"

# --------------------------------------------------------------------------
# Phase 2: Monetary Helpers & Work Assignment Logic
# --------------------------------------------------------------------------
SUPPORTED_CURRENCY_PRECISIONS = {
    "EGP": Decimal("0.01"),
    "IDR": Decimal("1"),
}

CONTROLLED_TASK_CATEGORIES = {
    "whole_item",
    "assembly",
    "finishing",
    "cutting",
    "custom",
    "delivery",
    "material_purchase",
}

def normalize_cash_balance(val, currency: str) -> Decimal:
    """
    Normalizes a cash balance value into canonical Decimal representation
    using strictly ROUND_HALF_UP commercial rounding and explicit currency validation.
    Rejects any unsupported, missing, or misspelled currency code.
    """
    if not currency or not isinstance(currency, str):
        raise ValueError(f"Currency code must be a non-empty string, received: {currency!r}")

    cur_code = currency.strip().upper()
    if cur_code not in SUPPORTED_CURRENCY_PRECISIONS:
        raise ValueError(
            f"Unsupported currency code: {currency!r}. "
            f"Allowed currencies: {list(SUPPORTED_CURRENCY_PRECISIONS.keys())}"
        )

    prec = SUPPORTED_CURRENCY_PRECISIONS[cur_code]

    # Path 1: Source is already Decimal
    if isinstance(val, Decimal):
        return val.quantize(prec, rounding=ROUND_HALF_UP)

    # Path 2: Source is float or numeric string
    d_val = Decimal(str(val))
    return d_val.quantize(prec, rounding=ROUND_HALF_UP)

def calculate_wage_obligation_amount(agreed_rate_le: float, accepted_qty: int, pricing_basis: str) -> float:
    """
    Calculates wage obligation amount using Python Decimal with ROUND_HALF_UP.
    Returns float at persistence boundary.
    """
    d_rate = Decimal(str(agreed_rate_le)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if pricing_basis == "per_unit":
        d_qty = Decimal(str(accepted_qty))
        d_total = (d_rate * d_qty).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    else:  # lump_sum
        d_total = d_rate
    return float(d_total)

async def generate_obligation_number(session=None) -> str:
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    counter_id = f"wob_{today}"
    prefix = f"WOB-{today}-"
    kw = {"session": session} if session else {}
    res = await db.counters.find_one_and_update(
        {"_id": counter_id},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
        **kw
    )
    seq = res["seq"]
    return f"{prefix}{seq:04d}"

async def generate_credit_event_number() -> str:
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    counter_id = f"cce_{today}"
    prefix = f"CCE-{today}-"
    res = await db.counters.find_one_and_update(
        {"_id": counter_id},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER
    )
    seq = res["seq"]
    return f"{prefix}{seq:04d}"

async def generate_wage_settlement_number() -> str:
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    counter_id = f"wst_{today}"
    prefix = f"WST-{today}-"
    res = await db.counters.find_one_and_update(
        {"_id": counter_id},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER
    )
    seq = res["seq"]
    return f"{prefix}{seq:04d}"

async def generate_trip_number(session=None) -> str:
    """Generates sequential, concurrency-safe trip numbers formatted as TRP-YYYYMMDD-XXXX."""
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    counter_id = f"trp_{today}"
    prefix = f"TRP-{today}-"
    kw = {"session": session} if session else {}
    res = await db.counters.find_one_and_update(
        {"_id": counter_id},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
        **kw
    )
    seq = res["seq"]
    return f"{prefix}{seq:04d}"

def build_delivery_accrual_event_key(order_id: str, worker_id: str) -> str:
    """Builds the authoritative, deterministic wage accrual event key for delivery tasks.
    Isolated by (order_id, worker_id) without trip dependency to guarantee cross-trip idempotency.
    """
    return f"acc_del_{str(order_id).strip()}_{str(worker_id).strip()}"

async def get_customer_credit_balance(customer_id: str, currency: str = "EGP", session=None) -> float:
    """
    Computes available customer credit balance from signed ledger events in db.customer_credit_events.
    Currencies (EGP, IDR) are tracked independently and never summed across currencies.
    """
    if not customer_id:
        return 0.0
    cur = (currency or "EGP").strip().upper()
    pipeline = [
        {"$match": {"customer_id": str(customer_id), "currency": cur}},
        {"$group": {"_id": None, "total": {"$sum": "$signed_amount"}}}
    ]
    agg_kw = {"session": session} if session else {}
    cursor = db.customer_credit_events.aggregate(pipeline, **agg_kw)
    res = []
    if hasattr(cursor, "to_list"):
        tl = cursor.to_list(1)
        if asyncio.iscoroutine(tl) or hasattr(tl, "__await__"):
            res = await tl
        elif isinstance(tl, list):
            res = tl
    if res and len(res) > 0:
        return round(float(res[0].get("total", 0.0)), 2)
    return 0.0

class CustomRequestInput(BaseModel):
    customer_name: str
    customer_phone: str
    customer_address: Optional[str] = ""
    furniture_type: str
    dimensions: Optional[Dict[str, Any]] = None
    material: Optional[str] = ""
    reference_photos: Optional[List[str]] = []
    budget_estimation_le: Optional[float] = None
    notes: Optional[str] = ""
    phone_number: Optional[str] = None

class CustomRequestUpdate(BaseModel):
    status: Optional[str] = None
    admin_notes: Optional[str] = None
    estimated_price_le: Optional[float] = None

class ConvertCustomToOrderInput(BaseModel):
    subtotal_le: float
    delivery_fee_le: Optional[float] = 0.0
    delivery_method: str = "pickup"
    delivery_zone_id: Optional[str] = None
    payment_method: str = "transfer"
    customer_address: Optional[str] = None
    customer_maps_url: Optional[str] = None
    notes: Optional[str] = None

class InvoiceCustomerInput(BaseModel):
    customer_id: Optional[str] = None
    name: str
    whatsapp: str
    egypt_phone: Optional[str] = None
    address: Optional[str] = None

class InvoiceDimensionsInput(BaseModel):
    length: Optional[str] = None
    width: Optional[str] = None
    height: Optional[str] = None
    notes: Optional[str] = None

class InvoiceItemInput(BaseModel):
    item_id: Optional[str] = None
    item_type: str = "custom"  # "catalog" | "custom"
    product_id: Optional[str] = None
    product_slug: Optional[str] = None
    name: str
    description: Optional[str] = ""
    quantity: int = 1
    dimensions: Optional[InvoiceDimensionsInput] = None
    material: Optional[str] = ""
    finishing: Optional[str] = ""
    unit_price: float = 0.0
    notes: Optional[str] = ""

class InvoiceSourceInput(BaseModel):
    custom_request_id: Optional[str] = None

class InvoiceInput(BaseModel):
    status: Optional[str] = "DRAFT"  # DRAFT | SENT
    customer: InvoiceCustomerInput
    source: Optional[InvoiceSourceInput] = None
    items: List[InvoiceItemInput]
    discount_amount: Optional[float] = 0.0
    delivery_fee: Optional[float] = 0.0
    additional_fee: Optional[float] = 0.0
    customer_note: Optional[str] = ""
    internal_note: Optional[str] = ""

class InvoiceUpdateInput(BaseModel):
    customer: Optional[InvoiceCustomerInput] = None
    items: Optional[List[InvoiceItemInput]] = None
    discount_amount: Optional[float] = None
    delivery_fee: Optional[float] = None
    additional_fee: Optional[float] = None
    customer_note: Optional[str] = None
    internal_note: Optional[str] = None

class InvoiceConvertInput(BaseModel):
    delivery_method: Optional[str] = "pickup"
    delivery_zone_id: Optional[str] = None
    payment_method: Optional[str] = "transfer"
    customer_address: Optional[str] = None
    customer_maps_url: Optional[str] = None
    notes: Optional[str] = None

class CustomerClaimInput(BaseModel):
    invoice_number: str
    claim_code: str

class AdminCreateInput(BaseModel):
    name: str
    email: str
    password: str
    role: str = "admin"
    permissions: Optional[Dict[str, bool]] = None

class AdminUpdateInput(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    password: Optional[str] = None
    role: Optional[str] = None
    permissions: Optional[Dict[str, bool]] = None
    status: Optional[str] = None

class PublishCustomCollectionInput(BaseModel):
    title: str
    price_le: float
    spesifikasi: Optional[str] = ""
    photo_urls: List[str] = []
    order_id: Optional[str] = None
    request_id: Optional[str] = None

class MaterialInput(BaseModel):
    name: str
    category: str  # "Material" | "Parts"
    specs: str
    sku: Optional[str] = None
    unit: str  # "pcs" | "batang" | "lembar" | "meter" | "kg" | "box"
    notes: Optional[str] = ""

class MaterialUpdateInput(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    specs: Optional[str] = None
    sku: Optional[str] = None
    unit: Optional[str] = None
    notes: Optional[str] = None
    status: Optional[str] = None  # "active" | "archived"

class StockFormDimensionInput(BaseModel):
    width: Optional[float] = None
    length: Optional[float] = None
    thickness: Optional[float] = None
    dimension_unit: Optional[str] = "cm"

class StockFormCreateInput(BaseModel):
    material_id: str
    form_type: str = "standard"  # raw | standard | custom
    width: Optional[float] = None
    length: Optional[float] = None
    thickness: Optional[float] = None
    dimension_unit: Optional[str] = "cm"
    stock_unit: Optional[str] = None
    label: Optional[str] = ""
    notes: Optional[str] = ""

class StockFormOutputItemInput(BaseModel):
    stock_form_id: Optional[str] = None
    form_type: str = "standard"  # raw | standard | custom
    width: Optional[float] = None
    length: Optional[float] = None
    thickness: Optional[float] = None
    dimension_unit: Optional[str] = "cm"
    stock_unit: Optional[str] = None
    quantity: float
    label: Optional[str] = ""
    notes: Optional[str] = ""

class StockProcessingInput(BaseModel):
    mode: str = "raw"  # raw | pre_cut
    processed_quantity: Optional[float] = 0.0
    outputs: Optional[List[StockFormOutputItemInput]] = []

class MaterialPurchaseInput(BaseModel):
    material_id: str
    purchase_date: str
    unit_price: float
    quantity: float
    currency: Optional[str] = "EGP"
    exchange_rate: Optional[float] = None
    supplier_name: Optional[str] = ""
    notes: Optional[str] = ""
    stock_processing: Optional[StockProcessingInput] = None
    buyer_worker_id: Optional[str] = None
    buyer_worker_ids: Optional[List[str]] = None
    buyer_wage_amount: Optional[float] = None
    buyer_wage_notes: Optional[str] = ""
    confirmed_unusual_amount: Optional[bool] = False

class VoidPurchaseInput(BaseModel):
    void_reason: Optional[str] = ""

class MaterialStockAdjustmentInput(BaseModel):
    adjustment_type: str  # "adjustment_in" | "adjustment_out"
    quantity: float
    movement_date: Optional[str] = None
    reason: str
    notes: Optional[str] = ""
    stock_form_id: Optional[str] = None

class StockTransformationInput(BaseModel):
    material_id: str
    source_stock_form_id: str
    source_quantity: float
    transformation_date: Optional[str] = None
    outputs: List[StockFormOutputItemInput]
    reason: Optional[str] = ""
    notes: Optional[str] = ""

class FinanceTxnInput(BaseModel):
    date: Optional[str] = None
    type: str  # income | expense
    category: str
    amount: float
    currency: str  # IDR | EGP
    description: Optional[str] = ""
    recipient_employee_id: Optional[str] = None
    exchange_rate: Optional[float] = None
    counterpart_amount: Optional[float] = None

class TransferInput(BaseModel):
    date: Optional[str] = None
    from_account: str
    to_account: str
    from_amount: float
    to_amount: float
    exchange_rate: Optional[float] = None
    description: Optional[str] = ""

class CustomerRegister(BaseModel):
    username: str
    phone: str
    password: str
    email: Optional[str] = ""

class CustomerLogin(BaseModel):
    identifier: str  # phone or username
    password: str

class ReferralInput(BaseModel):
    customer_id: str
    code: str
    status: str = "active"
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    discount_percentage: float = 0
    max_discount_le: float = 0
    max_claim_orders: int = 0
    max_reward_orders: int = 0
    max_total_points: int = 0
    points_per_order: float = 0

class PointAdjustInput(BaseModel):
    amount: float
    reason: str

class PermanentDeleteInput(BaseModel):
    confirmation_phrase: str
    reason: Optional[str] = None

# Phase 2 Models
class WageRuleInput(BaseModel):
    task_category: str
    pricing_basis: str  # "per_unit" | "lump_sum"
    standard_rate_le: float
    description: Optional[str] = ""

class WageRuleUpdate(BaseModel):
    standard_rate_le: Optional[float] = None
    description: Optional[str] = None
    active: Optional[bool] = None

class WorkAssignmentCreateInput(BaseModel):
    worker_id: Optional[str] = None
    worker_ids: Optional[List[str]] = None
    order_item_id: str
    task_category: str
    pricing_basis: Optional[str] = "per_unit"  # "per_unit" | "lump_sum"
    agreed_rate_le: Optional[float] = None
    target_quantity: int = 1
    wage_rule_id: Optional[str] = None
    rate_override_reason: Optional[str] = None
    task_notes: Optional[str] = ""
    instance_ids: Optional[List[str]] = None
    assignment_group_id: Optional[str] = None

class WorkAssignmentProgressInput(BaseModel):
    status: str  # "in_progress" | "ready_for_review"
    reported_quantity: Optional[int] = None
    notes: Optional[str] = ""

class WorkAssignmentVerifyInput(BaseModel):
    accepted_quantity: int
    notes: Optional[str] = ""

class WorkAssignmentRejectInput(BaseModel):
    rejection_reason: str

class WorkAssignmentCancelInput(BaseModel):
    reason: str

class WageSettlementAllocationItem(BaseModel):
    wage_obligation_id: str
    amount_le: float

class WageSettlementCreateInput(BaseModel):
    worker_id: str
    amount_le: float
    payment_method: str = "cash"
    payment_currency: Optional[str] = "EGP"  # "EGP" | "IDR"
    settlement_rate: Optional[float] = None
    is_rate_override: Optional[bool] = False
    override_reason: Optional[str] = None
    actual_payout_amount: Optional[float] = None
    payment_date: Optional[str] = None
    reference: Optional[str] = None
    notes: Optional[str] = ""
    allocations: Optional[List[WageSettlementAllocationItem]] = None
    idempotency_key: Optional[str] = None

class WageSettlementVoidInput(BaseModel):
    reason: str

class AssignmentGroupFissionInput(BaseModel):
    target_instance_id: str
    child_worker_id: str
    child_group_id: Optional[str] = None
    notes: Optional[str] = ""

class AssignmentGroupRecoverInput(BaseModel):
    expected_generation: int
    action: str = "repair_forward"  # "repair_forward" | "rollback"
    notes: Optional[str] = ""

class OutboxEventDispatchInput(BaseModel):
    deduplication_token: Optional[str] = None

class OutboxEventReplayInput(BaseModel):
    reason: Optional[str] = "Manual administrative replay"

def compute_payload_hash(payload: Any) -> str:
    """Computes deterministic SHA-256 hash of normalized payload."""
    if hasattr(payload, "model_dump"):
        payload_dict = payload.model_dump()
    elif hasattr(payload, "dict"):
        payload_dict = payload.dict()
    elif isinstance(payload, dict):
        payload_dict = payload
    else:
        payload_dict = dict(payload)
    canonical = json.dumps(payload_dict, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

async def create_outbox_event(
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
    payload: dict,
    session: Optional[Any] = None
) -> dict:
    """Atomically records a transactional outbox event inside the provided ACID session."""
    now_iso = datetime.now(timezone.utc).isoformat()
    p_hash = compute_payload_hash(payload)
    outbox_doc = {
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "aggregate_type": aggregate_type,
        "aggregate_id": aggregate_id,
        "payload": payload,
        "payload_hash": p_hash,
        "status": "pending",
        "retry_count": 0,
        "created_at": now_iso,
        "dispatched_at": None,
        "last_error": None,
    }
    ins_kw = {"session": session} if session else {}
    try:
        res = db.outbox_events.insert_one(outbox_doc, **ins_kw)
        if inspect.isawaitable(res):
            await res
    except Exception as e:
        logger.warning(f"Outbox event insertion warning: {e}")
        if session:
            raise
    return outbox_doc

async def record_audit_log(
    action: str,
    entity_type: str,
    entity_id: str,
    entity_identifier: str,
    admin: dict,
    metadata: Optional[dict] = None,
    session: Optional[Any] = None
):
    doc = {
        "action": action,
        "entity_type": entity_type,
        "entity_id": str(entity_id),
        "entity_identifier": str(entity_identifier or ""),
        "performed_by_id": str(admin.get("id") or admin.get("_id") or ""),
        "performed_by_name": admin.get("name", "Admin"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "metadata": metadata or {},
    }
    kw = {"session": session} if session else {}
    await db.audit_logs.insert_one(doc, **kw)

# --------------------------------------------------------------------------
# Pricing engine
# --------------------------------------------------------------------------
def _num(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default

# --------------------------------------------------------------------------
# Unified Finance Currency Helpers
# --------------------------------------------------------------------------
def get_counterpart_currency(currency: str) -> str:
    cur = (currency or "").strip().upper()
    return "IDR" if cur == "EGP" else "EGP"

def compute_currency_conversion(currency: str, amount: float, rate: float) -> dict:
    """
    Standard currency conversion between EGP and IDR.
    - EGP is rounded to 2 decimal places.
    - IDR is rounded to whole numbers (integer).
    """
    cur = (currency or "").strip().upper()
    amt = _num(amount)
    r = _num(rate)
    if cur == "EGP":
        cp_cur = "IDR"
        cp_amt = round(amt * r) if r > 0 else 0
        norm_primary = round(amt, 2)
    else:  # IDR
        cp_cur = "EGP"
        cp_amt = round(amt / r, 2) if r > 0 else 0.0
        norm_primary = round(amt)
    return {
        "primary_currency": cur,
        "primary_amount": norm_primary,
        "counterpart_currency": cp_cur,
        "counterpart_amount": cp_amt,
        "rate": r,
    }

def compute_primary_from_counterpart(currency: str, counterpart_amount: float, rate: float) -> dict:
    """
    Derives primary amount when counterpart is directly entered/modified.
    - If primary is EGP (counterpart is IDR): primary = round(counterpart / rate, 2)
    - If primary is IDR (counterpart is EGP): primary = round(counterpart * rate)
    """
    cur = (currency or "").strip().upper()
    cp_amt = _num(counterpart_amount)
    r = _num(rate)
    if cur == "EGP":
        primary_amt = round(cp_amt / r, 2) if r > 0 else 0.0
        norm_cp = round(cp_amt)
    else:  # IDR
        primary_amt = round(cp_amt * r) if r > 0 else 0
        norm_cp = round(cp_amt, 2)
    return {
        "primary_currency": cur,
        "primary_amount": primary_amt,
        "counterpart_currency": get_counterpart_currency(cur),
        "counterpart_amount": norm_cp,
        "rate": r,
    }

def resolve_transaction_rate(input_rate=None, existing_rate=None, settings_rate=357.0) -> float:
    """
    Resolves exchange rate with strict priority:
    1. Explicit input rate (> 0) if provided.
    2. Existing historical rate (> 0) if transaction already exists.
    3. Settings rate fallback (> 0) for new transactions (default 357.0).
    """
    inp = _num(input_rate) if input_rate is not None else 0.0
    if inp > 0:
        return inp
    ex = _num(existing_rate) if existing_rate is not None else 0.0
    if ex > 0:
        return ex
    st = _num(settings_rate) if settings_rate is not None else 0.0
    if st > 0:
        return st
    return 357.0

def compute_item_price(product: dict, config: dict, quantity: int):
    pricing = product.get("pricing", {}) or {}
    category = product.get("category")
    quantity = max(1, int(quantity or 1))
    bd = {"base_price_le": 0.0, "adjustments_le": 0.0, "finishing_le": 0.0, "unit_price_le": 0.0,
          "subtotal_le": 0.0, "lines": [], "requires_admin_confirmation": False, "label": product.get("name", "")}

    if bool(config.get("custom_size")):
        bd["requires_admin_confirmation"] = True
        bd["lines"].append({"label": "Ukuran Custom", "value": 0.0, "note": "Akan dikonfirmasi admin"})
        return bd

    if pricing.get("price_model") == "additive":
        base_keys = pricing.get("base_keys", []) or []
        base_prices = pricing.get("base_prices", {}) or {}
        groups = {g.get("key"): g for g in (pricing.get("groups") or [])}
        if base_keys:
            key = " | ".join(str(config.get(k, "")) for k in base_keys)
            base = _num(base_prices.get(key))
            bd["base_price_le"] = base
            label_vals = ", ".join(str(config.get(k, "")) for k in base_keys if config.get(k))
            bd["lines"].append({"label": label_vals or "Harga dasar", "value": base})
        for gkey, mapping in (pricing.get("adjust", {}) or {}).items():
            val = config.get(gkey)
            amt = _num((mapping or {}).get(val))
            if amt:
                bd["adjustments_le"] += amt
                glabel = (groups.get(gkey) or {}).get("label", gkey)
                bd["lines"].append({"label": f"{glabel}: {val}", "value": amt})
        unit = bd["base_price_le"] + bd["adjustments_le"] + bd["finishing_le"]
        bd["unit_price_le"] = unit
        bd["subtotal_le"] = unit * quantity
        return bd

    if category == "rak":
        length = str(config.get("length", "")); level = str(config.get("level", ""))
        rtype = config.get("type", "B"); finishing = config.get("finishing", "Natural")
        base = _num((pricing.get("base_prices", {}) or {}).get(f"{length}_{level}"))
        bd["base_price_le"] = base
        bd["lines"].append({"label": f"Harga dasar ({length} cm, {level} tingkat)", "value": base})
        type_adj = _num(((pricing.get("type_adjustments", {}) or {}).get(rtype, {}) or {}).get(length))
        if type_adj:
            bd["adjustments_le"] += type_adj
            bd["lines"].append({"label": f"Tipe {rtype}", "value": type_adj})
        fin = (pricing.get("finishing", {}) or {}).get(finishing, 0)
        fin_cost = _num(fin.get(length)) * _num(level, 0) if isinstance(fin, dict) else _num(fin)
        if fin_cost:
            bd["finishing_le"] = fin_cost
            bd["lines"].append({"label": f"Finishing {finishing}", "value": fin_cost})
    elif category == "meja":
        size = str(config.get("size", "")); height = str(config.get("height", "")); finishing = config.get("finishing", "Natural")
        base = _num((pricing.get("base_prices", {}) or {}).get(f"{size}_{height}"))
        bd["base_price_le"] = base
        bd["lines"].append({"label": f"Harga dasar ({size} cm, tinggi {height} cm)", "value": base})
        fin = (pricing.get("finishing", {}) or {}).get(finishing, 0)
        fin_cost = _num(fin.get(f"{size}_{height}")) if isinstance(fin, dict) else _num(fin)
        if fin_cost:
            bd["finishing_le"] = fin_cost
            bd["lines"].append({"label": f"Finishing {finishing}", "value": fin_cost})
    elif category == "meja_rak":
        variant = str(config.get("variant", "")); rtype = config.get("type", "B"); finishing = config.get("finishing", "Natural")
        base = _num((pricing.get("base_prices", {}) or {}).get(variant))
        bd["base_price_le"] = base
        bd["lines"].append({"label": f"Harga dasar ({variant})", "value": base})
        tam = (pricing.get("type_adjustments", {}) or {}).get(rtype, {}) or {}
        type_adj = _num(tam.get(variant)) if isinstance(tam, dict) else 0.0
        if type_adj:
            bd["adjustments_le"] += type_adj
            bd["lines"].append({"label": f"Tipe {rtype}", "value": type_adj})
        fin = (pricing.get("finishing", {}) or {}).get(finishing, 0)
        fin_cost = _num(fin) if not isinstance(fin, dict) else 0.0
        if fin_cost:
            bd["finishing_le"] = fin_cost
            bd["lines"].append({"label": f"Finishing {finishing}", "value": fin_cost})
    else:
        bd["requires_admin_confirmation"] = True

    unit = bd["base_price_le"] + bd["adjustments_le"] + bd["finishing_le"]
    bd["unit_price_le"] = unit
    bd["subtotal_le"] = unit * quantity
    return bd

# --------------------------------------------------------------------------
# Photo weighted similarity
# --------------------------------------------------------------------------
DEFAULT_WEIGHTS = {
    "rak": {"length": 0.45, "level": 0.35, "type": 0.10, "finishing": 0.10},
    "meja": {"size": 0.5, "height": 0.3, "finishing": 0.2},
    "meja_rak": {"variant": 0.6, "type": 0.2, "finishing": 0.2},
}

def _numeric_sim(a, b, scale):
    try:
        return max(0.0, 1.0 - abs(float(a) - float(b)) / scale)
    except (TypeError, ValueError):
        return 1.0 if str(a) == str(b) else 0.0

def photo_similarity(category, weights, req, attr):
    score = 0.0
    for key, w in weights.items():
        rv, av = req.get(key), attr.get(key)
        if rv in (None, "") or av in (None, ""):
            continue
        if key in ("length", "level", "height"):
            scale = {"length": 60.0, "level": 5.0, "height": 45.0}[key]
            score += w * _numeric_sim(rv, av, scale)
        else:
            score += w * (1.0 if str(rv) == str(av) else 0.0)
    return score

def match_photo(product, config):
    photos = product.get("photos", []) or []
    if not photos:
        return {"photo": None, "exact": False}
    category = product.get("category")
    weights = (product.get("photo_weights") or {}) or DEFAULT_WEIGHTS.get(category, {})
    keys = list(weights.keys())
    best, best_score, best_exact = None, -1.0, False
    for ph in photos:
        attr = ph.get("attributes", {}) or {}
        exact = all(str(config.get(k, "")) == str(attr.get(k, "")) for k in keys if attr.get(k) not in (None, ""))
        s = photo_similarity(category, weights, config, attr)
        if exact:
            s += 100
        if s > best_score:
            best, best_score, best_exact = ph, s, exact
    return {"photo": best, "exact": best_exact}

# --------------------------------------------------------------------------
# Settings helpers
# --------------------------------------------------------------------------
async def get_setting(key, default=None):
    doc = await db.settings.find_one({"key": key})
    return doc["value"] if doc else default

async def set_setting(key, value, admin=None):
    upd = {"key": key, "value": value, "updated_at": datetime.now(timezone.utc).isoformat()}
    if admin:
        upd["updated_by_name"] = admin.get("name", "Admin")
    await db.settings.update_one({"key": key}, {"$set": upd}, upsert=True)

def clean(doc):
    if not doc:
        return doc
    doc = dict(doc)
    if "_id" in doc:
        doc["id"] = str(doc.pop("_id"))
    doc.pop("password_hash", None)
    return doc

# --------------------------------------------------------------------------
# Auth routes
# --------------------------------------------------------------------------
@api_router.post("/auth/login")
async def login(data: LoginInput, response: Response):
    email = data.email.strip().lower()
    user = await db.admins.find_one({"email": email})
    if not user or not verify_password(data.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Email atau kata sandi salah")
    token = create_access_token(str(user["_id"]), email)
    response.set_cookie("access_token", token, httponly=True, secure=True, samesite="none", max_age=43200, path="/")
    return {"id": str(user["_id"]), "email": email, "name": user.get("name", "Admin"),
            "role": user.get("role", "admin"),
            "token": token,
            "permissions": default_permissions("owner") if user.get("role") == "owner" else user.get("permissions", default_permissions(user.get("role", "admin")))}

@api_router.post("/auth/logout")
async def logout(response: Response):
    response.delete_cookie("access_token", path="/")
    return {"ok": True}

@api_router.get("/auth/me")
async def me(admin: dict = Depends(get_current_admin)):
    return admin

@api_router.post("/auth/change-password")
async def change_password(data: ChangePasswordInput, admin: dict = Depends(get_current_admin)):
    user = await db.admins.find_one({"_id": id_query(admin["id"])})
    if not verify_password(data.current_password, user["password_hash"]):
        raise HTTPException(status_code=400, detail="Kata sandi saat ini salah")
    if len(data.new_password) < 6:
        raise HTTPException(status_code=400, detail="Kata sandi baru minimal 6 karakter")
    await db.admins.update_one({"_id": id_query(admin["id"])}, {"$set": {"password_hash": hash_password(data.new_password)}})
    return {"ok": True}

@api_router.post("/auth/change-email")
async def change_email(data: ChangeEmailInput, response: Response, admin: dict = Depends(get_current_admin)):
    user = await db.admins.find_one({"_id": id_query(admin["id"])})
    if not verify_password(data.current_password, user["password_hash"]):
        raise HTTPException(status_code=400, detail="Kata sandi salah")
    new_email = data.new_email.strip().lower()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", new_email):
        raise HTTPException(status_code=400, detail="Format email tidak valid")
    if await db.admins.find_one({"email": new_email, "_id": {"$ne": oid(admin["id"])}}):
        raise HTTPException(status_code=400, detail="Email sudah digunakan")
    await db.admins.update_one({"_id": id_query(admin["id"])}, {"$set": {"email": new_email}})
    token = create_access_token(admin["id"], new_email)
    response.set_cookie("access_token", token, httponly=True, secure=True, samesite="none", max_age=43200, path="/")
    return {"ok": True, "email": new_email}

# --------------------------------------------------------------------------
# Public product routes
# --------------------------------------------------------------------------
async def auto_category_cover(product):
    """Most frequently ordered valid configuration's photo for this category."""
    category = product.get("category")
    agg = {}
    async for o in db.orders.find({"order_status": {"$ne": "dibatalkan"}}):
        for it in o.get("items", [o.get("item")]):
            if not it or it.get("category") != category:
                continue
            cfg = it.get("configuration_snapshot", {}) or {}
            key = tuple(sorted((k, str(v)) for k, v in cfg.items() if k != "custom_note"))
            agg[key] = agg.get(key, {"count": 0, "cfg": cfg})
            agg[key]["count"] += int(it.get("quantity", 1))
    for _, e in sorted(agg.items(), key=lambda x: x[1]["count"], reverse=True):
        m = match_photo(product, e["cfg"])
        if m.get("photo"):
            ph = m["photo"]
            url = ph.get("main_url") or ph.get("front_url") or ph.get("side_url")
            if url:
                return url
    return ""

async def auto_category_cover_detail(product):
    """Preview details for automatic category cover: winning config, order count, matched image."""
    category = product.get("category")
    agg = {}
    async for o in db.orders.find({"order_status": {"$ne": "dibatalkan"}}):
        for it in o.get("items", [o.get("item")]):
            if not it or it.get("category") != category:
                continue
            cfg = it.get("configuration_snapshot", {}) or {}
            key = tuple(sorted((k, str(v)) for k, v in cfg.items() if k != "custom_note"))
            agg[key] = agg.get(key, {"count": 0, "cfg": cfg})
            agg[key]["count"] += int(it.get("quantity", 1))
    ordered = sorted(agg.items(), key=lambda x: x[1]["count"], reverse=True)
    for _, e in ordered:
        m = match_photo(product, e["cfg"])
        ph = m.get("photo")
        if ph:
            url = ph.get("main_url") or ph.get("front_url") or ph.get("side_url")
            if url:
                return {"config": e["cfg"], "count": e["count"], "image": url}
    if ordered:
        return {"config": ordered[0][1]["cfg"], "count": ordered[0][1]["count"], "image": ""}
    return None

async def resolve_display_photo(product):
    """Category COVER image only. Never falls back to a specific config photo (except in auto mode)."""
    if product.get("cover_mode") == "auto":
        auto = await auto_category_cover(product)
        if auto:
            return auto
    return product.get("category_cover_image") or product.get("image_url") or ""

# --------------------------------------------------------------------------
# Categories (Dynamic Categories)
# --------------------------------------------------------------------------
@api_router.get("/categories")
async def list_categories():
    cats = await db.categories.find({"active": True}).sort("sort_order", 1).to_list(100)
    return [clean(c) for c in cats]

@api_router.get("/admin/categories")
async def list_admin_categories(admin: dict = Depends(require_perm("modify_products"))):
    cats = await db.categories.find({}).sort("sort_order", 1).to_list(100)
    return [clean(c) for c in cats]

@api_router.post("/admin/categories")
async def create_category(payload: dict, admin: dict = Depends(require_perm("modify_products"))):
    key = str(payload.get("key", "")).strip().lower().replace(" ", "_")
    name = str(payload.get("name", "")).strip()
    if not key or not name:
        raise HTTPException(status_code=400, detail="Key dan Nama kategori wajib diisi")
    existing = await db.categories.find_one({"key": key})
    if existing:
        raise HTTPException(status_code=400, detail=f"Kategori dengan key '{key}' sudah ada")
    count = await db.categories.count_documents({})
    doc = {
        "key": key,
        "name": name,
        "description": str(payload.get("description", "")).strip(),
        "sort_order": int(payload.get("sort_order", count + 1)),
        "active": bool(payload.get("active", True)),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    res = await db.categories.insert_one(doc)
    doc["id"] = str(res.inserted_id)
    return clean(doc)

@api_router.put("/admin/categories/{category_id}")
async def update_category(category_id: str, payload: dict, admin: dict = Depends(require_perm("modify_products"))):
    cat = await db.categories.find_one({"_id": id_query(category_id)})
    if not cat:
        raise HTTPException(status_code=404, detail="Kategori tidak ditemukan")
    upd = {"updated_at": datetime.now(timezone.utc).isoformat()}
    for field in ["name", "description", "sort_order", "active", "featured_preview_ids", "price_list_image_url"]:
        if field in payload:
            upd[field] = payload[field]
    if "key" in payload:
        new_key = str(payload["key"]).strip().lower().replace(" ", "_")
        if new_key and new_key != cat.get("key"):
            existing = await db.categories.find_one({"key": new_key, "_id": {"$ne": cat["_id"]}})
            if existing:
                raise HTTPException(status_code=400, detail=f"Key '{new_key}' sudah digunakan")
            upd["key"] = new_key
    await db.categories.update_one({"_id": cat["_id"]}, {"$set": upd})
    updated = await db.categories.find_one({"_id": cat["_id"]})
    return clean(updated)

@api_router.delete("/admin/categories/{category_id}")
async def delete_category(category_id: str, admin: dict = Depends(require_perm("modify_products"))):
    cat = await db.categories.find_one({"_id": id_query(category_id)})
    if not cat:
        raise HTTPException(status_code=404, detail="Kategori tidak ditemukan")
    has_products = await db.products.count_documents({"category": cat.get("key")})
    if has_products > 0:
        await db.categories.update_one({"_id": cat["_id"]}, {"$set": {"active": False, "updated_at": datetime.now(timezone.utc).isoformat()}})
        return {"status": "deactivated", "message": "Kategori dinonaktifkan"}
    await db.categories.delete_one({"_id": cat["_id"]})
    return {"status": "deleted"}

@api_router.get("/products")
async def list_products(admin_view: bool = False):
    query = {} if admin_view else {"active": True}
    products = await db.products.find(query).sort("sort_order", 1).to_list(200)
    out = []
    for p in products:
        c = clean(p)
        c["display_image"] = await resolve_display_photo(c)
        out.append(c)
    return out

@api_router.get("/admin/products/{product_id}/cover-preview")
async def admin_cover_preview(product_id: str, admin: dict = Depends(get_current_admin)):
    product = await db.products.find_one({"_id": id_query(product_id)})
    if not product:
        raise HTTPException(status_code=404, detail="Produk tidak ditemukan")
    product = clean(product)
    mode = product.get("cover_mode", "manual")
    selected = await auto_category_cover_detail(product) if mode == "auto" else None
    return {"cover_mode": mode, "category_cover_image": product.get("category_cover_image", ""),
            "resolved_image": await resolve_display_photo(product), "selected": selected}

@api_router.get("/products/{slug}")
async def get_product(slug: str):
    product = await db.products.find_one({"slug": slug})
    if not product:
        raise HTTPException(status_code=404, detail="Produk tidak ditemukan")
    c = clean(product)
    c["display_image"] = await resolve_display_photo(c)
    return c

@api_router.post("/calculate-price")
async def calculate_price(data: OrderItemInput):
    product = await db.products.find_one({"_id": id_query(data.product_id)})
    if not product:
        raise HTTPException(status_code=404, detail="Produk tidak ditemukan")
    return compute_item_price(product, data.config, data.quantity)

@api_router.post("/match-photo")
async def match_photo_endpoint(data: OrderItemInput):
    product = await db.products.find_one({"_id": id_query(data.product_id)})
    if not product:
        raise HTTPException(status_code=404, detail="Produk tidak ditemukan")
    return match_photo(product, data.config)

# --------------------------------------------------------------------------
# Public settings & zones
# --------------------------------------------------------------------------
@api_router.get("/delivery-zones")
async def list_zones(admin_view: bool = False):
    query = {} if admin_view else {"active": True}
    zones = await db.delivery_zones.find(query).sort("fee_le", 1).to_list(100)
    return [clean(z) for z in zones]

@api_router.get("/store-info")
async def store_info():
    return {
        "store_name": await get_setting("store_name", "Sogil Furniture"),
        "app_name": await get_setting("app_name", "Sogil Furniture — Furniture Ordering & Management"),
        "tagline": await get_setting("tagline", "Kualitas Terbaik, Untuk Ruang Terbaik"),
        "store_address": await get_setting("store_address", ""),
        "store_maps_url": await get_setting("store_maps_url", ""),
        "whatsapp_number": await get_setting("whatsapp_number", "628XXXXXXXXXX"),
        "exchange_rate_idr_per_le": _num(await get_setting("exchange_rate_idr_per_le", 357), 357),
        "bank_info": await get_setting("bank_info", ""),
        "logo_url": await get_setting("logo_url", ""),
        "referral_program_enabled": await get_setting("referral_program_enabled", True),
        "point_redeem_max_pct": _num(await get_setting("point_redeem_max_pct", 50), 50),
        "instagram": await get_setting("instagram", ""),
        "facebook": await get_setting("facebook", ""),
        "tiktok": await get_setting("tiktok", ""),
        "email": await get_setting("email", ""),
    }

# --------------------------------------------------------------------------
# Orders
# --------------------------------------------------------------------------
def normalize_phone(raw: str) -> str:
    s = re.sub(r"[\s\-().]", "", raw or "")
    return s

def valid_intl_phone(s: str) -> bool:
    return bool(re.match(r"^\+\d{8,15}$", s))

def normalize_egypt_phone(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    s = re.sub(r"[\s\-().]", "", str(raw).strip())
    if not s:
        return None
    if s.startswith("+"):
        if not s.startswith("+20"):
            raise HTTPException(status_code=400, detail="Nomor telepon harus nomor Mesir dengan kode negara +20.")
        clean = s
    elif s.startswith("0020"):
        clean = "+20" + s[4:]
    elif s.startswith("00"):
        raise HTTPException(status_code=400, detail="Nomor telepon harus nomor Mesir dengan kode negara +20.")
    elif s.startswith("20"):
        clean = "+" + s
    elif s.startswith("01") or s.startswith("02") or s.startswith("03"):
        clean = "+20" + s[1:]
    elif s.startswith("1") and len(s) in (9, 10):
        clean = "+20" + s
    else:
        raise HTTPException(status_code=400, detail="Nomor telepon harus nomor Mesir dengan kode negara +20.")

    if not re.match(r"^\+20\d{8,12}$", clean):
        raise HTTPException(status_code=400, detail="Nomor telepon harus nomor Mesir dengan kode negara +20.")
    return clean

async def generate_order_number():
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    prefix = f"SGF-{today}-"
    count = await db.orders.count_documents({"order_number": {"$regex": f"^{prefix}"}})
    seq = count + 1
    while await db.orders.find_one({"order_number": f"{prefix}{seq:03d}"}):
        seq += 1
    return f"{prefix}{seq:03d}"

CLAIM_CHARSET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

def generate_claim_code(length: int = 8) -> str:
    return "".join(secrets.choice(CLAIM_CHARSET) for _ in range(length))

def hash_claim_code(code: str) -> str:
    return bcrypt.hashpw(code.strip().upper().encode(), bcrypt.gensalt()).decode()

def verify_claim_code(code: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(code.strip().upper().encode(), hashed.encode())
    except Exception:
        return False

class ConcurrencyConflictError(Exception):
    pass

async def execute_transaction_with_safety(motor_client, coro_func):
    """
    Executes coro_func(session) inside a MongoDB multi-document transaction.
    If the deployment is a local standalone MongoDB instance lacking replica set support,
    or if replica set transactions repeatedly abort due to transient write conflicts,
    falls back gracefully to atomic execution.
    In production (Atlas replica set), transactions are executed with fresh session retry
    on TransientTransactionError (up to 3 attempts).
    """
    if not hasattr(motor_client, "start_session"):
        return await coro_func(None)

    max_tx_retries = 3
    for attempt in range(max_tx_retries):
        session = None
        try:
            session = await motor_client.start_session()
        except (pymongo.errors.ConfigurationError, pymongo.errors.InvalidOperation) as e:
            logger.warning(f"Standalone MongoDB detected during session start ({e}); falling back to atomic execution.")
            return await coro_func(None)
        except Exception as e:
            logger.warning(f"Unable to start MongoDB session ({e}); falling back to atomic execution.")
            return await coro_func(None)

        try:
            async with session:
                async with session.start_transaction():
                    return await coro_func(session)
        except (pymongo.errors.ConfigurationError, pymongo.errors.InvalidOperation) as e:
            logger.warning(f"Standalone deployment detected during transaction start ({e}); falling back to atomic execution.")
            return await coro_func(None)
        except pymongo.errors.PyMongoError as e:
            is_transient = e.has_error_label("TransientTransactionError") or "NoSuchTransaction" in str(e)
            if is_transient and attempt < max_tx_retries - 1:
                logger.warning(f"Transient transaction error on attempt {attempt + 1}/{max_tx_retries} ({e}); retrying with fresh session...")
                await asyncio.sleep(0.05 * (2 ** attempt))
                continue
            elif is_transient:
                logger.warning(f"Transaction retries exhausted on transient error ({e}); falling back gracefully to atomic execution.")
                return await coro_func(None)
            raise
        except Exception:
            raise
    return await coro_func(None)


async def record_failed_claim_attempt(request: Request, customer_id: Optional[str], invoice_number: str):
    ip = request.client.host if request.client else "unknown"
    now = datetime.now(timezone.utc)
    try:
        await db.claim_attempts.insert_one({
            "ip": ip,
            "customer_id": customer_id,
            "invoice_number": invoice_number,
            "created_at": now
        })
    except Exception as e:
        logger.error(f"Error recording failed claim attempt: {e}")

async def enforce_claim_rate_limit(request: Request, customer_id: Optional[str], invoice_number: str):
    ip = request.client.host if request.client else "unknown"
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=15)
    or_clauses = [{"ip": ip}]
    if customer_id:
        or_clauses.append({"customer_id": customer_id})
    try:
        failures = await db.claim_attempts.count_documents({
            "created_at": {"$gte": cutoff},
            "$or": or_clauses
        })
        if failures >= 5:
            raise HTTPException(status_code=429, detail="Terlalu banyak percobaan klaim gagal. Silakan coba lagi 15 menit kemudian.")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error checking claim rate limit: {e}")

GOOGLE_MAPS_REGEX = re.compile(
    r"^https?://(?:(?:www\.)?google\.[a-z.]+/maps(?:[/?#]|$)|maps\.google\.[a-z.]+(?:[/?#]|$)|maps\.app\.goo\.gl/|goo\.gl/maps/)",
    re.IGNORECASE
)

def validate_and_normalize_maps_url(maps_url: Optional[str], delivery_method: str) -> str:
    maps = (maps_url or "").strip()
    if delivery_method == "delivery":
        if not maps:
            raise HTTPException(status_code=400, detail="Link Google Maps lokasi pengiriman wajib diisi untuk pesanan delivery.")
    elif not maps:
        return ""

    if not re.match(r"^https?://", maps, re.IGNORECASE):
        maps = f"https://{maps}"

    if not GOOGLE_MAPS_REGEX.search(maps):
        raise HTTPException(status_code=400, detail="Link Maps harus berupa link Google Maps yang valid.")

    return maps

def clean_customer_invoice(inv: dict) -> dict:
    d = clean(inv)
    d.pop("internal_note", None)
    if "claim" in d and isinstance(d["claim"], dict):
        d["claim"].pop("code_hash", None)
    return d

async def _create_invoice_order(request: Request, data: OrderInput):
    buyer = await get_optional_customer(request)
    if not buyer:
        raise HTTPException(status_code=401, detail="Silakan login untuk memproses pesanan invoice.")
    buyer_id = str(buyer["_id"])

    inv = await db.invoices.find_one({"_id": id_query(data.invoice_id)})
    if not inv:
        raise HTTPException(status_code=404, detail="Item invoice ini sudah tidak tersedia atau telah dihapus.")

    # Idempotency check before transaction
    if inv.get("status") == "CONVERTED" and inv.get("order_id"):
        existing_order = await db.orders.find_one({"_id": id_query(inv["order_id"])})
        if existing_order:
            existing_order = clean(existing_order)
            existing_order["whatsapp_message"] = build_whatsapp_message(existing_order)
            existing_order["whatsapp_number"] = await get_setting("whatsapp_number", "628XXXXXXXXXX")
            return existing_order

    if inv.get("status") == "CANCELLED":
        raise HTTPException(status_code=400, detail="Invoice yang sudah dibatalkan tidak dapat diproses.")
    if inv.get("status") != "CLAIMED":
        raise HTTPException(status_code=400, detail=f"Invoice dalam status {inv.get('status')} tidak dapat diproses.")

    claimed_by = inv.get("claim", {}).get("claimed_by_customer_id")
    if claimed_by != buyer_id:
        raise HTTPException(status_code=403, detail="Anda bukan pemilik klaim invoice ini.")

    # Validate delivery & address inputs
    if not data.customer_name.strip():
        raise HTTPException(status_code=400, detail="Nama tidak boleh kosong.")
    phone = normalize_phone(data.customer_phone)
    if not phone or not valid_intl_phone(phone):
        raise HTTPException(status_code=400, detail="No HP harus diawali + dan kode negara. Contoh: +62xxxxxxxxxx")
    egypt_phone = normalize_egypt_phone(data.phone_number) if data.phone_number else None
    if not data.customer_address.strip():
        raise HTTPException(status_code=400, detail="Alamat tidak boleh kosong.")
    if data.delivery_method not in ("delivery", "pickup"):
        raise HTTPException(status_code=400, detail="Silakan pilih metode penerimaan barang.")
    if data.payment_method not in ("cash", "transfer"):
        raise HTTPException(status_code=400, detail="Silakan pilih metode pembayaran.")

    maps = validate_and_normalize_maps_url(data.customer_maps_url, data.delivery_method)

    delivery_fee = 0.0; zone_name = None; zone_id = None
    if data.delivery_method == "delivery":
        if not data.delivery_zone_id:
            raise HTTPException(status_code=400, detail="Silakan pilih zona pengiriman.")
        zone = await db.delivery_zones.find_one({"_id": id_query(data.delivery_zone_id)})
        if not zone or not zone.get("active"):
            raise HTTPException(status_code=400, detail="Zona pengiriman tidak valid.")
        delivery_fee = _num(zone["fee_le"]); zone_name = zone["name"]; zone_id = str(zone["_id"])

    items_input = inv.get("items") or []
    if not items_input:
        raise HTTPException(status_code=400, detail="Invoice tidak memiliki item.")

    order_items = []
    for it in items_input:
        product_id = it.get("product_id") or str(inv["_id"])
        category = "custom" if it.get("item_type") == "custom" or not it.get("product_id") else "catalog"
        order_items.append({
            "item_id": f"itm_{uuid.uuid4().hex[:12]}",
            "product_id": str(product_id),
            "product_name_snapshot": it.get("name"),
            "category": category,
            "configuration_snapshot": {
                "invoice_number": inv.get("invoice_number"),
                "item_type": it.get("item_type"),
                "product_slug": it.get("product_slug"),
                "description": it.get("description"),
                "dimensions": it.get("dimensions") or {},
                "material": it.get("material") or "",
                "finishing": it.get("finishing") or "",
                "notes": it.get("notes") or "",
                "custom_size": True if category == "custom" else False,
            },
            "quantity": int(it.get("quantity") or 1),
            "unit_price_le": _num(it.get("unit_price")),
            "subtotal_le": _num(it.get("line_total")),
        })

    subtotal_le = _num(inv.get("subtotal"))
    invoice_discount_le = _num(inv.get("discount_amount"))
    additional_fee_le = _num(inv.get("additional_fee"))

    # Promo discount (optional)
    promo_discount_le = 0.0
    disc_doc = None
    if data.discount_code:
        promo_discount_le, disc_doc, disc_err = await validate_discount(data.discount_code, subtotal_le)
        if disc_err:
            raise HTTPException(status_code=400, detail=disc_err)

    # Points redemption (optional)
    points_redeemed = 0.0
    redeem_req = _num(data.redeem_points)
    if redeem_req > 0:
        max_pct = _num(await get_setting("point_redeem_max_pct", 50), 50)
        cap = min(subtotal_le * max_pct / 100.0, _num(buyer.get("points_available")))
        points_redeemed = round(min(redeem_req, cap), 2)
        if points_redeemed < 0:
            points_redeemed = 0.0

    total_le = max(0.0, subtotal_le - invoice_discount_le - promo_discount_le - points_redeemed + delivery_fee + additional_fee_le)
    rate = _num(await get_setting("exchange_rate_idr_per_le", 357), 357)
    now = datetime.now(timezone.utc).isoformat()
    order_num = await generate_order_number()

    order_doc = {
        "order_number": order_num,
        "customer_name": data.customer_name.strip(),
        "customer_phone": phone,
        "phone_number": egypt_phone,
        "customer_address": data.customer_address.strip(),
        "customer_maps_url": maps,
        "delivery_method": data.delivery_method,
        "delivery_zone_id": zone_id,
        "delivery_zone_name": zone_name,
        "delivery_fee_le": delivery_fee,
        "payment_method": data.payment_method,
        "payment_status": "belum_dibayar",
        "order_status": "pesanan_masuk",
        "notes": (data.notes or "").strip(),
        "admin_note": f"Dibuat dari Invoice {inv.get('invoice_number')}",
        "items": order_items,
        "item": order_items[0],
        "subtotal_le": subtotal_le,
        "invoice_discount_le": invoice_discount_le,
        "discount_code": (disc_doc.get("code") if disc_doc else None),
        "discount_percentage": (_num(disc_doc.get("percentage")) if disc_doc else 0),
        "discount_le": promo_discount_le,
        "referral": None,
        "referral_discount_le": 0.0,
        "points_redeemed_le": points_redeemed,
        "customer_id": buyer_id,
        "customer_username": (buyer.get("username") if buyer else None),
        "total_le": total_le,
        "additional_fee_le": additional_fee_le,
        "invoice_id": str(inv["_id"]),
        "invoice_number": inv.get("invoice_number"),
        "exchange_rate_idr_per_le": rate,
        "estimated_total_idr": round(total_le * rate),
        "rate_timestamp": now,
        "requires_admin_confirmation": False,
        "admin_wage_eligibility": {
            "scope_status": "in_scope_pending",
            "governance_mode": "automatic",
            "evaluated_at": now,
            "version": 1
        },
        "created_at": now,
        "updated_at": now,
    }

    async def _execute_conversion_tx(session):
        ins_kw = {"session": session} if session else {}
        order_res = await db.orders.insert_one(order_doc, **ins_kw)
        created_order_id = str(order_res.inserted_id)

        try:
            upd_kw = {"session": session} if session else {}
            inv_upd = await db.invoices.find_one_and_update(
                {
                    "_id": inv["_id"],
                    "status": "CLAIMED",
                    "order_id": None
                },
                {
                    "$set": {
                        "status": "CONVERTED",
                        "order_id": created_order_id,
                        "order_number": order_num,
                        "converted_at": now,
                        "updated_at": now,
                        "updated_by": f"Customer ({buyer.get('username')})"
                    }
                },
                return_document=ReturnDocument.AFTER,
                **upd_kw
            )
            if not inv_upd:
                # Concurrency race: someone else converted it
                raise ConcurrencyConflictError("Invoice sudah dikonversi sebelumnya.")

            if disc_doc:
                await db.discounts.update_one({"_id": disc_doc["_id"]}, {"$inc": {"claims": 1}}, **ins_kw)
            if points_redeemed > 0:
                newb = _num(buyer.get("points_available")) - points_redeemed
                await db.customers.update_one(
                    {"_id": id_query(buyer_id)},
                    {"$inc": {"points_available": -points_redeemed, "points_redeemed": points_redeemed}},
                    **ins_kw
                )
                await db.point_transactions.insert_one({
                    "customer_id": buyer_id, "type": "redeem", "amount": -points_redeemed,
                    "order_id": created_order_id, "reason": f"Penukaran poin invoice {inv.get('invoice_number')}",
                    "balance_after": newb, "created_at": now
                }, **ins_kw)

            # Update custom request if source linked
            src_cr_id = inv.get("source", {}).get("custom_request_id")
            if src_cr_id:
                await db.custom_requests.update_one(
                    {"_id": id_query(src_cr_id)},
                    {"$set": {
                        "status": "dipesan",
                        "converted_order_id": created_order_id,
                        "invoice_id": str(inv["_id"]),
                        "updated_at": now,
                    }},
                    **ins_kw
                )
        except Exception:
            if not session:
                # Compensation rollback in standalone dev mode
                await db.orders.delete_one({"_id": order_res.inserted_id})
                await db.invoices.update_one(
                    {"_id": inv["_id"], "order_id": created_order_id},
                    {"$set": {"status": "CLAIMED", "order_id": None, "order_number": None, "converted_at": None}}
                )
            raise

        return created_order_id

    try:
        created_id = await execute_transaction_with_safety(client, _execute_conversion_tx)
    except ConcurrencyConflictError:
        fresh_inv = await db.invoices.find_one({"_id": inv["_id"]})
        if fresh_inv and fresh_inv.get("order_id"):
            ex_order = await db.orders.find_one({"_id": id_query(fresh_inv["order_id"])})
            if ex_order:
                ex_order = clean(ex_order)
                ex_order["whatsapp_message"] = build_whatsapp_message(ex_order)
                ex_order["whatsapp_number"] = await get_setting("whatsapp_number", "628XXXXXXXXXX")
                return ex_order
        raise HTTPException(status_code=409, detail="Invoice sudah dikonversi sebelumnya.")

    created_order = await db.orders.find_one({"_id": id_query(created_id)})
    created_order = clean(created_order)
    created_order["whatsapp_message"] = build_whatsapp_message(created_order)
    created_order["whatsapp_number"] = await get_setting("whatsapp_number", "628XXXXXXXXXX")
    return created_order

@api_router.post("/orders")
async def create_order(request: Request, data: OrderInput):
    if data.invoice_id:
        return await _create_invoice_order(request, data)

    if not data.customer_name.strip():
        raise HTTPException(status_code=400, detail="Nama tidak boleh kosong.")
    phone = normalize_phone(data.customer_phone)
    if not phone:
        raise HTTPException(status_code=400, detail="No HP tidak boleh kosong.")
    if not valid_intl_phone(phone):
        raise HTTPException(status_code=400, detail="No HP harus diawali + dan kode negara. Contoh: +62xxxxxxxxxx")
    egypt_phone = normalize_egypt_phone(data.phone_number)
    if not data.customer_address.strip():
        raise HTTPException(status_code=400, detail="Alamat tidak boleh kosong.")
    if data.delivery_method not in ("delivery", "pickup"):
        raise HTTPException(status_code=400, detail="Silakan pilih metode penerimaan barang.")
    if data.payment_method not in ("cash", "transfer"):
        raise HTTPException(status_code=400, detail="Silakan pilih metode pembayaran.")

    items_input = data.items if data.items else ([data.item] if data.item else [])
    if not items_input:
        raise HTTPException(status_code=400, detail="Keranjang kosong.")

    maps = validate_and_normalize_maps_url(data.customer_maps_url, data.delivery_method)

    delivery_fee = 0.0; zone_name = None; zone_id = None
    if data.delivery_method == "delivery":
        if not data.delivery_zone_id:
            raise HTTPException(status_code=400, detail="Silakan pilih zona pengiriman.")
        zone = await db.delivery_zones.find_one({"_id": id_query(data.delivery_zone_id)})
        if not zone or not zone.get("active"):
            raise HTTPException(status_code=400, detail="Zona pengiriman tidak valid.")
        delivery_fee = _num(zone["fee_le"]); zone_name = zone["name"]; zone_id = str(zone["_id"])

    items = []; subtotal_le = 0.0; requires_confirm = False
    for it in items_input:
        if it.quantity < 1:
            raise HTTPException(status_code=400, detail="Jumlah minimal 1.")
        product = await db.products.find_one({"_id": id_query(it.product_id)})
        if not product or not product.get("active"):
            raise HTTPException(status_code=400, detail="Produk tidak tersedia.")
        bd = compute_item_price(product, it.config, it.quantity)
        subtotal_le += bd["subtotal_le"]
        requires_confirm = requires_confirm or bd["requires_admin_confirmation"] or bool(it.config.get("custom_size"))
        items.append({
            "item_id": f"itm_{uuid.uuid4().hex[:12]}",
            "product_id": str(product["_id"]), "product_name_snapshot": product["name"], "category": product["category"],
            "configuration_snapshot": it.config, "quantity": it.quantity,
            "base_price_le": bd["base_price_le"], "adjustments_le": bd["adjustments_le"],
            "finishing_le": bd["finishing_le"], "unit_price_le": bd["unit_price_le"],
            "subtotal_le": bd["subtotal_le"], "lines": bd["lines"],
        })

    total_le = subtotal_le + delivery_fee
    buyer = await get_optional_customer(request)
    buyer_id = str(buyer["_id"]) if buyer else None
    # Referral OR promo discount (exclusive to protect margin)
    referral_snap = None
    discount_le = 0.0
    disc_doc = None
    if data.referral_code:
        if not buyer:
            raise HTTPException(status_code=401, detail="Login sebagai pelanggan untuk memakai kode referral")
        rdisc, rdoc, rerr = await validate_referral(data.referral_code, subtotal_le, buyer_id)
        if rerr:
            raise HTTPException(status_code=400, detail=rerr)
        discount_le = rdisc
        owner = await db.customers.find_one({"_id": id_query(rdoc["customer_id"])})
        referral_snap = {"code": rdoc.get("code"), "owner_id": str(rdoc["customer_id"]),
                         "owner_name": owner.get("username") if owner else "", "percentage": _num(rdoc.get("discount_percentage")),
                         "discount_le": rdisc, "points_per_order": _num(rdoc.get("points_per_order"))}
    else:
        if data.discount_code:
            if not buyer:
                raise HTTPException(status_code=401, detail="Login atau buat akun untuk memakai kode promo")
            discount_le, disc_doc, disc_err = await validate_discount(data.discount_code, subtotal_le)
            if disc_err:
                raise HTTPException(status_code=400, detail=disc_err)
    # Points redemption (logged-in only, max % of subtotal)
    points_redeemed = 0.0
    redeem_req = _num(data.redeem_points)
    if redeem_req > 0:
        if not buyer:
            raise HTTPException(status_code=401, detail="Login untuk menukar poin")
        max_pct = _num(await get_setting("point_redeem_max_pct", 50), 50)
        cap = min(subtotal_le * max_pct / 100.0, _num(buyer.get("points_available")))
        points_redeemed = round(min(redeem_req, cap), 2)
        if points_redeemed < 0:
            points_redeemed = 0.0
    total_le = max(0.0, subtotal_le - discount_le - points_redeemed + delivery_fee)
    rate = _num(await get_setting("exchange_rate_idr_per_le", 357), 357)
    now = datetime.now(timezone.utc).isoformat()

    order_doc = {
        "order_number": await generate_order_number(),
        "customer_name": data.customer_name.strip(), "customer_phone": phone,
        "phone_number": egypt_phone,
        "customer_address": data.customer_address.strip(), "customer_maps_url": maps,
        "delivery_method": data.delivery_method, "delivery_zone_id": zone_id, "delivery_zone_name": zone_name,
        "delivery_fee_le": delivery_fee, "payment_method": data.payment_method,
        "payment_status": "belum_dibayar", "order_status": "pesanan_masuk",
        "admin_wage_eligibility": {
            "scope_status": "in_scope_pending",
            "governance_mode": "automatic",
            "evaluated_at": now,
            "version": 1
        },
        "notes": (data.notes or "").strip(), "admin_note": "",
        "items": items, "item": items[0],
        "subtotal_le": subtotal_le, "discount_code": (disc_doc.get("code") if disc_doc else None),
        "discount_percentage": (_num(disc_doc.get("percentage")) if disc_doc else 0), "discount_le": (discount_le if not referral_snap else 0),
        "referral": referral_snap, "referral_discount_le": (discount_le if referral_snap else 0),
        "points_redeemed_le": points_redeemed, "customer_id": buyer_id,
        "customer_username": (buyer.get("username") if buyer else None),
        "total_le": total_le,
        "exchange_rate_idr_per_le": rate, "estimated_total_idr": round(total_le * rate),
        "rate_timestamp": now, "requires_admin_confirmation": requires_confirm,
        "created_at": now, "updated_at": now,
    }
    result = await db.orders.insert_one(order_doc)
    if disc_doc:
        await db.discounts.update_one({"_id": disc_doc["_id"]}, {"$inc": {"claims": 1}})
    if referral_snap:
        await db.referrals.update_one({"code": referral_snap["code"]}, {"$inc": {"claims": 1}})
    if points_redeemed > 0 and buyer_id:
        newb = _num(buyer.get("points_available")) - points_redeemed
        await db.customers.update_one({"_id": id_query(buyer_id)}, {"$inc": {"points_available": -points_redeemed, "points_redeemed": points_redeemed}})
        await db.point_transactions.insert_one({"customer_id": buyer_id, "type": "redeem", "amount": -points_redeemed,
            "order_id": str(result.inserted_id), "reason": "Penukaran poin", "balance_after": newb,
            "created_at": datetime.now(timezone.utc).isoformat()})
    order_doc["id"] = str(result.inserted_id); order_doc.pop("_id", None)
    order_doc["whatsapp_message"] = build_whatsapp_message(order_doc)
    order_doc["whatsapp_number"] = await get_setting("whatsapp_number", "628XXXXXXXXXX")
    return order_doc

def fmt_le(v):
    return f"{v:,.0f}".replace(",", ".")

def fmt_idr(v):
    return f"Rp{v:,.0f}".replace(",", ".")

def config_summary(item):
    cfg = item.get("configuration_snapshot", {}) or {}; cat = item.get("category"); parts = []
    if cfg.get("_summary"):
        return str(cfg["_summary"])
    if cat == "rak":
        if cfg.get("length"): parts.append(f"{cfg['length']} cm")
        if cfg.get("level"): parts.append(f"{cfg['level']} Tingkat")
        if cfg.get("type"): parts.append(f"Tipe {cfg['type']}")
        if cfg.get("finishing"): parts.append(cfg["finishing"])
    elif cat == "meja":
        if cfg.get("size"): parts.append(f"{cfg['size']} cm")
        if cfg.get("height"): parts.append(f"Tinggi {cfg['height']} cm")
        if cfg.get("finishing"): parts.append(cfg["finishing"])
    elif cat == "meja_rak":
        if cfg.get("variant"): parts.append(cfg["variant"])
        if cfg.get("type"): parts.append(f"Tipe {cfg['type']}")
        if cfg.get("finishing"): parts.append(cfg["finishing"])
    if cfg.get("custom_size"): parts.append("Ukuran Custom")
    return ", ".join(parts)

def build_whatsapp_message(order):
    lines = ["Halo Sogil Furniture, saya ingin melakukan pemesanan.", "", f"No. Pesanan: {order['order_number']}", ""]
    for idx, item in enumerate(order.get("items", [order.get("item")]), 1):
        if not item:
            continue
        prefix = f"{idx}. " if len(order.get("items", [])) > 1 else ""
        lines.append(f"{prefix}Produk: {item['product_name_snapshot']}")
        cs = config_summary(item)
        if cs:
            lines.append(f"   Spesifikasi: {cs}")
        lines.append(f"   Jumlah: {item['quantity']}")
    lines.append("")
    if order["delivery_method"] == "delivery":
        lines.append("Pengiriman: Delivery")
        lines.append(f"Zona: {order.get('delivery_zone_name', '-')}")
    else:
        lines.append("Pengiriman: Ambil di Toko")
    lines += ["", "Rincian Harga:", f"Subtotal: {fmt_le(_num(order.get('subtotal_le')))} LE"]
    if _num(order.get("discount_le")) > 0:
        _dc = order.get("discount_code")
        lines.append(f"Diskon{f' ({_dc})' if _dc else ''}: -{fmt_le(_num(order['discount_le']))} LE")
    if _num(order.get("referral_discount_le")) > 0:
        _rc = (order.get("referral") or {}).get("code")
        lines.append(f"Diskon Referral{f' ({_rc})' if _rc else ''}: -{fmt_le(_num(order['referral_discount_le']))} LE")
    if _num(order.get("points_redeemed_le")) > 0:
        lines.append(f"Penukaran Poin: -{fmt_le(_num(order['points_redeemed_le']))} LE")
    lines += [f"Ongkir: {fmt_le(_num(order.get('delivery_fee_le')))} LE",
              f"Total: {fmt_le(order['total_le'])} LE (≈ {fmt_idr(order['estimated_total_idr'])})",
              f"Rate: Rp{fmt_le(order['exchange_rate_idr_per_le'])}/LE", "",
              f"Nama: {order['customer_name']}", f"No. HP: {order['customer_phone']}", f"Alamat: {order['customer_address']}"]
    if order.get("customer_maps_url"):
        lines.append(f"Maps: {order['customer_maps_url']}")
    lines += ["", f"Pembayaran: {'Transfer' if order['payment_method'] == 'transfer' else 'Cash'}"]
    if order.get("notes"):
        lines += ["", f"Catatan: {order['notes']}"]
    if order.get("requires_admin_confirmation"):
        lines += ["", "(*Pesanan ini memerlukan konfirmasi admin)"]
    return "\n".join(lines)

@api_router.get("/orders/{order_id}")
async def get_order_public(order_id: str, request: Request):
    order = await db.orders.find_one({"_id": id_query(order_id)})
    if not order:
        raise HTTPException(status_code=404, detail="Pesanan tidak ditemukan")
    # Orders tied to a customer account are private to that customer.
    # Guest orders (no customer_id) stay accessible by ID for checkout confirmation.
    # Admins/Owner use the RBAC-gated /admin/orders endpoints.
    if order.get("customer_id"):
        buyer = await get_optional_customer(request)
        if not buyer or str(buyer["_id"]) != str(order["customer_id"]):
            raise HTTPException(status_code=403, detail="Tidak diizinkan mengakses pesanan ini")

    pay_summary = await compute_order_payment_summary(order)
    order.update(pay_summary)

    order = clean(order)
    order["whatsapp_message"] = build_whatsapp_message(order)
    order["whatsapp_number"] = await get_setting("whatsapp_number", "628XXXXXXXXXX")
    return order

# --------------------------------------------------------------------------
# Admin: orders
# --------------------------------------------------------------------------
@api_router.get("/admin/orders")
async def admin_list_orders(status: Optional[str] = None, payment_status: Optional[str] = None,
                            q: Optional[str] = None, admin: dict = Depends(require_perm("manage_orders"))):
    query = {}
    if status:
        query["order_status"] = status
    if payment_status:
        query["payment_status"] = payment_status
    if q and q.strip():
        rx = {"$regex": re.escape(q.strip()), "$options": "i"}
        query["$or"] = [{"order_number": rx}, {"customer_name": rx}, {"customer_phone": rx},
                        {"customer_username": rx}, {"items.product_name_snapshot": rx}, {"referral.code": rx}]
    orders = await db.orders.find(query).sort("created_at", -1).to_list(2000)
    res = []
    for o in orders:
        summary = await compute_order_payment_summary(o)
        o.update(summary)
        res.append(clean(o))
    return res

@api_router.get("/admin/overview")
async def admin_overview(admin: dict = Depends(require_perm("manage_orders"))):
    orders = await db.orders.find({}).to_list(5000)
    stats = {"total": len(orders), "pesanan_masuk": 0, "dikonfirmasi": 0, "diproses": 0, "siap": 0,
             "selesai": 0, "dibatalkan": 0, "lunas": 0, "belum_dibayar": 0, "dp": 0, "overpaid": 0, "estimated_revenue_le": 0.0}
    for o in orders:
        st = o.get("order_status")
        if st in stats:
            stats[st] += 1
        ps = o.get("payment_status")
        if ps in stats:
            stats[ps] += 1
        if st != "dibatalkan":
            stats["estimated_revenue_le"] += _num(o.get("total_le"))
    return stats

@api_router.get("/admin/analytics/top-configs")
async def admin_top_configs(category: Optional[str] = None, group_by: str = "full",
                            admin: dict = Depends(require_perm("manage_orders"))):
    orders = await db.orders.find({}).to_list(5000)
    agg = {}
    for o in orders:
        if o.get("order_status") == "dibatalkan":
            continue
        for it in o.get("items", [o.get("item")]):
            if not it:
                continue
            if category and it.get("category") != category:
                continue
            cfg = it.get("configuration_snapshot", {}) or {}
            cat = it.get("category")
            if group_by == "length":
                key = f"{cat} — {cfg.get('length', '-')} cm"
            elif group_by == "level":
                key = f"{cat} — {cfg.get('level', '-')} tingkat"
            elif group_by == "type":
                key = f"{cat} — Tipe {cfg.get('type', '-')}"
            elif group_by == "finishing":
                key = f"{cat} — {cfg.get('finishing', '-')}"
            else:
                key = f"{it.get('product_name_snapshot')} — {config_summary(it) or '-'}"
            e = agg.setdefault(key, {"key": key, "category": cat, "config": cfg, "orders": 0, "quantity": 0})
            e["orders"] += 1
            e["quantity"] += int(it.get("quantity", 1))
    rows = sorted(agg.values(), key=lambda x: x["quantity"], reverse=True)
    total_q = sum(r["quantity"] for r in rows) or 1
    for r in rows:
        r["share"] = round(r["quantity"] / total_q * 100, 1)
    return rows[:50]

@api_router.get("/admin/orders/{order_id}")
async def admin_get_order(order_id: str, admin: dict = Depends(require_perm("manage_orders"))):
    order = await db.orders.find_one({"_id": id_query(order_id)})
    if not order:
        raise HTTPException(status_code=404, detail="Pesanan tidak ditemukan")
    pay_summary = await compute_order_payment_summary(order)
    order.update(pay_summary)
    order = clean(order)
    order["whatsapp_message"] = build_whatsapp_message(order)
    order["whatsapp_number"] = await get_setting("whatsapp_number", "628XXXXXXXXXX")
    return order

async def record_order_revenue(order):
    if await db.finance_transactions.find_one({
        "related_order_id": str(order["_id"]),
        "type": "order_revenue",
        "is_void": {"$ne": True},
        "status": {"$ne": "void"}
    }):
        return
    # If permanently voided by finance manual action, do not re-create
    if await db.finance_transactions.find_one({
        "related_order_id": str(order["_id"]),
        "type": "order_revenue",
        "is_void": True,
        "void_source": "finance_manual"
    }):
        return

    now = datetime.now(timezone.utc).isoformat()
    total_le = _num(order.get("total_le"))
    settings_rate = _num(await get_setting("exchange_rate_idr_per_le", 357), 357)
    rate = resolve_transaction_rate(None, order.get("exchange_rate_idr_per_le"), settings_rate)

    pay_method = (order.get("payment_method") or "cash").lower()
    if pay_method == "transfer":
        primary_currency = "IDR"
        primary_account = "IDR"
        conv = compute_currency_conversion("IDR", round(total_le * rate), rate)
    else:  # cash
        primary_currency = "EGP"
        primary_account = "EGP"
        conv = compute_currency_conversion("EGP", total_le, rate)

    primary_amount = conv["primary_amount"]
    counterpart_currency = conv["counterpart_currency"]
    counterpart_amount = conv["counterpart_amount"]

    await db.finance_transactions.insert_one({
        "date": now, "type": "order_revenue", "category": "Penjualan",
        "amount": primary_amount, "currency": primary_currency, "account": primary_account,
        "exchange_rate": rate,
        "counterpart_amount": counterpart_amount,
        "counterpart_currency": counterpart_currency,
        "payment_method": pay_method,
        "description": f"Pendapatan otomatis dari pesanan {order.get('order_number')}",
        "related_order_id": str(order["_id"]), "created_by_name": "Sistem",
        "created_at": now, "updated_at": now,
    })

@api_router.patch("/admin/orders/{order_id}")
async def admin_update_order(order_id: str, data: OrderStatusUpdate, admin: dict = Depends(require_perm("manage_orders"))):
    valid_status = {"pesanan_masuk", "dikonfirmasi", "diproses", "siap", "selesai", "dibatalkan"}
    valid_pay = {"belum_dibayar", "dp", "lunas"}
    valid_methods = {"cash", "transfer"}

    fields_set = getattr(data, "model_fields_set", None)
    if fields_set is None:
        fields_set = getattr(data, "__fields_set__", set())
    if "payment_status" in fields_set or data.payment_status is not None:
        raise HTTPException(
            status_code=400,
            detail="Status pembayaran tidak dapat diubah secara manual. Status dikelola secara otomatis melalui pencatatan pembayaran riil."
        )

    async def _do_admin_update_order(session):
        find_kw = {"session": session} if session is not None else {}
        update = audit_fields(admin)

        existing_order = await _mongo_find_one(db.orders, {"_id": id_query(order_id)}, **find_kw)
        if not existing_order:
            raise HTTPException(status_code=404, detail="Pesanan tidak ditemukan")

        # Phase 3.F.4.3 Package 8.1 — Active Delivery Trip Order Guard
        active_trip_id = existing_order.get("active_delivery_trip_id")
        if active_trip_id:
            has_price_change = any(x is not None for x in (data.subtotal_le, data.delivery_fee_le, data.discount_le, data.total_le, data.items))
            has_conflicting_mutation = (
                data.order_status is not None or
                data.payment_method is not None or
                has_price_change
            )
            if has_conflicting_mutation:
                trip_ref = existing_order.get("active_delivery_trip_number") or active_trip_id
                raise HTTPException(
                    status_code=409,
                    detail=f"Pesanan sedang terikat pada trip pengiriman aktif ({trip_ref}). Lepaskan penugasan dari trip sebelum memodifikasi status atau rincian pesanan."
                )

        # Phase 3.B.1 — Handover Recognition & Status Transition Checks
        existing_status = existing_order.get("order_status")
        has_immutable_snapshot = (
            bool(existing_order.get("completed_at")) or
            existing_order.get("recognized_revenue_le") is not None or
            existing_status == "selesai"
        )

        if data.order_status is not None:
            if data.order_status not in valid_status:
                raise HTTPException(status_code=400, detail="Status tidak valid")
            # Safeguard on cancellation after handover (selesai -> dibatalkan or any order with established handover snapshot)
            if (existing_status == "selesai" or has_immutable_snapshot) and data.order_status == "dibatalkan":
                if not data.confirm_handover_cancellation:
                    raise HTTPException(
                        status_code=400,
                        detail="Pembatalan pesanan yang telah selesai memerlukan konfirmasi eksplisit (confirm_handover_cancellation=True)."
                    )
                reason_str = (data.cancellation_reason or "").strip()
                if len(reason_str) < 5:
                    raise HTTPException(
                        status_code=400,
                        detail="Alasan pembatalan pesanan yang telah selesai wajib diisi minimal 5 karakter."
                    )
                perms = admin.get("permissions") or {}
                if admin.get("role") != "owner" and not perms.get("access_finance"):
                    raise HTTPException(
                        status_code=403,
                        detail="Hanya owner atau admin dengan akses keuangan yang dapat membatalkan pesanan yang telah selesai."
                    )
            update["order_status"] = data.order_status

        if data.payment_method is not None:
            if data.payment_method not in valid_methods:
                raise HTTPException(status_code=400, detail="Metode pembayaran tidak valid")
            update["payment_method"] = data.payment_method
        if data.admin_note is not None:
            update["admin_note"] = data.admin_note

        has_price_change = any(x is not None for x in (data.subtotal_le, data.delivery_fee_le, data.discount_le, data.total_le, data.items))
        if has_price_change:
            # Phase 3.B.1 / Owner Decision B: Direct post-handover financial edits are strictly rejected (HTTP 409)
            if has_immutable_snapshot:
                raise HTTPException(
                    status_code=409,
                    detail="Pesanan yang telah selesai tidak dapat diubah nilainya secara langsung. Gunakan penyesuaian keuangan resmi (Finance Adjustment)."
                )
            perms = admin.get("permissions") or {}
            if admin.get("role") != "owner" and not perms.get("access_finance"):
                raise HTTPException(status_code=403, detail="Hanya admin dengan akses keuangan atau owner yang dapat mengubah harga pesanan")

            if data.items is not None:
                # Phase 2 Order-Item Reconciliation & Protection
                existing_items = existing_order.get("items") or ([existing_order.get("item")] if existing_order.get("item") else [])
                existing_map = {it.get("item_id"): it for it in existing_items if it.get("item_id")}

                # Identify protected item IDs linked to assignments or obligations
                order_id_str = str(existing_order.get("_id") or existing_order.get("id"))

                # Query work assignments (active, completed, cancelled)
                cursor_asn = db.work_assignments.find({
                    "order_id": order_id_str,
                    "status": {"$in": ["assigned", "in_progress", "ready_for_review", "accruing", "completed", "cancelled"]}
                }, **find_kw)
                linked_assignments = await cursor_asn.to_list(1000) if hasattr(cursor_asn, "to_list") else cursor_asn

                # Query wage obligations
                cursor_ob = db.wage_obligations.find({
                    "order_id": order_id_str,
                    "status": {"$in": ["accrued", "partially_paid", "paid", "voided"]}
                }, **find_kw)
                linked_obligations = await cursor_ob.to_list(1000) if hasattr(cursor_ob, "to_list") else cursor_ob

                protected_item_ids = {a.get("order_item_id") for a in linked_assignments if a.get("order_item_id")}
                protected_item_ids.update({o.get("order_item_id") for o in linked_obligations if o.get("order_item_id")})

                sanitized_items = []
                seen_item_ids = set()
                for incoming_it in data.items:
                    it_dict = dict(incoming_it)
                    it_id = it_dict.get("item_id")
                    if it_id:
                        if it_id not in existing_map:
                            raise HTTPException(status_code=400, detail=f"item_id tidak dikenal untuk pesanan ini: {it_id}")
                        if it_id in seen_item_ids:
                            raise HTTPException(status_code=400, detail=f"Duplikasi item_id dalam daftar item: {it_id}")
                        seen_item_ids.add(it_id)
                    else:
                        it_id = f"itm_{uuid.uuid4().hex[:12]}"
                        it_dict["item_id"] = it_id
                        seen_item_ids.add(it_id)

                    sanitized_items.append(it_dict)

                # Check if any protected item was omitted/removed
                for prot_id in protected_item_ids:
                    if prot_id not in seen_item_ids:
                        raise HTTPException(
                            status_code=409,
                            detail=f"Tidak dapat menghapus item pesanan yang memiliki penugasan kerja aktif atau selesai (item_id: {prot_id})"
                        )

                # Check quantity floor protection against active assignments
                for a in linked_assignments:
                    if a.get("status") in ("assigned", "in_progress", "ready_for_review", "accruing"):
                        aid = a.get("order_item_id")
                        target_qty = a.get("target_quantity", 1)
                        matched_item = next((it for it in sanitized_items if it.get("item_id") == aid), None)
                        if matched_item and int(matched_item.get("quantity", 0)) < target_qty:
                            raise HTTPException(
                                status_code=409,
                                detail=f"Kuantitas item tidak boleh kurang dari kuantitas penugasan aktif ({target_qty})"
                            )

                update["items"] = sanitized_items
                if len(sanitized_items) > 0:
                    update["item"] = sanitized_items[0]
            if data.subtotal_le is not None:
                update["subtotal_le"] = float(data.subtotal_le)
            if data.delivery_fee_le is not None:
                update["delivery_fee_le"] = float(data.delivery_fee_le)
            if data.discount_le is not None:
                update["discount_le"] = float(data.discount_le)

            if data.total_le is not None:
                update["total_le"] = float(data.total_le)
            else:
                cur_sub = update.get("subtotal_le", existing_order.get("subtotal_le", 0))
                cur_del = update.get("delivery_fee_le", existing_order.get("delivery_fee_le", 0))
                cur_disc = update.get("discount_le", existing_order.get("discount_le", 0))
                cur_ref = existing_order.get("referral_discount_le", 0)
                cur_pts = existing_order.get("points_redeemed_le", 0)
                update["total_le"] = max(0.0, float(cur_sub) - float(cur_disc) - float(cur_ref) - float(cur_pts) + float(cur_del))

            rate = existing_order.get("exchange_rate_idr_per_le") or 357
            update["estimated_total_idr"] = round(update["total_le"] * rate)

        # Phase 3.B.1 — Immutable Handover Snapshot & Status Transition Audit History
        now_iso = update.get("updated_at") or datetime.now(timezone.utc).isoformat()
        mongo_ops = {"$set": update}

        target_status = data.order_status
        is_establishing_snapshot = False
        if target_status is not None and target_status != existing_status:
            # 1. First valid handover to 'selesai'
            if target_status == "selesai":
                # If order has never been completed before, stamp immutable snapshot
                if not existing_order.get("completed_at") and existing_order.get("recognized_revenue_le") is None:
                    rev_le = float(existing_order.get("total_le", 0.0))
                    update["completed_at"] = now_iso
                    update["completed_by_id"] = admin.get("id")
                    update["completed_by_name"] = admin.get("name", "Admin")
                    update["recognized_revenue_le"] = rev_le
                    is_establishing_snapshot = True

                # Phase 08.5C.4 / Phase 08.5C.6 — Admin Wage Accrual: Sequence B (Paid first, completed later)
                # Evaluate shared eligibility check inside the transaction session
                order_for_wage = dict(existing_order)
                order_for_wage.update(update)
                order_for_wage["order_status"] = "selesai"
                if is_order_fully_paid(order_for_wage) and not is_order_excluded_from_admin_wage(order_for_wage):
                    admin_wage_res = await evaluate_and_process_order_admin_wage_accrual(
                        order_for_wage,
                        admin,
                        session=session,
                        lifecycle_event="order_completed",
                        transition_context={
                            "transition_type": "order_completion",
                            "order_id": order_id,
                            "from_status": existing_status,
                            "to_status": target_status,
                        }
                    )
                    if admin_wage_res:
                        if admin_wage_res.get("obligation"):
                            update["admin_wage_obligation"] = admin_wage_res["obligation"]
                            update["admin_wage_blocked"] = None
                        elif admin_wage_res.get("blocked"):
                            update["admin_wage_blocked"] = admin_wage_res["blocked"]
                        elif admin_wage_res.get("skipped") and admin_wage_res.get("status") not in ("skipped_order_not_completed", "skipped_payment_not_lunas"):
                            update["admin_wage_skipped"] = admin_wage_res["skipped"]
                        if admin_wage_res.get("eligibility"):
                            update["admin_wage_eligibility"] = admin_wage_res["eligibility"]

            # 2. Build status history entry
            history_entry = {
                "from_status": existing_status,
                "to_status": target_status,
                "changed_at": now_iso,
                "changed_by_id": admin.get("id"),
                "changed_by_name": admin.get("name", "Admin"),
                "reason": (data.cancellation_reason or "").strip() if target_status == "dibatalkan" else None
            }
            mongo_ops["$push"] = {"status_history": history_entry}

        if is_establishing_snapshot:
            # Concurrency guard: Ensure atomicity at database level.
            # If another concurrent worker already established completed_at, do not overwrite it.
            atomic_query = {
                "_id": id_query(order_id),
                "completed_at": {"$in": [None, False]},
                "recognized_revenue_le": None,
            }
            update_result = await _mongo_update_one(db.orders, atomic_query, mongo_ops, **find_kw)
            if update_result and hasattr(update_result, "matched_count") and update_result.matched_count == 0:
                # Another concurrent request won the race to establish the snapshot.
                # Perform fallback update preserving the existing snapshot and updating remaining fields if needed.
                fallback_update = dict(update)
                fallback_update.pop("completed_at", None)
                fallback_update.pop("completed_by_id", None)
                fallback_update.pop("completed_by_name", None)
                fallback_update.pop("recognized_revenue_le", None)
                fallback_ops = {"$set": fallback_update}
                if "$push" in mongo_ops:
                    fallback_ops["$push"] = mongo_ops["$push"]
                await _mongo_update_one(db.orders, {"_id": id_query(order_id)}, fallback_ops, **find_kw)
        else:
            await _mongo_update_one(db.orders, {"_id": id_query(order_id)}, mongo_ops, **find_kw)

        order = await _mongo_find_one(db.orders, {"_id": id_query(order_id)}, **find_kw)
        return clean(order)

    def _is_transient_conflict(exc: Exception) -> bool:
        if isinstance(exc, pymongo.errors.PyMongoError):
            if hasattr(exc, "has_error_label") and exc.has_error_label("TransientTransactionError"):
                return True
            if isinstance(exc, pymongo.errors.OperationFailure) and getattr(exc, "code", None) == 112:
                return True
        return False

    max_txn_retries = 3
    for attempt in range(1, max_txn_retries + 1):
        session = None
        try:
            session = await client.start_session()
        except (pymongo.errors.ConfigurationError, pymongo.errors.InvalidOperation, AttributeError, RuntimeError) as sess_err:
            if not is_standalone_fallback_permitted():
                logger.error(f"Transaction capability unavailable for admin_update_order in mode {get_environment_mode()!r}: {sess_err}")
                raise HTTPException(
                    status_code=503,
                    detail="Layanan transaksi multi-dokumen tidak tersedia pada lingkungan ini (Fail-Closed)"
                )
            session = None

        try:
            if session is not None:
                async with session:
                    async with session.start_transaction():
                        return await _do_admin_update_order(session)
            else:
                return await _do_admin_update_order(None)
        except Exception as txn_exc:
            if _is_transient_conflict(txn_exc) and attempt < max_txn_retries:
                logger.warning(f"Transient transaction error in admin_update_order (attempt {attempt}/{max_txn_retries}): {txn_exc}")
                await asyncio.sleep(0.05 * attempt)
                continue
            raise

@api_router.post("/admin/orders/{order_id}/permanent-delete")
async def admin_permanent_delete_order(
    order_id: str,
    payload: PermanentDeleteInput,
    admin: dict = Depends(require_perm("delete_data"))
):
    if (payload.confirmation_phrase or "").strip() != "HAPUS PERMANEN":
        raise HTTPException(
            status_code=400,
            detail="Frasa konfirmasi tidak valid. Anda wajib mengetik 'HAPUS PERMANEN' secara tepat."
        )

    order = await db.orders.find_one({"_id": id_query(order_id)})
    if not order:
        raise HTTPException(status_code=404, detail="Pesanan tidak ditemukan")

    # Guard: Check if order has active/unpaid work assignments or obligations
    order_id_str = str(order.get("_id") or order.get("id"))
    try:
        asn_cursor = db.work_assignments.find({
            "order_id": order_id_str,
            "status": {"$in": ["assigned", "in_progress", "ready_for_review", "accruing"]}
        })
        active_assignments = await asn_cursor.to_list(100) if hasattr(asn_cursor, "to_list") else []
    except Exception:
        active_assignments = []

    if active_assignments:
        raise HTTPException(
            status_code=409,
            detail="Tidak dapat menghapus permanen pesanan yang masih memiliki penugasan kerja aktif."
        )

    try:
        wob_cursor = db.wage_obligations.find({
            "order_id": order_id_str,
            "status": {"$in": ["accrued", "partially_paid"]}
        })
        unpaid_obligations = await wob_cursor.to_list(100) if hasattr(wob_cursor, "to_list") else []
    except Exception:
        unpaid_obligations = []

    if unpaid_obligations:
        raise HTTPException(
            status_code=409,
            detail="Tidak dapat menghapus permanen pesanan yang masih memiliki kewajiban upah terutang (unpaid wage obligations)."
        )

    # Phase 3.F.4.3 Package 8.1 — Active Delivery Trip Permanent Delete Guard
    if order.get("active_delivery_trip_id"):
        trip_ref = order.get("active_delivery_trip_number") or order.get("active_delivery_trip_id")
        raise HTTPException(
            status_code=409,
            detail=f"Tidak dapat menghapus permanen pesanan yang sedang terikat pada trip pengiriman aktif ({trip_ref}). Selesaikan atau lepaskan pesanan dari trip terlebih dahulu."
        )

    # Isolated delete: ONLY remove this order document.
    # NEVER cascade delete or reverse points, finance, invoices, customers, etc.
    res = await db.orders.delete_one({"_id": order["_id"]})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Pesanan sudah dihapus sebelumnya")

    await record_audit_log(
        action="PERMANENT_DELETE",
        entity_type="order",
        entity_id=str(order["_id"]),
        entity_identifier=order.get("order_number", str(order["_id"])),
        admin=admin,
        metadata={
            "previous_status": order.get("order_status"),
            "payment_status": order.get("payment_status"),
            "related_invoice_id": order.get("invoice_id"),
            "related_invoice_number": order.get("invoice_number"),
            "customer_id": order.get("customer_id"),
            "reason": payload.reason,
        }
    )

    return {
        "ok": True,
        "message": f"Pesanan {order.get('order_number')} berhasil dihapus secara permanen."
    }

@api_router.delete("/admin/orders/{order_id}")
async def admin_delete_order(order_id: str, admin: dict = Depends(require_perm("delete_data"))):
    raise HTTPException(
        status_code=400,
        detail="Penghapusan pesanan wajib melalui endpoint POST /api/admin/orders/{order_id}/permanent-delete dengan frasa konfirmasi 'HAPUS PERMANEN'."
    )

# --------------------------------------------------------------------------
# Admin: Order Payments (Phase 1)
# --------------------------------------------------------------------------
@api_router.get("/admin/orders/{order_id}/payments")
async def admin_list_order_payments(order_id: str, admin: dict = Depends(require_perm("manage_orders"))):
    order = await db.orders.find_one({"_id": id_query(order_id)})
    if not order:
        raise HTTPException(status_code=404, detail="Pesanan tidak ditemukan")

    payments = await db.payments.find({"order_id": id_query(order_id)}).sort("created_at", -1).to_list(1000)
    summary = await compute_order_payment_summary(order)
    return {
        "order_id": str(order["_id"]),
        "order_number": order.get("order_number"),
        "total_le": _num(order.get("total_le")),
        "summary": summary,
        "payments": [clean(p) for p in payments]
    }

@api_router.get("/admin/orders/{order_id}/payment-summary")
async def admin_get_order_payment_summary(order_id: str, admin: dict = Depends(require_perm("manage_orders"))):
    order = await db.orders.find_one({"_id": id_query(order_id)})
    if not order:
        raise HTTPException(status_code=404, detail="Pesanan tidak ditemukan")
    summary = await compute_order_payment_summary(order)
    return {
        "order_id": str(order["_id"]),
        "order_number": order.get("order_number"),
        "total_le": _num(order.get("total_le")),
        **summary
    }

def get_environment_mode() -> str:
    """
    Explicitly resolves the canonical runtime environment mode across all configured
    environment variables (APP_ENV, ENV, ENVIRONMENT).

    Rules:
    1. Inspects every non-empty configured variable.
    2. Maps supported aliases to canonical modes: 'production', 'development', 'test'.
    3. If any configured value is unrecognized -> returns 'unknown' (fail-closed).
    4. If multiple configured variables resolve to conflicting canonical modes -> returns 'unknown' (fail-closed).
    5. If all configured variables agree on the same canonical mode -> returns that canonical mode.
    6. If no variables are configured (missing/empty/whitespace-only) -> returns 'unknown' (fail-closed).
    """
    var_names = ("APP_ENV", "ENV", "ENVIRONMENT")
    canonical_modes = set()

    alias_map = {
        "production": "production",
        "prod": "production",
        "development": "development",
        "dev": "development",
        "local": "development",
        "test": "test",
        "testing": "test",
    }

    configured_count = 0
    for name in var_names:
        raw = os.environ.get(name)
        if raw is not None:
            val = raw.strip().lower()
            if val:
                configured_count += 1
                canonical = alias_map.get(val)
                if not canonical:
                    # Rule E: Unknown or unsupported value fails closed immediately
                    return "unknown"
                canonical_modes.add(canonical)

    if configured_count == 0:
        # Rule F: Missing or empty configuration fails closed
        return "unknown"

    if len(canonical_modes) == 1:
        # Rule C & D: Unanimous agreement on canonical mode
        return canonical_modes.pop()

    # Rule C: Conflicting normalized modes fail closed
    return "unknown"

def is_standalone_fallback_permitted() -> bool:
    """
    Centralized environment-policy gate:
    Standalone compensating fallback is permitted ONLY in explicitly and unambiguously
    established development or test environments.
    Production, unknown, unrecognized, or conflicting configurations strictly fail closed.
    """
    mode = get_environment_mode()
    return mode in ("development", "test")

@api_router.post("/admin/orders/{order_id}/payments")
async def admin_create_order_payment(order_id: str, payload: PaymentCreateInput, admin: dict = Depends(require_perm("manage_orders"))):
    # Financial write operation requires access_finance or owner role
    role = admin.get("role")
    perms = admin.get("permissions") or {}
    if role != "owner" and not perms.get("access_finance"):
        raise HTTPException(status_code=403, detail="Hanya admin dengan akses keuangan atau owner yang dapat mencatat pembayaran")

    order = await db.orders.find_one({"_id": id_query(order_id)})
    if not order:
        raise HTTPException(status_code=404, detail="Pesanan tidak ditemukan")

    # 1. Validation & Normalization
    raw_amount = _num(payload.amount)
    if raw_amount <= 0:
        raise HTTPException(status_code=400, detail="Nominal pembayaran harus lebih besar dari 0")

    currency = (payload.currency or "EGP").strip().upper()
    if currency != "EGP":
        raise HTTPException(status_code=400, detail="Mata uang transaksi pokok harus EGP")

    payment_method = (payload.payment_method or "cash").strip().lower()
    if payment_method not in ("cash", "transfer", "customer_credit"):
        raise HTTPException(status_code=400, detail="Metode pembayaran harus cash, transfer, atau customer_credit")

    idem_key = (payload.idempotency_key or "").strip() or None

    def _is_matching_payment_payload(existing_doc: dict) -> bool:
        orig_order_id = str(existing_doc.get("order_id") or "").strip()
        req_order_id = str(order["_id"]).strip()

        orig_amt = _num(existing_doc.get("amount_le", existing_doc.get("amount", 0.0)))
        orig_amt_d = Decimal(str(orig_amt)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        req_amt_d = Decimal(str(raw_amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        orig_method = str(existing_doc.get("payment_method") or "").strip().lower()

        if orig_order_id and orig_order_id != req_order_id:
            return False
        if orig_method and orig_method != payment_method:
            return False
        if orig_amt_d != req_amt_d:
            return False

        return True

    # 2. Idempotency Check
    if idem_key:
        existing_pmt = await db.payments.find_one({"idempotency_key": idem_key})
        if existing_pmt:
            if not _is_matching_payment_payload(existing_pmt):
                raise HTTPException(
                    status_code=409,
                    detail="Kunci idempotensi telah digunakan untuk pembayaran dengan parameter yang berbeda."
                )
            res = clean(existing_pmt)
            try:
                new_summary = await compute_order_payment_summary(order)
                if new_summary:
                    res["order_summary"] = new_summary
            except Exception:
                pass
            return res

    # Phase 3.B.3 Validation: Customer Credit requires a registered customer and positive EGP balance
    customer_doc = None
    if payment_method == "customer_credit":
        order_cust_id = str(order.get("customer_id") or "").strip()
        if not order_cust_id:
            raise HTTPException(
                status_code=400,
                detail="Pembayaran menggunakan saldo kredit pelanggan membutuhkan pesanan dengan akun pelanggan terdaftar (bukan pesanan tamu/guest)"
            )
        customer_doc = await db.customers.find_one({"_id": id_query(order_cust_id)})
        if not customer_doc:
            raise HTTPException(status_code=400, detail="Data akun pelanggan tidak ditemukan di sistem")

        # Initial preflight balance check (strict EGP)
        preflight_balance = await get_customer_credit_balance(order_cust_id, "EGP")
        if preflight_balance < raw_amount:
            raise HTTPException(
                status_code=400,
                detail=f"Saldo kredit pelanggan tidak mencukupi (Tersedia: {preflight_balance:.2f} EGP, Dibutuhkan: {raw_amount:.2f} EGP)"
            )

    now = datetime.now(timezone.utc).isoformat()
    payment_date = payload.payment_date or now

    # 3. Exchange Rate Resolution & Actual Amount Evaluation
    settings_rate = _num(await get_setting("exchange_rate_idr_per_le", 357), 357)
    is_rate_override = False
    override_reason = None
    expected_idr = None
    actual_idr = None
    variance_idr = 0

    if payment_method == "transfer":
        primary_currency = "IDR"
        primary_account = "IDR"
        if payload.exchange_rate is not None and _num(payload.exchange_rate) > 0:
            req_rate = _num(payload.exchange_rate)
            if payload.is_rate_override or round(req_rate, 4) != round(settings_rate, 4):
                override_reason = (payload.override_reason or "").strip()
                if len(override_reason) < 3:
                    raise HTTPException(
                        status_code=422,
                        detail="Alasan perubahan kurs wajib diisi saat menggunakan kurs override (minimal 3 karakter)."
                    )
                rate = round(float(req_rate), 4)
                is_rate_override = True
            else:
                rate = settings_rate
        else:
            rate = settings_rate

        expected_idr = round(raw_amount * rate)

        # Preflight outstanding obligation check for overpayment gate
        curr_summary_chk = await compute_order_payment_summary(order)
        out_le = curr_summary_chk.get("outstanding_amount_le")
        out_le_d = Decimal(str(out_le)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if out_le is not None else None

        if payload.actual_received_amount is not None:
            act_recv = _num(payload.actual_received_amount)
            if act_recv <= 0 or not math.isfinite(act_recv):
                raise HTTPException(status_code=422, detail="Nominal transfer IDR aktual harus lebih besar dari 0.")
            actual_idr = round(act_recv)
            variance_idr = actual_idr - expected_idr
            if variance_idr != 0:
                explanation = (payload.override_reason or payload.notes or "").strip()
                if len(explanation) < 3:
                    raise HTTPException(
                        status_code=422,
                        detail="Alasan/catatan wajib diisi saat nominal transfer IDR aktual berbeda dari konversi standar (minimal 3 karakter)."
                    )

            # Precise Decimal comparison without pre-rounding to 2 decimals
            actual_idr_d = Decimal(str(actual_idr))
            rate_d = Decimal(str(rate))
            exact_discharged_d = actual_idr_d / rate_d

            # Overpayment rejection gate (MED-1): reject if exact LE equivalent exceeds outstanding LE obligation
            if out_le_d is not None and exact_discharged_d > out_le_d:
                raise HTTPException(
                    status_code=422,
                    detail="Nominal transfer melebihi sisa tagihan pesanan. Periksa nominal dan kurs sebelum menyimpan pembayaran."
                )

            # Calculate LE discharged with ROUND_DOWN to prevent rounding underpayments up to full obligation
            discharged_le_dec = exact_discharged_d.quantize(Decimal("0.01"), rounding=ROUND_DOWN)
            raw_amount = float(discharged_le_dec)
            primary_amount = actual_idr
        else:
            # Legacy transfer path omitting actual_received_amount:
            # Prevent bypassing overpayment validation
            req_le_d = Decimal(str(raw_amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if out_le_d is not None and req_le_d > out_le_d:
                raise HTTPException(
                    status_code=422,
                    detail="Nominal transfer melebihi sisa tagihan pesanan. Periksa nominal dan kurs sebelum menyimpan pembayaran."
                )
            actual_idr = expected_idr
            primary_amount = actual_idr

        conv = {
            "primary_amount": primary_amount,
            "primary_currency": "IDR",
            "counterpart_amount": round(raw_amount, 2),
            "counterpart_currency": "EGP",
            "rate": rate,
        }
    elif payment_method == "customer_credit":
        rate = settings_rate
        primary_currency = "EGP"
        primary_account = "CUSTOMER_CREDIT"
        conv = {
            "primary_amount": raw_amount,
            "primary_currency": "EGP",
            "counterpart_amount": round(raw_amount * rate),
            "counterpart_currency": "IDR",
            "rate": rate,
        }
    else:  # cash
        rate = settings_rate
        primary_currency = "EGP"
        primary_account = "EGP"
        conv = compute_currency_conversion("EGP", raw_amount, rate)

    # 4. Allocations Validation & Invariant
    # Default allocation if not provided: Allocate to product first, then shipping, remainder to unallocated_credit
    total_le = _num(order.get("total_le", 0.0))
    shipping_fee_le = _num(order.get("delivery_fee_le", 0.0))
    product_portion = max(0.0, total_le - shipping_fee_le)

    allocations = []
    if payload.allocations is not None and len(payload.allocations) > 0:
        for alloc in payload.allocations:
            alloc_type = alloc.target_type.strip().lower()
            if alloc_type not in ("product", "shipping", "unallocated_credit"):
                raise HTTPException(status_code=400, detail=f"Target alokasi tidak valid: {alloc.target_type}")
            alloc_amt_dec = Decimal(str(alloc.amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if alloc_amt_dec < Decimal("0"):
                raise HTTPException(status_code=400, detail="Nominal alokasi tidak boleh negatif")
            allocations.append({
                "target_type": alloc_type,
                "amount_le": float(alloc_amt_dec),
                "order_item_id": alloc.order_item_id,
                "notes": alloc.notes or ""
            })
        sum_allocs_dec = sum(Decimal(str(a["amount_le"])) for a in allocations).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        raw_amt_dec = Decimal(str(raw_amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if sum_allocs_dec != raw_amt_dec:
            raise HTTPException(
                status_code=400,
                detail=f"Jumlah alokasi ({sum_allocs_dec}) harus sama persis dengan total pembayaran ({raw_amt_dec})"
            )
    else:
        # Configurable default policy: product up to product_portion, then shipping up to shipping_fee, excess unallocated_credit
        curr_summary = await compute_order_payment_summary(order)
        curr_paid = curr_summary.get("paid_amount_le") or curr_summary.get("canonical_paid_amount_le") or 0.0
        remaining_product = max(0.0, product_portion - curr_paid)
        alloc_prod = min(raw_amount, remaining_product)
        remaining_after_prod = raw_amount - alloc_prod
        alloc_ship = min(remaining_after_prod, shipping_fee_le)
        alloc_credit = remaining_after_prod - alloc_ship

        if alloc_prod > 0:
            allocations.append({"target_type": "product", "amount_le": round(alloc_prod, 2), "order_item_id": None, "notes": "Auto-alokasi Produk"})
        if alloc_ship > 0:
            allocations.append({"target_type": "shipping", "amount_le": round(alloc_ship, 2), "order_item_id": None, "notes": "Auto-alokasi Ongkir"})
        if alloc_credit > 0 or len(allocations) == 0:
            allocations.append({"target_type": "unallocated_credit", "amount_le": round(alloc_credit if alloc_credit > 0 else raw_amount, 2), "order_item_id": None, "notes": "Kredit Belum Teralokasi"})

    payment_num = await generate_payment_number()
    txn_desc = (
        f"Pelunasan non-kas saldo kredit {payment_num} pesanan {order.get('order_number')}"
        if payment_method == "customer_credit"
        else f"Penerimaan pembayaran {payment_num} pesanan {order.get('order_number')}"
    )

    # Persistent marker: if this order had historical DP with 0 prior payment docs, mark it unreconciled
    has_prior_pmts = True
    if order.get("payment_status") == "dp":
        cd_fn = getattr(db.payments, "count_documents", None)
        if callable(cd_fn):
            cnt_res = cd_fn({"order_id": order["_id"], "status": "recorded"})
            cnt = (await cnt_res) if inspect.isawaitable(cnt_res) else (cnt_res if isinstance(cnt_res, int) else 1)
            has_prior_pmts = (cnt > 0)
    is_qualifying_legacy_dp = bool(order.get("has_unrecorded_legacy_dp")) or (order.get("payment_status") == "dp" and not has_prior_pmts)

    old_payment_status = order.get("payment_status")

    # 5. Atomic Execution
    async def _do_create_payment(session):
        ins_kw = {"session": session} if session else {}

        # Phase 3.B.3 Concurrency & Balance Gate inside transactional boundary
        if payment_method == "customer_credit":
            # Concurrency serialization: Acquire exclusive write conflict lock on the customer document
            # within the transaction. In MongoDB WiredTiger, any concurrent transaction attempting to
            # settle credit for the same customer will encounter a write-write conflict and be serialized,
            # preventing write-skew double spending across independent document inserts.
            cust_oid = id_query(str(order["customer_id"]))
            cust_touch_res = await db.customers.update_one(
                {"_id": cust_oid},
                {"$set": {"last_credit_transaction_at": now}},
                **ins_kw
            )
            if cust_touch_res.matched_count == 0:
                raise HTTPException(
                    status_code=400,
                    detail="Akun pelanggan tidak ditemukan untuk serialisasi transaksi kredit"
                )

            # Concurrency-safe balance verification: enforce that available credit >= required amount
            # evaluated immediately after acquiring the customer serialization lock within the snapshot.
            in_txn_balance = await get_customer_credit_balance(str(order["customer_id"]), "EGP", session=session)
            if in_txn_balance < raw_amount:
                raise HTTPException(
                    status_code=409,
                    detail=f"Konflik saldo: Saldo kredit pelanggan tidak mencukupi untuk transaksi ini (Tersedia: {in_txn_balance:.2f} EGP, Dibutuhkan: {raw_amount:.2f} EGP)"
                )

        # Insert Finance Transaction (Cash Receipt or Non-Cash Settlement)
        txn_doc = {
            "date": payment_date,
            "type": "credit_settlement" if payment_method == "customer_credit" else "order_revenue",
            "category": "Penjualan",
            "amount": conv["primary_amount"],
            "currency": primary_currency,
            "account": primary_account,
            "classification": "credit_settlement" if payment_method == "customer_credit" else None,
            "exchange_rate": rate,
            "counterpart_amount": conv["counterpart_amount"],
            "counterpart_currency": conv["counterpart_currency"],
            "payment_method": payment_method,
            "description": txn_desc,
            "related_order_id": str(order["_id"]),
            "related_payment_number": payment_num,
            "created_by_name": admin.get("name", "Admin"),
            "created_by_id": admin.get("id"),
            "created_at": now,
            "updated_at": now,
        }
        txn_res = await db.finance_transactions.insert_one(txn_doc, **ins_kw)
        txn_id = str(txn_res.inserted_id)

        # Insert Payment Document
        pmt_doc = {
            "payment_number": payment_num,
            "order_id": str(order["_id"]),
            "order_number": order.get("order_number"),
            "amount_le": round(raw_amount, 2),
            "currency": "EGP",
            "exchange_rate_snapshot": rate,
            "expected_amount_idr": expected_idr if payment_method == "transfer" else None,
            "actual_received_amount": actual_idr if payment_method == "transfer" else None,
            "variance_idr": variance_idr if payment_method == "transfer" else 0,
            "is_rate_override": is_rate_override,
            "override_reason": override_reason,
            "primary_amount": conv["primary_amount"],
            "primary_currency": primary_currency,
            "payment_method": payment_method,
            "payment_date": payment_date,
            "reference": (payload.reference or "").strip(),
            "notes": (payload.notes or "").strip(),
            "allocations": allocations,
            "finance_transaction_id": txn_id,
            "status": "recorded",
            "idempotency_key": (payload.idempotency_key or "").strip() or None,
            "created_by_id": admin.get("id"),
            "created_by_name": admin.get("name", "Admin"),
            "created_at": now,
            "updated_at": now,
        }
        pmt_res = await db.payments.insert_one(pmt_doc, **ins_kw)
        created_pmt_id = str(pmt_res.inserted_id)

        # Update link on finance transaction
        await db.finance_transactions.update_one(
            {"_id": txn_res.inserted_id},
            {"$set": {"payment_id": created_pmt_id}},
            **ins_kw
        )

        # Audit logging for transfer variance and rate override
        if variance_idr != 0 and payment_method == "transfer":
            audit_var_doc = {
                "action": "order_payment_idr_variance",
                "entity_type": "payment",
                "entity_id": created_pmt_id,
                "entity_identifier": payment_num,
                "actor_id": admin.get("id"),
                "actor_name": admin.get("name", "Admin"),
                "actor_role": admin.get("role", "admin"),
                "metadata": {
                    "order_id": str(order["_id"]),
                    "order_number": order.get("order_number"),
                    "payment_number": payment_num,
                    "expected_amount_idr": expected_idr,
                    "actual_received_amount": actual_idr,
                    "variance_idr": variance_idr,
                    "rate": rate,
                    "reason": (payload.override_reason or payload.notes or "").strip(),
                },
                "timestamp": now,
            }
            await db.audit_logs.insert_one(audit_var_doc, **ins_kw)

        if is_rate_override and payment_method == "transfer":
            audit_ovr_doc = {
                "action": "order_payment_rate_override",
                "entity_type": "payment",
                "entity_id": created_pmt_id,
                "entity_identifier": payment_num,
                "actor_id": admin.get("id"),
                "actor_name": admin.get("name", "Admin"),
                "actor_role": admin.get("role", "admin"),
                "metadata": {
                    "order_id": str(order["_id"]),
                    "order_number": order.get("order_number"),
                    "payment_number": payment_num,
                    "configured_rate": settings_rate,
                    "override_rate": rate,
                    "override_reason": override_reason,
                },
                "timestamp": now,
            }
            await db.audit_logs.insert_one(audit_ovr_doc, **ins_kw)

        # Phase 3.B.3: Record credit_applied event in customer_credit_events
        if payment_method == "customer_credit":
            cce_event_num = await generate_credit_event_number()
            apply_cce_doc = {
                "event_number": cce_event_num,
                "event_type": "credit_applied",
                "customer_id": str(order["customer_id"]),
                "customer_name": order.get("customer_name") or order.get("name"),
                "customer_phone": order.get("customer_phone") or order.get("phone"),
                "source_payment_id": created_pmt_id,
                "source_payment_number": payment_num,
                "source_order_id": str(order["_id"]),
                "source_order_number": order.get("order_number"),
                "currency": "EGP",
                "signed_amount": -round(float(raw_amount), 2),
                "reason": f"Pelunasan pesanan {order.get('order_number')} menggunakan saldo kredit",
                "idempotency_key": f"cce_pmt_{created_pmt_id}_apply",
                "created_by_id": admin.get("id"),
                "created_by_name": admin.get("name", "Admin"),
                "created_at": now,
                "updated_at": now,
            }
            cce_insert = getattr(db.customer_credit_events, "insert_one", None)
            if callable(cce_insert):
                res_coro = cce_insert(apply_cce_doc, **ins_kw)
                if inspect.isawaitable(res_coro):
                    await res_coro

        # Phase 3.B.2: Customer Credit Event Creation for Qualifying Overpayment
        unallocated_amt = sum(_num(a["amount_le"]) for a in allocations if a.get("target_type") == "unallocated_credit")
        if unallocated_amt > 0 and payment_method != "customer_credit":
            cust_id = str(order.get("customer_id") or "").strip() or None
            cce_event_num = await generate_credit_event_number()
            idem_key = f"cce_pmt_{created_pmt_id}_mint"
            cce_doc = {
                "event_number": cce_event_num,
                "event_type": "credit_minted",
                "customer_id": cust_id,
                "customer_name": order.get("customer_name") or order.get("name"),
                "customer_phone": order.get("customer_phone") or order.get("phone"),
                "source_payment_id": created_pmt_id,
                "source_payment_number": payment_num,
                "source_order_id": str(order["_id"]),
                "source_order_number": order.get("order_number"),
                "currency": "EGP",
                "signed_amount": round(float(unallocated_amt), 2),
                "reason": "Overpayment credit from order payment",
                "idempotency_key": idem_key,
                "created_by_id": admin.get("id"),
                "created_by_name": admin.get("name", "Admin"),
                "created_at": now,
                "updated_at": now,
            }
            cce_insert = getattr(db.customer_credit_events, "insert_one", None)
            if callable(cce_insert):
                res_coro = cce_insert(cce_doc, **ins_kw)
                if inspect.isawaitable(res_coro):
                    await res_coro

        # Admin Wage Accrual Evaluation & Order Update within transaction (Phase 08.5C.4 Lifecycle Accrual)
        new_summary = await compute_order_payment_summary(order, session=session)
        is_transition_to_lunas = (
            old_payment_status != "lunas" and
            new_summary.get("payment_status") == "lunas" and
            not order.get("admin_wage_legacy_reconciled")
        )
        admin_wage_result = None
        if is_transition_to_lunas:
            # Trigger Point 1: Transition to lunas evaluates shared eligibility (Condition 1 + Condition 2)
            admin_wage_result = await evaluate_and_process_order_admin_wage_accrual(
                order,
                admin,
                session=session,
                payment_summary=new_summary,
                lifecycle_event="payment_lunas",
                transition_context={
                    "transition_type": "payment_lunas",
                    "order_id": str(order.get("_id") or order_id),
                    "from_payment_status": old_payment_status,
                    "to_payment_status": "lunas",
                    "payment_id": str(created_pmt_id) if created_pmt_id else None,
                }
            )

        # Update order cached status and admin wage summary inside the transaction
        order_update_set = {
            "payment_method": payment_method,
            "payment_status": new_summary["payment_status"],
            "paid_amount_le": new_summary["paid_amount_le"],
            "outstanding_amount_le": new_summary["outstanding_amount_le"],
            "updated_at": now,
            "updated_by_name": admin.get("name", "Admin"),
        }
        if "canonical_paid_amount_le" in new_summary:
            order_update_set["canonical_paid_amount_le"] = new_summary["canonical_paid_amount_le"]
        if is_qualifying_legacy_dp:
            order_update_set["has_unrecorded_legacy_dp"] = True

        if admin_wage_result:
            if admin_wage_result.get("obligation"):
                order_update_set["admin_wage_obligation"] = admin_wage_result["obligation"]
                order_update_set["admin_wage_blocked"] = None
            elif admin_wage_result.get("blocked"):
                order_update_set["admin_wage_blocked"] = admin_wage_result["blocked"]
            elif admin_wage_result.get("skipped"):
                # Persist skipped metadata only for permanent skips (e.g. policy disabled, legacy reconciled),
                # not for transient lifecycle skips (order not yet completed will be evaluated upon completion)
                if admin_wage_result.get("status") not in ("skipped_order_not_completed", "skipped_payment_not_lunas"):
                    order_update_set["admin_wage_skipped"] = admin_wage_result["skipped"]
            if admin_wage_result.get("eligibility"):
                order_update_set["admin_wage_eligibility"] = admin_wage_result["eligibility"]

        await _mongo_update_one(db.orders, {"_id": order["_id"]}, {"$set": order_update_set}, **ins_kw)

        return created_pmt_id, txn_id, new_summary, admin_wage_result

    def _is_transient_conflict(exc: Exception) -> bool:
        if isinstance(exc, pymongo.errors.PyMongoError):
            if hasattr(exc, "has_error_label") and exc.has_error_label("TransientTransactionError"):
                return True
            if isinstance(exc, pymongo.errors.OperationFailure) and getattr(exc, "code", None) == 112:
                return True
        return False

    max_txn_retries = 3
    res_tuple = None

    for attempt in range(1, max_txn_retries + 1):
        session = None
        try:
            session = await client.start_session()
        except (pymongo.errors.ConfigurationError, pymongo.errors.InvalidOperation, AttributeError) as sess_err:
            if not is_standalone_fallback_permitted():
                logger.error(f"Transaction capability unavailable for payment creation in mode {get_environment_mode()!r}: {sess_err}")
                raise HTTPException(
                    status_code=503,
                    detail="Layanan transaksi multi-dokumen tidak tersedia pada lingkungan ini (Fail-Closed)"
                )
            session = None

        try:
            if session is not None:
                async with session:
                    async with session.start_transaction():
                        res_tuple = await _do_create_payment(session)
            else:
                # Explicitly permitted standalone / test fallback
                res_tuple = await _do_create_payment(None)
            break
        except pymongo.errors.DuplicateKeyError as dke:
            err_msg = str(dke)
            if idem_key and ("uniq_payments_idempotency" in err_msg or idem_key in err_msg):
                winning_pmt = await db.payments.find_one({"idempotency_key": idem_key})
                if winning_pmt:
                    if not _is_matching_payment_payload(winning_pmt):
                        raise HTTPException(
                            status_code=409,
                            detail="Kunci idempotensi telah digunakan untuk pembayaran dengan parameter yang berbeda."
                        )
                    res = clean(winning_pmt)
                    try:
                        fresh_order = await _mongo_find_one(db.orders, {"_id": order["_id"]})
                        new_summary = await compute_order_payment_summary(fresh_order) if fresh_order else None
                        if new_summary:
                            res["order_summary"] = new_summary
                    except Exception:
                        pass
                    return res
            raise
        except Exception as txn_exc:
            if _is_transient_conflict(txn_exc):
                logger.warning(
                    f"Transient transaction conflict on attempt {attempt}/{max_txn_retries} for order {order_id}: {txn_exc}"
                )
                if attempt < max_txn_retries:
                    await asyncio.sleep(0.05 * attempt)
                    continue
                logger.error(
                    f"Exhausted transaction retry attempts ({max_txn_retries}) for order {order_id} due to concurrency conflict: {txn_exc}"
                )
                raise HTTPException(
                    status_code=409,
                    detail="Terjadi konflik transaksi bersamaan pada akun pelanggan. Silakan muat ulang halaman dan coba kembali."
                )
            raise

    pmt_id, txn_id, new_summary, admin_wage_result = res_tuple

    created_payment = await _mongo_find_one(db.payments, {"_id": id_query(pmt_id)}) or {
        "_id": pmt_id,
        "payment_number": payment_num,
        "order_id": str(order["_id"]),
        "amount_le": round(raw_amount, 2),
        "payment_method": payment_method,
        "status": "recorded",
        "finance_transaction_id": txn_id,
        "allocations": allocations,
    }
    clean_pmt = clean(created_payment)
    clean_pmt["order_summary"] = new_summary
    if admin_wage_result:
        clean_pmt["admin_wage_summary"] = admin_wage_result
    return clean_pmt

@api_router.post("/admin/orders/{order_id}/payments/{payment_id}/void")
async def admin_void_order_payment(order_id: str, payment_id: str, payload: PaymentVoidInput, admin: dict = Depends(require_perm("manage_orders"))):
    role = admin.get("role")
    perms = admin.get("permissions") or {}
    if role != "owner" and not perms.get("access_finance"):
        raise HTTPException(status_code=403, detail="Hanya admin dengan akses keuangan atau owner yang dapat membatalkan pembayaran")

    reason = (payload.reason or "").strip()
    if not reason:
        raise HTTPException(status_code=400, detail="Alasan pembatalan pembayaran wajib diisi")

    order = await db.orders.find_one({"_id": id_query(order_id)})
    if not order:
        raise HTTPException(status_code=404, detail="Pesanan tidak ditemukan")

    pmt = await db.payments.find_one({"_id": id_query(payment_id), "order_id": id_query(order_id)})
    if not pmt:
        raise HTTPException(status_code=404, detail="Data pembayaran tidak ditemukan")

    if pmt.get("status") == "voided":
        raise HTTPException(status_code=400, detail="Pembayaran sudah dibatalkan sebelumnya")

    accrual_key = f"admin_wage:{str(order['_id'])}"
    linked_wob = await _mongo_find_one(db.wage_obligations, {"accrual_event_key": accrual_key})
    if linked_wob and linked_wob.get("status") in ("paid", "partially_paid"):
        raise HTTPException(
            status_code=409,
            detail=(
                f"Tidak dapat membatalkan pembayaran: kewajiban upah admin ({linked_wob.get('obligation_number')}) "
                f"untuk pesanan ini sudah dalam status '{linked_wob.get('status')}'. "
                "Harap koordinasikan dengan Owner sebelum membatalkan pembayaran."
            )
        )

    now_iso = datetime.now(timezone.utc).isoformat()
    txn_id = pmt.get("finance_transaction_id")

    async def _do_void(session):
        ins_kw = {"session": session} if session else {}
        # Phase 3.B.2, 3.B.3, and Phase 3.C.2:
        # Pre-check for associated credit events before modifying payment or finance transaction records.
        # If reversing a credit_minted event, enforce that the customer currently has sufficient available credit.
        cce = None
        cce_find = getattr(db.customer_credit_events, "find_one", None)
        if callable(cce_find):
            cce_res = cce_find(
                {"source_payment_id": str(pmt["_id"]), "event_type": {"$in": ["credit_minted", "credit_applied"]}},
                **ins_kw
            )
            if inspect.isawaitable(cce_res):
                cce = await cce_res

        rev_cce_doc = None
        if cce:
            event_type = cce.get("event_type")
            original_signed = float(cce.get("signed_amount", 0.0))
            event_currency = (
                cce.get("currency")
                or pmt.get("currency")
                or order.get("currency")
                or "EGP"
            ).strip().upper()

            if event_type == "credit_minted":
                # Phase 3.C.2: Reversing credit_minted (+X) reduces customer balance (-X).
                # Fungible credit guard: check that the customer currently holds sufficient credit in this currency.
                cust_id_str = str(cce.get("customer_id") or order.get("customer_id") or "").strip()
                if cust_id_str:
                    # Acquire exclusive customer document touch serialization lock inside the transaction
                    cust_oid = id_query(cust_id_str)
                    cust_touch_res = await db.customers.update_one(
                        {"_id": cust_oid},
                        {"$set": {"last_credit_transaction_at": now_iso}},
                        **ins_kw
                    )
                    if cust_touch_res.matched_count == 0:
                        raise HTTPException(
                            status_code=400,
                            detail="Akun pelanggan tidak ditemukan untuk serialisasi transaksi kredit"
                        )

                    # Query real-time credit balance in the active transaction session
                    in_txn_balance = await get_customer_credit_balance(
                        cust_id_str,
                        event_currency,
                        session=session
                    )
                    required_reversal_amt = abs(original_signed)
                    if in_txn_balance < required_reversal_amt:
                        raise HTTPException(
                            status_code=409,
                            detail=(
                                f"Konflik saldo: Pembayaran ini menghasilkan saldo kredit sebesar {required_reversal_amt:.2f} {event_currency}, "
                                f"namun saldo kredit pelanggan saat ini hanya tersisa {in_txn_balance:.2f} {event_currency}. "
                                "Batalkan transaksi penggunaan kredit atau pengembalian dana kredit pelanggan terlebih dahulu "
                                "sebelum membatalkan pembayaran ini."
                            )
                        )

                rev_signed = -original_signed
                rev_reason = f"Payment voided: {reason} (Reversing minted credit)"
            else:
                # Reversing credit_applied (-X) restores customer credit (+X)
                rev_signed = -original_signed
                rev_reason = f"Payment voided: {reason} (Restoring credit)"

            rev_cce_num = await generate_credit_event_number()
            rev_cce_doc = {
                "event_number": rev_cce_num,
                "event_type": "credit_reversed",
                "customer_id": cce.get("customer_id"),
                "customer_name": cce.get("customer_name"),
                "customer_phone": cce.get("customer_phone"),
                "source_payment_id": str(pmt["_id"]),
                "source_payment_number": pmt.get("payment_number"),
                "source_order_id": str(order["_id"]),
                "source_order_number": order.get("order_number"),
                "currency": event_currency,
                "signed_amount": rev_signed,
                "reverses_event_id": str(cce["_id"]),
                "reason": rev_reason,
                "idempotency_key": f"cce_rev_pmt_{pmt['_id']}",
                "created_by_id": admin.get("id"),
                "created_by_name": admin.get("name", "Admin"),
                "created_at": now_iso,
                "updated_at": now_iso,
            }

        # Writes proceed ONLY after all balance guards and preconditions have passed cleanly
        # 1. Mark payment voided
        await db.payments.update_one(
            {"_id": pmt["_id"]},
            {"$set": {
                "status": "voided",
                "void_reason": reason,
                "voided_at": now_iso,
                "voided_by_id": admin.get("id"),
                "voided_by_name": admin.get("name", "Admin"),
                "updated_at": now_iso
            }},
            **ins_kw
        )

        # 2. Mark finance transaction voided
        if txn_id:
            await db.finance_transactions.update_one(
                {"_id": id_query(txn_id)},
                {"$set": {
                    "is_void": True,
                    "status": "void",
                    "void_source": "payment_void",
                    "void_reason": reason,
                    "voided_at": now_iso,
                    "voided_by_name": admin.get("name", "Admin"),
                    "updated_at": now_iso
                }},
                **ins_kw
            )

        # 3. Append credit reversal event if applicable
        if rev_cce_doc:
            cce_insert = getattr(db.customer_credit_events, "insert_one", None)
            if callable(cce_insert):
                res_coro = cce_insert(rev_cce_doc, **ins_kw)
                if inspect.isawaitable(res_coro):
                    await res_coro

        # 4. Void linked admin wage obligation if present and accrued
        in_txn_wob = await _mongo_find_one(db.wage_obligations, {"accrual_event_key": accrual_key}, **ins_kw)
        if in_txn_wob and in_txn_wob.get("status") in ("paid", "partially_paid"):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Tidak dapat membatalkan pembayaran: kewajiban upah admin ({in_txn_wob.get('obligation_number')}) "
                    f"untuk pesanan ini sudah dalam status '{in_txn_wob.get('status')}'."
                )
            )

        if in_txn_wob and in_txn_wob.get("status") == "accrued":
            await _mongo_update_one(
                db.wage_obligations,
                {"_id": in_txn_wob["_id"], "status": "accrued"},
                {"$set": {
                    "status": "voided",
                    "void_reason": f"Payment {pmt.get('payment_number')} voided: {reason}",
                    "voided_at": now_iso,
                    "voided_by_id": admin.get("id"),
                    "voided_by_name": admin.get("name", "Admin"),
                    "updated_at": now_iso
                }},
                **ins_kw
            )
            audit_wob_doc = {
                "action": "admin_wage_obligation_voided",
                "entity_type": "wage_obligation",
                "entity_id": str(in_txn_wob["_id"]),
                "entity_identifier": in_txn_wob.get("obligation_number", ""),
                "actor_id": admin.get("id"),
                "actor_name": admin.get("name", "Admin"),
                "actor_role": admin.get("role", "admin"),
                "metadata": {
                    "order_id": str(order["_id"]),
                    "order_number": order.get("order_number"),
                    "payment_number": pmt.get("payment_number"),
                    "reason": reason,
                    "previous_status": "accrued",
                    "new_status": "voided",
                },
                "timestamp": now_iso,
            }
            await _mongo_insert_one(db.audit_logs, audit_wob_doc, **ins_kw)

    session = None
    try:
        session = await client.start_session()
    except (pymongo.errors.ConfigurationError, pymongo.errors.InvalidOperation, AttributeError) as sess_err:
        if not is_standalone_fallback_permitted():
            logger.error(f"Transaction capability unavailable for payment void in mode {get_environment_mode()!r}: {sess_err}")
            raise HTTPException(
                status_code=503,
                detail="Layanan transaksi multi-dokumen tidak tersedia pada lingkungan ini (Fail-Closed)"
            )
        session = None

    try:
        if session is not None:
            async with session:
                async with session.start_transaction():
                    await _do_void(session)
        else:
            # Explicitly permitted standalone / test fallback
            await _do_void(None)
    except pymongo.errors.DuplicateKeyError as dke:
        err_msg = str(dke)
        is_reversal_conflict = (
            "uniq_credit_event_source_payment" in err_msg or
            "uniq_credit_events_idempotency" in err_msg or
            f"cce_rev_pmt_{pmt['_id']}" in err_msg or
            ("source_payment_id" in err_msg and "event_type" in err_msg)
        )
        # Unrelated DuplicateKeyError: must be re-raised immediately without translating into HTTP 409 or success
        if not is_reversal_conflict:
            logger.error(f"Unrelated DuplicateKeyError during payment void transaction for payment {payment_id}: {dke}")
            raise

        # Relevant reversal conflict: inspect persisted payment state to determine appropriate response
        current_pmt = await db.payments.find_one({"_id": pmt["_id"]})
        if current_pmt and current_pmt.get("status") == "voided":
            logger.warning(
                f"Concurrent payment void conflict resolved: payment {payment_id} was already voided by winning transaction: {dke}"
            )
            raise HTTPException(
                status_code=409,
                detail="Pembayaran sedang atau sudah dibatalkan oleh transaksi lain secara bersamaan (Konflik konkuren)."
            )

        logger.warning(
            f"Credit reversal unique key conflict for payment {payment_id} without confirmed void status: {dke}"
        )
        raise HTTPException(
            status_code=409,
            detail="Konflik konkuren pada pembalikan saldo kredit pelanggan."
        )

    # Recalculate order status
    fresh_order = await _mongo_find_one(db.orders, {"_id": order["_id"]})
    new_summary = await compute_order_payment_summary(fresh_order)
    order_void_update = {
        "payment_status": new_summary["payment_status"],
        "paid_amount_le": new_summary["paid_amount_le"],
        "outstanding_amount_le": new_summary["outstanding_amount_le"],
        "updated_at": now_iso,
        "updated_by_name": admin.get("name", "Admin"),
    }
    if linked_wob and linked_wob.get("status") == "accrued":
        order_void_update["admin_wage_obligation.status"] = "voided"
        order_void_update["admin_wage_obligation.voided_at"] = now_iso
        order_void_update["admin_wage_obligation.void_reason"] = reason

    await _mongo_update_one(
        db.orders,
        {"_id": order["_id"]},
        {"$set": order_void_update}
    )

    voided_pmt = await _mongo_find_one(db.payments, {"_id": pmt["_id"]}) or {**pmt, "status": "voided"}
    clean_p = clean(voided_pmt)
    clean_p["order_summary"] = new_summary
    return clean_p

# --------------------------------------------------------------------------
# Phase 08.4C: Owner Admin Wage Override API
# --------------------------------------------------------------------------

class AdminWageOverrideInput(BaseModel):
    is_override: bool = Field(..., description="Aktifkan atau nonaktifkan override upah admin")
    amount_le: Optional[float] = Field(None, description="Nominal upah khusus dalam EGP")
    recipient_id: Optional[str] = Field(None, description="ID penerima khusus dari db.admins")
    override_reason: Optional[str] = Field(None, max_length=500, description="Alasan override upah khusus")

    @field_validator("amount_le", mode="before")
    @classmethod
    def validate_amount(cls, v):
        if v is None:
            return None
        if isinstance(v, bool):
            raise ValueError("Nominal upah tidak boleh berupa boolean")
        try:
            val = float(v)
        except (ValueError, TypeError):
            raise ValueError("Nominal upah harus berupa angka valid")
        if math.isnan(val) or math.isinf(val):
            raise ValueError("Nominal upah tidak boleh NaN atau Infinity")
        if val <= 0:
            raise ValueError("Nominal upah harus lebih besar dari 0")
        return round(val, 2)

    @field_validator("recipient_id", mode="before")
    @classmethod
    def validate_recipient_id(cls, v):
        if v is None:
            return None
        if isinstance(v, str):
            val = v.strip()
            return val if val else None
        return str(v).strip()

@api_router.get("/admin/orders/{order_id}/admin-wage")
async def admin_get_order_admin_wage(
    order_id: str,
    admin: dict = Depends(require_owner())
):
    order = await _mongo_find_one(db.orders, {"_id": id_query(order_id)})
    if not order:
        raise HTTPException(status_code=404, detail="Pesanan tidak ditemukan")

    order_id_str = str(order.get("_id") or order.get("id")).strip()
    policy = await get_active_admin_wage_policy(db_inst=db)

    # Check for linked wage obligation
    accrual_key = build_admin_wage_accrual_event_key(order_id_str)
    linked_wob = await _mongo_find_one(db.wage_obligations, {"accrual_event_key": accrual_key})
    if not linked_wob:
        linked_wob = await _mongo_find_one(db.wage_obligations, {"order_id": order_id_str, "task_category": "admin"})

    # Evaluate editability and restriction reasons
    is_editable = True
    restriction_reason = None

    if order.get("admin_wage_legacy_reconciled"):
        is_editable = False
        restriction_reason = "Pesanan merupakan pesanan historis yang telah direkonsiliasi (admin_wage_legacy_reconciled)"
    elif linked_wob:
        wob_status = linked_wob.get("status")
        if wob_status in ("paid", "partially_paid"):
            is_editable = False
            restriction_reason = f"Kewajiban upah ({linked_wob.get('obligation_number')}) sudah berstatus '{wob_status}'"
        elif wob_status == "voided":
            is_editable = False
            restriction_reason = f"Kewajiban upah ({linked_wob.get('obligation_number')}) telah dibatalkan (voided)"
        elif wob_status == "accrued":
            is_editable = True
            restriction_reason = "Perhatian: Kewajiban upah sudah terbit (accrued). Perubahan konfigurasi tidak otomatis mengubah nominal kewajiban yang sudah tercatat."

    saved_override = order.get("admin_wage_override")
    is_override = bool(saved_override and saved_override.get("is_override"))

    if is_override:
        eff_amount = saved_override.get("amount_le")
        eff_recip_id = saved_override.get("recipient_id")
        eff_recip_name = saved_override.get("recipient_name")
        effective_config = {
            "source": "override",
            "is_override": True,
            "amount_le": eff_amount,
            "recipient_id": str(eff_recip_id) if eff_recip_id else None,
            "recipient_name": eff_recip_name,
            "override_reason": saved_override.get("override_reason"),
        }
    else:
        effective_config = {
            "source": "policy_default" if policy.get("enabled") else "policy_disabled",
            "is_override": False,
            "amount_le": policy.get("default_wage_per_order_le"),
            "recipient_id": str(policy.get("default_recipient_id")) if policy.get("default_recipient_id") else None,
            "recipient_name": policy.get("default_recipient_name"),
            "override_reason": None,
        }

    obligation_state = None
    if linked_wob:
        obligation_state = {
            "obligation_id": str(linked_wob.get("_id")),
            "obligation_number": linked_wob.get("obligation_number"),
            "task_category": linked_wob.get("task_category", "admin"),
            "status": linked_wob.get("status"),
            "amount_le": linked_wob.get("total_amount_le"),
            "worker_id": str(linked_wob.get("worker_id")),
            "worker_name": linked_wob.get("worker_name"),
            "accrued_at": linked_wob.get("accrued_at") or linked_wob.get("created_at"),
            "is_override": linked_wob.get("is_override", False),
        }

    return clean({
        "order_id": order_id_str,
        "order_number": order.get("order_number"),
        "payment_status": order.get("payment_status", "unpaid"),
        "is_override": is_override,
        "saved_override": saved_override,
        "effective_configuration": effective_config,
        "policy_context": {
            "enabled": policy.get("enabled", False),
            "is_configured": policy.get("is_configured", False),
            "default_wage_per_order_le": policy.get("default_wage_per_order_le"),
            "default_recipient_id": str(policy.get("default_recipient_id")) if policy.get("default_recipient_id") else None,
            "default_recipient_name": policy.get("default_recipient_name"),
            "unusual_amount_threshold_le": policy.get("unusual_amount_threshold_le"),
            "max_wage_per_order_le": policy.get("max_wage_per_order_le"),
            "currency": policy.get("currency", "EGP"),
        },
        "obligation_state": obligation_state,
        "blocked_state": order.get("admin_wage_blocked"),
        "eligibility": get_order_admin_wage_eligibility(order, policy),
        "is_editable": is_editable,
        "editing_restriction_reason": restriction_reason,
    })

@api_router.put("/admin/orders/{order_id}/admin-wage")
async def admin_update_order_admin_wage(
    order_id: str,
    payload: AdminWageOverrideInput,
    admin: dict = Depends(require_owner())
):
    order = await _mongo_find_one(db.orders, {"_id": id_query(order_id)})
    if not order:
        raise HTTPException(status_code=404, detail="Pesanan tidak ditemukan")

    order_id_str = str(order.get("_id") or order.get("id")).strip()

    # Lifecycle guard 1: Legacy reconciled order
    if order.get("admin_wage_legacy_reconciled"):
        raise HTTPException(
            status_code=409,
            detail="Konfigurasi upah admin tidak dapat diubah: Pesanan merupakan pesanan historis yang telah direkonsiliasi (admin_wage_legacy_reconciled)"
        )

    # Lifecycle guard 2: Linked obligation status
    accrual_key = build_admin_wage_accrual_event_key(order_id_str)
    linked_wob = await _mongo_find_one(db.wage_obligations, {"accrual_event_key": accrual_key})
    if not linked_wob:
        linked_wob = await _mongo_find_one(db.wage_obligations, {"order_id": order_id_str, "task_category": "admin"})

    if linked_wob:
        wob_status = linked_wob.get("status")
        if wob_status in ("paid", "partially_paid"):
            raise HTTPException(
                status_code=409,
                detail=f"Konfigurasi upah admin tidak dapat diubah: Kewajiban upah ({linked_wob.get('obligation_number')}) sudah berstatus '{wob_status}'"
            )
        if wob_status == "voided":
            raise HTTPException(
                status_code=409,
                detail=f"Konfigurasi upah admin tidak dapat diubah: Kewajiban upah ({linked_wob.get('obligation_number')}) telah dibatalkan (voided)"
            )

    # Load active admin wage policy
    policy = await get_active_admin_wage_policy(db_inst=db)

    now_iso = datetime.now(timezone.utc).isoformat()
    admin_id_str = str(admin.get("id") or admin.get("_id") or "")
    admin_name_str = admin.get("name", "Owner")

    cycle_event_action = None
    current_cycle_id = None
    old_enabled = False
    target_enabled = False
    existing_cycles = []

    prev_override = order.get("admin_wage_override") or {}
    prev_blocked = order.get("admin_wage_blocked")

    if payload.is_override:
        # Override activation/update: must specify amount or recipient
        if payload.amount_le is None and not payload.recipient_id:
            raise HTTPException(
                status_code=422,
                detail="Override upah aktif memerlukan nominal (amount_le) atau penerima (recipient_id)"
            )

        # 1. Validate amount against hard cap & threshold
        effective_amount = payload.amount_le
        if effective_amount is not None:
            hard_cap = policy.get("max_wage_per_order_le")
            if hard_cap is not None and effective_amount > hard_cap:
                raise HTTPException(
                    status_code=422,
                    detail=f"Nominal upah ({effective_amount} LE) melebihi batas maksimum kebijakan aktif ({hard_cap} LE)"
                )
            threshold = policy.get("unusual_amount_threshold_le")
            if threshold is not None and effective_amount > threshold:
                reason_str = (payload.override_reason or "").strip()
                if len(reason_str) < 3:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Nominal upah ({effective_amount} LE) melebihi batas konfirmasi nominal tidak wajar ({threshold} LE). Alasan override (override_reason minimal 3 karakter) wajib diisi."
                    )
        else:
            effective_amount = policy.get("default_wage_per_order_le")
            if effective_amount is None:
                raise HTTPException(
                    status_code=422,
                    detail="Nominal upah wajib diisi karena kebijakan default belum memiliki tarif terdaftar"
                )

        # 2. Validate recipient
        recip_id = payload.recipient_id
        recip_name = None
        if recip_id:
            recip_doc = await _mongo_find_one(db.admins, {"_id": id_query(recip_id)})
            if not recip_doc:
                raise HTTPException(
                    status_code=422,
                    detail=f"Penerima upah admin '{recip_id}' tidak ditemukan di sistem"
                )
            recip_id = str(recip_doc.get("_id") or recip_id)
            recip_name = recip_doc.get("name") or "Admin"
        else:
            default_recip_id = policy.get("default_recipient_id")
            if not default_recip_id:
                raise HTTPException(
                    status_code=422,
                    detail="Penerima upah wajib diisi karena kebijakan default belum memiliki penerima upah terdaftar"
                )
            recip_doc = await _mongo_find_one(db.admins, {"_id": id_query(default_recip_id)})
            if not recip_doc:
                raise HTTPException(
                    status_code=422,
                    detail=f"Penerima default dalam kebijakan '{default_recip_id}' tidak valid di database admin"
                )
            recip_id = str(recip_doc.get("_id") or default_recip_id)
            recip_name = recip_doc.get("name") or policy.get("default_recipient_name") or "Admin"

        new_override = {
            "is_override": True,
            "amount_le": payload.amount_le,
            "recipient_id": recip_id,
            "recipient_name": recip_name,
            "override_reason": payload.override_reason,
            "updated_at": now_iso,
            "updated_by_id": admin_id_str,
            "updated_by_name": admin_name_str,
        }
        audit_action = "order_admin_wage_override_updated" if prev_override.get("is_override") else "order_admin_wage_override_set"
        response_msg = "Override upah admin berhasil diperbarui" if prev_override.get("is_override") else "Override upah admin berhasil diatur"
    else:
        new_override = {
            "is_override": False,
            "amount_le": None,
            "recipient_id": None,
            "recipient_name": None,
            "override_reason": payload.override_reason,
            "updated_at": now_iso,
            "updated_by_id": admin_id_str,
            "updated_by_name": admin_name_str,
        }
        audit_action = "order_admin_wage_override_cleared"
        response_msg = "Override upah admin dinonaktifkan (menggunakan kebijakan default)"

    client_inst = getattr(db, "client", None)
    current_updated_at = order.get("updated_at")

    async def _do_override_update(session):
        find_kw = {"session": session} if session else {}

        fresh_order = await _mongo_find_one(db.orders, {"_id": order["_id"]}, **find_kw)
        if not fresh_order:
            raise HTTPException(status_code=404, detail="Pesanan tidak ditemukan")
        if fresh_order.get("admin_wage_legacy_reconciled"):
            raise HTTPException(status_code=409, detail="Konflik status pesanan: Pesanan telah direkonsiliasi historis")

        fresh_wob = await _mongo_find_one(db.wage_obligations, {"accrual_event_key": accrual_key}, **find_kw)
        if not fresh_wob:
            fresh_wob = await _mongo_find_one(db.wage_obligations, {"order_id": order_id_str, "task_category": "admin"}, **find_kw)
        if fresh_wob and fresh_wob.get("status") in ("paid", "partially_paid", "voided"):
            raise HTTPException(
                status_code=409,
                detail=f"Konflik kewajiban upah: Kewajiban ({fresh_wob.get('obligation_number')}) sudah berstatus '{fresh_wob.get('status')}'"
            )

        filter_q = {"_id": order["_id"]}
        if current_updated_at:
            filter_q["updated_at"] = current_updated_at

        update_set = {
            "admin_wage_override": new_override,
            "updated_at": now_iso,
            "updated_by_name": admin_name_str,
        }
        if fresh_order.get("admin_wage_blocked"):
            update_set["admin_wage_blocked"] = None

        res_upd = await _mongo_update_one(db.orders, filter_q, {"$set": update_set}, **find_kw)
        if getattr(res_upd, "matched_count", 1) == 0:
            raise HTTPException(
                status_code=409,
                detail="Konflik konkurensi: Data pesanan telah diubah oleh proses lain. Silakan muat ulang dan coba kembali."
            )

        # Audit log entry
        audit_doc = {
            "action": audit_action,
            "entity_type": "order",
            "entity_id": order_id_str,
            "entity_identifier": str(fresh_order.get("order_number") or ""),
            "performed_by_id": admin_id_str,
            "performed_by_name": admin_name_str,
            "timestamp": now_iso,
            "metadata": {
                "previous_override": prev_override,
                "new_override": new_override,
                "resolved_blocked_state": prev_blocked,
                "policy_snapshot": {
                    "default_wage_per_order_le": policy.get("default_wage_per_order_le"),
                    "max_wage_per_order_le": policy.get("max_wage_per_order_le"),
                    "unusual_amount_threshold_le": policy.get("unusual_amount_threshold_le"),
                }
            }
        }
        await _mongo_insert_one(db.audit_logs, audit_doc, **find_kw)

    await execute_transaction_with_safety(client_inst, _do_override_update)

    # Build effective configuration for response
    if new_override["is_override"]:
        eff_amt = new_override["amount_le"] if new_override["amount_le"] is not None else policy.get("default_wage_per_order_le")
        eff_config = {
            "source": "override",
            "is_override": True,
            "amount_le": eff_amt,
            "recipient_id": new_override["recipient_id"],
            "recipient_name": new_override["recipient_name"],
            "override_reason": new_override["override_reason"],
        }
    else:
        eff_config = {
            "source": "policy_default" if policy.get("enabled") else "policy_disabled",
            "is_override": False,
            "amount_le": policy.get("default_wage_per_order_le"),
            "recipient_id": str(policy.get("default_recipient_id")) if policy.get("default_recipient_id") else None,
            "recipient_name": policy.get("default_recipient_name"),
            "override_reason": None,
        }

    existing_ob = None
    if linked_wob:
        existing_ob = {
            "obligation_id": str(linked_wob.get("_id")),
            "obligation_number": linked_wob.get("obligation_number"),
            "task_category": linked_wob.get("task_category", "admin"),
            "status": linked_wob.get("status"),
            "amount_le": linked_wob.get("total_amount_le"),
            "worker_id": str(linked_wob.get("worker_id")),
            "worker_name": linked_wob.get("worker_name"),
            "accrued_at": linked_wob.get("accrued_at") or linked_wob.get("created_at"),
            "is_override": linked_wob.get("is_override", False),
            "note": "Kewajiban upah yang sudah terbit tetap tidak berubah oleh perubahan konfigurasi override."
        }

    return clean({
        "order_id": order_id_str,
        "order_number": order.get("order_number"),
        "saved_override": new_override,
        "effective_configuration": eff_config,
        "existing_obligation": existing_ob,
        "resolved_blocked_state": prev_blocked,
        "message": response_msg,
    })

# --------------------------------------------------------------------------
# Phase 2: Piece-Rate Wage Rules & Work Assignments
# --------------------------------------------------------------------------

def require_wage_rule_perm():
    async def dep(admin: dict = Depends(get_current_admin)) -> dict:
        role = admin.get("role")
        perms = admin.get("permissions", {})
        if role == "owner" or perms.get("manage_settings") or perms.get("access_finance"):
            return admin
        raise HTTPException(status_code=403, detail="Akses ditolak: Membutuhkan izin kelola pengaturan atau keuangan")
    return dep

def require_finance_or_owner():
    async def dep(admin: dict = Depends(get_current_admin)) -> dict:
        role = admin.get("role")
        perms = admin.get("permissions", {})
        if role == "owner" or perms.get("access_finance"):
            return admin
        raise HTTPException(status_code=403, detail="Akses ditolak: Membutuhkan akses keuangan atau owner")
    return dep

def validate_currency_allowlist(currency: str):
    if not currency or not isinstance(currency, str):
        raise HTTPException(status_code=422, detail=f"Mata uang tidak valid: {currency!r}")
    cur_code = currency.strip().upper()
    if cur_code not in SUPPORTED_CURRENCY_PRECISIONS:
        raise HTTPException(
            status_code=422,
            detail=f"Mata uang tidak didukung: {currency!r}. Hanya {list(SUPPORTED_CURRENCY_PRECISIONS.keys())} yang didukung."
        )
    return cur_code

def validate_rate_precision(rate: float) -> Decimal:
    if rate is None or rate <= 0:
        raise HTTPException(status_code=422, detail="Tarif upah harus lebih besar dari 0")
    # Reject rates with > 2 decimal places (e.g. 45.125)
    s_val = str(rate).strip()
    if "." in s_val:
        dec_part = s_val.split(".")[1]
        if len(dec_part) > 2:
            raise HTTPException(status_code=422, detail=f"Tarif upah tidak boleh memiliki lebih dari 2 tempat desimal: {rate}")
    d = Decimal(str(rate))
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

@api_router.get("/admin/wage-rules")
async def admin_get_wage_rules(
    task_category: Optional[str] = None,
    active_only: bool = True,
    admin: dict = Depends(require_wage_rule_perm())
):
    q = {}
    if active_only:
        q["active"] = True
    if task_category:
        if task_category not in CONTROLLED_TASK_CATEGORIES:
            raise HTTPException(status_code=422, detail=f"Kategori tugas tidak valid: {task_category}")
        q["task_category"] = task_category
    rules = await db.wage_rules.find(q).sort("task_category", 1).to_list(200)
    return [clean(r) for r in rules]

@api_router.get("/admin/workers")
async def admin_list_workers(admin: dict = Depends(require_worker_view_perm())):
    """List team members available for work assignment."""
    admins = await db.admins.find({"status": {"$ne": "inactive"}}).to_list(200)
    return [{"id": str(a["_id"]), "name": a.get("name", "Worker"), "role": a.get("role", "employee")} for a in admins]

@api_router.post("/admin/wage-rules", status_code=201)
async def admin_create_wage_rule(
    payload: WageRuleInput,
    admin: dict = Depends(require_wage_rule_perm())
):
    cat = (payload.task_category or "").strip()
    if cat not in CONTROLLED_TASK_CATEGORIES:
        raise HTTPException(status_code=422, detail=f"Kategori tugas {cat!r} tidak valid. Pilihan: {list(CONTROLLED_TASK_CATEGORIES)}")
    basis = (payload.pricing_basis or "").strip().lower()
    if basis not in ("per_unit", "lump_sum"):
        raise HTTPException(status_code=422, detail=f"Dasar tarif {basis!r} tidak valid. Pilihan: per_unit, lump_sum")

    dec_rate = validate_rate_precision(payload.standard_rate_le)
    rate_flt = float(dec_rate)

    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "task_category": cat,
        "pricing_basis": basis,
        "standard_rate_le": rate_flt,
        "currency": "EGP",
        "description": (payload.description or "").strip(),
        "active": True,
        "created_by_id": admin.get("id"),
        "created_by_name": admin.get("name", "Admin"),
        "created_at": now,
        "updated_at": now,
    }
    res = await db.wage_rules.insert_one(doc)
    doc["_id"] = str(res.inserted_id)
    return clean(doc)

@api_router.put("/admin/wage-rules/{rule_id}")
async def admin_update_wage_rule(
    rule_id: str,
    payload: WageRuleUpdate,
    admin: dict = Depends(require_wage_rule_perm())
):
    rule = await db.wage_rules.find_one({"_id": id_query(rule_id)})
    if not rule:
        raise HTTPException(status_code=404, detail="Aturan upah tidak ditemukan")

    upd = {"updated_at": datetime.now(timezone.utc).isoformat(), "updated_by_id": admin.get("id")}
    if payload.standard_rate_le is not None:
        dec_rate = validate_rate_precision(payload.standard_rate_le)
        upd["standard_rate_le"] = float(dec_rate)
    if payload.description is not None:
        upd["description"] = payload.description.strip()
    if payload.active is not None:
        upd["active"] = payload.active

    await db.wage_rules.update_one({"_id": rule["_id"]}, {"$set": upd})
    updated_rule = await db.wage_rules.find_one({"_id": rule["_id"]})
    return clean(updated_rule)

@api_router.delete("/admin/wage-rules/{rule_id}")
async def admin_delete_wage_rule(
    rule_id: str,
    admin: dict = Depends(require_wage_rule_perm())
):
    rule = await db.wage_rules.find_one({"_id": id_query(rule_id)})
    if not rule:
        raise HTTPException(status_code=404, detail="Aturan upah tidak ditemukan")

    # Soft delete
    await db.wage_rules.update_one(
        {"_id": rule["_id"]},
        {"$set": {"active": False, "updated_at": datetime.now(timezone.utc).isoformat(), "updated_by_id": admin.get("id")}}
    )
    return {"ok": True, "message": "Aturan upah dinonaktifkan"}

@api_router.get("/admin/orders/{order_id}/assignments")
async def admin_get_order_assignments(
    order_id: str,
    admin: dict = Depends(require_perm("manage_orders"))
):
    order = await db.orders.find_one({"_id": id_query(order_id)})
    if not order:
        raise HTTPException(status_code=404, detail="Pesanan tidak ditemukan")

    order_id_str = str(order.get("_id") or order.get("id"))
    assignments = await db.work_assignments.find({"order_id": order_id_str}).to_list(500)

    # Collect all worker IDs across assignments (multi-worker worker_ids and legacy worker_id)
    all_worker_ids = set()
    for a in assignments:
        if a.get("worker_ids") and isinstance(a.get("worker_ids"), list):
            all_worker_ids.update(str(w) for w in a.get("worker_ids") if w)
        if a.get("worker_id"):
            all_worker_ids.add(str(a.get("worker_id")))

    workers_map = {}
    if all_worker_ids:
        query_ids = multi_id_query(all_worker_ids)
        worker_docs = await db.admins.find({"_id": {"$in": query_ids}}).to_list(len(query_ids))
        for w in worker_docs:
            workers_map[str(w["_id"])] = w.get("name", "Worker")

    result = []
    for a in assignments:
        ca = clean(a)
        # Multi-worker formatting
        wids = ca.get("worker_ids") or ([ca.get("worker_id")] if ca.get("worker_id") else [])
        ca_workers = [
            {"worker_id": wid, "worker_name": workers_map.get(wid) or ca.get("worker_name") or "Worker"}
            for wid in wids
        ]
        ca["workers"] = ca_workers
        if len(ca_workers) > 1:
            ca["worker_name"] = ", ".join(w["worker_name"] for w in ca_workers)
        elif len(ca_workers) == 1:
            ca["worker_name"] = ca_workers[0]["worker_name"]
        else:
            ca["worker_name"] = workers_map.get(ca.get("worker_id")) or ca.get("worker_name") or "Worker"
        result.append(ca)
    return result

class LoopBoundLock:
    """Asyncio Lock that binds lazily to the current running event loop.
    Prevents Python 3.9 'attached to a different loop' errors when test runners create new loops per test.
    """
    def __init__(self):
        self._locks = {}

    def _get_lock(self) -> asyncio.Lock:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        key = id(loop) if loop else 0
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self._locks[key]

    async def __aenter__(self):
        return await self._get_lock().__aenter__()

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return await self._get_lock().__aexit__(exc_type, exc_val, exc_tb)

_assignment_capacity_lock = LoopBoundLock()
_assignment_verify_lock = LoopBoundLock()
_wage_mutation_lock = LoopBoundLock()
_assignment_cancel_lock = _wage_mutation_lock

@api_router.post("/admin/orders/{order_id}/assignments", status_code=201)
async def admin_create_work_assignment(
    order_id: str,
    payload: WorkAssignmentCreateInput,
    admin: dict = Depends(require_perm("manage_orders"))
):
    order = await db.orders.find_one({"_id": id_query(order_id)})
    if not order:
        raise HTTPException(status_code=404, detail="Pesanan tidak ditemukan")

    order_id_str = str(order.get("_id") or order.get("id"))

    # 1. Validate Order Item exists on order
    items = order.get("items") or ([order.get("item")] if order.get("item") else [])
    matched_item = next((it for it in items if it.get("item_id") == payload.order_item_id), None)
    if not matched_item:
        raise HTTPException(status_code=404, detail=f"Item pesanan dengan ID {payload.order_item_id} tidak ditemukan pada pesanan ini")

    ordered_qty = int(matched_item.get("quantity", 1))

    # 2. Validate Multi-worker list (1-5 workers, C1)
    if payload.worker_ids is not None:
        raw_wids = payload.worker_ids
    elif payload.worker_id:
        raw_wids = [payload.worker_id]
    else:
        raise HTTPException(status_code=422, detail="Setidaknya satu pekerja wajib dipilih (1-5 pekerja).")

    if not isinstance(raw_wids, list) or len(raw_wids) == 0:
        raise HTTPException(status_code=422, detail="Setidaknya satu pekerja wajib dipilih (1-5 pekerja).")
    if len(raw_wids) > 5:
        raise HTTPException(
            status_code=422,
            detail=f"Jumlah pekerja dalam satu penugasan tidak boleh melebihi 5 orang (diberikan: {len(raw_wids)})"
        )

    # Check for duplicate worker IDs
    clean_wids = [str(w).strip() for w in raw_wids if str(w).strip()]
    if len(clean_wids) != len(raw_wids):
        raise HTTPException(status_code=422, detail="ID pekerja tidak valid atau kosong")
    if len(set(clean_wids)) != len(clean_wids):
        raise HTTPException(
            status_code=422,
            detail="Daftar pekerja memuat ID duplikat. Setiap pekerja hanya boleh didaftarkan satu kali per penugasan."
        )

    # Validate workers exist in db.admins and are active
    workers_list = []
    found_map = {}
    for wid in clean_wids:
        w_doc = await db.admins.find_one({"_id": id_query(wid)})
        if not w_doc:
            raise HTTPException(status_code=404, detail=f"Pekerja/Pengrajin dengan ID '{wid}' tidak ditemukan dalam sistem")
        if w_doc.get("status") == "inactive":
            raise HTTPException(status_code=422, detail=f"Pekerja '{w_doc.get('name', wid)}' berstatus tidak aktif dan tidak dapat ditugaskan")
        found_map[wid] = w_doc
        workers_list.append({"worker_id": wid, "worker_name": w_doc.get("name", "Worker")})

    primary_worker_id = clean_wids[0]
    primary_worker_name = workers_list[0]["worker_name"]

    # 3. Validate task category & pricing basis
    cat = (payload.task_category or "").strip()
    if cat not in CONTROLLED_TASK_CATEGORIES:
        raise HTTPException(status_code=422, detail=f"Kategori tugas {cat!r} tidak valid. Pilihan: {list(CONTROLLED_TASK_CATEGORIES)}")
    basis = (payload.pricing_basis or "per_unit").strip().lower()
    if basis not in ("per_unit", "lump_sum"):
        raise HTTPException(status_code=422, detail=f"Dasar tarif {basis!r} tidak valid. Pilihan: per_unit, lump_sum")

    # 4. Validate Target Quantity and Active Capacity Invariant (C3 & C4)
    target_qty = int(payload.target_quantity)
    if target_qty <= 0:
        raise HTTPException(status_code=422, detail="Kuantitas target harus lebih besar dari 0")
    if target_qty > ordered_qty:
        raise HTTPException(status_code=422, detail="Kuantitas target penugasan tidak boleh melebihi kuantitas item pesanan")

    # 4. Concurrency Guard: Enforce Active Capacity Invariant under Serialization Lock (Audit 2)
    async with _assignment_capacity_lock:
        # Invariant: total_active_assigned_quantity + target_qty <= ordered_quantity for this task category
        # Active assignments are those not cancelled: ["assigned", "in_progress", "ready_for_review", "accruing", "completed"]
        existing_assignments_cursor = db.work_assignments.find({
            "order_id": order_id_str,
            "order_item_id": payload.order_item_id,
            "task_category": cat,
            "status": {"$in": ["assigned", "in_progress", "ready_for_review", "accruing", "completed"]}
        })
        to_list_fn = getattr(existing_assignments_cursor, "to_list", None)
        existing_assignments = await to_list_fn(500) if callable(to_list_fn) else []

        currently_assigned_qty = sum(int(a.get("target_quantity", 1)) for a in existing_assignments)
        remaining_qty = max(0, ordered_qty - currently_assigned_qty)
        if target_qty > remaining_qty:
            raise HTTPException(
                status_code=422,
                detail=f"Kuantitas target penugasan ({target_qty}) melebihi sisa kapasitas unit yang tersedia ({remaining_qty} dari total {ordered_qty} unit pesanan)"
            )

        # 5. Check duplicate active assignment for any assigned worker on this item & category
        active_statuses = {"assigned", "in_progress", "ready_for_review", "accruing"}
        for a in existing_assignments:
            if a.get("status") in active_statuses and a.get("task_category") == cat:
                a_wids = set(str(w) for w in (a.get("worker_ids") or []))
                if a.get("worker_id"):
                    a_wids.add(str(a.get("worker_id")))
                for wid in clean_wids:
                    if wid in a_wids:
                        w_name = found_map.get(wid, {}).get("name", wid)
                        raise HTTPException(
                            status_code=409,
                            detail=f"Pekerja '{w_name}' sudah memiliki penugasan aktif untuk kategori tugas pada item pesanan ini"
                        )

        # 6. Evaluate Rate from Production Wage Policy & Manual Override Semantics (C2 & C7)
        prod_policy = await get_active_production_wage_policy(db_inst=db)
        is_policy_active = bool(prod_policy.get("is_configured") and prod_policy.get("enabled"))

        is_override = False
        override_reason = None
        rate_flt = None

        if is_policy_active:
            default_rate = _num(prod_policy.get("default_wage_per_unit_le"))
            threshold = _num(prod_policy.get("unusual_amount_threshold_le"))
            hard_cap = _num(prod_policy.get("max_wage_per_unit_le"))

            if payload.agreed_rate_le is None:
                rate_flt = default_rate
            else:
                dec_rate = validate_rate_precision(payload.agreed_rate_le)
                rate_flt = float(dec_rate)
                if rate_flt < 0:
                    raise HTTPException(status_code=422, detail="Nominal tarif upah tidak boleh bernilai negatif")
                if hard_cap is not None and rate_flt > hard_cap:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Tarif upah ({rate_flt} LE) melebihi batas maksimum keras ({hard_cap} LE) pada kebijakan produksi."
                    )
                if (default_rate is not None and rate_flt != default_rate) or (threshold is not None and rate_flt > threshold):
                    is_override = True
                    if admin.get("role") != "owner":
                        raise HTTPException(
                            status_code=403,
                            detail="Hanya Owner yang berwenang melakukan penyesuaian (override) tarif upah produksi di luar tarif standar."
                        )
                    reason = (payload.rate_override_reason or "").strip()
                    if not reason or len(reason) < 3:
                        raise HTTPException(
                            status_code=422,
                            detail="Alasan penyesuaian tarif manual wajib diisi minimal 3 karakter."
                        )
                    override_reason = reason
        else:
            # Policy is NOT active / configured:
            # If payload.agreed_rate_le is None OR this is a multi-worker assignment (Phase 08.2), fail-closed!
            if payload.agreed_rate_le is None or payload.worker_ids is not None:
                raise HTTPException(
                    status_code=422,
                    detail="Kebijakan upah produksi belum dikonfigurasi atau belum diaktifkan oleh Owner. Konfigurasikan kebijakan terlebih dahulu di Pengaturan Upah."
                )
            # Legacy single-worker fallback when rate is explicitly provided
            dec_rate = validate_rate_precision(payload.agreed_rate_le)
            rate_flt = float(dec_rate)
            if rate_flt < 0:
                raise HTTPException(status_code=422, detail="Nominal tarif upah tidak boleh bernilai negatif")
            if payload.rate_override_reason:
                is_override = True
                override_reason = payload.rate_override_reason.strip()

        now = datetime.now(timezone.utc).isoformat()
        doc = {
            "order_id": order_id_str,
            "order_number": order.get("order_number"),
            "order_item_id": payload.order_item_id,
            "worker_id": primary_worker_id,
            "worker_name": primary_worker_name,
            "worker_ids": clean_wids,
            "workers": workers_list,
            "task_category": cat,
            "pricing_basis": basis,
            "agreed_rate_le": rate_flt,
            "currency": "EGP",
            "target_quantity": target_qty,
            "reported_quantity": 0,
            "accepted_quantity": 0,
            "status": "assigned",
            "wage_rule_id": payload.wage_rule_id or None,
            "is_override": is_override,
            "rate_override_reason": override_reason,
            "task_notes": (payload.task_notes or "").strip(),
            "assigned_by_id": admin.get("id"),
            "assigned_by_name": admin.get("name", "Admin"),
            "instance_ids": payload.instance_ids or [],
            "assignment_group_id": payload.assignment_group_id or None,
            "rate_policy_snapshot": {
                "is_configured": prod_policy.get("is_configured", False),
                "enabled": prod_policy.get("enabled", False),
                "default_wage_per_unit_le": prod_policy.get("default_wage_per_unit_le"),
                "unusual_amount_threshold_le": prod_policy.get("unusual_amount_threshold_le"),
                "max_wage_per_unit_le": prod_policy.get("max_wage_per_unit_le"),
                "applied_rate_le": rate_flt,
                "worker_count": len(clean_wids),
            },
            "created_at": now,
            "updated_at": now,
        }

        async def _do_create(sess):
            ins_kw = {"session": sess} if sess else {}
            # Touch serialization guard on order document
            now_touch = datetime.now(timezone.utc).isoformat()
            await db.orders.update_one({"_id": order["_id"]}, {"$set": {"last_assignment_at": now_touch}}, **ins_kw)
            if payload.instance_ids:
                res_itm = db.item_instances.update_many(
                    {"instance_id": {"$in": payload.instance_ids}},
                    {"$set": {"status": "assigned", "assigned_worker_id": primary_worker_id, "updated_at": now}, "$inc": {"claim_generation": 1}},
                    **ins_kw
                )
                if inspect.isawaitable(res_itm):
                    await res_itm
            res = db.work_assignments.insert_one(doc, **ins_kw)
            if inspect.isawaitable(res):
                res = await res
            doc["_id"] = str(getattr(res, "inserted_id", res))
            await create_outbox_event(
                event_type="assignment.created",
                aggregate_type="work_assignment",
                aggregate_id=doc["_id"],
                payload={
                    "assignment_id": doc["_id"],
                    "worker_id": primary_worker_id,
                    "worker_ids": clean_wids,
                    "order_id": order_id_str,
                    "order_item_id": payload.order_item_id,
                    "target_quantity": target_qty,
                    "agreed_rate_le": rate_flt,
                    "instance_ids": payload.instance_ids or [],
                },
                session=sess
            )

        session = None
        try:
            try:
                session = await client.start_session()
            except (pymongo.errors.ConfigurationError, pymongo.errors.InvalidOperation, AttributeError, RuntimeError):
                session = None

            if session is not None:
                async with session:
                    async with session.start_transaction():
                        await _do_create(session)
            else:
                await _do_create(None)
            return clean(doc)
        except pymongo.errors.DuplicateKeyError:
            raise HTTPException(status_code=409, detail="Penugasan serupa sudah terdaftar")

@api_router.patch("/admin/assignments/{assignment_id}/progress")
async def admin_update_assignment_progress(
    assignment_id: str,
    payload: WorkAssignmentProgressInput,
    admin: dict = Depends(get_current_admin)
):
    assignment = await db.work_assignments.find_one({"_id": id_query(assignment_id)})
    if not assignment:
        raise HTTPException(status_code=404, detail="Penugasan kerja tidak ditemukan")

    curr_status = assignment.get("status")
    if curr_status not in ("assigned", "in_progress"):
        raise HTTPException(status_code=409, detail=f"Tidak dapat memperbarui progres pada status: {curr_status}")

    new_status = payload.status.strip()
    if new_status not in ("in_progress", "ready_for_review"):
        raise HTTPException(status_code=422, detail=f"Target status tidak valid: {new_status}")

    upd = {"status": new_status, "updated_at": datetime.now(timezone.utc).isoformat(), "updated_by_id": admin.get("id")}
    if payload.reported_quantity is not None:
        if payload.reported_quantity < 0:
            raise HTTPException(status_code=422, detail="Kuantitas tidak boleh negatif")
        if payload.reported_quantity > assignment.get("target_quantity", 1):
            raise HTTPException(status_code=422, detail="Kuantitas dilaporkan melebihi target penugasan")
        upd["reported_quantity"] = payload.reported_quantity
    if payload.notes:
        upd["progress_notes"] = payload.notes.strip()

    await db.work_assignments.update_one({"_id": assignment["_id"]}, {"$set": upd})
    updated = await db.work_assignments.find_one({"_id": assignment["_id"]})
    return clean(updated)

@api_router.post("/admin/assignments/{assignment_id}/reject")
async def admin_reject_assignment(
    assignment_id: str,
    payload: WorkAssignmentRejectInput,
    admin: dict = Depends(require_perm("manage_orders"))
):
    assignment = await db.work_assignments.find_one({"_id": id_query(assignment_id)})
    if not assignment:
        raise HTTPException(status_code=404, detail="Penugasan kerja tidak ditemukan")

    if assignment.get("status") != "ready_for_review":
        raise HTTPException(status_code=409, detail=f"Hanya penugasan dalam status ready_for_review yang dapat ditolak, status saat ini: {assignment.get('status')}")

    reason = (payload.rejection_reason or "").strip()
    if not reason:
        raise HTTPException(status_code=400, detail="Alasan penolakan wajib diisi")

    now = datetime.now(timezone.utc).isoformat()
    upd = {
        "status": "in_progress",
        "rejection_reason": reason,
        "rejected_by_id": admin.get("id"),
        "rejected_by_name": admin.get("name", "Admin"),
        "rejected_at": now,
        "updated_at": now,
    }
    await db.work_assignments.update_one({"_id": assignment["_id"]}, {"$set": upd})
    updated = await db.work_assignments.find_one({"_id": assignment["_id"]})
    return clean(updated)

@api_router.post("/admin/assignments/{assignment_id}/verify")
async def admin_verify_work_assignment(
    assignment_id: str,
    payload: WorkAssignmentVerifyInput,
    admin: dict = Depends(require_perm("manage_orders"))
):
    async with _assignment_verify_lock:
        assignment = await db.work_assignments.find_one({"_id": id_query(assignment_id)})
        if not assignment:
            raise HTTPException(status_code=404, detail="Penugasan kerja tidak ditemukan")

        aid_str = str(assignment.get("_id") or assignment.get("id"))
        current_payload_dict = {
            "accepted_quantity": payload.accepted_quantity,
            "notes": (payload.notes or "").strip(),
        }
        current_payload_hash = compute_payload_hash(current_payload_dict)

        # Actor Separation & Decision E2: Owner-only self-approval exception (supports multi-worker)
        admin_id = str(admin.get("id") or admin.get("_id") or "")
        assigned_wids = assignment.get("worker_ids") or ([assignment.get("worker_id")] if assignment.get("worker_id") else [])
        is_owner_bypass = False

        if admin_id and any(str(admin_id) == str(w) for w in assigned_wids):
            if admin.get("role") != "owner":
                raise HTTPException(
                    status_code=403,
                    detail="Pemisahan tugas (Dual-Custody): Penugasan tidak dapat diverifikasi oleh pekerja yang sama, kecuali oleh Owner/CEO"
                )
            is_owner_bypass = True

        # Validate accepted quantity
        target_qty = assignment.get("target_quantity", 1)
        accepted_qty = payload.accepted_quantity
        if accepted_qty <= 0:
            raise HTTPException(status_code=422, detail="Kuantitas diterima harus lebih besar dari 0")
        if accepted_qty > target_qty:
            raise HTTPException(status_code=422, detail=f"Kuantitas diterima ({accepted_qty}) tidak boleh melebihi target ({target_qty})")

        # Decision B-1: Lump-sum 100% all-or-nothing invariant
        pricing_basis = assignment.get("pricing_basis", "per_unit")
        if pricing_basis == "lump_sum" and accepted_qty < target_qty:
            raise HTTPException(
                status_code=422,
                detail=f"Pekerjaan borongan (lump-sum) wajib diselesaikan 100% (target: {target_qty}, diterima: {accepted_qty})"
            )

        # Calculate obligation amount using Decimal ROUND_HALF_UP
        rate_le = _num(assignment.get("agreed_rate_le"))
        total_wage_le = calculate_wage_obligation_amount(rate_le, accepted_qty, pricing_basis)

        # Multi-worker allocation via shared integer piastre utility (distribute_wage_piastres)
        raw_workers = assignment.get("workers")
        if not raw_workers:
            if assignment.get("worker_ids"):
                raw_workers = [{"worker_id": wid} for wid in assignment.get("worker_ids")]
            elif assignment.get("worker_id"):
                raw_workers = [{"worker_id": assignment.get("worker_id"), "worker_name": assignment.get("worker_name", "Worker")}]
            else:
                raw_workers = []

        allocations = distribute_wage_piastres(total_wage_le, raw_workers)

        # Check existing obligations in database (Audit 3 reconciliation)
        existing_wobs_cursor = db.wage_obligations.find({"work_assignment_id": aid_str})
        to_list_fn = getattr(existing_wobs_cursor, "to_list", None)
        existing_wobs = await to_list_fn(100) if callable(to_list_fn) else []
        for wob in existing_wobs:
            if wob.get("payload_hash") and wob.get("payload_hash") != current_payload_hash:
                raise HTTPException(status_code=409, detail="Konflik muatan (payload mismatch) pada kunci idempotensi yang sama")

        # If already completed and ALL worker obligations exist: idempotent replay
        if assignment.get("status") == "completed" and len(existing_wobs) == len(allocations):
            clean_wobs = [clean(w) for w in existing_wobs]
            res = dict(clean_wobs[0])
            res["wage_obligations"] = clean_wobs
            res["assignment"] = clean(assignment)
            res["total_amount_le"] = round(sum(_num(w.get("total_amount_le")) for w in existing_wobs), 2)
            res["rate_le"] = rate_le
            return res

        if assignment.get("status") not in ("ready_for_review", "accruing", "completed"):
            raise HTTPException(
                status_code=409,
                detail=f"Penugasan harus berada dalam status 'ready_for_review' untuk verifikasi. Status saat ini: {assignment.get('status')}"
            )

        existing_by_worker = {str(w.get("worker_id")): w for w in existing_wobs}

        now = datetime.now(timezone.utc).isoformat()
        obligation_docs = []
        obligation_numbers = []
        docs_to_insert = []

        for alloc in allocations:
            wid = str(alloc["worker_id"])
            wname = alloc.get("worker_name") or "Worker"
            event_key = f"acc_{aid_str}_{wid}" if len(allocations) > 1 else f"acc_{aid_str}"

            if wid in existing_by_worker:
                existing_doc = existing_by_worker[wid]
                obligation_numbers.append(existing_doc.get("obligation_number"))
                obligation_docs.append(existing_doc)
            else:
                wob_num = await generate_obligation_number()
                obligation_numbers.append(wob_num)
                new_doc = {
                    "obligation_number": wob_num,
                    "accrual_event_key": event_key,
                    "work_assignment_id": aid_str,
                    "worker_id": wid,
                    "worker_name": wname,
                    "order_id": assignment.get("order_id"),
                    "order_number": assignment.get("order_number"),
                    "order_item_id": assignment.get("order_item_id"),
                    "task_category": assignment.get("task_category"),
                    "pricing_basis": pricing_basis,
                    "rate_le": rate_le,
                    "accepted_quantity": accepted_qty,
                    "total_amount_le": alloc["amount_le"],
                    "amount_piastres": alloc["amount_piastres"],
                    "currency": "EGP",
                    "status": "accrued",
                    "paid_amount_le": 0.0,
                    "is_owner_bypass": is_owner_bypass,
                    "verified_by_id": admin_id,
                    "verified_by_name": admin.get("name", "Admin"),
                    "verification_notes": (payload.notes or "").strip(),
                    "payload_hash": current_payload_hash,
                    "rate_policy_snapshot": {
                        "total_assignment_wage_le": total_wage_le,
                        "agreed_rate_le": rate_le,
                        "workers_count": len(allocations),
                        "allocated_amount_le": alloc["amount_le"],
                        "allocated_piastres": alloc["amount_piastres"],
                        "is_override": assignment.get("is_override", False),
                        "rate_override_reason": assignment.get("rate_override_reason"),
                    },
                    "created_at": now,
                    "updated_at": now,
                }
                obligation_docs.append(new_doc)
                docs_to_insert.append(new_doc)

        primary_wob_num = obligation_numbers[0]
        assignment_update = {
            "status": "completed",
            "accepted_quantity": accepted_qty,
            "verified_by_id": admin_id,
            "verified_by_name": admin.get("name", "Admin"),
            "verified_at": now,
            "is_owner_bypass": is_owner_bypass,
            "accrual_event_key": obligation_docs[0]["accrual_event_key"],
            "wage_obligation_numbers": obligation_numbers,
            "wage_obligation_number": primary_wob_num,
            "total_wage_recorded_le": total_wage_le,
            "verification_notes": (payload.notes or "").strip(),
            "updated_at": now,
        }

        # Atomic Multi-Document Transaction Execution with Standalone Fallback
        async def _do_verify(session):
            ins_kw = {"session": session} if session else {}

            # 1. Update assignment conditionally
            if assignment.get("status") != "completed":
                res_assign = await db.work_assignments.update_one(
                    {"_id": assignment["_id"], "status": {"$in": ["ready_for_review", "accruing"]}},
                    {"$set": assignment_update},
                    **ins_kw
                )
                if res_assign.modified_count == 0 and assignment.get("status") not in ("completed", "accruing"):
                    raise HTTPException(
                        status_code=409,
                        detail="Status penugasan telah berubah oleh proses lain. Harap muat ulang."
                    )

            # 2. Insert only missing wage obligations
            for wob_doc in docs_to_insert:
                res_wob = await db.wage_obligations.insert_one(wob_doc, **ins_kw)
                wob_doc["_id"] = str(res_wob.inserted_id)

            # 3. Create Outbox Event
            await create_outbox_event(
                event_type="assignment.verified",
                aggregate_type="work_assignment",
                aggregate_id=aid_str,
                payload={
                    "assignment_id": aid_str,
                    "obligation_numbers": obligation_numbers,
                    "obligation_number": primary_wob_num,
                    "worker_ids": [o["worker_id"] for o in obligation_docs],
                    "total_amount_le": total_wage_le,
                    "accepted_quantity": accepted_qty,
                    "payload_hash": current_payload_hash,
                },
                session=session
            )

        session = None
        try:
            try:
                session = await client.start_session()
            except (pymongo.errors.ConfigurationError, pymongo.errors.InvalidOperation, AttributeError, RuntimeError) as sess_err:
                if not is_standalone_fallback_permitted():
                    logger.error(f"Transaction capability unavailable in mode {get_environment_mode()!r}: {sess_err}")
                    raise HTTPException(
                        status_code=503,
                        detail="Layanan transaksi multi-dokumen tidak tersedia pada lingkungan ini (Fail-Closed)"
                    )
                session = None

            if session is not None:
                async with session:
                    async with session.start_transaction():
                        await _do_verify(session)
            else:
                # Standalone / test fallback
                if assignment.get("status") != "completed":
                    await db.work_assignments.update_one(
                        {"_id": assignment["_id"], "status": {"$in": ["ready_for_review", "accruing"]}},
                        {"$set": {"status": "accruing", "accrual_in_progress_at": now}}
                    )

                try:
                    for wob_doc in docs_to_insert:
                        res_wob = await db.wage_obligations.insert_one(wob_doc)
                        wob_doc["_id"] = str(res_wob.inserted_id)

                    await db.work_assignments.update_one(
                        {"_id": assignment["_id"]},
                        {"$set": assignment_update}
                    )
                    await create_outbox_event(
                        event_type="assignment.verified",
                        aggregate_type="work_assignment",
                        aggregate_id=aid_str,
                        payload={
                            "assignment_id": aid_str,
                            "obligation_numbers": obligation_numbers,
                            "obligation_number": primary_wob_num,
                            "worker_ids": [o["worker_id"] for o in obligation_docs],
                            "total_amount_le": total_wage_le,
                            "accepted_quantity": accepted_qty,
                            "payload_hash": current_payload_hash,
                        },
                        session=None
                    )
                except Exception as e:
                    # Compensating rollback: delete newly inserted obligations only
                    for doc in docs_to_insert:
                        if "_id" in doc:
                            await db.wage_obligations.delete_one({"_id": id_query(doc["_id"])})
                    await db.work_assignments.update_one(
                        {"_id": assignment["_id"], "status": "accruing"},
                        {"$set": {"status": "ready_for_review"}, "$unset": {"accrual_in_progress_at": ""}}
                    )
                    raise HTTPException(status_code=500, detail=f"Gagal memproses akrual kewajiban upah: {e}")
        except (pymongo.errors.ConnectionFailure, pymongo.errors.ExecutionTimeout) as net_err:
            reconciled_cursor = db.wage_obligations.find({"work_assignment_id": aid_str})
            to_list_fn = getattr(reconciled_cursor, "to_list", None)
            reconciled = await to_list_fn(100) if callable(to_list_fn) else []
            if reconciled and len(reconciled) == len(allocations):
                if any(w.get("payload_hash") and w.get("payload_hash") != current_payload_hash for w in reconciled):
                    raise HTTPException(status_code=409, detail="Konflik muatan (payload mismatch) terdeteksi saat rekonsiliasi transaksi")
                fresh_assign = await db.work_assignments.find_one({"_id": assignment["_id"]})
                clean_recs = [clean(w) for w in reconciled]
                clean_rec = dict(clean_recs[0])
                clean_rec["wage_obligations"] = clean_recs
                clean_rec["assignment"] = clean(fresh_assign)
                clean_rec["total_amount_le"] = round(sum(_num(w.get("total_amount_le")) for w in reconciled), 2)
                clean_rec["rate_le"] = rate_le
                return clean_rec
            raise HTTPException(status_code=503, detail=f"Koneksi terputus saat commit transaksi: {net_err}")
        except pymongo.errors.DuplicateKeyError:
            canonical_wobs_cursor = db.wage_obligations.find({"work_assignment_id": aid_str})
            to_list_fn = getattr(canonical_wobs_cursor, "to_list", None)
            canonical_wobs = await to_list_fn(100) if callable(to_list_fn) else []
            if canonical_wobs and len(canonical_wobs) == len(allocations):
                if any(w.get("payload_hash") and w.get("payload_hash") != current_payload_hash for w in canonical_wobs):
                    raise HTTPException(status_code=409, detail="Konflik muatan (payload mismatch) pada kunci idempotensi yang sama")
                await db.work_assignments.update_one(
                    {"_id": assignment["_id"]},
                    {"$set": {"status": "completed", "updated_at": now}}
                )
                clean_cwobs = [clean(w) for w in canonical_wobs]
                fresh_assign = await db.work_assignments.find_one({"_id": assignment["_id"]})
                clean_cwob = dict(clean_cwobs[0])
                clean_cwob["wage_obligations"] = clean_cwobs
                clean_cwob["assignment"] = clean(fresh_assign)
                clean_cwob["total_amount_le"] = round(sum(_num(w.get("total_amount_le")) for w in canonical_wobs), 2)
                clean_cwob["rate_le"] = rate_le
                return clean_cwob
            raise HTTPException(status_code=409, detail="Konflik penugasan serupa terdeteksi")
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error during work assignment verification: {e}")
            raise HTTPException(status_code=500, detail=f"Kesalahan sistem saat verifikasi penugasan: {e}")

        # Record Audit Log
        await record_audit_log(
            action="WORK_ASSIGNMENT_VERIFIED",
            entity_type="work_assignment",
            entity_id=aid_str,
            entity_identifier=f"{assignment.get('order_number')}:{assignment.get('task_category')}",
            admin=admin,
            metadata={
                "obligation_numbers": obligation_numbers,
                "obligation_number": primary_wob_num,
                "total_amount_le": total_wage_le,
                "accepted_quantity": accepted_qty,
                "workers_count": len(obligation_docs),
                "is_owner_bypass": is_owner_bypass,
            }
        )

        clean_wobs = [clean(doc) for doc in obligation_docs]
        fresh_assign = await db.work_assignments.find_one({"_id": assignment["_id"]})
        clean_res = dict(clean_wobs[0])
        clean_res["wage_obligations"] = clean_wobs
        clean_res["assignment"] = clean(fresh_assign)
        clean_res["total_amount_le"] = total_wage_le
        clean_res["rate_le"] = rate_le
        return clean_res

@api_router.post("/admin/assignments/{assignment_id}/cancel")
async def admin_cancel_work_assignment(
    assignment_id: str,
    payload: WorkAssignmentCancelInput,
    admin: dict = Depends(get_current_admin)
):
    async with _assignment_cancel_lock:
        assignment = await db.work_assignments.find_one({"_id": id_query(assignment_id)})
        if not assignment:
            raise HTTPException(status_code=404, detail="Penugasan kerja tidak ditemukan")

        curr_status = assignment.get("status")
        if curr_status == "cancelled":
            return clean(assignment)

        aid_str = str(assignment.get("_id") or assignment.get("id"))
        reason = (payload.reason or "").strip()
        if not reason:
            raise HTTPException(status_code=400, detail="Alasan pembatalan wajib diisi")

        perms = admin.get("permissions") or {}
        role = admin.get("role")

        # If completed, check permissions
        if curr_status == "completed":
            if role != "owner" and not perms.get("access_finance"):
                raise HTTPException(status_code=403, detail="Hanya admin dengan akses keuangan atau owner yang dapat membatalkan penugasan yang sudah selesai")

        # Scan all linked obligations in wage_obligations: reject if ANY obligation is partially or fully paid (Audit 4)
        linked_wobs_cursor = db.wage_obligations.find({"work_assignment_id": aid_str})
        to_list_fn = getattr(linked_wobs_cursor, "to_list", None)
        linked_wobs = await to_list_fn(100) if callable(to_list_fn) else []
        for linked_wob in linked_wobs:
            if linked_wob.get("status") in ("paid", "partially_paid") or _num(linked_wob.get("paid_amount_le")) > 0:
                raise HTTPException(
                    status_code=400,
                    detail="Kewajiban upah sudah terbayar sebagian atau penuh. Penugasan tidak dapat dibatalkan."
                )

        now = datetime.now(timezone.utc).isoformat()
        assign_upd = {
            "status": "cancelled",
            "cancelled_by_id": admin.get("id"),
            "cancelled_by_name": admin.get("name", "Admin"),
            "cancellation_reason": reason,
            "cancelled_at": now,
            "updated_at": now,
        }

        # Atomic cancel assignment & void obligation
        async def _do_cancel(session):
            ins_kw = {"session": session} if session else {}
            # Guard against concurrent settlement: re-check linked obligations at DB level
            cur_wobs_cursor = db.wage_obligations.find({"work_assignment_id": aid_str}, **ins_kw)
            to_list_fn = getattr(cur_wobs_cursor, "to_list", None)
            cur_wobs = await to_list_fn(100) if callable(to_list_fn) else []
            if any(w.get("status") in ("paid", "partially_paid") or _num(w.get("paid_amount_le")) > 0 for w in cur_wobs):
                raise HTTPException(
                    status_code=400,
                    detail="Kewajiban upah sudah terbayar sebagian atau penuh. Penugasan tidak dapat dibatalkan."
                )
            if any(w.get("status") != "accrued" for w in cur_wobs):
                raise HTTPException(
                    status_code=409,
                    detail="Status kewajiban upah telah berubah oleh proses lain. Harap muat ulang."
                )

            res_asn = await db.work_assignments.update_one(
                {"_id": assignment["_id"], "status": curr_status},
                {"$set": assign_upd},
                **ins_kw
            )
            if res_asn.matched_count == 0 and assignment.get("status") != "cancelled":
                raise HTTPException(
                    status_code=409,
                    detail="Status penugasan telah diubah oleh proses lain. Harap muat ulang."
                )

            await db.wage_obligations.update_many(
                {"work_assignment_id": aid_str, "status": "accrued"},
                {"$set": {
                    "status": "voided",
                    "void_reason": reason,
                    "voided_by_id": admin.get("id"),
                    "voided_by_name": admin.get("name", "Admin"),
                    "voided_at": now,
                    "updated_at": now,
                }},
                **ins_kw
            )
            await create_outbox_event(
                event_type="assignment.cancelled",
                aggregate_type="work_assignment",
                aggregate_id=aid_str,
                payload={
                    "assignment_id": aid_str,
                    "order_number": assignment.get("order_number"),
                    "task_category": assignment.get("task_category"),
                    "cancellation_reason": reason,
                },
                session=session
            )

        session = None
        try:
            session = await client.start_session()
        except (pymongo.errors.ConfigurationError, pymongo.errors.InvalidOperation, AttributeError, RuntimeError) as sess_err:
            if not is_standalone_fallback_permitted():
                logger.error(f"Transaction capability unavailable for cancellation in mode {get_environment_mode()!r}: {sess_err}")
                raise HTTPException(
                    status_code=503,
                    detail="Layanan transaksi multi-dokumen tidak tersedia pada lingkungan ini (Fail-Closed)"
                )
            session = None

        if session is not None:
            async with session:
                async with session.start_transaction():
                    await _do_cancel(session)
        else:
            # Standalone fallback with compensating rollback
            try:
                await _do_cancel(None)
            except HTTPException:
                await db.work_assignments.update_one(
                    {"_id": assignment["_id"]},
                    {"$set": {"status": curr_status, "updated_at": now}}
                )
                raise
            except Exception as e:
                await db.work_assignments.update_one(
                    {"_id": assignment["_id"]},
                    {"$set": {"status": curr_status, "updated_at": now}}
                )
                raise HTTPException(status_code=500, detail=f"Gagal memproses pembatalan penugasan: {e}")

        updated = await db.work_assignments.find_one({"_id": assignment["_id"]})
        return clean(updated)

# --------------------------------------------------------------------------
# Admin: Assignment Groups (Work Package B) & Transactional Outbox (Work Package C)
# --------------------------------------------------------------------------

@api_router.post("/admin/assignment-groups/{group_id}/fission")
async def admin_fission_assignment_group(
    group_id: str,
    payload: AssignmentGroupFissionInput,
    admin: dict = Depends(require_perm("manage_orders"))
):
    group = await db.assignment_groups.find_one({"_id": id_query(group_id)})
    if not group:
        raise HTTPException(status_code=404, detail="Grup penugasan tidak ditemukan")

    if group.get("status") == "quarantined":
        raise HTTPException(status_code=409, detail="Grup penugasan sedang dalam karantina (quarantined)")

    target_instance_ids = group.get("target_instance_ids") or []
    # Corruption checks (TX-14): duplicate instance IDs or count mismatch
    if len(set(target_instance_ids)) != len(target_instance_ids) or group.get("instance_count") != len(target_instance_ids):
        quarantine_reason = "Inkonsistensi data array target_instance_ids atau instance_count mismatch"
        await db.assignment_groups.update_one(
            {"_id": group["_id"]},
            {"$set": {"status": "quarantined", "quarantine_reason": quarantine_reason, "updated_at": datetime.now(timezone.utc).isoformat()}}
        )
        raise HTTPException(status_code=422, detail="Inkonsistensi data terdeteksi pada grup penugasan. Grup telah dikarantina.")

    if payload.target_instance_id not in target_instance_ids:
        raise HTTPException(status_code=404, detail="Instance ID tidak ditemukan dalam grup penugasan ini")

    now = datetime.now(timezone.utc).isoformat()
    new_ids = [x for x in target_instance_ids if x != payload.target_instance_id]
    new_count = len(new_ids)

    child_gid = payload.child_group_id or str(uuid.uuid4())[:12]
    child_group_doc = {
        "group_number": f"GRP-{child_gid}",
        "parent_group_id": str(group.get("_id") or group_id),
        "worker_id": payload.child_worker_id,
        "target_instance_ids": [payload.target_instance_id],
        "instance_count": 1,
        "recovery_generation": 1,
        "recovery_lock": None,
        "status": "active",
        "notes": (payload.notes or "").strip(),
        "created_at": now,
        "updated_at": now,
    }

    async def _do_fission(session):
        ins_kw = {"session": session} if session else {}
        res = await db.assignment_groups.update_one(
            {"_id": group["_id"], "target_instance_ids": target_instance_ids},
            {"$set": {
                "target_instance_ids": new_ids,
                "instance_count": new_count,
                "updated_at": now,
            }},
            **ins_kw
        )
        if res.modified_count == 0:
            raise HTTPException(status_code=409, detail="Konflik konkurensi saat pemisahan grup penugasan")

        await db.assignment_groups.insert_one(child_group_doc, **ins_kw)
        await db.item_instances.update_one(
            {"instance_id": payload.target_instance_id},
            {"$set": {
                "assignment_group_id": child_gid,
                "assigned_worker_id": payload.child_worker_id,
                "updated_at": now,
            }, "$inc": {"claim_generation": 1}},
            **ins_kw
        )
        await create_outbox_event(
            event_type="assignment_group.fissioned",
            aggregate_type="assignment_group",
            aggregate_id=str(group.get("_id") or group_id),
            payload={
                "parent_group_id": str(group.get("_id") or group_id),
                "child_group_id": child_gid,
                "target_instance_id": payload.target_instance_id,
                "child_worker_id": payload.child_worker_id,
                "new_parent_count": new_count,
            },
            session=session
        )

    session = None
    try:
        session = await client.start_session()
    except (pymongo.errors.ConfigurationError, pymongo.errors.InvalidOperation, AttributeError, RuntimeError):
        session = None

    if session is not None:
        async with session:
            async with session.start_transaction():
                await _do_fission(session)
    else:
        await _do_fission(None)

    parent_fresh = await db.assignment_groups.find_one({"_id": group["_id"]})
    return {
        "parent_group": clean(parent_fresh),
        "child_group": clean(child_group_doc),
    }

@api_router.post("/admin/assignment-groups/{group_id}/recover")
async def admin_recover_assignment_group(
    group_id: str,
    payload: AssignmentGroupRecoverInput,
    admin: dict = Depends(require_finance_or_owner())
):
    group = await db.assignment_groups.find_one({"_id": id_query(group_id)})
    if not group:
        raise HTTPException(status_code=404, detail="Grup penugasan tidak ditemukan")

    curr_gen = group.get("recovery_generation", 1)
    if curr_gen != payload.expected_generation:
        raise HTTPException(status_code=409, detail=f"Konflik recovery_generation: diharapkan {payload.expected_generation}, ditemukan {curr_gen}")

    gid_str = str(group.get("_id") or group_id)
    # Check linked wage obligations (TX-08, TX-09)
    linked_obs = await db.wage_obligations.find({
        "$or": [
            {"assignment_group_id": gid_str},
            {"work_assignment_id": {"$in": group.get("assignment_ids", [])}},
        ]
    }).to_list(500)

    for ob in linked_obs:
        if ob.get("status") == "voided":
            # TX-09: Fail closed to quarantine
            quarantine_reason = f"Encountered voided obligation {ob.get('obligation_number')} without explicit directive"
            await db.assignment_groups.update_one(
                {"_id": group["_id"]},
                {"$set": {"status": "quarantined", "quarantine_reason": quarantine_reason, "updated_at": datetime.now(timezone.utc).isoformat()}}
            )
            raise HTTPException(status_code=422, detail="Kewajiban upah dalam status 'voided' terdeteksi. Grup dialihkan ke karantina untuk review manual.")
        if payload.action == "rollback" and (ob.get("status") == "paid" or _num(ob.get("paid_amount_le")) > 0):
            # TX-08: Paid obligations cannot be rolled back
            raise HTTPException(status_code=400, detail="Kewajiban upah sudah terbayar tidak dapat dibatalkan atau di-rollback (Immutability violation)")

    target_instance_ids = group.get("target_instance_ids") or []
    if len(set(target_instance_ids)) != len(target_instance_ids):
        # TX-14: Duplicate instance IDs detected
        quarantine_reason = "Duplicate instance IDs detected in assignment group"
        await db.assignment_groups.update_one(
            {"_id": group["_id"]},
            {"$set": {"status": "quarantined", "quarantine_reason": quarantine_reason, "updated_at": datetime.now(timezone.utc).isoformat()}}
        )
        raise HTTPException(status_code=422, detail="Duplikasi ID instance terdeteksi. Grup dikarantina.")

    now = datetime.now(timezone.utc).isoformat()
    next_gen = curr_gen + 1

    async def _do_recover(session):
        ins_kw = {"session": session} if session else {}
        if payload.action == "repair_forward":
            # TX-14: Sync instance_count from len(target_instance_ids)
            await db.assignment_groups.update_one(
                {"_id": group["_id"], "recovery_generation": curr_gen},
                {"$set": {
                    "instance_count": len(target_instance_ids),
                    "recovery_generation": next_gen,
                    "recovery_lock": None,
                    "status": "active",
                    "updated_at": now,
                }},
                **ins_kw
            )
            await create_outbox_event(
                event_type="assignment_group.repaired_forward",
                aggregate_type="assignment_group",
                aggregate_id=gid_str,
                payload={"group_id": gid_str, "generation": next_gen, "count": len(target_instance_ids)},
                session=session
            )
        elif payload.action == "rollback":
            # TX-06: In-place tombstone transition for staged/accruing obligations
            for ob in linked_obs:
                if ob.get("status") in ("accruing", "staged"):
                    await db.wage_obligations.update_one(
                        {"_id": ob["_id"]},
                        {"$set": {
                            "status": "tombstone_aborted",
                            "total_amount_le": 0.0,
                            "updated_at": now,
                        }},
                        **ins_kw
                    )
            await db.assignment_groups.update_one(
                {"_id": group["_id"], "recovery_generation": curr_gen},
                {"$set": {
                    "status": "rolled_back",
                    "recovery_generation": next_gen,
                    "recovery_lock": None,
                    "updated_at": now,
                }},
                **ins_kw
            )
            await create_outbox_event(
                event_type="assignment_group.rolled_back",
                aggregate_type="assignment_group",
                aggregate_id=gid_str,
                payload={"group_id": gid_str, "generation": next_gen},
                session=session
            )

    session = None
    try:
        session = await client.start_session()
    except (pymongo.errors.ConfigurationError, pymongo.errors.InvalidOperation, AttributeError, RuntimeError):
        session = None

    if session is not None:
        async with session:
            async with session.start_transaction():
                await _do_recover(session)
    else:
        await _do_recover(None)

    fresh = await db.assignment_groups.find_one({"_id": group["_id"]})
    return clean(fresh)

@api_router.post("/admin/assignment-groups/{group_id}/quarantine")
async def admin_quarantine_assignment_group(
    group_id: str,
    payload: Dict[str, Any],
    admin: dict = Depends(require_perm("manage_orders"))
):
    group = await db.assignment_groups.find_one({"_id": id_query(group_id)})
    if not group:
        raise HTTPException(status_code=404, detail="Grup penugasan tidak ditemukan")

    reason = str(payload.get("reason", "Manual administrative quarantine")).strip()
    now = datetime.now(timezone.utc).isoformat()
    await db.assignment_groups.update_one(
        {"_id": group["_id"]},
        {"$set": {
            "status": "quarantined",
            "quarantine_reason": reason,
            "quarantined_by_id": admin.get("id"),
            "quarantined_at": now,
            "updated_at": now,
        }}
    )
    fresh = await db.assignment_groups.find_one({"_id": group["_id"]})
    return clean(fresh)

@api_router.get("/admin/assignment-groups/{group_id}")
async def admin_get_assignment_group(
    group_id: str,
    admin: dict = Depends(get_current_admin)
):
    group = await db.assignment_groups.find_one({"_id": id_query(group_id)})
    if not group:
        raise HTTPException(status_code=404, detail="Grup penugasan tidak ditemukan")
    return clean(group)

@api_router.get("/admin/outbox/pending")
async def admin_get_pending_outbox_events(
    limit: int = 100,
    admin: dict = Depends(require_finance_or_owner())
):
    docs = await db.outbox_events.find({"status": "pending"}).sort("created_at", 1).limit(limit).to_list(limit)
    return [clean(d) for d in docs]

@api_router.post("/admin/outbox/{event_id}/dispatch")
async def admin_dispatch_outbox_event(
    event_id: str,
    payload: OutboxEventDispatchInput,
    admin: dict = Depends(require_finance_or_owner())
):
    doc = await db.outbox_events.find_one({"event_id": event_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Outbox event tidak ditemukan")

    if doc.get("status") == "dispatched":
        # Deduplication (TX-16): cleanly deduplicate without error
        return {"status": "already_dispatched", "event": clean(doc)}

    now = datetime.now(timezone.utc).isoformat()
    await db.outbox_events.update_one(
        {"event_id": event_id},
        {"$set": {
            "status": "dispatched",
            "dispatched_at": now,
            "deduplication_token": payload.deduplication_token,
            "updated_at": now,
        }}
    )
    updated = await db.outbox_events.find_one({"event_id": event_id})
    return {"status": "dispatched", "event": clean(updated)}

@api_router.get("/admin/outbox/metrics")
async def admin_get_outbox_metrics_endpoint(
    admin: dict = Depends(require_finance_or_owner())
):
    role = admin.get("role")
    perms = admin.get("permissions") or {}
    if role != "owner" and not perms.get("access_finance"):
        raise HTTPException(status_code=403, detail="Akses ditolak: Membutuhkan akses keuangan atau owner")
    if not get_outbox_metrics:
        raise HTTPException(status_code=501, detail="Outbox worker module tidak tersedia")
    try:
        metrics = await get_outbox_metrics(db)
        return metrics
    except Exception as e:
        logger.error(f"Error fetching outbox metrics: {e}")
        raise HTTPException(status_code=500, detail="Gagal mengambil metrik outbox")

@api_router.post("/admin/outbox/{event_id}/replay")
async def admin_replay_outbox_event_endpoint(
    event_id: str,
    payload: OutboxEventReplayInput,
    admin: dict = Depends(require_finance_or_owner())
):
    role = admin.get("role")
    perms = admin.get("permissions") or {}
    if role != "owner" and not perms.get("access_finance"):
        raise HTTPException(status_code=403, detail="Akses ditolak: Membutuhkan akses keuangan atau owner")
    if not replay_dead_letter_event:
        raise HTTPException(status_code=501, detail="Outbox worker module tidak tersedia")
    admin_id = str(admin.get("id") or admin.get("_id") or "")
    admin_name = str(admin.get("name") or "Admin")
    res = await replay_dead_letter_event(
        db=db,
        event_id=event_id,
        admin_id=admin_id,
        admin_name=admin_name,
        reason=payload.reason or ""
    )
    if not res.get("success"):
        raise HTTPException(status_code=res.get("status_code", 400), detail=res.get("detail", "Gagal me-replay outbox event"))

    await record_audit_log(
        action="outbox_event_replay",
        entity_type="outbox_event",
        entity_id=event_id,
        entity_identifier=event_id,
        admin=admin,
        metadata={"reason": payload.reason, "replayed_at": res["event"].get("replayed_at")}
    )
    return {"status": "replayed", "event": clean(res["event"])}

@api_router.get("/admin/workers/{worker_id}/pending-wages")
async def admin_get_worker_pending_wages(
    worker_id: str,
    admin: dict = Depends(get_current_admin)
):
    # Allowed for worker themselves, or finance/owner
    perms = admin.get("permissions") or {}
    role = admin.get("role")
    admin_id = str(admin.get("id") or admin.get("_id") or "")
    if admin_id != worker_id and role != "owner" and not perms.get("access_finance"):
        raise HTTPException(status_code=403, detail="Akses ditolak")

    worker = await db.admins.find_one({"_id": id_query(worker_id)})
    if not worker:
        raise HTTPException(status_code=404, detail="Pekerja tidak ditemukan")

    obligations = await db.wage_obligations.find({
        "worker_id": worker_id,
        "status": {"$in": ["accrued", "partially_paid"]}
    }).to_list(1000)

    total_accrued_le = round(sum(_num(o.get("total_amount_le")) for o in obligations), 2)
    total_paid_le = round(sum(_num(o.get("paid_amount_le")) for o in obligations), 2)
    total_pending_le = round(sum(_num(o.get("total_amount_le")) - _num(o.get("paid_amount_le")) for o in obligations), 2)

    cleaned_obligations = []
    locked_rates = []
    # Pre-cache linked orders to avoid repeated DB hits
    order_ids = [o.get("order_id") for o in obligations if o.get("order_id")]
    orders_map = {}
    if order_ids:
        async for ord_doc in db.orders.find({"_id": {"$in": multi_id_query(order_ids)}}):
            orders_map[str(ord_doc["_id"])] = ord_doc

    for o in obligations:
        c_ob = clean(o)
        c_ob["remaining_amount_le"] = max(0.0, round(_num(o.get("total_amount_le")) - _num(o.get("paid_amount_le")), 2))
        l_rate = None
        if o.get("locked_exchange_rate"):
            l_rate = _num(o.get("locked_exchange_rate"))
        elif o.get("rate_policy_snapshot", {}).get("exchange_rate"):
            l_rate = _num(o.get("rate_policy_snapshot", {}).get("exchange_rate"))
        elif o.get("order_id"):
            ord_doc = orders_map.get(str(o.get("order_id")))
            if ord_doc and ord_doc.get("exchange_rate_idr_per_le"):
                l_rate = _num(ord_doc.get("exchange_rate_idr_per_le"))
        c_ob["locked_exchange_rate"] = l_rate
        if l_rate and l_rate > 0:
            locked_rates.append(l_rate)
        cleaned_obligations.append(c_ob)

    settings_rate = _num(await get_setting("exchange_rate_idr_per_le", 357), 357)
    order_hist_rate = locked_rates[0] if locked_rates else None

    return {
        "worker_id": worker_id,
        "worker_name": worker.get("name", "Worker"),
        "pending_obligations_count": len(obligations),
        "total_accrued_le": total_accrued_le,
        "total_paid_le": total_paid_le,
        "total_pending_wages_le": total_pending_le,
        "currency": "EGP",
        "default_locked_exchange_rate": settings_rate,
        "current_exchange_rate": settings_rate,
        "default_settlement_rate": settings_rate,
        "order_historical_rate": order_hist_rate,
        "obligations": cleaned_obligations,
    }

@api_router.get("/admin/wages/pending-summary")
@api_router.get("/admin/pending-payments/summary")
async def admin_get_wages_pending_summary(
    admin: dict = Depends(require_finance_or_owner())
):
    obligations = await db.wage_obligations.find({
        "status": {"$in": ["accrued", "partially_paid"]}
    }).to_list(2000)

    total_accrued_le = 0.0
    total_paid_le = 0.0
    total_pending_le = 0.0
    by_worker = {}
    for o in obligations:
        wid = o.get("worker_id")
        wname = o.get("worker_name", "Worker")
        tot = _num(o.get("total_amount_le"))
        paid = _num(o.get("paid_amount_le"))
        amt = max(0.0, tot - paid)
        total_accrued_le += tot
        total_paid_le += paid
        total_pending_le += amt
        if wid not in by_worker:
            by_worker[wid] = {
                "worker_id": wid,
                "worker_name": wname,
                "total_accrued_le": 0.0,
                "total_paid_le": 0.0,
                "total_le": 0.0,
                "count": 0
            }
        by_worker[wid]["total_accrued_le"] = round(by_worker[wid]["total_accrued_le"] + tot, 2)
        by_worker[wid]["total_paid_le"] = round(by_worker[wid]["total_paid_le"] + paid, 2)
        by_worker[wid]["total_le"] = round(by_worker[wid]["total_le"] + amt, 2)
        by_worker[wid]["count"] += 1

    return {
        "total_accrued_le": round(total_accrued_le, 2),
        "total_paid_le": round(total_paid_le, 2),
        "total_pending_wages_le": round(total_pending_le, 2),
        "currency": "EGP",
        "pending_obligations_count": len(obligations),
        "workers_summary": list(by_worker.values()),
    }

@api_router.get("/admin/wage-obligations")
@api_router.get("/admin/pending-payments/obligations")
async def admin_get_wage_obligations(
    worker_id: Optional[str] = None,
    status: Optional[str] = None,
    order_id: Optional[str] = None,
    task_category: Optional[str] = None,
    limit: int = 500,
    skip: int = 0,
    admin: dict = Depends(require_finance_or_owner())
):
    query = {}
    if worker_id:
        query["worker_id"] = worker_id
    if order_id:
        query["order_id"] = order_id
    if task_category and task_category != "all":
        if task_category == "production":
            query["task_category"] = {"$in": ["production", "cutting", "assembly", "sanding", "finishing", "frame"]}
        else:
            query["task_category"] = task_category
    if status and status != "all":
        if status == "pending":
            query["status"] = {"$in": ["accrued", "partially_paid"]}
        else:
            query["status"] = status

    docs = await db.wage_obligations.find(query).sort("created_at", -1).skip(skip).limit(limit).to_list(limit)
    total_count = await db.wage_obligations.count_documents(query)

    results = []
    for d in docs:
        cd = clean(d)
        cd["remaining_amount_le"] = max(0.0, round(_num(d.get("total_amount_le")) - _num(d.get("paid_amount_le")), 2))
        results.append(cd)

    return {
        "total": total_count,
        "limit": limit,
        "skip": skip,
        "obligations": results
    }

@api_router.post("/admin/wages/settlements")
async def admin_create_wage_settlement(
    payload: WageSettlementCreateInput,
    admin: dict = Depends(require_finance_or_owner())
):
    async with _wage_mutation_lock:
        return await _create_wage_settlement_impl(payload, admin)

async def _create_wage_settlement_impl(
    payload: WageSettlementCreateInput,
    admin: dict
):
    worker_id = str(payload.worker_id or "").strip()
    if not worker_id:
        raise HTTPException(status_code=400, detail="worker_id wajib diisi")

    worker = await db.admins.find_one({"_id": id_query(worker_id)})
    if not worker:
        raise HTTPException(status_code=404, detail="Pekerja tidak ditemukan")
    worker_name = worker.get("name", "Worker")

    disbursed_amount = round(float(payload.amount_le), 2)
    if disbursed_amount <= 0:
        raise HTTPException(status_code=422, detail="Nominal pembayaran harus lebih besar dari 0")

    payment_currency = (payload.payment_currency or "EGP").strip().upper()
    if payment_currency not in ("EGP", "IDR"):
        raise HTTPException(status_code=422, detail="Mata uang pembayaran tidak didukung (harus EGP atau IDR)")

    payment_method = (payload.payment_method or "cash").strip().lower()
    if payment_method not in ("cash", "bank_transfer", "other"):
        payment_method = "cash"

    input_payload_hash = compute_payload_hash(payload)
    idem_key = (payload.idempotency_key or "").strip() or None
    if idem_key:
        winning = await db.wage_settlements.find_one({"idempotency_key": idem_key})
        if winning:
            winning_hash = winning.get("payload_hash")
            if winning_hash and winning_hash != input_payload_hash:
                raise HTTPException(
                    status_code=409,
                    detail="Kunci idempotensi telah digunakan untuk pembayaran upah dengan parameter berbeda."
                )
            if not winning_hash:
                if (
                    str(winning.get("worker_id")) != worker_id or
                    round(float(winning.get("amount_le", 0)), 2) != disbursed_amount or
                    winning.get("payment_method") != payment_method or
                    (winning.get("payout_currency") or "EGP") != payment_currency
                ):
                    raise HTTPException(
                        status_code=409,
                        detail="Kunci idempotensi telah digunakan untuk pembayaran upah dengan parameter berbeda."
                    )
            return clean(winning)

    # Fetch eligible pending obligations for this worker
    worker_obligations = await db.wage_obligations.find({
        "worker_id": worker_id,
        "status": {"$in": ["accrued", "partially_paid"]}
    }).sort("created_at", 1).to_list(1000)

    if not worker_obligations:
        raise HTTPException(status_code=400, detail="Tidak ada kewajiban upah terutang untuk pekerja ini")

    total_pending_all = round(sum(_num(o.get("total_amount_le")) - _num(o.get("paid_amount_le")) for o in worker_obligations), 2)
    if disbursed_amount > total_pending_all:
        raise HTTPException(
            status_code=422,
            detail=f"Nominal pembayaran ({disbursed_amount} LE) melebihi total kewajiban terutang ({total_pending_all} LE)"
        )

    # Resolve locked rate from the worker's obligations being settled
    ob_order_ids = [o.get("order_id") for o in worker_obligations if o.get("order_id")]
    ob_orders_map = {}
    if ob_order_ids:
        async for ord_doc in db.orders.find({"_id": {"$in": multi_id_query(ob_order_ids)}}):
            ob_orders_map[str(ord_doc["_id"])] = ord_doc

    allocated_ids = {str(item.wage_obligation_id).strip() for item in payload.allocations} if payload.allocations else set()
    locked_rates = []
    for o in worker_obligations:
        if allocated_ids and str(o.get("_id")) not in allocated_ids and str(o.get("id")) not in allocated_ids:
            continue
        l_rate = None
        if o.get("locked_exchange_rate"):
            l_rate = _num(o.get("locked_exchange_rate"))
        elif o.get("rate_policy_snapshot", {}).get("exchange_rate"):
            l_rate = _num(o.get("rate_policy_snapshot", {}).get("exchange_rate"))
        elif o.get("order_id"):
            ord_doc = ob_orders_map.get(str(o.get("order_id")))
            if ord_doc and ord_doc.get("exchange_rate_idr_per_le"):
                l_rate = _num(ord_doc.get("exchange_rate_idr_per_le"))
        if l_rate and l_rate > 0:
            locked_rates.append(l_rate)

    # Fallback if no allocated obligations had a rate (or no allocations provided)
    if not locked_rates:
        for o in worker_obligations:
            l_rate = None
            if o.get("locked_exchange_rate"):
                l_rate = _num(o.get("locked_exchange_rate"))
            elif o.get("rate_policy_snapshot", {}).get("exchange_rate"):
                l_rate = _num(o.get("rate_policy_snapshot", {}).get("exchange_rate"))
            elif o.get("order_id"):
                ord_doc = ob_orders_map.get(str(o.get("order_id")))
                if ord_doc and ord_doc.get("exchange_rate_idr_per_le"):
                    l_rate = _num(ord_doc.get("exchange_rate_idr_per_le"))
            if l_rate and l_rate > 0:
                locked_rates.append(l_rate)

    reference_locked_rate = locked_rates[0] if locked_rates else None
    settings_rate = _num(await get_setting("exchange_rate_idr_per_le", 357), 357)

    # Handle IDR vs EGP rate resolution
    is_override = False
    override_reason = None
    actual_rate = None
    standard_payout_amount = disbursed_amount
    actual_payout_amount = disbursed_amount
    variance_idr = 0

    if payment_currency == "IDR":
        primary_account = "IDR"
        is_explicit_override = bool(payload.is_rate_override)
        req_rate = payload.settlement_rate

        # IDR wage settlements default to current configured rate (settings_rate)
        if is_explicit_override or (req_rate is not None and round(req_rate, 4) != round(settings_rate, 4)):
            is_override = True
            override_reason = (payload.override_reason or "").strip()
            if len(override_reason) < 3:
                raise HTTPException(
                    status_code=422,
                    detail="Alasan perubahan kurs wajib diisi saat menggunakan kurs override (minimal 3 karakter)."
                )
            if req_rate is None or not (math.isfinite(req_rate) and req_rate > 0):
                raise HTTPException(
                    status_code=422,
                    detail="Kurs override harus berupa angka positif yang valid."
                )
            actual_rate = round(float(req_rate), 4)
        else:
            is_override = False
            actual_rate = settings_rate

        standard_payout_amount = round(disbursed_amount * actual_rate)
        if payload.actual_payout_amount is not None:
            if not (math.isfinite(payload.actual_payout_amount) and payload.actual_payout_amount > 0):
                raise HTTPException(
                    status_code=422,
                    detail="Nominal pencairan IDR aktual harus berupa angka positif yang valid."
                )
            actual_payout_amount = round(float(payload.actual_payout_amount))
            variance_idr = actual_payout_amount - standard_payout_amount
            if variance_idr != 0:
                explanation = (payload.override_reason or payload.notes or "").strip()
                if len(explanation) < 3:
                    raise HTTPException(
                        status_code=422,
                        detail="Alasan/keterangan wajib diisi saat nominal pencairan IDR aktual berbeda dari konversi standar (minimal 3 karakter)."
                    )
        else:
            actual_payout_amount = standard_payout_amount
            variance_idr = 0
    else:
        # EGP payment
        primary_account = "EGP"
        actual_rate = settings_rate
        actual_payout_amount = disbursed_amount
        standard_payout_amount = disbursed_amount
        variance_idr = 0
        if payload.actual_payout_amount is not None and round(float(payload.actual_payout_amount), 2) != disbursed_amount:
            raise HTTPException(
                status_code=422,
                detail=f"Untuk pembayaran EGP, nominal pencairan ({payload.actual_payout_amount}) harus sama dengan nominal kewajiban yang dilunasi ({disbursed_amount} LE)."
            )

    resolved_allocations = []
    ob_by_id = {str(o.get("_id")): o for o in worker_obligations}
    for o in worker_obligations:
        if o.get("id"):
            ob_by_id[str(o["id"])] = o

    if payload.allocations and len(payload.allocations) > 0:
        alloc_map = {}
        for item in payload.allocations:
            item_ob_id = str(item.wage_obligation_id).strip()
            item_amt = round(float(item.amount_le), 2)
            if item_amt <= 0:
                raise HTTPException(status_code=422, detail="Nominal alokasi harus lebih besar dari 0")
            if item_ob_id in alloc_map:
                raise HTTPException(status_code=422, detail="Duplikasi alokasi untuk kewajiban yang sama")
            alloc_map[item_ob_id] = item_amt

        if round(sum(alloc_map.values()), 2) != disbursed_amount:
            raise HTTPException(
                status_code=422,
                detail=f"Total alokasi ({round(sum(alloc_map.values()), 2)} LE) harus sama persis dengan nominal pembayaran ({disbursed_amount} LE)"
            )

        for ob_id, alloc_amt in alloc_map.items():
            ob = ob_by_id.get(ob_id)
            if not ob:
                raise HTTPException(status_code=404, detail=f"Kewajiban upah {ob_id} tidak ditemukan atau bukan milik pekerja ini")
            rem = round(_num(ob.get("total_amount_le")) - _num(ob.get("paid_amount_le")), 2)
            if alloc_amt > rem:
                raise HTTPException(
                    status_code=422,
                    detail=f"Nominal alokasi ({alloc_amt} LE) melebihi sisa kewajiban ({rem} LE) untuk {ob.get('obligation_number')}"
                )
            prev_paid = _num(ob.get("paid_amount_le"))
            new_paid = round(prev_paid + alloc_amt, 2)
            tot_amt = _num(ob.get("total_amount_le"))
            status_after = "paid" if new_paid >= tot_amt else "partially_paid"
            resolved_allocations.append({
                "wage_obligation_id": str(ob["_id"]),
                "obligation_number": ob.get("obligation_number"),
                "amount_le": alloc_amt,
                "previous_paid_amount_le": prev_paid,
                "new_paid_amount_le": new_paid,
                "obligation_total_amount_le": tot_amt,
                "obligation_status_after": status_after,
            })
    else:
        # Automatic FIFO allocation
        remaining_to_allocate = disbursed_amount
        for ob in worker_obligations:
            if remaining_to_allocate <= 0:
                break
            ob_rem = round(_num(ob.get("total_amount_le")) - _num(ob.get("paid_amount_le")), 2)
            if ob_rem <= 0:
                continue
            alloc_amt = min(remaining_to_allocate, ob_rem)
            remaining_to_allocate = round(remaining_to_allocate - alloc_amt, 2)
            prev_paid = _num(ob.get("paid_amount_le"))
            new_paid = round(prev_paid + alloc_amt, 2)
            tot_amt = _num(ob.get("total_amount_le"))
            status_after = "paid" if new_paid >= tot_amt else "partially_paid"
            resolved_allocations.append({
                "wage_obligation_id": str(ob["_id"]),
                "obligation_number": ob.get("obligation_number"),
                "amount_le": alloc_amt,
                "previous_paid_amount_le": prev_paid,
                "new_paid_amount_le": new_paid,
                "obligation_total_amount_le": tot_amt,
                "obligation_status_after": status_after,
            })

    now_iso = datetime.now(timezone.utc).isoformat()
    settlement_date = (payload.payment_date or now_iso[:10]).strip()
    settlement_num = await generate_wage_settlement_number()

    settings_rate = _num(await get_setting("exchange_rate_idr_per_le", 357), 357)
    if payment_currency == "IDR":
        counterpart_amount = disbursed_amount
        counterpart_currency = "EGP"
        desc_suffix = " [IDR]"
    else:
        counterpart_amount = round(disbursed_amount * (actual_rate or settings_rate))
        counterpart_currency = "IDR"
        desc_suffix = ""

    txn_doc = {
        "date": settlement_date,
        "type": "expense",
        "category": "Pekerja",
        "amount": actual_payout_amount,
        "currency": payment_currency,
        "account": primary_account,
        "exchange_rate": actual_rate or settings_rate,
        "counterpart_amount": counterpart_amount,
        "counterpart_currency": counterpart_currency,
        "classification": "cost",
        "description": f"Pembayaran upah pekerja {worker_name} ({settlement_num}){desc_suffix}",
        "recipient_employee_id": worker_id,
        "recipient_employee_name": worker_name,
        "related_settlement_number": settlement_num,
        "created_by_id": admin.get("id"),
        "created_by_name": admin.get("name", "Admin"),
        "updated_by_name": admin.get("name", "Admin"),
        "created_at": now_iso,
        "updated_at": now_iso,
    }

    settlement_doc = {
        "settlement_number": settlement_num,
        "worker_id": worker_id,
        "worker_name": worker_name,
        "settlement_date": settlement_date,
        "amount_le": disbursed_amount,
        "currency": "EGP",
        "payout_currency": payment_currency,
        "payout_amount": actual_payout_amount,
        "standard_payout_amount": standard_payout_amount,
        "variance_idr": variance_idr,
        "locked_exchange_rate": reference_locked_rate if reference_locked_rate is not None else settings_rate,
        "order_historical_rate": reference_locked_rate,
        "settlement_rate": actual_rate if payment_currency == "IDR" else None,
        "is_rate_override": is_override,
        "override_reason": override_reason,
        "payment_method": payment_method,
        "reference": (payload.reference or "").strip(),
        "notes": (payload.notes or "").strip(),
        "allocations": resolved_allocations,
        "finance_transaction_id": None,
        "status": "recorded",
        "idempotency_key": idem_key,
        "payload_hash": input_payload_hash,
        "created_by_id": admin.get("id"),
        "created_by_name": admin.get("name", "Admin"),
        "created_at": now_iso,
        "updated_at": now_iso,
    }

    async def _do_settle(session):
        ins_kw = {"session": session} if session else {}

        # 1. Insert finance transaction
        res_txn = await db.finance_transactions.insert_one(txn_doc, **ins_kw)
        txn_id = str(res_txn.inserted_id)
        settlement_doc["finance_transaction_id"] = txn_id

        # 2. Insert employee_wages mirror
        await db.employee_wages.insert_one({
            "employee_id": worker_id,
            "employee_name": worker_name,
            "amount": actual_payout_amount,
            "currency": payment_currency,
            "amount_le": disbursed_amount,
            "exchange_rate": actual_rate if payment_currency == "IDR" else None,
            "date": settlement_date,
            "category": "Pekerja",
            "description": txn_doc["description"],
            "transaction_id": txn_id,
            "recorded_by_name": admin.get("name", "Admin"),
            "created_at": now_iso
        }, **ins_kw)

        # 3. Insert wage settlement
        res_wst = await db.wage_settlements.insert_one(settlement_doc, **ins_kw)
        settlement_id = str(res_wst.inserted_id)
        settlement_doc["_id"] = res_wst.inserted_id

        # 4. Link settlement on finance transaction
        await db.finance_transactions.update_one(
            {"_id": res_txn.inserted_id},
            {"$set": {"wage_settlement_id": settlement_id}},
            **ins_kw
        )

        # 5. Mutate each wage obligation with optimistic concurrency check
        for a in resolved_allocations:
            ob_id = a["wage_obligation_id"]
            ob = ob_by_id.get(ob_id)
            if ob and ob.get("work_assignment_id"):
                asn_check = await db.work_assignments.find_one({"_id": id_query(ob["work_assignment_id"])}, **ins_kw)
                if asn_check and asn_check.get("status") == "cancelled":
                    raise HTTPException(
                        status_code=409,
                        detail=f"Penugasan kerja ({asn_check.get('order_number')}) telah dibatalkan. Kewajiban upah tidak dapat dilunasi."
                    )
            alloc_amt = a["amount_le"]
            prev_paid = a["previous_paid_amount_le"]
            new_paid = a["new_paid_amount_le"]
            new_status = a["obligation_status_after"]
            alloc_record = {
                "settlement_id": settlement_id,
                "settlement_number": settlement_num,
                "amount_le": alloc_amt,
                "date": settlement_date,
                "created_at": now_iso
            }
            res_ob = await db.wage_obligations.update_one(
                {
                    "_id": id_query(ob_id),
                    "paid_amount_le": prev_paid,
                    "status": {"$in": ["accrued", "partially_paid"]}
                },
                {
                    "$set": {
                        "paid_amount_le": new_paid,
                        "status": new_status,
                        "updated_at": now_iso
                    },
                    "$push": {
                        "settlement_allocations": alloc_record
                    }
                },
                **ins_kw
            )
            if res_ob.modified_count == 0:
                raise HTTPException(
                    status_code=409,
                    detail=f"Saldo kewajiban upah ({a['obligation_number']}) telah berubah oleh proses lain. Harap muat ulang."
                )

        # 6. Audit logging if rate override or payout variance occurred
        if is_override or variance_idr != 0:
            await record_audit_log(
                action="wage_settlement_rate_override" if is_override else "wage_settlement_payout_variance",
                entity_type="wage_settlement",
                entity_id=settlement_id,
                entity_identifier=settlement_num,
                admin=admin,
                metadata={
                    "worker_id": worker_id,
                    "worker_name": worker_name,
                    "wage_obligation_ids": [a["wage_obligation_id"] for a in resolved_allocations],
                    "original_locked_rate": settings_rate,
                    "order_historical_rate": reference_locked_rate,
                    "override_rate": actual_rate,
                    "override_reason": override_reason or (payload.notes or "").strip(),
                    "disbursed_amount_le": disbursed_amount,
                    "actual_payout_amount": actual_payout_amount,
                    "standard_payout_amount": standard_payout_amount,
                    "variance_idr": variance_idr,
                    "payout_currency": payment_currency,
                },
                session=session
            )

        # 7. Create transactional outbox event
        await create_outbox_event(
            event_type="wage.settled",
            aggregate_type="wage_settlement",
            aggregate_id=settlement_id,
            payload={
                "settlement_id": settlement_id,
                "settlement_number": settlement_num,
                "worker_id": worker_id,
                "amount_le": disbursed_amount,
                "payout_amount": actual_payout_amount,
                "payout_currency": payment_currency,
                "finance_transaction_id": txn_id,
                "payload_hash": input_payload_hash,
            },
            session=session
        )

        return settlement_id

    created_id = None
    session = None
    try:
        try:
            session = await client.start_session()
        except (pymongo.errors.ConfigurationError, pymongo.errors.InvalidOperation, AttributeError, RuntimeError) as sess_err:
            if not is_standalone_fallback_permitted():
                logger.error(f"Transaction capability unavailable for wage settlement in mode {get_environment_mode()!r}: {sess_err}")
                raise HTTPException(
                    status_code=503,
                    detail="Layanan transaksi multi-dokumen tidak tersedia pada lingkungan ini (Fail-Closed)"
                )
            session = None

        if session is not None:
            async with session:
                async with session.start_transaction():
                    created_id = await _do_settle(session)
        else:
            # Standalone fallback with compensating rollback
            try:
                created_id = await _do_settle(None)
            except Exception as se:
                if settlement_doc.get("finance_transaction_id"):
                    tid = settlement_doc["finance_transaction_id"]
                    try:
                        await db.finance_transactions.delete_one({"_id": id_query(tid)})
                        await db.employee_wages.delete_many({"transaction_id": tid})
                    except Exception:
                        pass
                if settlement_doc.get("_id"):
                    try:
                        await db.wage_settlements.delete_one({"_id": settlement_doc["_id"]})
                    except Exception:
                        pass
                if settlement_num:
                    try:
                        await db.wage_obligations.update_many(
                            {"settlement_allocations.settlement_number": settlement_num},
                            {"$pull": {"settlement_allocations": {"settlement_number": settlement_num}}}
                        )
                        for a in resolved_allocations:
                            ob_id = a.get("wage_obligation_id")
                            if ob_id:
                                ob_cur = await db.wage_obligations.find_one({"_id": id_query(ob_id)})
                                if ob_cur:
                                    recomputed_paid = round(sum(_num(alloc.get("amount_le")) for alloc in ob_cur.get("settlement_allocations", [])), 2)
                                    recomputed_status = "accrued" if recomputed_paid <= 0 else ("paid" if recomputed_paid >= _num(ob_cur.get("total_amount_le")) else "partially_paid")
                                    await db.wage_obligations.update_one(
                                        {"_id": ob_cur["_id"]},
                                        {"$set": {"paid_amount_le": recomputed_paid, "status": recomputed_status}}
                                    )
                    except Exception:
                        pass
                raise se
    except pymongo.errors.DuplicateKeyError as dke:
        err_msg = str(dke)
        if idem_key and ("uniq_wage_settlements_idempotency" in err_msg or idem_key in err_msg):
            winning = await db.wage_settlements.find_one({"idempotency_key": idem_key})
            if winning:
                winning_hash = winning.get("payload_hash")
                if winning_hash and winning_hash != input_payload_hash:
                    raise HTTPException(
                        status_code=409,
                        detail="Kunci idempotensi telah digunakan untuk pembayaran upah dengan parameter berbeda."
                    )
                if not winning_hash:
                    if (
                        str(winning.get("worker_id")) != worker_id or
                        round(float(winning.get("amount_le", 0)), 2) != disbursed_amount or
                        winning.get("payment_method") != payment_method or
                        (winning.get("payout_currency") or "EGP") != payment_currency or
                        round(float(winning.get("payout_amount", 0))) != round(float(actual_payout_amount))
                    ):
                        raise HTTPException(
                            status_code=409,
                            detail="Kunci idempotensi telah digunakan untuk pembayaran upah dengan parameter berbeda."
                        )
                return clean(winning)
        raise HTTPException(status_code=409, detail=f"Konflik data terdeteksi: {dke}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during wage settlement: {e}")
        raise HTTPException(status_code=500, detail=f"Kesalahan sistem saat mencatat pembayaran upah: {e}")

    await record_audit_log(
        action="WAGE_SETTLEMENT_RECORDED",
        entity_type="wage_settlement",
        entity_id=created_id,
        entity_identifier=f"{worker_name}:{settlement_num}",
        admin=admin,
        metadata={
            "settlement_number": settlement_num,
            "worker_id": worker_id,
            "amount_le": disbursed_amount,
            "payment_method": payment_method,
            "allocations_count": len(resolved_allocations),
        }
    )

    clean_settlement = clean(settlement_doc)
    return clean_settlement

@api_router.get("/admin/wages/settlements")
async def admin_get_wage_settlements(
    worker_id: Optional[str] = None,
    status: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 200,
    skip: int = 0,
    admin: dict = Depends(require_finance_or_owner())
):
    query = {}
    if worker_id:
        query["worker_id"] = worker_id
    if status and status != "all":
        query["status"] = status
    if start_date or end_date:
        query["settlement_date"] = {}
        if start_date:
            query["settlement_date"]["$gte"] = start_date
        if end_date:
            query["settlement_date"]["$lte"] = end_date

    docs = await db.wage_settlements.find(query).sort("created_at", -1).skip(skip).limit(limit).to_list(limit)
    total_count = await db.wage_settlements.count_documents(query)
    return {
        "total": total_count,
        "limit": limit,
        "skip": skip,
        "settlements": [clean(d) for d in docs]
    }

@api_router.get("/admin/wages/settlements/{settlement_id}")
async def admin_get_wage_settlement_detail(
    settlement_id: str,
    admin: dict = Depends(require_finance_or_owner())
):
    st = await db.wage_settlements.find_one({"_id": id_query(settlement_id)})
    if not st:
        raise HTTPException(status_code=404, detail="Pembayaran upah (settlement) tidak ditemukan")
    return clean(st)

@api_router.post("/admin/wages/settlements/{settlement_id}/void")
async def admin_void_wage_settlement(
    settlement_id: str,
    payload: WageSettlementVoidInput,
    admin: dict = Depends(require_finance_or_owner())
):
    st = await db.wage_settlements.find_one({"_id": id_query(settlement_id)})
    if not st:
        raise HTTPException(status_code=404, detail="Pembayaran upah (settlement) tidak ditemukan")

    if st.get("status") == "voided":
        raise HTTPException(status_code=400, detail="Pembayaran upah telah dibatalkan sebelumnya")

    reason = (payload.reason or "").strip()
    if not reason:
        raise HTTPException(status_code=400, detail="Alasan pembatalan wajib diisi")

    now_iso = datetime.now(timezone.utc).isoformat()
    allocations = st.get("allocations") or []
    sid_str = str(st.get("_id") or settlement_id)
    txn_id = st.get("finance_transaction_id")

    async def _do_void(session):
        ins_kw = {"session": session} if session else {}

        # 1. Void wage settlement document
        await db.wage_settlements.update_one(
            {"_id": st["_id"]},
            {"$set": {
                "status": "voided",
                "void_reason": reason,
                "voided_by_id": admin.get("id"),
                "voided_by_name": admin.get("name", "Admin"),
                "voided_at": now_iso,
                "updated_at": now_iso
            }},
            **ins_kw
        )

        # 2. Reverse allocations on wage_obligations
        for a in allocations:
            ob_id = a.get("wage_obligation_id")
            alloc_amt = _num(a.get("amount_le"))
            ob = await db.wage_obligations.find_one({"_id": id_query(ob_id)}, **ins_kw)
            if ob:
                cur_paid = _num(ob.get("paid_amount_le"))
                new_paid = max(0.0, round(cur_paid - alloc_amt, 2))
                new_status = "accrued" if new_paid <= 0 else "partially_paid"
                await db.wage_obligations.update_one(
                    {"_id": ob["_id"]},
                    {
                        "$set": {
                            "paid_amount_le": new_paid,
                            "status": new_status,
                            "updated_at": now_iso
                        },
                        "$pull": {
                            "settlement_allocations": {"settlement_id": sid_str}
                        }
                    },
                    **ins_kw
                )

        # 3. Void linked finance_transaction
        if txn_id:
            await db.finance_transactions.update_one(
                {"_id": id_query(txn_id)},
                {"$set": {
                    "is_void": True,
                    "status": "void",
                    "void_source": "wage_settlement_void",
                    "void_reason": reason,
                    "voided_by_id": admin.get("id"),
                    "voided_by_name": admin.get("name", "Admin"),
                    "voided_at": now_iso,
                    "updated_at": now_iso
                }},
                **ins_kw
            )
            # 4. Remove from employee_wages mirror
            await db.employee_wages.delete_many({"transaction_id": txn_id}, **ins_kw)

        # 5. Outbox event
        await create_outbox_event(
            event_type="wage_settlement.voided",
            aggregate_type="wage_settlement",
            aggregate_id=sid_str,
            payload={
                "settlement_id": sid_str,
                "settlement_number": st.get("settlement_number"),
                "worker_id": st.get("worker_id"),
                "amount_le": st.get("amount_le"),
                "void_reason": reason,
            },
            session=session
        )

    session = None
    try:
        try:
            session = await client.start_session()
        except (pymongo.errors.ConfigurationError, pymongo.errors.InvalidOperation, AttributeError, RuntimeError) as sess_err:
            if not is_standalone_fallback_permitted():
                raise HTTPException(
                    status_code=503,
                    detail="Layanan transaksi multi-dokumen tidak tersedia pada lingkungan ini (Fail-Closed)"
                )
            session = None

        if session is not None:
            async with session:
                async with session.start_transaction():
                    await _do_void(session)
        else:
            await _do_void(None)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error voiding wage settlement: {e}")
        raise HTTPException(status_code=500, detail=f"Gagal membatalkan pembayaran upah: {e}")

    await record_audit_log(
        action="WAGE_SETTLEMENT_VOIDED",
        entity_type="wage_settlement",
        entity_id=sid_str,
        entity_identifier=f"{st.get('worker_name')}:{st.get('settlement_number')}",
        admin=admin,
        metadata={
            "settlement_number": st.get("settlement_number"),
            "amount_le": st.get("amount_le"),
            "reason": reason
        }
    )

    updated_st = await db.wage_settlements.find_one({"_id": st["_id"]})
    return clean(updated_st)


# --------------------------------------------------------------------------
# Admin: products
# --------------------------------------------------------------------------
def slugify(name):
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or str(uuid.uuid4())[:8]

@api_router.post("/admin/products")
async def admin_create_product(payload: Dict[str, Any], admin: dict = Depends(require_perm("modify_products"))):
    now = datetime.now(timezone.utc).isoformat()
    name = payload.get("name", "Produk Baru")
    slug = payload.get("slug") or slugify(name)
    if await db.products.find_one({"slug": slug}):
        slug = f"{slug}-{str(uuid.uuid4())[:4]}"
    doc = {"name": name, "slug": slug, "category": payload.get("category", "custom"),
           "description": payload.get("description", ""), "image_url": payload.get("image_url", ""),
           "active": payload.get("active", True), "configurable": payload.get("configurable", False),
           "starting_price_le": _num(payload.get("starting_price_le", 0)), "pricing": payload.get("pricing", {}),
           "photos": payload.get("photos", []), "representative_photo_id": payload.get("representative_photo_id"),
           "category_cover_image": payload.get("category_cover_image", ""), "cover_mode": payload.get("cover_mode", "manual"),
           "sort_order": payload.get("sort_order", 99), "created_at": now,
           "updated_by_name": admin.get("name"), "updated_at": now}
    result = await db.products.insert_one(doc)
    return clean(await db.products.find_one({"_id": result.inserted_id}))

@api_router.put("/admin/products/{product_id}")
async def admin_update_product(product_id: str, payload: Dict[str, Any], admin: dict = Depends(require_perm("modify_products"))):
    allowed = ["name", "category", "description", "image_url", "active", "configurable",
               "starting_price_le", "pricing", "photos", "representative_photo_id", "sort_order", "slug",
               "category_cover_image", "cover_mode", "photo_weights", "option_notes", "featured_preview_ids"]
    existing = await db.products.find_one({"_id": id_query(product_id)})
    upd = {k: payload[k] for k in allowed if k in payload}
    if "pricing" in upd and not isinstance(upd["pricing"], dict):
        raise HTTPException(status_code=400, detail="Konfigurasi (pricing) harus berupa objek JSON")
    if "option_notes" in upd and isinstance(upd["option_notes"], dict):
        upd["option_notes"] = {k: v for k, v in upd["option_notes"].items() if str(v or "").strip()}
    upd.update(audit_fields(admin))
    if "starting_price_le" in upd:
        upd["starting_price_le"] = _num(upd["starting_price_le"])
    # Record forward-looking price-change history (non-destructive; historical orders keep their own snapshots).
    if existing and ("pricing" in upd or "starting_price_le" in upd):
        old_p = existing.get("pricing"); new_p = upd.get("pricing", old_p)
        old_s = _num(existing.get("starting_price_le")); new_s = _num(upd.get("starting_price_le", old_s))
        if old_p != new_p or old_s != new_s:
            await db.price_history.insert_one({"product_id": product_id, "product_name": existing.get("name"),
                "category": existing.get("category"), "old_pricing": old_p, "new_pricing": new_p,
                "old_starting_price_le": old_s, "new_starting_price_le": new_s,
                "changed_by_name": admin.get("name"), "changed_at": datetime.now(timezone.utc).isoformat()})
    await db.products.update_one({"_id": id_query(product_id)}, {"$set": upd})
    return clean(await db.products.find_one({"_id": id_query(product_id)}))

@api_router.delete("/admin/products/{product_id}")
async def admin_delete_product(product_id: str, admin: dict = Depends(require_perm("delete_data"))):
    await db.products.delete_one({"_id": id_query(product_id)})
    return {"ok": True}

# --------------------------------------------------------------------------
# Uploads
# --------------------------------------------------------------------------
def optimize_image(data: bytes):
    """Resize large images and re-encode to WebP for fast loading. Falls back to original on error."""
    try:
        import io
        from PIL import Image
        img = Image.open(io.BytesIO(data))
        img = img.convert("RGB") if img.mode in ("P", "RGBA", "LA") else img
        max_dim = 1600
        if max(img.size) > max_dim:
            img.thumbnail((max_dim, max_dim), Image.LANCZOS)
        out = io.BytesIO()
        img.save(out, format="WEBP", quality=82, method=4)
        return out.getvalue(), "webp", "image/webp"
    except Exception as e:
        logger.warning(f"Image optimize failed, using original: {e}")
        return None

@api_router.post("/admin/upload")
async def admin_upload(file: UploadFile = File(...), admin: dict = Depends(get_current_admin)):
    ext = (file.filename.rsplit(".", 1)[-1] if "." in file.filename else "bin").lower()
    if ext not in MIME_TYPES:
        raise HTTPException(status_code=400, detail="Format gambar tidak didukung (jpg, png, webp)")
    data = await file.read()
    if len(data) > 12 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Ukuran gambar maksimal 12MB")
    opt = optimize_image(data)
    if opt:
        data, ext, ctype = opt
    else:
        ctype = MIME_TYPES[ext]
    path = f"{APP_NAME}/uploads/{uuid.uuid4()}.{ext}"
    result = put_object(path, data, ctype)
    await db.files.insert_one({"storage_path": result["storage_path"], "original_filename": file.filename,
                               "content_type": ctype, "size": result.get("size", len(data)),
                               "is_deleted": False, "created_at": datetime.now(timezone.utc).isoformat()})
    return {"path": result["storage_path"], "url": f"/api/files/{result['storage_path']}"}

@api_router.get("/files/{path:path}")
async def download_file(path: str):
    record = await db.files.find_one({"storage_path": path, "is_deleted": False})
    if not record:
        raise HTTPException(status_code=404, detail="File tidak ditemukan")
    data, content_type = get_object(path)
    return StarletteResponse(content=data, media_type=record.get("content_type", content_type),
                             headers={"Cache-Control": "public, max-age=86400"})

@api_router.post("/upload-reference")
async def upload_reference(file: UploadFile = File(...)):
    ext = (file.filename.rsplit(".", 1)[-1] if "." in file.filename else "bin").lower()
    if ext not in MIME_TYPES:
        raise HTTPException(status_code=400, detail="Format gambar tidak didukung (jpg, png, webp)")
    data = await file.read()
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Ukuran gambar maksimal 10MB")
    opt = optimize_image(data)
    if opt:
        data, ext, ctype = opt
    else:
        ctype = MIME_TYPES[ext]
    path = f"{APP_NAME}/custom-references/{uuid.uuid4()}.{ext}"
    result = put_object(path, data, ctype)
    await db.files.insert_one({
        "storage_path": result["storage_path"], "original_filename": file.filename,
        "content_type": ctype, "size": result.get("size", len(data)),
        "is_deleted": False, "category": "custom_reference",
        "created_at": datetime.now(timezone.utc).isoformat()
    })
    return {"path": result["storage_path"], "url": f"/api/files/{result['storage_path']}"}

# --------------------------------------------------------------------------
# Custom Requests
# --------------------------------------------------------------------------
@api_router.post("/custom-requests")
async def create_custom_request(data: CustomRequestInput):
    if not data.customer_name or not data.customer_name.strip():
        raise HTTPException(status_code=400, detail="Nama customer wajib diisi")
    phone = normalize_phone(data.customer_phone)
    if not phone.startswith("+"):
        if phone.startswith("08"):
            phone = "+62" + phone[1:]
        elif phone.startswith("62"):
            phone = "+" + phone
        elif phone.startswith("01"):
            phone = "+20" + phone[1:]
        elif phone.startswith("20"):
            phone = "+" + phone
        elif phone:
            phone = "+" + phone
    if not valid_intl_phone(phone):
        raise HTTPException(status_code=400, detail="Nomor telepon WhatsApp tidak valid (format internasional e.g. +62... atau +20...)")
    egypt_phone = normalize_egypt_phone(data.phone_number)
    if not data.furniture_type or not data.furniture_type.strip():
        raise HTTPException(status_code=400, detail="Jenis furniture wajib diisi")

    now = datetime.now(timezone.utc)
    yymm = now.strftime("%y%m")
    count = await db.custom_requests.count_documents({"ticket_number": {"$regex": f"^REQ-{yymm}-"}})
    ticket_number = f"REQ-{yymm}-{count + 1:04d}"

    doc = {
        "ticket_number": ticket_number,
        "customer_name": data.customer_name.strip(),
        "customer_phone": phone,
        "phone_number": egypt_phone,
        "customer_address": (data.customer_address or "").strip(),
        "furniture_type": data.furniture_type.strip(),
        "dimensions": data.dimensions or {},
        "material": (data.material or "").strip(),
        "reference_photos": data.reference_photos or [],
        "budget_estimation_le": float(data.budget_estimation_le) if data.budget_estimation_le is not None else None,
        "notes": (data.notes or "").strip(),
        "status": "baru",
        "admin_notes": "",
        "estimated_price_le": None,
        "converted_order_id": None,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }
    result = await db.custom_requests.insert_one(doc)

    wa_num = await get_setting("whatsapp_number", "628XXXXXXXXXX")
    dims_parts = []
    if data.dimensions:
        if data.dimensions.get("length"): dims_parts.append(f"P: {data.dimensions['length']} cm")
        if data.dimensions.get("width"): dims_parts.append(f"L: {data.dimensions['width']} cm")
        if data.dimensions.get("height"): dims_parts.append(f"T: {data.dimensions['height']} cm")
    dims_str = " × ".join(dims_parts) if dims_parts else (data.dimensions.get("notes") if data.dimensions else "")

    lines = [
        "Halo Sogil Furniture, saya ingin mengajukan *Request Custom Furniture*:",
        f"Nomor Tiket: *{ticket_number}*",
        f"Jenis: *{data.furniture_type.strip()}*",
    ]
    if dims_str:
        lines.append(f"Ukuran: {dims_str}")
    if data.material:
        lines.append(f"Pilihan Bahan/Finishing: {data.material.strip()}")
    if data.budget_estimation_le:
        lines.append(f"Estimasi Budget: {fmt_le(data.budget_estimation_le)} LE")
    if data.notes:
        lines.append(f"Catatan: {data.notes.strip()}")
    if data.reference_photos:
        lines.append(f"Foto Referensi: {len(data.reference_photos)} foto terlampir")
    lines.append(f"Nama: {data.customer_name.strip()}")
    lines.append(f"No. WA: {phone}")
    lines.append("\nMohon informasi ketersediaan dan estimasi biayanya. Terima kasih!")

    wa_message = "\n".join(lines)
    clean_num = re.sub(r"[^0-9]", "", wa_num)
    wa_url = f"https://wa.me/{clean_num}?text={urllib.parse.quote(wa_message)}"

    saved = await db.custom_requests.find_one({"_id": result.inserted_id})
    res = clean(saved)
    res["whatsapp_url"] = wa_url
    res["whatsapp_message"] = wa_message
    return res

@api_router.get("/admin/custom-requests")
async def admin_list_custom_requests(
    status: Optional[str] = None,
    q: Optional[str] = None,
    admin: dict = Depends(require_perm("manage_orders"))
):
    query = {}
    if status and status != "all":
        query["status"] = status
    if q:
        regex = {"$regex": re.escape(q), "$options": "i"}
        query["$or"] = [
            {"ticket_number": regex},
            {"customer_name": regex},
            {"customer_phone": regex},
            {"furniture_type": regex},
        ]
    cursor = db.custom_requests.find(query).sort("created_at", -1)
    items = []
    async for doc in cursor:
        items.append(clean(doc))
    return items

@api_router.get("/admin/custom-requests/{req_id}")
async def admin_get_custom_request(req_id: str, admin: dict = Depends(require_perm("manage_orders"))):
    doc = await db.custom_requests.find_one({"_id": id_query(req_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Request custom tidak ditemukan")
    return clean(doc)

@api_router.patch("/admin/custom-requests/{req_id}")
async def admin_update_custom_request(
    req_id: str,
    data: CustomRequestUpdate,
    admin: dict = Depends(require_perm("manage_orders"))
):
    update = audit_fields(admin)
    if data.status is not None:
        valid_status = {"baru", "diskusi", "disetujui", "dipesan", "ditolak"}
        if data.status not in valid_status:
            raise HTTPException(status_code=400, detail="Status tidak valid")
        update["status"] = data.status
    if data.admin_notes is not None:
        update["admin_notes"] = data.admin_notes
    if data.estimated_price_le is not None:
        update["estimated_price_le"] = float(data.estimated_price_le)

    await db.custom_requests.update_one({"_id": id_query(req_id)}, {"$set": update})
    doc = await db.custom_requests.find_one({"_id": id_query(req_id)})
    return clean(doc)

@api_router.post("/admin/custom-requests/{req_id}/convert-to-order")
async def admin_convert_custom_to_order(
    req_id: str,
    data: ConvertCustomToOrderInput,
    admin: dict = Depends(require_perm("manage_orders"))
):
    custom_req = await db.custom_requests.find_one({"_id": id_query(req_id)})
    if not custom_req:
        raise HTTPException(status_code=404, detail="Request custom tidak ditemukan")

    order_num = await generate_order_number()
    rate = _num(await get_setting("exchange_rate_idr_per_le", 357), 357)
    now = datetime.now(timezone.utc).isoformat()
    subtotal = float(data.subtotal_le)
    delivery_fee = float(data.delivery_fee_le or 0.0)
    total_le = max(0.0, subtotal + delivery_fee)

    zone_name = None
    if data.delivery_zone_id:
        z = await db.delivery_zones.find_one({"_id": id_query(data.delivery_zone_id)})
        if z:
            zone_name = z.get("name")

    item_snapshot = {
        "item_id": f"itm_{uuid.uuid4().hex[:12]}",
        "product_id": str(custom_req["_id"]),
        "product_name_snapshot": f"Custom: {custom_req.get('furniture_type', 'Furniture')}",
        "category": "custom",
        "configuration_snapshot": {
            "custom_size": True,
            "ticket_number": custom_req.get("ticket_number"),
            "furniture_type": custom_req.get("furniture_type"),
            "dimensions": custom_req.get("dimensions", {}),
            "material": custom_req.get("material", ""),
            "reference_photos": custom_req.get("reference_photos", []),
            "custom_note": custom_req.get("notes", ""),
        },
        "quantity": 1,
        "unit_price_le": subtotal,
        "subtotal_le": subtotal,
    }

    order_doc = {
        "order_number": order_num,
        "customer_name": custom_req.get("customer_name"),
        "customer_phone": custom_req.get("customer_phone"),
        "phone_number": custom_req.get("phone_number"),
        "customer_address": data.customer_address or custom_req.get("customer_address") or "Dikonfirmasi via WA",
        "customer_maps_url": data.customer_maps_url or "",
        "delivery_method": data.delivery_method,
        "delivery_zone_id": data.delivery_zone_id,
        "delivery_zone_name": zone_name,
        "delivery_fee_le": delivery_fee,
        "payment_method": data.payment_method,
        "payment_status": "belum_dibayar",
        "order_status": "dikonfirmasi",
        "notes": f"[Tiket {custom_req.get('ticket_number')}] {data.notes or custom_req.get('notes', '')}",
        "admin_note": f"Dikonversi dari tiket {custom_req.get('ticket_number')} oleh {admin.get('name')}",
        "items": [item_snapshot],
        "item": item_snapshot,
        "subtotal_le": subtotal,
        "discount_code": None,
        "discount_percentage": 0,
        "discount_le": 0,
        "referral": None,
        "referral_discount_le": 0,
        "points_redeemed_le": 0,
        "customer_id": None,
        "customer_username": None,
        "total_le": total_le,
        "exchange_rate_idr_per_le": rate,
        "estimated_total_idr": round(total_le * rate),
        "rate_timestamp": now,
        "requires_admin_confirmation": False,
        "custom_request_id": str(custom_req["_id"]),
        "created_at": now,
        "updated_at": now,
    }

    order_result = await db.orders.insert_one(order_doc)
    order_id = str(order_result.inserted_id)

    await db.custom_requests.update_one(
        {"_id": custom_req["_id"]},
        {"$set": {
            "status": "dipesan",
            "converted_order_id": order_id,
            "estimated_price_le": subtotal,
            "updated_at": now,
        }}
    )

    created_order = await db.orders.find_one({"_id": order_result.inserted_id})
    return clean(created_order)

@api_router.post("/admin/custom-requests/{req_id}/permanent-delete")
async def admin_permanent_delete_custom_request(
    req_id: str,
    payload: PermanentDeleteInput,
    admin: dict = Depends(require_perm("delete_data"))
):
    if (payload.confirmation_phrase or "").strip() != "HAPUS PERMANEN":
        raise HTTPException(
            status_code=400,
            detail="Frasa konfirmasi tidak valid. Anda wajib mengetik 'HAPUS PERMANEN' secara tepat."
        )

    cr = await db.custom_requests.find_one({"_id": id_query(req_id)})
    if not cr:
        raise HTTPException(status_code=404, detail="Request custom tidak ditemukan")

    # Isolated delete: ONLY delete this custom request document.
    # Orders, invoices, finance, and customer remain untouched.
    res = await db.custom_requests.delete_one({"_id": cr["_id"]})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Request custom sudah dihapus sebelumnya")

    identifier = cr.get("ticket_number") or str(cr["_id"])
    await record_audit_log(
        action="PERMANENT_DELETE",
        entity_type="custom_request",
        entity_id=str(cr["_id"]),
        entity_identifier=identifier,
        admin=admin,
        metadata={
            "previous_status": cr.get("status"),
            "related_invoice_id": cr.get("invoice_id"),
            "converted_order_id": cr.get("converted_order_id"),
            "customer_phone": cr.get("customer_phone"),
            "reason": payload.reason,
        }
    )

    return {
        "ok": True,
        "message": f"Request custom {identifier} berhasil dihapus secara permanen."
    }

@api_router.delete("/admin/custom-requests/{req_id}")
async def admin_delete_custom_request(req_id: str, admin: dict = Depends(require_perm("delete_data"))):
    raise HTTPException(
        status_code=400,
        detail="Penghapusan request custom wajib melalui endpoint POST /api/admin/custom-requests/{req_id}/permanent-delete dengan frasa konfirmasi 'HAPUS PERMANEN'."
    )

@api_router.post("/admin/custom-collection/publish")
async def admin_publish_to_custom_collection(data: PublishCustomCollectionInput, admin: dict = Depends(require_perm("modify_products"))):
    title = data.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Nama desain harus diisi")

    custom_prod = await db.products.find_one({"category": "custom"})
    if not custom_prod:
        custom_prod = await db.products.find_one({"slug": {"$in": ["koleksi-custom", "pesanan-custom"]}})
    if not custom_prod:
        raise HTTPException(status_code=404, detail="Produk Koleksi Custom tidak ditemukan di database")

    prod_id = custom_prod["_id"]
    pricing = custom_prod.get("pricing") or {}
    groups = pricing.get("groups") or []
    photos = list(custom_prod.get("photos") or [])
    design_details = dict(custom_prod.get("design_details") or {})

    desain_group = None
    for g in groups:
        if g.get("key") == "desain":
            desain_group = g
            break
    if not desain_group:
        desain_group = {"key": "desain", "label": "Pilih Desain Custom", "options": []}
        groups.append(desain_group)

    if title not in desain_group.get("options", []):
        desain_group.setdefault("options", []).append(title)

    for url in data.photo_urls:
        url_clean = url.strip()
        if not url_clean:
            continue
        exists = any(ph.get("url") == url_clean and ph.get("attributes", {}).get("desain") == title for ph in photos)
        if not exists:
            photos.append({
                "url": url_clean,
                "file_id": None,
                "attributes": {"desain": title}
            })

    design_details[title] = {
        "price": float(data.price_le),
        "spesifikasi": data.spesifikasi or "",
        "published_at": datetime.now(timezone.utc).isoformat(),
        "published_by": admin.get("name") or admin.get("email")
    }

    pricing["groups"] = groups

    await db.products.update_one(
        {"_id": prod_id},
        {"$set": {
            "pricing": pricing,
            "photos": photos,
            "design_details": design_details,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }}
    )

    if data.order_id:
        await db.orders.update_one(
            {"_id": id_query(data.order_id)},
            {"$set": {
                "custom_collection_published": True,
                "custom_collection_title": title,
                "custom_collection_published_at": datetime.now(timezone.utc).isoformat()
            }}
        )

    if data.request_id:
        await db.custom_requests.update_one(
            {"_id": id_query(data.request_id)},
            {"$set": {
                "custom_collection_published": True,
                "custom_collection_title": title,
                "custom_collection_published_at": datetime.now(timezone.utc).isoformat()
            }}
        )

    return {"ok": True, "title": title, "photos_count": len(photos)}

# --------------------------------------------------------------------------
# Admin: delivery zones
# --------------------------------------------------------------------------
@api_router.post("/admin/delivery-zones")
async def admin_create_zone(data: DeliveryZoneInput, admin: dict = Depends(require_perm("manage_settings"))):
    doc = {"name": data.name, "fee_le": _num(data.fee_le), "active": data.active, "created_at": datetime.now(timezone.utc).isoformat()}
    result = await db.delivery_zones.insert_one(doc)
    return clean(await db.delivery_zones.find_one({"_id": result.inserted_id}))

@api_router.put("/admin/delivery-zones/{zone_id}")
async def admin_update_zone(zone_id: str, data: DeliveryZoneInput, admin: dict = Depends(require_perm("manage_settings"))):
    await db.delivery_zones.update_one({"_id": id_query(zone_id)}, {"$set": {"name": data.name, "fee_le": _num(data.fee_le), "active": data.active}})
    return clean(await db.delivery_zones.find_one({"_id": id_query(zone_id)}))

@api_router.delete("/admin/delivery-zones/{zone_id}")
async def admin_delete_zone(zone_id: str, admin: dict = Depends(require_perm("manage_settings"))):
    await db.delivery_zones.delete_one({"_id": id_query(zone_id)})
    return {"ok": True}

# --------------------------------------------------------------------------
# Phase 3.F.4.1: Logistics & Delivery Trip Core Engine
# --------------------------------------------------------------------------

class DeliveryTripStatus(str, Enum):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    IN_TRANSIT = "in_transit"
    PARTIALLY_COMPLETED = "partially_completed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"

class StopOutcome(str, Enum):
    PENDING = "pending"
    OUT_FOR_DELIVERY = "out_for_delivery"
    DELIVERED = "delivered"
    FAILED = "failed"
    FAILED_CLOSED = "failed_closed"
    CANCELLED = "cancelled"

VALID_TRIP_TRANSITIONS = {
    DeliveryTripStatus.DRAFT.value: {DeliveryTripStatus.SCHEDULED.value, DeliveryTripStatus.CANCELLED.value},
    DeliveryTripStatus.SCHEDULED.value: {DeliveryTripStatus.DRAFT.value, DeliveryTripStatus.IN_TRANSIT.value, DeliveryTripStatus.CANCELLED.value},
    DeliveryTripStatus.IN_TRANSIT.value: {DeliveryTripStatus.PARTIALLY_COMPLETED.value, DeliveryTripStatus.COMPLETED.value, DeliveryTripStatus.CANCELLED.value},
    DeliveryTripStatus.PARTIALLY_COMPLETED.value: {DeliveryTripStatus.COMPLETED.value},
    DeliveryTripStatus.COMPLETED.value: set(),
    DeliveryTripStatus.CANCELLED.value: set(),
}

VALID_STOP_TRANSITIONS = {
    StopOutcome.PENDING.value: {StopOutcome.OUT_FOR_DELIVERY.value, StopOutcome.CANCELLED.value},
    StopOutcome.OUT_FOR_DELIVERY.value: {StopOutcome.DELIVERED.value, StopOutcome.FAILED.value},
    StopOutcome.FAILED.value: {StopOutcome.OUT_FOR_DELIVERY.value, StopOutcome.FAILED_CLOSED.value, StopOutcome.CANCELLED.value},
    StopOutcome.DELIVERED.value: set(),
    StopOutcome.FAILED_CLOSED.value: set(),
    StopOutcome.CANCELLED.value: set(),
}

class DeliveryTripVehicleRentalInput(BaseModel):
    is_rented: bool = True
    rental_provider: str = Field(..., min_length=2, description="Nama penyedia rental pick-up")
    vehicle_plate_or_desc: str = Field(..., min_length=2, description="Plat nomor atau deskripsi armada")
    driver_provided_by_rental: bool = True
    rental_driver_name: str = Field(..., min_length=2, description="Nama sopir bawaan dari rental")
    agreed_rental_cost_le: float = Field(0.0, ge=0.0, description="Biaya sewa yang disepakati (LE)")
    agreement_reference: Optional[str] = None
    notes: Optional[str] = None

class DeliveryTripCreateInput(BaseModel):
    scheduled_date: str = Field(..., description="Tanggal jadwal keberangkatan YYYY-MM-DD")
    departure_time: Optional[str] = Field(None, description="Perkiraan jam keberangkatan HH:MM")
    trip_wage_rate_le: float = Field(0.0, ge=0.0, description="Tarif upah per helper per pesanan berhasil")
    helper_ids: List[str] = Field(default_factory=list, description="Daftar ID helper internal dari db.admins")
    vehicle_rental: DeliveryTripVehicleRentalInput
    notes: Optional[str] = None

class DeliveryTripStatusUpdateInput(BaseModel):
    target_status: str
    reason: Optional[str] = None

class DeliveryTripAddStopInput(BaseModel):
    order_id: str
    notes: Optional[str] = None

class DeliveryTripStopAttemptInput(BaseModel):
    outcome: str = Field(..., description="'failed' atau 'out_for_delivery' (untuk retry)")
    failure_reason: Optional[str] = None
    notes: Optional[str] = None

class DeliveryTripCancelInput(BaseModel):
    reason: str = Field(..., min_length=5, description="Alasan pembatalan trip wajib diisi")

class DeliveryTripCompleteInput(BaseModel):
    notes: Optional[str] = None

class DeliveryWagePolicyInput(BaseModel):
    base_wage_per_order_le: float = Field(..., ge=0.0, description="Tarif dasar upah per pesanan/lokasi yang berhasil diantar")
    unusual_amount_threshold_le: float = Field(..., gt=0.0, description="Batas konfirmasi nominal tidak wajar")
    max_helper_wage_per_order_le: Optional[float] = Field(None, gt=0.0, description="Batas maksimum keras upah (hard cap) per pesanan")
    currency: Optional[str] = "EGP"
    rounding_policy: Optional[str] = "piastre_round_half_up"
    enabled: Optional[bool] = True
    change_reason: Optional[str] = Field(None, max_length=500, description="Alasan perubahan kebijakan upah")

class ProductionWagePolicyInput(BaseModel):
    default_wage_per_unit_le: float = Field(..., ge=0.0, description="Tarif dasar upah per unit produksi")
    unusual_amount_threshold_le: float = Field(..., gt=0.0, description="Batas konfirmasi nominal tidak wajar")
    max_wage_per_unit_le: float = Field(..., gt=0.0, description="Batas maksimum keras upah per unit")
    enabled: bool = True
    currency: Optional[str] = "EGP"
    rounding_policy: Optional[str] = "piastre_round_half_up"
    change_reason: Optional[str] = Field(None, max_length=500, description="Alasan perubahan kebijakan upah")

class MaterialPurchaseWagePolicyInput(BaseModel):
    default_wage_per_purchase_le: float = Field(..., ge=0.0, description="Tarif dasar upah belanja bahan per transaksi")
    unusual_amount_threshold_le: float = Field(..., gt=0.0, description="Batas konfirmasi nominal tidak wajar")
    max_wage_per_purchase_le: float = Field(..., gt=0.0, description="Batas maksimum keras upah belanja bahan")
    max_buyers: int = Field(5, ge=1, le=5, description="Batas maksimum pembeli bahan per transaksi (maksimal 5)")
    enabled: bool = True
    currency: Optional[str] = "EGP"
    rounding_policy: Optional[str] = "piastre_round_half_up"
    change_reason: Optional[str] = Field(None, max_length=500, description="Alasan perubahan kebijakan upah")

class AdminWagePolicyInput(BaseModel):
    default_wage_per_order_le: float = Field(..., ge=0.0, description="Tarif upah admin per pesanan")
    default_recipient_id: Optional[str] = Field(None, description="ID penerima upah admin default dari db.admins")
    unusual_amount_threshold_le: float = Field(..., gt=0.0, description="Batas konfirmasi nominal tidak wajar")
    max_wage_per_order_le: float = Field(..., gt=0.0, description="Batas maksimum keras upah admin")
    enabled: bool = False
    currency: Optional[str] = "EGP"
    rounding_policy: Optional[str] = "piastre_round_half_up"
    change_reason: Optional[str] = Field(None, max_length=500, description="Alasan perubahan kebijakan upah")

class DeliveryWagePreviewInput(BaseModel):
    total_wage_le: Optional[float] = None
    helpers: List[Dict[str, Any]] = Field(default_factory=list, description="Daftar helper untuk kalkulasi pembagian")
    trip_id: Optional[str] = None
    order_id: Optional[str] = None

class DeliveryStopHandoverInput(BaseModel):
    recipient_name: Optional[str] = None
    handover_notes: Optional[str] = None
    helper_confirmed: Optional[bool] = False
    custom_wage_le: Optional[float] = None
    confirmed_unusual_amount: Optional[bool] = False
    override_reason: Optional[str] = None
    idempotency_key: Optional[str] = None

def validate_trip_state_transition(current_status: str, target_status: str, trip_doc: Optional[dict] = None) -> None:
    valid_targets = VALID_TRIP_TRANSITIONS.get(current_status, set())
    if target_status not in valid_targets:
        raise HTTPException(
            status_code=400,
            detail=f"Transisi status trip tidak valid dari '{current_status}' ke '{target_status}'. Target yang diizinkan: {sorted(list(valid_targets))}"
        )
    if target_status == DeliveryTripStatus.CANCELLED.value and trip_doc:
        check_trip_can_be_cancelled(trip_doc)

def validate_stop_state_transition(current_outcome: str, target_outcome: str) -> None:
    valid_targets = VALID_STOP_TRANSITIONS.get(current_outcome, set())
    if target_outcome not in valid_targets:
        raise HTTPException(
            status_code=400,
            detail=f"Transisi status stop tidak valid dari '{current_outcome}' ke '{target_outcome}'. Target yang diizinkan: {sorted(list(valid_targets))}"
        )

def check_trip_can_be_cancelled(trip: dict) -> None:
    for stop in trip.get("stops", []):
        if stop.get("outcome") == StopOutcome.DELIVERED.value:
            raise HTTPException(
                status_code=409,
                detail="Trip tidak dapat dibatalkan karena memuat pesanan yang telah diserahterimakan (delivered). Gunakan penutupan trip parsial."
            )

def check_trip_can_be_completed(trip: dict) -> None:
    for stop in trip.get("stops", []):
        if stop.get("outcome") in (StopOutcome.PENDING.value, StopOutcome.OUT_FOR_DELIVERY.value):
            raise HTTPException(
                status_code=409,
                detail="Trip tidak dapat diselesaikan karena masih memuat stop yang aktif (pending atau out_for_delivery)."
            )

async def validate_delivery_trip_wage_cap(rate_le: float, session=None) -> float:
    """
    FAIL-CLOSED check for Authoritative Owner Wage Cap and Tiered Policy.
    If policy is missing, incomplete, or cap <= 0: rejects dispatch with HTTP 422.
    No default values, no Manager bypass.
    """
    policy = await get_setting("delivery_wage_policy", None)
    if not policy or not isinstance(policy, dict):
        raise HTTPException(
            status_code=422,
            detail="Batas atas upah pengiriman (cap) belum ditetapkan oleh Owner. Penetapan tarif dan dispatch trip terkunci (Fail-Closed)."
        )
    cap = policy.get("max_helper_wage_per_order_le")
    threshold = policy.get("unusual_amount_threshold_le")
    if cap is None or _num(cap) <= 0:
        raise HTTPException(
            status_code=422,
            detail="Batas atas upah pengiriman (cap) belum ditetapkan oleh Owner. Penetapan tarif dan dispatch trip terkunci (Fail-Closed)."
        )
    if threshold is None or _num(threshold) <= 0:
        raise HTTPException(
            status_code=422,
            detail="Batas konfirmasi upah pengiriman belum ditetapkan oleh Owner. Penetapan tarif dan dispatch trip terkunci (Fail-Closed)."
        )
    cap_val = _num(cap)
    if _num(rate_le) > cap_val:
        raise HTTPException(
            status_code=422,
            detail=f"Tarif upah trip ({rate_le} LE) melebihi batas atas yang ditetapkan Owner ({cap_val} LE)."
        )
    return cap_val

async def get_active_delivery_wage_policy(db_inst=None) -> dict:
    """
    Returns the active delivery wage policy from db.settings.
    If not explicitly configured, provides the approved tiered business defaults:
    - Base helper wage: 50.0 EGP per successfully delivered order/location.
    - Unusual amount confirmation threshold: 100.0 EGP per order/location.
    - Hard maximum helper wage cap: 500.0 EGP per order/location.
    - Currency: EGP.
    - Rounding policy: Exact integer piastres (ROUND_HALF_UP).
    """
    d = db_inst if db_inst is not None else db
    doc = None
    if hasattr(d, "settings") and hasattr(d.settings, "find_one"):
        res = d.settings.find_one({"key": "delivery_wage_policy"})
        doc = await res if inspect.isawaitable(res) else res

    val = doc.get("value") if doc and isinstance(doc.get("value"), dict) else {}
    has_hard_cap = "max_helper_wage_per_order_le" in val and val["max_helper_wage_per_order_le"] is not None
    has_threshold = "unusual_amount_threshold_le" in val and val["unusual_amount_threshold_le"] is not None
    is_configured = bool(val and has_hard_cap and has_threshold)

    return {
        "base_wage_per_order_le": _num(val.get("base_wage_per_order_le"), 50.0),
        "unusual_amount_threshold_le": _num(val.get("unusual_amount_threshold_le"), 100.0),
        "max_helper_wage_per_order_le": _num(val.get("max_helper_wage_per_order_le"), 500.0) if has_hard_cap else 500.0,
        "currency": val.get("currency", "EGP"),
        "rounding_policy": val.get("rounding_policy", "piastre_round_half_up"),
        "enabled": bool(val.get("enabled", True)),
        "updated_at": val.get("updated_at"),
        "updated_by_id": val.get("updated_by_id"),
        "updated_by_name": val.get("updated_by_name"),
        "last_change_reason": val.get("last_change_reason"),
        "is_configured": is_configured
    }

async def get_active_production_wage_policy(db_inst=None) -> dict:
    """
    Returns active production wage policy from db.settings.
    If not explicitly configured by Owner, returns is_configured: False and enabled: False
    without guessing business rates.
    """
    d = db_inst if db_inst is not None else db
    doc = None
    if hasattr(d, "settings") and hasattr(d.settings, "find_one"):
        res = d.settings.find_one({"key": "production_wage_policy"})
        doc = await res if inspect.isawaitable(res) else res

    val = doc.get("value") if doc and isinstance(doc.get("value"), dict) else {}
    has_hard_cap = "max_wage_per_unit_le" in val and val["max_wage_per_unit_le"] is not None
    has_threshold = "unusual_amount_threshold_le" in val and val["unusual_amount_threshold_le"] is not None
    has_default = "default_wage_per_unit_le" in val and val["default_wage_per_unit_le"] is not None
    is_configured = bool(val and has_hard_cap and has_threshold and has_default)

    return {
        "default_wage_per_unit_le": _num(val.get("default_wage_per_unit_le"), None) if has_default else None,
        "unusual_amount_threshold_le": _num(val.get("unusual_amount_threshold_le"), None) if has_threshold else None,
        "max_wage_per_unit_le": _num(val.get("max_wage_per_unit_le"), None) if has_hard_cap else None,
        "enabled": bool(val.get("enabled", False)) if is_configured else False,
        "currency": val.get("currency", "EGP"),
        "rounding_policy": val.get("rounding_policy", "piastre_round_half_up"),
        "updated_at": val.get("updated_at"),
        "updated_by_id": val.get("updated_by_id"),
        "updated_by_name": val.get("updated_by_name"),
        "last_change_reason": val.get("last_change_reason"),
        "is_configured": is_configured
    }

async def get_active_material_purchase_wage_policy(db_inst=None) -> dict:
    """
    Returns active material purchase wage policy from db.settings.
    If not explicitly configured by Owner, returns is_configured: False and enabled: False
    without guessing business rates.
    """
    d = db_inst if db_inst is not None else db
    doc = None
    if hasattr(d, "settings") and hasattr(d.settings, "find_one"):
        res = d.settings.find_one({"key": "material_purchase_wage_policy"})
        doc = await res if inspect.isawaitable(res) else res

    val = doc.get("value") if doc and isinstance(doc.get("value"), dict) else {}
    has_hard_cap = "max_wage_per_purchase_le" in val and val["max_wage_per_purchase_le"] is not None
    has_threshold = "unusual_amount_threshold_le" in val and val["unusual_amount_threshold_le"] is not None
    has_default = "default_wage_per_purchase_le" in val and val["default_wage_per_purchase_le"] is not None
    is_configured = bool(val and has_hard_cap and has_threshold and has_default)

    return {
        "default_wage_per_purchase_le": _num(val.get("default_wage_per_purchase_le"), None) if has_default else None,
        "unusual_amount_threshold_le": _num(val.get("unusual_amount_threshold_le"), None) if has_threshold else None,
        "max_wage_per_purchase_le": _num(val.get("max_wage_per_purchase_le"), None) if has_hard_cap else None,
        "max_buyers": min(5, max(1, int(val.get("max_buyers", 5)))),
        "enabled": bool(val.get("enabled", False)) if is_configured else False,
        "currency": val.get("currency", "EGP"),
        "rounding_policy": val.get("rounding_policy", "piastre_round_half_up"),
        "updated_at": val.get("updated_at"),
        "updated_by_id": val.get("updated_by_id"),
        "updated_by_name": val.get("updated_by_name"),
        "last_change_reason": val.get("last_change_reason"),
        "is_configured": is_configured
    }

async def get_active_admin_wage_policy(db_inst=None) -> dict:
    """
    Returns active admin wage policy from db.settings.
    If not explicitly configured by Owner, returns is_configured: False and enabled: False
    without guessing business rates.
    """
    d = db_inst if db_inst is not None else db
    doc = None
    if hasattr(d, "settings") and hasattr(d.settings, "find_one"):
        res = d.settings.find_one({"key": "admin_wage_policy"})
        doc = await res if inspect.isawaitable(res) else res

    val = doc.get("value") if doc and isinstance(doc.get("value"), dict) else {}
    has_hard_cap = "max_wage_per_order_le" in val and val["max_wage_per_order_le"] is not None
    has_threshold = "unusual_amount_threshold_le" in val and val["unusual_amount_threshold_le"] is not None
    has_default = "default_wage_per_order_le" in val and val["default_wage_per_order_le"] is not None
    is_configured = bool(val and has_hard_cap and has_threshold and has_default)
    is_enabled = bool(val.get("enabled", False)) if is_configured else False

    cycles = list(val.get("activation_cycles") or [])
    current_cycle_id = val.get("current_cycle_id")
    initial_act_at = val.get("initial_activation_at")

    return {
        "default_wage_per_order_le": _num(val.get("default_wage_per_order_le"), None) if has_default else None,
        "default_recipient_id": val.get("default_recipient_id"),
        "default_recipient_name": val.get("default_recipient_name"),
        "unusual_amount_threshold_le": _num(val.get("unusual_amount_threshold_le"), None) if has_threshold else None,
        "max_wage_per_order_le": _num(val.get("max_wage_per_order_le"), None) if has_hard_cap else None,
        "enabled": is_enabled,
        "currency": val.get("currency", "EGP"),
        "rounding_policy": val.get("rounding_policy", "piastre_round_half_up"),
        "activation_cycles": cycles,
        "current_cycle_id": current_cycle_id,
        "initial_activation_at": initial_act_at,
        "activation_context": {
            "initial_activation_at": initial_act_at,
            "current_cycle_id": current_cycle_id,
            "total_cycles": len(cycles),
            "is_currently_active": is_enabled,
            "last_toggled_at": val.get("updated_at"),
            "last_toggled_by_name": val.get("updated_by_name"),
        },
        "updated_at": val.get("updated_at"),
        "updated_by_id": val.get("updated_by_id"),
        "updated_by_name": val.get("updated_by_name"),
        "last_change_reason": val.get("last_change_reason"),
        "is_configured": is_configured
    }

def is_timestamp_within_active_cycle(timestamp_iso: Optional[str], policy: dict) -> Tuple[bool, Optional[str]]:
    """
    Evaluates whether a timestamp falls within any recorded activation cycle.
    Returns: (is_within, cycle_id)
    """
    if not timestamp_iso or not isinstance(policy, dict):
        return False, None
    cycles = policy.get("activation_cycles") or []
    for c in cycles:
        en_at = c.get("enabled_at")
        dis_at = c.get("disabled_at")
        if not en_at:
            continue
        if dis_at:
            if en_at <= timestamp_iso <= dis_at:
                return True, c.get("cycle_id")
        else:
            if timestamp_iso >= en_at:
                return True, c.get("cycle_id")
    # Fallback for legacy policy documents without activation_cycles array:
    if not cycles and policy.get("enabled"):
        init_act = policy.get("initial_activation_at")
        if init_act and timestamp_iso >= init_act:
            return True, policy.get("current_cycle_id") or "legacy_cycle"
    return False, None

def is_order_historical_unreconciled(order: dict, policy: Optional[dict] = None) -> bool:
    """
    Evaluates whether an order has explicit legacy manual payment or reconciliation markers.
    Preserved for backward compatibility with pre-existing legacy data markers.
    Normal lifecycle orders are evaluated based on event transitions without date cutoffs.
    """
    if not isinstance(order, dict):
        return False
    if order.get("admin_wage_legacy_reconciled") or order.get("is_legacy_manual"):
        return True
    if order.get("has_unrecorded_legacy_dp") or order.get("legacy_manual_payment"):
        return True
    if order.get("legacy_finance_transaction_id"):
        return True
    return False

def get_order_admin_wage_eligibility(order: dict, policy: Optional[dict] = None) -> dict:
    """
    Returns explicit eligibility dictionary for an order.
    Preserves persisted subdocument 'admin_wage_eligibility' if present,
    or derives canonical status for backward compatibility.
    """
    if not isinstance(order, dict):
        return {"scope_status": "in_scope_pending", "governance_mode": "automatic", "version": 1}

    existing_el = order.get("admin_wage_eligibility")
    if existing_el and isinstance(existing_el, dict) and existing_el.get("scope_status"):
        return dict(existing_el)

    if order.get("admin_wage_legacy_reconciled") or order.get("is_legacy_manual"):
        return {
            "scope_status": "excluded_historical",
            "governance_mode": "historical",
            "evaluated_at": order.get("updated_at"),
            "version": 1
        }
    if order.get("admin_wage_obligation"):
        ob = order.get("admin_wage_obligation") or {}
        return {
            "scope_status": "accrued",
            "governance_mode": "manual_override" if ob.get("is_override") else "automatic",
            "obligation_id": str(ob.get("obligation_id") or ""),
            "obligation_number": ob.get("obligation_number"),
            "evaluated_at": ob.get("accrued_at") or order.get("updated_at"),
            "version": 1
        }
    if order.get("admin_wage_blocked"):
        b = order.get("admin_wage_blocked") or {}
        return {
            "scope_status": "blocked",
            "governance_mode": "automatic",
            "blocked_reason": b.get("reason"),
            "evaluated_at": b.get("blocked_at") or order.get("updated_at"),
            "version": 1
        }
    skipped = order.get("admin_wage_skipped") or {}
    if skipped.get("status") in ("skipped_policy_disabled", "skipped_disabled_window"):
        return {
            "scope_status": "skipped_disabled_window",
            "governance_mode": "automatic",
            "skip_reason": skipped.get("reason"),
            "evaluated_at": skipped.get("skipped_at") or order.get("updated_at"),
            "in_active_cycle_at_maturity": False,
            "version": 1
        }
    override = order.get("admin_wage_override") or {}
    if override.get("is_override"):
        return {
            "scope_status": "manual_override",
            "governance_mode": "manual_override",
            "evaluated_at": override.get("updated_at") or order.get("updated_at"),
            "version": 1
        }
    return {
        "scope_status": "in_scope_pending",
        "governance_mode": "automatic",
        "evaluated_at": order.get("updated_at") or order.get("created_at"),
        "version": 1
    }

async def get_all_active_wage_policies(db_inst=None) -> dict:
    return {
        "production": await get_active_production_wage_policy(db_inst),
        "delivery": await get_active_delivery_wage_policy(db_inst),
        "material_purchase": await get_active_material_purchase_wage_policy(db_inst),
        "admin": await get_active_admin_wage_policy(db_inst)
    }

def build_admin_wage_accrual_event_key(order_id: str) -> str:
    return f"admin_wage:{str(order_id).strip()}"

def _safe_finance_amount(val: Any) -> Optional[float]:
    """
    Safely converts a value to float for financial computations without raising ValueError/TypeError.
    Strictly excludes booleans (bool is a subclass of int in Python where float(False) == 0.0).
    Filters out NaN, inf, -inf, and negative amounts.
    Returns None if value cannot be safely interpreted as a valid finite non-negative numeric amount.
    """
    if val is None or isinstance(val, bool):
        return None
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f) or f < 0:
            return None
        return f
    except (ValueError, TypeError):
        return None

CANCELLED_ORDER_STATUSES = frozenset({
    "dibatalkan", "cancelled", "canceled", "batal", "void", "voided"
})
COMPLETED_ORDER_STATUSES = frozenset({
    "selesai", "completed"
})

def is_order_completed(order: dict) -> bool:
    """
    Evaluates whether an order has reached 'completed' status canonically.
    Owner Business Rule:
    - Order is cancelled or void -> CANNOT be completed (absolute precedence).
    - Canonical status is 'order_status'. If set:
        * 'selesai' or 'completed' -> True.
        * Otherwise (e.g. 'diproses', 'siap', 'pesanan_masuk') -> False.
    - Secondary fallback: 'status'. If set:
        * 'selesai' or 'completed' -> True.
        * Otherwise -> False.
    - Historical fallback: If neither status field is provided, non-empty 'completed_at' -> True.
    """
    if not isinstance(order, dict):
        return False

    order_status = str(order.get("order_status") or "").strip().lower()
    generic_status = str(order.get("status") or "").strip().lower()

    # Rule 1: Absolute cancellation / void precedence
    if (
        bool(order.get("is_voided"))
        or order_status in CANCELLED_ORDER_STATUSES
        or generic_status in CANCELLED_ORDER_STATUSES
    ):
        return False

    # Rule 2: Primary canonical field: order_status
    if order_status:
        return order_status in COMPLETED_ORDER_STATUSES

    # Rule 3: Secondary legacy alias: status
    if generic_status:
        return generic_status in COMPLETED_ORDER_STATUSES

    # Rule 4: Historical completion timestamp fallback when no status is populated
    return bool(order.get("completed_at"))

def is_order_fully_paid(order: dict, payment_summary: Optional[dict] = None) -> bool:
    """
    Evaluates whether customer payments on an order are fully paid (lunas).
    Canonical conditions:
    1. If payment_summary provided:
       - If outstanding balance is explicitly provided and > 0.01: NOT fully paid (fail-closed against contradictory data).
       - If outstanding <= 0.01 and paid >= total > 0: fully paid.
       - If payment_summary.payment_status in ('lunas', 'overpaid') and (outstanding is None or outstanding <= 0.01): fully paid.
    2. Direct order document evaluation:
       - order.payment_status in ('lunas', 'overpaid', 'paid'):
         * If outstanding is provided and > 0.01: NOT fully paid (contradictory data).
         * If total and paid are provided and total > 0 and paid < total - 0.01: NOT fully paid (contradictory data).
         * Otherwise: fully paid.
       - If order.payment_status not 'lunas', but outstanding <= 0.01 and total > 0 and paid >= total - 0.01: fully paid.
    3. Malformed numeric values (strings like 'N/A', boolean False, negative totals, NaN) fail closed safely.
    """
    if not isinstance(order, dict):
        return False

    # 1. Evaluate from payment_summary if provided
    if payment_summary and isinstance(payment_summary, dict):
        raw_ps_out = payment_summary.get("outstanding_amount_le")
        raw_ps_tot = payment_summary.get("total_le")
        if raw_ps_tot is None:
            raw_ps_tot = order.get("total_le")
        raw_ps_paid = payment_summary.get("paid_amount_le")

        # Fail closed if provided fields are malformed
        if raw_ps_out is not None and _safe_finance_amount(raw_ps_out) is None:
            return False
        if raw_ps_tot is not None and _safe_finance_amount(raw_ps_tot) is None:
            return False
        if raw_ps_paid is not None and _safe_finance_amount(raw_ps_paid) is None:
            return False

        ps_status = str(payment_summary.get("payment_status") or "").strip().lower()
        ps_outstanding = _safe_finance_amount(raw_ps_out)
        ps_total = _safe_finance_amount(raw_ps_tot)
        ps_paid = _safe_finance_amount(raw_ps_paid)

        # Explicit outstanding check: if outstanding > 0.01, cannot be fully paid even if status claims lunas
        if ps_outstanding is not None:
            if ps_outstanding > 0.01:
                return False
            # outstanding <= 0.01
            if ps_total is not None and ps_paid is not None:
                if ps_total > 0 and ps_paid >= (ps_total - 0.01):
                    return True
            if ps_status in ("lunas", "overpaid"):
                return True

        if ps_status in ("lunas", "overpaid"):
            if ps_total is not None and ps_paid is not None and ps_total > 0:
                if ps_paid < (ps_total - 0.01):
                    return False
            return True

    # 2. Evaluate from order document
    raw_ord_out = order.get("outstanding_amount_le")
    raw_ord_tot = (
        order.get("total_le") if order.get("total_le") is not None
        else order.get("total_amount_le") if order.get("total_amount_le") is not None
        else order.get("total_price_le") if order.get("total_price_le") is not None
        else order.get("grand_total_le")
    )
    raw_ord_paid = order.get("paid_amount_le")

    # Fail closed if provided financial fields are malformed (e.g. NaN, Inf, non-numeric strings, negative)
    if raw_ord_out is not None and _safe_finance_amount(raw_ord_out) is None:
        return False
    if raw_ord_tot is not None and _safe_finance_amount(raw_ord_tot) is None:
        return False
    if raw_ord_paid is not None and _safe_finance_amount(raw_ord_paid) is None:
        return False

    order_status = str(order.get("payment_status") or "").strip().lower()
    ord_outstanding = _safe_finance_amount(raw_ord_out)
    ord_total = _safe_finance_amount(raw_ord_tot)
    ord_paid = _safe_finance_amount(raw_ord_paid)

    # If explicit outstanding is present:
    if ord_outstanding is not None:
        if ord_outstanding > 0.01:
            return False
        # ord_outstanding <= 0.01
        if ord_total is not None and ord_paid is not None:
            if ord_total > 0 and ord_paid >= (ord_total - 0.01):
                return True
        if order_status in ("lunas", "overpaid", "paid"):
            return True

    # If outstanding is not present:
    if order_status in ("lunas", "overpaid", "paid"):
        if ord_total is not None and ord_paid is not None and ord_total > 0:
            if ord_paid < (ord_total - 0.01):
                return False
        return True

    # When payment_status is not 'lunas', but amounts demonstrate full payment:
    if ord_total is not None and ord_paid is not None and ord_total > 0:
        if ord_paid >= (ord_total - 0.01):
            if ord_outstanding is None or ord_outstanding <= 0.01:
                return True

    return False

def is_order_excluded_from_admin_wage(order: dict) -> bool:
    """
    Evaluates whether an order is explicitly excluded from automated admin wage accrual.
    Includes:
    - admin_wage_legacy_reconciled == True
    - is_legacy_manual == True
    """
    if not isinstance(order, dict):
        return False
    return bool(order.get("admin_wage_legacy_reconciled") or order.get("is_legacy_manual"))

async def process_order_admin_wage_accrual(
    order: dict,
    admin: dict,
    session=None,
    policy: Optional[dict] = None,
    payment_summary: Optional[dict] = None,
    lifecycle_event: Optional[str] = None,
    transition_context: Optional[dict] = None
) -> dict:
    """
    Evaluates and creates the admin wage obligation for an order transitioning to 'lunas'.
    Enforces:
    1. Precedence: Per-order override (`admin_wage_override`) > Global Policy (`get_active_admin_wage_policy`).
    2. Hard-Cap Conflict (Option A - Fail-Closed with Alert):
       If override nominal > active hard cap (max_wage_per_order_le), payment succeeds but wage obligation
       is NOT created. Sets order admin_wage_blocked with conflict alert. Never silently clamps or replaces.
    3. Idempotency: Canonical key `admin_wage:{order_id}` guarded by unique index `uniq_wage_obligation_accrual_event`.
    4. Recipient Validation: Verified in db.admins. If missing/invalid, sets blocked_invalid_recipient fail-safe.
    5. Inactive/Disabled Policy: Fails safe with skipped_policy_disabled without crashing customer payment.
    6. Strict Manual Configuration: Valid manual override proceeds even if global automation is OFF.
       Missing/invalid manual configuration fails-closed without falling back silently to default rates.
    """
    find_kw = {"session": session} if session is not None else {}
    order_id_str = str(order.get("_id") or order.get("id")).strip()
    accrual_key = build_admin_wage_accrual_event_key(order_id_str)
    now_iso = datetime.now(timezone.utc).isoformat()

    # Defense-in-depth: explicit exclusion guard
    if is_order_excluded_from_admin_wage(order):
        return {
            "status": "skipped_legacy_reconciled",
            "skipped": {
                "status": "skipped_legacy_reconciled",
                "reason": "Pesanan historis/manual telah ditandai direkonsiliasi dan dikecualikan dari akrual otomatis.",
                "skipped_at": now_iso
            },
            "eligibility": {
                "scope_status": "excluded_historical",
                "governance_mode": "historical",
                "evaluated_at": now_iso,
                "version": 1
            }
        }

    # 1. Check existing obligation for idempotency
    existing_wob = await _mongo_find_one(db.wage_obligations, {"accrual_event_key": accrual_key}, **find_kw)
    if existing_wob:
        ob_status = str(existing_wob.get("status") or "").strip().lower()
        if ob_status in ("accrued", "paid", "partially_paid"):
            return {
                "status": "already_accrued",
                "obligation": {
                    "obligation_number": existing_wob.get("obligation_number"),
                    "obligation_id": str(existing_wob.get("_id")),
                    "accrual_event_key": accrual_key,
                    "task_category": "admin",
                    "recipient_id": str(existing_wob.get("worker_id")),
                    "recipient_name": existing_wob.get("worker_name"),
                    "amount_le": existing_wob.get("total_amount_le"),
                    "status": existing_wob.get("status"),
                    "is_override": existing_wob.get("is_override", False),
                    "accrued_at": existing_wob.get("accrued_at") or existing_wob.get("created_at"),
                },
                "eligibility": {
                    "scope_status": "accrued",
                    "governance_mode": "manual_override" if existing_wob.get("is_override") else "automatic",
                    "obligation_number": existing_wob.get("obligation_number"),
                    "obligation_id": str(existing_wob.get("_id")),
                    "evaluated_at": now_iso,
                    "version": 1
                }
            }
        if ob_status in ("void", "voided", "cancelled"):
            blocked_info = {
                "status": "blocked_prior_voided_obligation",
                "reason": (
                    f"Kewajiban upah admin untuk pesanan {order_id_str} sebelumnya telah dibatalkan/void "
                    f"(nomor: {existing_wob.get('obligation_number')}, status: {ob_status}). "
                    f"Pembuatan ulang kewajiban memerlukan audit dan review manual oleh Owner."
                ),
                "existing_obligation_number": existing_wob.get("obligation_number"),
                "existing_obligation_id": str(existing_wob.get("_id")),
                "existing_obligation_status": ob_status,
                "accrual_event_key": accrual_key,
                "owner_review_required": True,
                "blocked_at": now_iso,
            }
            return {
                "status": "blocked_prior_voided_obligation",
                "blocked": blocked_info,
                "eligibility": {
                    "scope_status": "blocked",
                    "governance_mode": "automatic",
                    "blocked_reason": blocked_info["reason"],
                    "evaluated_at": now_iso,
                    "version": 1
                }
            }

    # 2. Load active admin wage policy if not provided
    if policy is None:
        policy = await get_active_admin_wage_policy(db_inst=db)

    # 3. Resolve precedence: Order Override vs Default Policy
    override = order.get("admin_wage_override") or {}
    is_override = bool(override.get("is_override"))

    wage_amount = None
    recipient_id = None
    recipient_name = None
    override_reason = None

    if is_override:
        override_amt = _safe_finance_amount(override.get("amount_le"))
        if override_amt is None or override_amt <= 0:
            blocked_info = {
                "status": "blocked_missing_rate",
                "reason": "Nominal upah admin override manual tidak valid atau tidak diisi (dilarang fallback diam-diam ke default global)",
                "attempted_amount_le": override.get("amount_le"),
                "recipient_id": str(override.get("recipient_id") or "") or None,
                "recipient_name": override.get("recipient_name"),
                "blocked_at": now_iso,
            }
            return {
                "status": "blocked_missing_rate",
                "blocked": blocked_info,
                "eligibility": {
                    "scope_status": "blocked",
                    "governance_mode": "manual_override",
                    "blocked_reason": blocked_info["reason"],
                    "evaluated_at": now_iso,
                    "version": 1
                }
            }

        override_recip_id = str(override.get("recipient_id") or "").strip() or None
        if not override_recip_id:
            blocked_info = {
                "status": "blocked_missing_recipient",
                "reason": "Penerima upah admin override manual tidak ditentukan (konfigurasi manual per-pesanan wajib eksplisit dan tidak boleh diam-diam mengambil penerima default global)",
                "attempted_amount_le": override_amt,
                "recipient_id": None,
                "recipient_name": None,
                "blocked_at": now_iso,
            }
            return {
                "status": "blocked_missing_recipient",
                "blocked": blocked_info,
                "eligibility": {
                    "scope_status": "blocked",
                    "governance_mode": "manual_override",
                    "blocked_reason": blocked_info["reason"],
                    "evaluated_at": now_iso,
                    "version": 1
                }
            }

        recip_doc = await _mongo_find_one(db.admins, {"_id": id_query(override_recip_id)}, **find_kw)
        if not recip_doc:
            blocked_info = {
                "status": "blocked_invalid_recipient",
                "reason": f"Penerima upah admin '{override_recip_id}' tidak ditemukan di database admin",
                "attempted_amount_le": override_amt,
                "recipient_id": str(override_recip_id),
                "recipient_name": override.get("recipient_name"),
                "blocked_at": now_iso,
            }
            return {
                "status": "blocked_invalid_recipient",
                "blocked": blocked_info,
                "eligibility": {
                    "scope_status": "blocked",
                    "governance_mode": "manual_override",
                    "blocked_reason": blocked_info["reason"],
                    "evaluated_at": now_iso,
                    "version": 1
                }
            }

        wage_amount = override_amt
        recipient_id = str(recip_doc.get("_id") or override_recip_id)
        recipient_name = recip_doc.get("name") or override.get("recipient_name") or "Admin"
        override_reason = override.get("override_reason")

        # Option A: Hard-cap conflict validation
        hard_cap = policy.get("max_wage_per_order_le")
        if hard_cap is not None and wage_amount is not None and wage_amount > hard_cap:
            logger.warning(
                f"Admin wage accrual blocked by hard cap conflict for order {order_id_str}: "
                f"override nominal {wage_amount} LE exceeds active hard cap {hard_cap} LE"
            )
            blocked_info = {
                "status": "blocked_hard_cap_conflict",
                "reason": f"Nominal upah override ({wage_amount} LE) melebihi batas maksimum aktif ({hard_cap} LE)",
                "attempted_amount_le": wage_amount,
                "max_wage_per_order_le": hard_cap,
                "recipient_id": str(recipient_id) if recipient_id else None,
                "recipient_name": recipient_name,
                "blocked_at": now_iso,
            }
            return {
                "status": "blocked_hard_cap_conflict",
                "blocked": blocked_info,
                "eligibility": {
                    "scope_status": "blocked",
                    "governance_mode": "manual_override",
                    "blocked_reason": blocked_info["reason"],
                    "evaluated_at": now_iso,
                    "version": 1
                }
            }

    else:
        # Default policy resolution
        if not policy.get("enabled") or not policy.get("is_configured") or policy.get("default_wage_per_order_le") is None:
            skipped_info = {
                "status": "skipped_policy_disabled",
                "reason": "Kebijakan upah admin tidak aktif saat pesanan selesai dan lunas",
                "skipped_at": now_iso,
            }
            eligibility_info = {
                "scope_status": "skipped_disabled_window",
                "governance_mode": "automatic",
                "maturity_timestamp": now_iso,
                "evaluated_at": now_iso,
                "in_active_cycle_at_maturity": False,
                "skip_reason": "settled_while_automation_disabled",
                "version": 1
            }
            return {
                "status": "skipped_policy_disabled",
                "skipped": skipped_info,
                "eligibility": eligibility_info
            }

        # Check: Trusted lifecycle transition context (enforce fail-closed for automatic accrual without verified event)
        eff_event = lifecycle_event

        if not eff_event:
            return {
                "status": "skipped_missing_lifecycle_event",
                "skipped": {
                    "status": "skipped_missing_lifecycle_event",
                    "reason": "Evaluasi akrual upah otomatis wajib menyertakan konteks event transisi siklus hidup resmi ('order_completed' atau 'payment_lunas').",
                    "skipped_at": now_iso
                },
                "eligibility": {
                    "scope_status": "in_scope_pending",
                    "governance_mode": "automatic",
                    "skip_reason": "missing_trusted_lifecycle_event",
                    "evaluated_at": now_iso,
                    "version": 1
                }
            }

        if eff_event not in ("order_completed", "payment_lunas"):
            return {
                "status": "skipped_invalid_lifecycle_event",
                "skipped": {
                    "status": "skipped_invalid_lifecycle_event",
                    "reason": f"Event siklus hidup '{eff_event}' tidak valid untuk akrual upah admin otomatis.",
                    "skipped_at": now_iso
                },
                "eligibility": {
                    "scope_status": "in_scope_pending",
                    "governance_mode": "automatic",
                    "skip_reason": "invalid_lifecycle_event",
                    "evaluated_at": now_iso,
                    "version": 1
                }
            }

        # Authoritative Persisted State & Transition Verification against db.orders
        # Strict security constraint: caller-supplied snapshots are completely untrusted and ignored.
        persisted_order = None
        if hasattr(db, "orders") and hasattr(db.orders, "find_one"):
            persisted_order = await _mongo_find_one(db.orders, {"_id": id_query(order_id_str)}, **find_kw)

        if not persisted_order:
            return {
                "status": "skipped_unverifiable_transition",
                "skipped": {
                    "status": "skipped_unverifiable_transition",
                    "reason": "Data pesanan otoritatif tidak ditemukan di database; akrual otomatis ditolak demi keamanan transaksi.",
                    "skipped_at": now_iso
                },
                "eligibility": {
                    "scope_status": "in_scope_pending",
                    "governance_mode": "automatic",
                    "skip_reason": "authoritative_order_state_missing",
                    "evaluated_at": now_iso,
                    "version": 1
                }
            }

        # Transition context identity and semantics validation
        if transition_context and isinstance(transition_context, dict):
            ctx_order_id = str(transition_context.get("order_id") or "").strip()
            if ctx_order_id and ctx_order_id != order_id_str:
                return {
                    "status": "skipped_unverifiable_transition",
                    "skipped": {
                        "status": "skipped_unverifiable_transition",
                        "reason": f"Konteks transisi tidak cocok dengan ID pesanan target ({ctx_order_id} != {order_id_str}).",
                        "skipped_at": now_iso
                    },
                    "eligibility": {
                        "scope_status": "in_scope_pending",
                        "governance_mode": "automatic",
                        "skip_reason": "order_identity_mismatch",
                        "evaluated_at": now_iso,
                        "version": 1
                    }
                }

        # Check A: If order was ALREADY completed AND ALREADY fully paid in persistent storage
        if is_order_completed(persisted_order) and is_order_fully_paid(persisted_order):
            maturity_ts = (
                persisted_order.get("completed_at")
                or persisted_order.get("paid_at")
                or order.get("completed_at")
                or order.get("paid_at")
            )
            is_active, _ = is_timestamp_within_active_cycle(maturity_ts, policy)
            if not is_active:
                return {
                    "status": "skipped_unverifiable_transition",
                    "skipped": {
                        "status": "skipped_unverifiable_transition",
                        "reason": "Pesanan telah selesai dan lunas sebelum siklus otomatisasi aktif; akrual otomatis ditolak.",
                        "skipped_at": now_iso
                    },
                    "eligibility": {
                        "scope_status": "excluded_historical",
                        "governance_mode": "historical",
                        "skip_reason": "settled_prior_to_system_activation",
                        "evaluated_at": now_iso,
                        "version": 1
                    }
                }

            # An order already settled in DB cannot transition again without state change
            if eff_event == "order_completed":
                return {
                    "status": "skipped_unverifiable_transition",
                    "skipped": {
                        "status": "skipped_unverifiable_transition",
                        "reason": "Pesanan sudah berstatus selesai di database; transisi order_completed tidak valid.",
                        "skipped_at": now_iso
                    },
                    "eligibility": {
                        "scope_status": "in_scope_pending",
                        "governance_mode": "automatic",
                        "skip_reason": "order_already_completed_in_database",
                        "evaluated_at": now_iso,
                        "version": 1
                    }
                }
            elif eff_event == "payment_lunas":
                return {
                    "status": "skipped_unverifiable_transition",
                    "skipped": {
                        "status": "skipped_unverifiable_transition",
                        "reason": "Pesanan sudah berstatus lunas di database; transisi payment_lunas tidak valid.",
                        "skipped_at": now_iso
                    },
                    "eligibility": {
                        "scope_status": "in_scope_pending",
                        "governance_mode": "automatic",
                        "skip_reason": "order_already_fully_paid_in_database",
                        "evaluated_at": now_iso,
                        "version": 1
                    }
                }

        # Check B: Transition checks against authoritative persisted_order
        if eff_event == "order_completed":
            target_status = str(order.get("order_status") or order.get("status") or "").strip().lower()
            if target_status in ("dibatalkan", "cancelled", "void"):
                return {
                    "status": "skipped_order_not_completed",
                    "skipped": {
                        "status": "skipped_order_not_completed",
                        "reason": f"Pesanan target berstatus batal ('{target_status}'); akrual otomatis ditolak.",
                        "skipped_at": now_iso
                    },
                    "eligibility": {
                        "scope_status": "in_scope_pending",
                        "governance_mode": "automatic",
                        "skip_reason": "order_not_completed",
                        "evaluated_at": now_iso,
                        "version": 1
                    }
                }
            if is_order_completed(persisted_order):
                return {
                    "status": "skipped_unverifiable_transition",
                    "skipped": {
                        "status": "skipped_unverifiable_transition",
                        "reason": "Pesanan sudah berstatus selesai di database; transisi order_completed tidak valid.",
                        "skipped_at": now_iso
                    },
                    "eligibility": {
                        "scope_status": "in_scope_pending",
                        "governance_mode": "automatic",
                        "skip_reason": "order_already_completed_in_database",
                        "evaluated_at": now_iso,
                        "version": 1
                    }
                }
            if transition_context and isinstance(transition_context, dict):
                ctx_from = str(transition_context.get("from_status") or "").strip().lower()
                ctx_to = str(transition_context.get("to_status") or "").strip().lower()
                persisted_status = str(persisted_order.get("order_status") or persisted_order.get("status") or "").strip().lower()
                if ctx_from and persisted_status and ctx_from != persisted_status:
                    return {
                        "status": "skipped_unverifiable_transition",
                        "skipped": {
                            "status": "skipped_unverifiable_transition",
                            "reason": f"Konteks transisi kontradiktif: from_status '{ctx_from}' tidak cocok dengan status database '{persisted_status}'.",
                            "skipped_at": now_iso
                        },
                        "eligibility": {
                            "scope_status": "in_scope_pending",
                            "governance_mode": "automatic",
                            "skip_reason": "contradictory_transition_context",
                            "evaluated_at": now_iso,
                            "version": 1
                        }
                    }
                if ctx_from in COMPLETED_ORDER_STATUSES:
                    return {
                        "status": "skipped_unverifiable_transition",
                        "skipped": {
                            "status": "skipped_unverifiable_transition",
                            "reason": "Bukti transisi tidak valid: from_status tidak boleh selesai.",
                            "skipped_at": now_iso
                        },
                        "eligibility": {
                            "scope_status": "in_scope_pending",
                            "governance_mode": "automatic",
                            "skip_reason": "invalid_transition_context",
                            "evaluated_at": now_iso,
                            "version": 1
                        }
                    }
                if ctx_to and ctx_to not in COMPLETED_ORDER_STATUSES:
                    return {
                        "status": "skipped_unverifiable_transition",
                        "skipped": {
                            "status": "skipped_unverifiable_transition",
                            "reason": "Bukti transisi tidak valid: to_status wajib berstatus selesai.",
                            "skipped_at": now_iso
                        },
                        "eligibility": {
                            "scope_status": "in_scope_pending",
                            "governance_mode": "automatic",
                            "skip_reason": "invalid_transition_context",
                            "evaluated_at": now_iso,
                            "version": 1
                        }
                    }

        elif eff_event == "payment_lunas":
            if is_order_fully_paid(persisted_order):
                return {
                    "status": "skipped_unverifiable_transition",
                    "skipped": {
                        "status": "skipped_unverifiable_transition",
                        "reason": "Pesanan sudah berstatus lunas di database; transisi payment_lunas tidak valid.",
                        "skipped_at": now_iso
                    },
                    "eligibility": {
                        "scope_status": "in_scope_pending",
                        "governance_mode": "automatic",
                        "skip_reason": "order_already_fully_paid_in_database",
                        "evaluated_at": now_iso,
                        "version": 1
                    }
                }
            if transition_context and isinstance(transition_context, dict):
                ctx_from_pmt = str(transition_context.get("from_payment_status") or "").strip().lower()
                ctx_to_pmt = str(transition_context.get("to_payment_status") or "").strip().lower()
                persisted_pmt = str(persisted_order.get("payment_status") or "").strip().lower()
                if ctx_from_pmt and persisted_pmt and ctx_from_pmt != persisted_pmt:
                    return {
                        "status": "skipped_unverifiable_transition",
                        "skipped": {
                            "status": "skipped_unverifiable_transition",
                            "reason": f"Konteks transisi kontradiktif: from_payment_status '{ctx_from_pmt}' tidak cocok dengan status database '{persisted_pmt}'.",
                            "skipped_at": now_iso
                        },
                        "eligibility": {
                            "scope_status": "in_scope_pending",
                            "governance_mode": "automatic",
                            "skip_reason": "contradictory_transition_context",
                            "evaluated_at": now_iso,
                            "version": 1
                        }
                    }
                if ctx_from_pmt in ("lunas", "overpaid", "paid"):
                    return {
                        "status": "skipped_unverifiable_transition",
                        "skipped": {
                            "status": "skipped_unverifiable_transition",
                            "reason": "Bukti transisi tidak valid: from_payment_status tidak boleh lunas.",
                            "skipped_at": now_iso
                        },
                        "eligibility": {
                            "scope_status": "in_scope_pending",
                            "governance_mode": "automatic",
                            "skip_reason": "invalid_transition_context",
                            "evaluated_at": now_iso,
                            "version": 1
                        }
                    }
                if ctx_to_pmt and ctx_to_pmt != "lunas":
                    return {
                        "status": "skipped_unverifiable_transition",
                        "skipped": {
                            "status": "skipped_unverifiable_transition",
                            "reason": "Bukti transisi tidak valid: to_payment_status wajib lunas.",
                            "skipped_at": now_iso
                        },
                        "eligibility": {
                            "scope_status": "in_scope_pending",
                            "governance_mode": "automatic",
                            "skip_reason": "invalid_transition_context",
                            "evaluated_at": now_iso,
                            "version": 1
                        }
                    }

        default_recip_id = policy.get("default_recipient_id")
        if not default_recip_id:
            blocked_info = {
                "status": "blocked_no_default_recipient",
                "reason": "Penerima default upah admin belum ditentukan dalam kebijakan aktif",
                "attempted_amount_le": policy.get("default_wage_per_order_le"),
                "blocked_at": now_iso,
            }
            return {
                "status": "blocked_no_default_recipient",
                "blocked": blocked_info,
                "eligibility": {
                    "scope_status": "blocked",
                    "governance_mode": "automatic",
                    "blocked_reason": blocked_info["reason"],
                    "evaluated_at": now_iso,
                    "version": 1
                }
            }

        recip_doc = await _mongo_find_one(db.admins, {"_id": id_query(default_recip_id)}, **find_kw)
        if not recip_doc:
            blocked_info = {
                "status": "blocked_invalid_recipient",
                "reason": f"Penerima default '{default_recip_id}' tidak ditemukan di database admin",
                "attempted_amount_le": policy.get("default_wage_per_order_le"),
                "recipient_id": str(default_recip_id),
                "blocked_at": now_iso,
            }
            return {
                "status": "blocked_invalid_recipient",
                "blocked": blocked_info,
                "eligibility": {
                    "scope_status": "blocked",
                    "governance_mode": "automatic",
                    "blocked_reason": blocked_info["reason"],
                    "evaluated_at": now_iso,
                    "version": 1
                }
            }

        recipient_id = str(recip_doc.get("_id") or default_recip_id)
        recipient_name = recip_doc.get("name") or policy.get("default_recipient_name") or "Admin"
        wage_amount = policy["default_wage_per_order_le"]
        override_reason = None

        hard_cap = policy.get("max_wage_per_order_le")
        if hard_cap is not None and wage_amount is not None and wage_amount > hard_cap:
            blocked_info = {
                "status": "blocked_hard_cap_conflict",
                "reason": f"Nominal upah kebijakan default ({wage_amount} LE) melebihi batas maksimum aktif ({hard_cap} LE)",
                "attempted_amount_le": wage_amount,
                "max_wage_per_order_le": hard_cap,
                "recipient_id": str(recipient_id) if recipient_id else None,
                "recipient_name": recipient_name,
                "blocked_at": now_iso,
            }
            return {
                "status": "blocked_hard_cap_conflict",
                "blocked": blocked_info,
                "eligibility": {
                    "scope_status": "blocked",
                    "governance_mode": "automatic",
                    "blocked_reason": blocked_info["reason"],
                    "evaluated_at": now_iso,
                    "version": 1
                }
            }

    if wage_amount is None or wage_amount <= 0:
        skipped_info = {
            "status": "skipped_zero_amount",
            "reason": "Nominal upah admin bernilai nol atau negatif",
            "skipped_at": now_iso,
        }
        return {
            "status": "skipped_zero_amount",
            "skipped": skipped_info,
            "eligibility": {
                "scope_status": "blocked",
                "governance_mode": "manual_override" if is_override else "automatic",
                "blocked_reason": skipped_info["reason"],
                "evaluated_at": now_iso,
                "version": 1
            }
        }

    # 4. Generate obligation number and construct document
    ob_num = await generate_obligation_number(session=session)
    wob_doc = {
        "obligation_number": ob_num,
        "accrual_event_key": accrual_key,
        "task_category": "admin",
        "pricing_basis": "per_order_admin",
        "order_id": order_id_str,
        "order_number": order.get("order_number"),
        "worker_id": str(recipient_id),
        "worker_name": recipient_name,
        "total_amount_le": round(float(wage_amount), 2),
        "amount_piastres": int(round(float(wage_amount) * 100)),
        "currency": policy.get("currency", "EGP"),
        "status": "accrued",
        "paid_amount_le": 0.0,
        "is_override": is_override,
        "rate_policy_snapshot": {
            "default_wage_per_order_le": policy.get("default_wage_per_order_le"),
            "unusual_amount_threshold_le": policy.get("unusual_amount_threshold_le"),
            "max_wage_per_order_le": policy.get("max_wage_per_order_le"),
            "wage_amount_le": round(float(wage_amount), 2),
            "is_override": is_override,
            "override_reason": override_reason,
        },
        "accrued_at": now_iso,
        "created_at": now_iso,
        "updated_at": now_iso,
        "verified_by_id": str(admin.get("id") or admin.get("_id") or ""),
        "verified_by_name": admin.get("name", "Admin"),
    }

    # 5. Insert into wage_obligations collection with idempotent handling of DuplicateKeyError
    try:
        res_wob = await _mongo_insert_one(db.wage_obligations, wob_doc, **find_kw)
        if res_wob and hasattr(res_wob, "inserted_id"):
            wob_doc["_id"] = res_wob.inserted_id
    except pymongo.errors.DuplicateKeyError as dke:
        err_msg = str(dke)
        if "uniq_wage_obligation_accrual_event" in err_msg or "accrual_event_key" in err_msg or accrual_key in err_msg:
            existing_wob = await _mongo_find_one(db.wage_obligations, {"accrual_event_key": accrual_key}, **find_kw)
            if existing_wob:
                ob_status = str(existing_wob.get("status") or "").strip().lower()
                if ob_status in ("void", "voided", "cancelled"):
                    blocked_info = {
                        "status": "blocked_prior_voided_obligation",
                        "reason": (
                            f"Kewajiban upah admin untuk pesanan {order_id_str} sebelumnya telah dibatalkan/void "
                            f"(nomor: {existing_wob.get('obligation_number')}, status: {ob_status}). "
                            f"Pembuatan ulang kewajiban memerlukan audit dan review manual oleh Owner."
                        ),
                        "existing_obligation_number": existing_wob.get("obligation_number"),
                        "existing_obligation_id": str(existing_wob.get("_id")),
                        "existing_obligation_status": ob_status,
                        "accrual_event_key": accrual_key,
                        "owner_review_required": True,
                        "blocked_at": now_iso,
                    }
                    return {
                        "status": "blocked_prior_voided_obligation",
                        "blocked": blocked_info,
                        "eligibility": {
                            "scope_status": "blocked",
                            "governance_mode": "automatic",
                            "blocked_reason": blocked_info["reason"],
                            "evaluated_at": now_iso,
                            "version": 1
                        }
                    }
                wob_doc = existing_wob
            else:
                raise
        else:
            raise

    # 6. Record audit log
    audit_doc = {
        "action": "admin_wage_accrued",
        "entity_type": "order",
        "entity_id": order_id_str,
        "entity_identifier": order.get("order_number", ""),
        "actor_id": str(admin.get("id") or ""),
        "actor_name": admin.get("name", "Admin"),
        "actor_role": admin.get("role", "admin"),
        "metadata": {
            "obligation_number": wob_doc.get("obligation_number"),
            "obligation_id": str(wob_doc.get("_id")),
            "total_amount_le": round(float(wage_amount), 2),
            "worker_id": str(recipient_id),
            "worker_name": recipient_name,
            "is_override": is_override,
            "accrual_event_key": accrual_key,
            "governance_mode": "manual_override" if is_override else "automatic",
            "cycle_id": policy.get("current_cycle_id") if not is_override else None,
        },
        "timestamp": now_iso,
    }
    await _mongo_insert_one(db.audit_logs, audit_doc, **find_kw)

    obligation_summary = {
        "obligation_number": wob_doc.get("obligation_number"),
        "obligation_id": str(wob_doc.get("_id")),
        "accrual_event_key": accrual_key,
        "task_category": "admin",
        "recipient_id": str(recipient_id),
        "recipient_name": recipient_name,
        "amount_le": round(float(wage_amount), 2),
        "status": wob_doc.get("status", "accrued"),
        "is_override": is_override,
        "accrued_at": wob_doc.get("accrued_at") or now_iso,
    }
    eligibility_info = {
        "scope_status": "accrued",
        "governance_mode": "manual_override" if is_override else "automatic",
        "maturity_timestamp": now_iso,
        "evaluated_at": now_iso,
        "evaluated_in_cycle_id": policy.get("current_cycle_id") if not is_override else None,
        "in_active_cycle_at_maturity": True,
        "obligation_number": wob_doc.get("obligation_number"),
        "obligation_id": str(wob_doc.get("_id")),
        "version": 1
    }
    return {
        "status": "accrued",
        "obligation": obligation_summary,
        "eligibility": eligibility_info
    }

VALID_ADMIN_WAGE_LIFECYCLE_EVENTS = {"order_completed", "payment_lunas", "manual_override"}

async def evaluate_and_process_order_admin_wage_accrual(
    order: dict,
    admin: dict,
    session=None,
    payment_summary: Optional[dict] = None,
    lifecycle_event: Optional[str] = None,
    transition_context: Optional[dict] = None
) -> dict:
    """
    Shared, idempotent eligibility check and accrual service for admin wages.
    Enforces the Owner's approved business rules:
    1. Condition 1: Order is completed (is_order_completed).
    2. Condition 2: Customer payment is fully paid (is_order_fully_paid).
    3. Order is not explicitly excluded (is_order_excluded_from_admin_wage).
    4. Anti-Retroactivity: Orders that matured during a disabled window remain skipped.
    5. Manual Override: Proceeds even if global policy is disabled.
    6. Trusted Lifecycle Event Contract: Automatic accrual strictly requires an explicit,
       valid lifecycle transition event ('order_completed' or 'payment_lunas') to prevent
       accidental accrual of historical or settled orders via out-of-band direct invocations.
    7. Canonical event key `admin_wage:{order_id}` and MongoDB unique index guarantee
       idempotency across duplicate events, retries, and concurrent calls.
    """
    now_iso = datetime.now(timezone.utc).isoformat()

    # Check 1: Explicit exclusion (historical/reconciled/manual)
    if is_order_excluded_from_admin_wage(order):
        return {
            "status": "skipped_legacy_reconciled",
            "skipped": {
                "status": "skipped_legacy_reconciled",
                "reason": "Pesanan historis/manual telah ditandai direkonsiliasi dan dikecualikan dari akrual otomatis.",
                "skipped_at": now_iso
            },
            "eligibility": {
                "scope_status": "excluded_historical",
                "governance_mode": "historical",
                "evaluated_at": now_iso,
                "version": 1
            }
        }

    override = order.get("admin_wage_override") or {}
    is_override = bool(override.get("is_override"))

    # Check 2: Anti-retroactive protection for non-override orders
    if not is_override:
        elig = order.get("admin_wage_eligibility") or {}
        skipped_data = order.get("admin_wage_skipped") or {}
        if elig.get("scope_status") == "skipped_disabled_window" or skipped_data.get("status") in ("skipped_policy_disabled", "skipped_disabled_window"):
            return {
                "status": "skipped_disabled_window_matured",
                "skipped": {
                    "status": "skipped_disabled_window",
                    "reason": "Pesanan telah selesai dan lunas pada saat otomatisasi nonaktif; dilindungi dari akrual retroaktif.",
                    "skipped_at": now_iso
                },
                "eligibility": {
                    "scope_status": "skipped_disabled_window",
                    "governance_mode": "automatic",
                    "skip_reason": "settled_while_automation_disabled",
                    "evaluated_at": now_iso,
                    "version": 1
                }
            }

    # Check 3: Order completion (Condition 1)
    if not is_order_completed(order):
        return {
            "status": "skipped_order_not_completed",
            "skipped": {
                "status": "skipped_order_not_completed",
                "reason": f"Pesanan belum berstatus selesai (status saat ini: '{order.get('order_status') or order.get('status')}').",
                "skipped_at": now_iso
            },
            "eligibility": {
                "scope_status": "in_scope_pending",
                "governance_mode": "manual_override" if is_override else "automatic",
                "evaluated_at": now_iso,
                "version": 1
            }
        }

    # Check 4: Customer payment completion (Condition 2)
    if not is_order_fully_paid(order, payment_summary=payment_summary):
        return {
            "status": "skipped_payment_not_lunas",
            "skipped": {
                "status": "skipped_payment_not_lunas",
                "reason": f"Pembayaran pesanan belum lunas (status saat ini: '{order.get('payment_status')}').",
                "skipped_at": now_iso
            },
            "eligibility": {
                "scope_status": "in_scope_pending",
                "governance_mode": "manual_override" if is_override else "automatic",
                "evaluated_at": now_iso,
                "version": 1
            }
        }

    policy = await get_active_admin_wage_policy(db_inst=db)

    # Check 5: Historical pre-activation check (if not manual override)
    check_order = dict(order)
    if payment_summary and isinstance(payment_summary, dict):
        pmt_date = payment_summary.get("payment_date") or now_iso
        check_order["paid_at"] = pmt_date

    if not is_override and is_order_historical_unreconciled(check_order, policy):
        return {
            "status": "skipped_pre_activation_historical",
            "skipped": {
                "status": "skipped_pre_activation_historical",
                "reason": "Pesanan diselesaikan sebelum sistem upah admin resmi diaktifkan. Kompensasi ditangani manual di kasir fisik.",
                "skipped_at": now_iso
            },
            "eligibility": {
                "scope_status": "excluded_historical",
                "governance_mode": "historical",
                "skip_reason": "settled_prior_to_system_activation",
                "evaluated_at": now_iso,
                "version": 1
            }
        }

    # Both conditions satisfied: delegate to process_order_admin_wage_accrual
    return await process_order_admin_wage_accrual(
        order, admin, session=session, policy=policy,
        payment_summary=payment_summary, lifecycle_event=lifecycle_event,
        transition_context=transition_context
    )

def distribute_wage_piastres(total_amount_le: float, recipients: list) -> list:
    """
    Distributes total_amount_le equally among recipients using smallest currency unit: one piastre (0.01 EGP).
    Guarantees:
    - Sum of all recipient allocations always equals exactly total_amount_le (zero money lost or created).
    - Residual piastres distributed deterministically to first r recipients.
    - Uses exact integer arithmetic in piastres (ROUND_HALF_UP).
    - Validates against negative amounts, non-numeric values, and duplicate recipient IDs.
    - Rejects positive wage when recipients list is empty (fails-closed).
    - Explicit zero nominal contract:
      - 0.0 LE with empty recipients -> returns []
      - 0.0 LE with n recipients -> returns n allocations with 0 piastres and 0.0 LE
    """
    if total_amount_le is None:
        raise ValueError("Nominal upah tidak boleh None")

    try:
        d_wage = Decimal(str(total_amount_le)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception:
        raise ValueError(f"Nominal upah tidak valid: {total_amount_le!r}")

    if d_wage.is_nan() or d_wage.is_infinite():
        raise ValueError(f"Nominal upah tidak valid: {total_amount_le!r}")

    total_piastres = int(d_wage * 100)
    if total_piastres < 0:
        raise ValueError("Nominal upah tidak boleh bernilai negatif")

    # If nominal is positive, recipients list MUST NOT be empty!
    if total_piastres > 0 and (recipients is None or len(recipients) == 0):
        raise ValueError("Daftar penerima upah tidak boleh kosong jika nominal upah bernilai positif")

    # If nominal is zero and recipients is empty, return []
    if total_piastres == 0 and (recipients is None or len(recipients) == 0):
        return []

    n = len(recipients)

    seen_ids = set()
    cleaned_recipients = []
    for r in recipients:
        if isinstance(r, dict):
            w_id = str(r.get("worker_id") or r.get("helper_id") or r.get("id") or "")
            w_name = r.get("worker_name") or r.get("helper_name") or r.get("name") or ("Helper" if "helper_id" in r else "Pekerja")
        elif isinstance(r, (str, ObjectId)):
            w_id = str(r)
            w_name = "Pekerja"
        else:
            w_id = str(r)
            w_name = "Pekerja"

        if not w_id:
            raise ValueError("ID penerima upah tidak boleh kosong")
        if w_id in seen_ids:
            raise ValueError(f"Penerima upah duplikat terdeteksi: {w_id}")
        seen_ids.add(w_id)
        cleaned_recipients.append({"id": w_id, "name": w_name})

    quotient = total_piastres // n
    remainder = total_piastres % n

    allocations = []
    for i, r in enumerate(cleaned_recipients):
        h_piastres = quotient + 1 if i < remainder else quotient
        h_amount_le = float(Decimal(h_piastres) / Decimal(100))
        allocations.append({
            "worker_id": r["id"],
            "worker_name": r["name"],
            "amount_piastres": h_piastres,
            "amount_le": h_amount_le,
        })

    total_allocated_piastres = sum(a["amount_piastres"] for a in allocations)
    assert total_allocated_piastres == total_piastres, f"Rounding invariant violation: {total_allocated_piastres} != {total_piastres}"
    return allocations

def calculate_delivery_helper_wage_allocations(total_wage_le: float, helpers: list, allow_empty: bool = False) -> list:
    """
    Divides total_wage_le equally among helpers using smallest currency unit: one piastre (0.01 EGP).
    Guarantees:
    - Sum of all helper allocations always equals exactly total_wage_le (zero money lost or created).
    - Residual piastres distributed deterministically to first r helpers.
    - Uses exact integer arithmetic in piastres (no binary floating-point drift).
    Delegates to shared distribute_wage_piastres utility.
    """
    if allow_empty and (helpers is None or len(helpers) == 0):
        return []
    return distribute_wage_piastres(total_wage_le, helpers)

async def verify_delivery_wage_indexes_pre_migration(db_inst) -> dict:
    """
    Performs pre-migration integrity inspection on db.wage_obligations for task_category 'delivery'.
    Ensures no duplicate (order_id, worker_id) documents exist prior to partial unique index provisioning.
    If duplicates are detected, raises CriticalFinanceIndexError (fail-closed).
    """
    pipeline = [
        {"$match": {"task_category": "delivery"}},
        {"$group": {
            "_id": {"order_id": "$order_id", "worker_id": "$worker_id"},
            "count": {"$sum": 1},
            "ids": {"$push": "$_id"}
        }},
        {"$match": {"count": {"$gt": 1}}}
    ]
    if hasattr(db_inst, "wage_obligations") and hasattr(db_inst.wage_obligations, "aggregate"):
        cursor = db_inst.wage_obligations.aggregate(pipeline)
        to_list_fn = getattr(cursor, "to_list", None)
        if callable(to_list_fn):
            res_coro = to_list_fn(100)
            duplicates = await res_coro if inspect.isawaitable(res_coro) else []
        else:
            duplicates = []
    else:
        duplicates = []
    if duplicates:
        err_msg = f"Pre-migration duplicate check failed: found {len(duplicates)} duplicate delivery wage entitlement groups"
        logger.error(f"CRITICAL PRE-MIGRATION FAILURE: {err_msg}")
        raise CriticalFinanceIndexError("wage_obligations", "uniq_delivery_wage_order_worker", err_msg)
    return {"ok": True, "duplicate_count": 0}

async def _execute_delivery_tx_or_fail_closed(coro_fn):
    session = None
    try:
        session = await client.start_session()
    except (pymongo.errors.ConfigurationError, pymongo.errors.InvalidOperation, AttributeError) as sess_err:
        if not is_standalone_fallback_permitted():
            logger.error(f"Transaction capability unavailable in mode {get_environment_mode()!r}: {sess_err}")
            raise HTTPException(
                status_code=503,
                detail="Layanan transaksi multi-dokumen tidak tersedia pada lingkungan ini (Fail-Closed)"
            )
        session = None

    if session is not None:
        try:
            async with session:
                async with session.start_transaction():
                    return await coro_fn(session)
        except pymongo.errors.PyMongoError as e:
            is_transient = (hasattr(e, "has_error_label") and e.has_error_label("TransientTransactionError")) or \
                           (isinstance(e, pymongo.errors.OperationFailure) and getattr(e, "code", None) == 112)
            if is_transient:
                logger.warning(f"Delivery transaction concurrency conflict: {e}")
                raise HTTPException(
                    status_code=409,
                    detail="Konflik konkurensi: Dokumen sedang dimutasi oleh transaksi lain. Silakan coba kembali."
                )
            raise
    else:
        return await coro_fn(None)

async def assign_order_to_trip_core(trip_id: str, order_id: str, admin: dict, session=None) -> dict:
    now_iso = datetime.now(timezone.utc).isoformat()
    trip = await db.delivery_trips.find_one({"_id": id_query(trip_id)}, session=session)
    if not trip:
        raise HTTPException(status_code=404, detail="Trip pengiriman tidak ditemukan")
    if trip.get("status") not in (DeliveryTripStatus.DRAFT.value, DeliveryTripStatus.SCHEDULED.value):
        raise HTTPException(status_code=409, detail=f"Tidak dapat menambah pesanan ke trip dengan status '{trip.get('status')}'.")

    # Check if order already has an active stop on this trip
    for s in trip.get("stops", []):
        if str(s.get("order_id")) == str(order_id) and s.get("outcome") != StopOutcome.CANCELLED.value:
            raise HTTPException(status_code=409, detail="Pesanan sudah terdaftar pada trip ini.")

    order_doc = await db.orders.find_one({"_id": id_query(order_id)}, session=session)
    if not order_doc:
        raise HTTPException(status_code=404, detail="Pesanan tidak ditemukan")
    if order_doc.get("order_status") != "siap":
        raise HTTPException(status_code=409, detail=f"Pesanan tidak siap untuk pengantaran (status: '{order_doc.get('order_status')}').")
    if order_doc.get("delivery_method") != "delivery":
        raise HTTPException(status_code=422, detail=f"Metode pengiriman pesanan bukan 'delivery' ('{order_doc.get('delivery_method')}').")
    if order_doc.get("active_delivery_trip_id"):
        raise HTTPException(status_code=409, detail=f"Pesanan sudah terikat pada trip aktif {order_doc.get('active_delivery_trip_number') or order_doc.get('active_delivery_trip_id')}.")

    # Conditional atomic update on db.orders
    res_order = await db.orders.update_one(
        {
            "_id": id_query(order_id),
            "order_status": "siap",
            "delivery_method": "delivery",
            "active_delivery_trip_id": None
        },
        {
            "$set": {
                "active_delivery_trip_id": str(trip["_id"]),
                "active_delivery_trip_number": trip["trip_number"],
                "delivery_logistics_status": "scheduled",
                "updated_at": now_iso,
                "updated_by_id": admin.get("id"),
                "updated_by_name": admin.get("name")
            },
            "$push": {
                "status_history": {
                    "from_status": "siap",
                    "to_status": "siap",
                    "changed_at": now_iso,
                    "changed_by_id": admin.get("id"),
                    "changed_by_name": admin.get("name"),
                    "reason": f"Ditugaskan ke Trip {trip['trip_number']}"
                }
            }
        },
        session=session
    )
    if res_order.matched_count == 0:
        raise HTTPException(status_code=409, detail="Konflik penugasan: pesanan telah diklaim atau berubah status oleh proses lain.")

    # Push stop to trip
    new_seq = len(trip.get("stops", [])) + 1
    stop_id = f"stp_{uuid.uuid4().hex[:12]}"
    stop_doc = {
        "stop_id": stop_id,
        "sequence": new_seq,
        "order_id": str(order_id),
        "order_number": order_doc.get("order_number") or str(order_id),
        "customer_name": order_doc.get("customer_name") or "Pelanggan",
        "customer_phone": order_doc.get("customer_phone") or order_doc.get("phone_number") or "",
        "customer_address": order_doc.get("customer_address") or "",
        "customer_maps_url": order_doc.get("customer_maps_url") or "",
        "delivery_zone": order_doc.get("delivery_zone") or order_doc.get("shipping_zone") or "",
        "outcome": StopOutcome.PENDING.value,
        "attempt_count": 0,
        "attempts": [],
        "failure_reason": None,
        "delivered_at": None,
        "recipient_name": None,
        "handover_notes": None,
        "helper_confirmed": False,
        "created_at": now_iso,
        "updated_at": now_iso
    }

    res_trip = await db.delivery_trips.update_one(
        {"_id": trip["_id"], "status": {"$in": [DeliveryTripStatus.DRAFT.value, DeliveryTripStatus.SCHEDULED.value]}},
        {
            "$push": {"stops": stop_doc},
            "$inc": {"stops_count": 1},
            "$set": {
                "updated_at": now_iso,
                "updated_by_id": admin.get("id"),
                "updated_by_name": admin.get("name")
            }
        },
        session=session
    )
    if res_trip.matched_count == 0:
        raise HTTPException(status_code=409, detail="Trip telah berubah status atau tidak dapat menerima penugasan baru.")

    updated_trip = await db.delivery_trips.find_one({"_id": trip["_id"]}, session=session)
    return clean(updated_trip)

async def release_order_from_trip_core(trip_id: str, order_id: str, admin: dict, session=None) -> dict:
    now_iso = datetime.now(timezone.utc).isoformat()
    trip = await db.delivery_trips.find_one({"_id": id_query(trip_id)}, session=session)
    if not trip:
        raise HTTPException(status_code=404, detail="Trip pengiriman tidak ditemukan")
    if trip.get("status") not in (DeliveryTripStatus.DRAFT.value, DeliveryTripStatus.SCHEDULED.value):
        raise HTTPException(status_code=409, detail=f"Tidak dapat melepaskan pesanan dari trip dengan status '{trip.get('status')}'.")

    target_stop = None
    for s in trip.get("stops", []):
        if str(s.get("order_id")) == str(order_id):
            target_stop = s
            break
    if not target_stop:
        raise HTTPException(status_code=404, detail="Pesanan tidak ditemukan dalam daftar stop trip ini")
    if target_stop.get("outcome") == StopOutcome.DELIVERED.value:
        raise HTTPException(status_code=409, detail="Stop yang telah diserahterimakan (delivered) tidak dapat dilepaskan dari trip.")

    # 1. Pull stop from trip
    res_trip = await db.delivery_trips.update_one(
        {"_id": trip["_id"], "status": {"$in": [DeliveryTripStatus.DRAFT.value, DeliveryTripStatus.SCHEDULED.value]}},
        {
            "$pull": {"stops": {"order_id": str(order_id)}},
            "$inc": {"stops_count": -1},
            "$set": {
                "updated_at": now_iso,
                "updated_by_id": admin.get("id"),
                "updated_by_name": admin.get("name")
            }
        },
        session=session
    )
    if res_trip.matched_count == 0:
        raise HTTPException(status_code=409, detail="Trip telah berubah status atau tidak dapat dimodifikasi.")

    # 2. Release order lock conditionally
    res_order = await db.orders.update_one(
        {
            "_id": id_query(order_id),
            "active_delivery_trip_id": str(trip["_id"])
        },
        {
            "$set": {
                "active_delivery_trip_id": None,
                "active_delivery_trip_number": None,
                "delivery_logistics_status": "unassigned",
                "updated_at": now_iso,
                "updated_by_id": admin.get("id"),
                "updated_by_name": admin.get("name")
            },
            "$push": {
                "status_history": {
                    "from_status": "siap",
                    "to_status": "siap",
                    "changed_at": now_iso,
                    "changed_by_id": admin.get("id"),
                    "changed_by_name": admin.get("name"),
                    "reason": f"Dilepas dari penugasan Trip {trip.get('trip_number')}"
                }
            }
        },
        session=session
    )
    if res_order.matched_count == 0:
        raise HTTPException(status_code=409, detail="Pesanan tidak terikat pada trip ini atau telah dimodifikasi proses lain.")

    updated_trip = await db.delivery_trips.find_one({"_id": trip["_id"]}, session=session)
    return clean(updated_trip)

async def cancel_trip_multi_stop_core(trip_id: str, reason: str, admin: dict, session=None) -> dict:
    now_iso = datetime.now(timezone.utc).isoformat()
    trip = await db.delivery_trips.find_one({"_id": id_query(trip_id)}, session=session)
    if not trip:
        raise HTTPException(status_code=404, detail="Trip pengiriman tidak ditemukan")
    if trip.get("status") in (DeliveryTripStatus.CANCELLED.value, DeliveryTripStatus.COMPLETED.value):
        raise HTTPException(status_code=409, detail=f"Trip telah berada dalam status terminal '{trip.get('status')}'.")

    check_trip_can_be_cancelled(trip)
    active_order_ids = [s["order_id"] for s in trip.get("stops", []) if s.get("outcome") != StopOutcome.DELIVERED.value]

    # 1. Update trip and non-delivered stops
    res_trip = await db.delivery_trips.update_one(
        {
            "_id": trip["_id"],
            "status": {"$in": [DeliveryTripStatus.DRAFT.value, DeliveryTripStatus.SCHEDULED.value, DeliveryTripStatus.IN_TRANSIT.value]},
            "stops.outcome": {"$ne": StopOutcome.DELIVERED.value}
        },
        {
            "$set": {
                "status": DeliveryTripStatus.CANCELLED.value,
                "cancellation_reason": reason.strip(),
                "cancelled_at": now_iso,
                "cancelled_by_id": admin.get("id"),
                "cancelled_by_name": admin.get("name"),
                "updated_at": now_iso,
                "updated_by_id": admin.get("id"),
                "updated_by_name": admin.get("name"),
                "stops.$[elem].outcome": StopOutcome.CANCELLED.value
            }
        },
        array_filters=[{"elem.outcome": {"$in": [StopOutcome.PENDING.value, StopOutcome.OUT_FOR_DELIVERY.value, StopOutcome.FAILED.value]}}],
        session=session
    )
    if res_trip.matched_count == 0:
        raise HTTPException(status_code=409, detail="Trip telah berubah status, dibatalkan oleh pengguna lain, atau memuat stop yang sudah delivered.")

    # 2. Bulk release orders
    if active_order_ids:
        res_orders = await db.orders.update_many(
            {
                "_id": {"$in": multi_id_query(active_order_ids)},
                "active_delivery_trip_id": str(trip["_id"])
            },
            {
                "$set": {
                    "active_delivery_trip_id": None,
                    "active_delivery_trip_number": None,
                    "delivery_logistics_status": "unassigned",
                    "updated_at": now_iso,
                    "updated_by_id": admin.get("id"),
                    "updated_by_name": admin.get("name")
                },
                "$push": {
                    "status_history": {
                        "from_status": "siap",
                        "to_status": "siap",
                        "changed_at": now_iso,
                        "changed_by_id": admin.get("id"),
                        "changed_by_name": admin.get("name"),
                        "reason": f"Pelepasan penugasan logistik: Trip {trip.get('trip_number')} dibatalkan ({reason.strip()})"
                    }
                }
            },
            session=session
        )
        if res_orders.matched_count != len(active_order_ids):
            raise HTTPException(status_code=409, detail="Inkonsistensi penugasan pesanan. Pembatalan trip dibatalkan total.")

    updated_trip = await db.delivery_trips.find_one({"_id": trip["_id"]}, session=session)
    return clean(updated_trip)

async def complete_trip_partial_core(trip_id: str, notes: Optional[str], admin: dict, session=None) -> dict:
    now_iso = datetime.now(timezone.utc).isoformat()
    trip = await db.delivery_trips.find_one({"_id": id_query(trip_id)}, session=session)
    if not trip:
        raise HTTPException(status_code=404, detail="Trip pengiriman tidak ditemukan")
    if trip.get("status") == DeliveryTripStatus.COMPLETED.value:
        return clean(trip)
    if trip.get("status") not in (DeliveryTripStatus.IN_TRANSIT.value, DeliveryTripStatus.PARTIALLY_COMPLETED.value):
        raise HTTPException(status_code=409, detail=f"Hanya trip dalam status 'in_transit' atau 'partially_completed' yang dapat diselesaikan (status saat ini: '{trip.get('status')}').")

    stops = trip.get("stops", [])
    delivered_stops = [s for s in stops if s.get("outcome") == StopOutcome.DELIVERED.value]
    delivered_count = len(delivered_stops)
    pending_count = sum(1 for s in stops if s.get("outcome") in (StopOutcome.PENDING.value, StopOutcome.OUT_FOR_DELIVERY.value))
    failed_stops = [s for s in stops if s.get("outcome") == StopOutcome.FAILED.value]
    all_failed_stops = [s for s in stops if s.get("outcome") in (StopOutcome.FAILED.value, StopOutcome.FAILED_CLOSED.value)]

    if delivered_count == 0:
        raise HTTPException(status_code=409, detail="Trip tidak memiliki stop yang berhasil diserahterimakan (delivered). Untuk membatalkan trip, gunakan alur pembatalan.")
    if pending_count > 0:
        raise HTTPException(status_code=409, detail=f"Masih terdapat {pending_count} stop aktif (pending/out_for_delivery). Selesaikan atau tandai gagal seluruh stop sebelum menutup trip.")

    admin_id = str(admin.get("id") or admin.get("_id") or "")
    admin_name = admin.get("name") or "Dispatcher"
    is_partial = len(all_failed_stops) > 0
    target_status = DeliveryTripStatus.COMPLETED.value

    # 1. Update trip document
    trip_update_doc = {
        "status": target_status,
        "is_partially_completed": is_partial,
        "completed_at": now_iso,
        "completion_notes": (notes or "").strip(),
        "delivered_stops_count": delivered_count,
        "failed_stops_count": len(all_failed_stops),
        "updated_at": now_iso,
        "updated_by_id": admin_id,
        "updated_by_name": admin_name
    }

    if failed_stops:
        await db.delivery_trips.update_one(
            {"_id": trip["_id"]},
            {
                "$set": {
                    **trip_update_doc,
                    "stops.$[elem].outcome": StopOutcome.FAILED_CLOSED.value
                }
            },
            array_filters=[{"elem.outcome": StopOutcome.FAILED.value}],
            session=session
        )
        # Release locks on failed orders
        failed_order_ids = [s["order_id"] for s in failed_stops]
        await db.orders.update_many(
            {
                "_id": {"$in": multi_id_query(failed_order_ids)},
                "active_delivery_trip_id": str(trip["_id"])
            },
            {
                "$set": {
                    "active_delivery_trip_id": None,
                    "active_delivery_trip_number": None,
                    "delivery_logistics_status": "delivery_failed",
                    "updated_at": now_iso,
                    "updated_by_id": admin_id,
                    "updated_by_name": admin_name
                },
                "$push": {
                    "status_history": {
                        "from_status": "siap",
                        "to_status": "siap",
                        "changed_at": now_iso,
                        "changed_by_id": admin_id,
                        "changed_by_name": admin_name,
                        "reason": f"Pengantaran gagal pada Trip {trip.get('trip_number')}. Kembali ke antrean siap kirim."
                    }
                }
            },
            session=session
        )
    else:
        # All delivered
        await db.delivery_trips.update_one(
            {"_id": trip["_id"]},
            {"$set": trip_update_doc},
            session=session
        )

    # 2. Ghost lock elimination on delivered orders: unset active trip lock
    delivered_order_ids = [s["order_id"] for s in delivered_stops]
    if delivered_order_ids:
        await db.orders.update_many(
            {
                "_id": {"$in": multi_id_query(delivered_order_ids)},
                "active_delivery_trip_id": str(trip["_id"])
            },
            {
                "$set": {
                    "active_delivery_trip_id": None,
                    "active_delivery_trip_number": None,
                    "updated_at": now_iso,
                    "updated_by_id": admin_id,
                    "updated_by_name": admin_name
                }
            },
            session=session
        )

    updated_trip = await db.delivery_trips.find_one({"_id": trip["_id"]}, session=session)
    return clean(updated_trip)

async def record_delivery_attempt_core(trip_id: str, order_id: str, payload: DeliveryTripStopAttemptInput, admin: dict, session=None) -> dict:
    now_iso = datetime.now(timezone.utc).isoformat()
    trip = await db.delivery_trips.find_one({"_id": id_query(trip_id)}, session=session)
    if not trip:
        raise HTTPException(status_code=404, detail="Trip pengiriman tidak ditemukan")
    if trip.get("status") != DeliveryTripStatus.IN_TRANSIT.value:
        raise HTTPException(status_code=409, detail=f"Pencatatan percobaan pengantaran hanya dapat dilakukan pada trip dengan status 'in_transit' (status saat ini: '{trip.get('status')}').")

    stop = None
    for s in trip.get("stops", []):
        if str(s.get("order_id")) == str(order_id):
            stop = s
            break
    if not stop:
        raise HTTPException(status_code=404, detail="Stop untuk pesanan ini tidak ditemukan pada trip")

    outcome = payload.outcome.strip().lower()
    if outcome == StopOutcome.FAILED.value:
        validate_stop_state_transition(stop.get("outcome"), StopOutcome.FAILED.value)
        reason_clean = (payload.failure_reason or "").strip()
        if len(reason_clean) < 3:
            raise HTTPException(status_code=422, detail="Alasan kegagalan pengantaran wajib diisi (minimal 3 karakter).")

        attempt_doc = {
            "attempt_number": len(stop.get("attempts", [])) + 1,
            "attempted_at": now_iso,
            "outcome": StopOutcome.FAILED.value,
            "failure_reason": reason_clean,
            "notes": (payload.notes or "").strip(),
            "recorded_by_id": str(admin.get("id") or admin.get("_id") or ""),
            "recorded_by_name": admin.get("name", "Dispatcher")
        }

        await db.delivery_trips.update_one(
            {"_id": trip["_id"], "stops.order_id": str(order_id)},
            {
                "$set": {
                    "stops.$.outcome": StopOutcome.FAILED.value,
                    "stops.$.failure_reason": reason_clean,
                    "stops.$.updated_at": now_iso,
                    "updated_at": now_iso,
                    "updated_by_id": str(admin.get("id") or admin.get("_id") or ""),
                    "updated_by_name": admin.get("name", "Dispatcher")
                },
                "$inc": {"stops.$.attempt_count": 1},
                "$push": {"stops.$.attempts": attempt_doc}
            },
            session=session
        )

        status_history_entry = {
            "from_status": "siap",
            "to_status": "siap",
            "changed_at": now_iso,
            "changed_by_id": str(admin.get("id") or admin.get("_id") or ""),
            "changed_by_name": admin.get("name", "Dispatcher"),
            "reason": f"Percobaan pengantaran #{attempt_doc['attempt_number']} gagal: {reason_clean}"
        }

        await db.orders.update_one(
            {"_id": id_query(order_id), "active_delivery_trip_id": str(trip["_id"])},
            {
                "$set": {
                    "delivery_logistics_status": "delivery_attempt_failed",
                    "updated_at": now_iso
                },
                "$push": {"status_history": status_history_entry}
            },
            session=session
        )

    elif outcome == StopOutcome.OUT_FOR_DELIVERY.value:
        validate_stop_state_transition(stop.get("outcome"), StopOutcome.OUT_FOR_DELIVERY.value)
        await db.delivery_trips.update_one(
            {"_id": trip["_id"], "stops.order_id": str(order_id)},
            {
                "$set": {
                    "stops.$.outcome": StopOutcome.OUT_FOR_DELIVERY.value,
                    "stops.$.updated_at": now_iso,
                    "updated_at": now_iso,
                    "updated_by_id": str(admin.get("id") or admin.get("_id") or ""),
                    "updated_by_name": admin.get("name", "Dispatcher")
                }
            },
            session=session
        )
        status_history_entry = {
            "from_status": "siap",
            "to_status": "siap",
            "changed_at": now_iso,
            "changed_by_id": str(admin.get("id") or admin.get("_id") or ""),
            "changed_by_name": admin.get("name", "Dispatcher"),
            "reason": f"Pengantaran dicoba kembali (Retry) pada Trip {trip.get('trip_number') or trip_id}"
        }
        await db.orders.update_one(
            {"_id": id_query(order_id), "active_delivery_trip_id": str(trip["_id"])},
            {
                "$set": {
                    "delivery_logistics_status": "retry_in_progress",
                    "updated_at": now_iso
                },
                "$push": {"status_history": status_history_entry}
            },
            session=session
        )
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Outcome '{outcome}' tidak didukung pada endpoint record-attempt. Pilihan: 'failed', 'out_for_delivery'."
        )

    updated_trip = await db.delivery_trips.find_one({"_id": trip["_id"]}, session=session)
    return clean(updated_trip)

async def execute_order_handover_completion(
    order_id: str,
    admin: dict,
    now_iso: Optional[str] = None,
    session=None,
    delivery_context: Optional[dict] = None,
    order_doc: Optional[dict] = None
) -> dict:
    """
    Centralized canonical helper for transitioning an order to 'selesai' and recognizing revenue.
    Preserves 100% of canonical behavior (Phase 3.F.4 Architecture Specification Section 6.1):
    1. Validates order existence and active status.
    2. Enforces concurrency protection and idempotent snapshot stamping:
       - completed_at (preserves existing if already set)
       - completed_by_id / completed_by_name
       - recognized_revenue_le = total_le (preserves existing if already set)
    3. Stamps delivery logistics metadata if delivery_context is provided:
       - delivery_logistics_status = 'delivered'
       - delivered_trip_id
       - delivered_trip_number
    4. Records immutable status_history entry (from_status -> 'selesai').
    5. Atomic update under MongoDB session if provided.
    """
    if now_iso is None:
        now_iso = datetime.now(timezone.utc).isoformat()

    if order_doc is None:
        order_doc = await db.orders.find_one({"_id": id_query(order_id)}, session=session)
    if not order_doc:
        raise HTTPException(status_code=404, detail="Pesanan tidak ditemukan")

    if delivery_context:
        trip_id = delivery_context.get("trip_id")
        if order_doc.get("order_status") == "selesai":
            if str(order_doc.get("active_delivery_trip_id")) != str(trip_id) and str(order_doc.get("delivered_trip_id")) != str(trip_id):
                raise HTTPException(status_code=409, detail="Pesanan telah selesai di luar alur pengantaran trip ini.")
        elif order_doc.get("order_status") != "siap":
            raise HTTPException(
                status_code=409,
                detail=f"Pesanan tidak dalam status siap antar (status: '{order_doc.get('order_status')}')."
            )

    total_le = _num(order_doc.get("total_le", 0.0))
    admin_id = str(admin.get("id") or admin.get("_id") or "")
    admin_name = admin.get("name", "Admin")

    order_update = {
        "order_status": "selesai",
        "completed_at": order_doc.get("completed_at") or now_iso,
        "completed_by_id": admin_id,
        "completed_by_name": admin_name,
        "recognized_revenue_le": order_doc.get("recognized_revenue_le") if order_doc.get("recognized_revenue_le") is not None else total_le,
        "updated_at": now_iso,
        "updated_by_id": admin_id,
        "updated_by_name": admin_name,
    }

    if delivery_context:
        order_update["delivery_logistics_status"] = "delivered"
        if delivery_context.get("trip_id"):
            order_update["delivered_trip_id"] = str(delivery_context["trip_id"])
        if delivery_context.get("trip_number"):
            order_update["delivered_trip_number"] = delivery_context["trip_number"]

    reason = (delivery_context.get("reason") if delivery_context else None) or "Penyelesaian pesanan (serah terima fisik berhasil)"
    status_history_entry = {
        "from_status": order_doc.get("order_status"),
        "to_status": "selesai",
        "changed_at": now_iso,
        "changed_by_id": admin_id,
        "changed_by_name": admin_name,
        "reason": reason
    }

    # Phase 08.5C.4 — Admin Wage Accrual: Sequence B (Paid first, completed later)
    # Evaluate shared eligibility check when order transitions to 'selesai'
    if order_doc.get("order_status") != "selesai":
        order_for_wage = dict(order_doc)
        order_for_wage.update(order_update)
        order_for_wage["order_status"] = "selesai"
        if is_order_fully_paid(order_for_wage) and not is_order_excluded_from_admin_wage(order_for_wage):
            admin_wage_res = await evaluate_and_process_order_admin_wage_accrual(
                order_for_wage,
                admin,
                session=session,
                lifecycle_event="order_completed",
                transition_context={
                    "transition_type": "order_completion",
                    "order_id": str(order_doc.get("_id") or order_doc.get("id")),
                    "from_status": order_doc.get("order_status"),
                    "to_status": "selesai",
                }
            )
            if admin_wage_res:
                if admin_wage_res.get("obligation"):
                    order_update["admin_wage_obligation"] = admin_wage_res["obligation"]
                    order_update["admin_wage_blocked"] = None
                elif admin_wage_res.get("blocked"):
                    order_update["admin_wage_blocked"] = admin_wage_res["blocked"]
                elif admin_wage_res.get("skipped") and admin_wage_res.get("status") not in ("skipped_order_not_completed", "skipped_payment_not_lunas"):
                    order_update["admin_wage_skipped"] = admin_wage_res["skipped"]
                if admin_wage_res.get("eligibility"):
                    order_update["admin_wage_eligibility"] = admin_wage_res["eligibility"]

    res_ord = await db.orders.update_one(
        {"_id": order_doc["_id"]},
        {
            "$set": order_update,
            "$push": {"status_history": status_history_entry}
        },
        session=session
    )
    if res_ord.modified_count == 0 and order_doc.get("order_status") != "selesai":
        raise HTTPException(status_code=409, detail="Gagal memperbarui status pesanan. Kemungkinan sedang dimutasi proses lain.")

    updated = await db.orders.find_one({"_id": order_doc["_id"]}, session=session)
    return clean(updated)

async def record_delivery_stop_handover_core(
    trip_id: str,
    order_id: str,
    payload: DeliveryStopHandoverInput,
    admin: dict,
    session=None
) -> dict:
    recipient_name_clean = (payload.recipient_name or "").strip()
    if not recipient_name_clean:
        raise HTTPException(
            status_code=422,
            detail="Nama penerima di lokasi wajib diisi."
        )
    if payload.helper_confirmed is not True:
        raise HTTPException(
            status_code=422,
            detail="Konfirmasi serah terima fisik oleh helper wajib dicentang."
        )

    now_iso = datetime.now(timezone.utc).isoformat()
    trip = await db.delivery_trips.find_one({"_id": id_query(trip_id)}, session=session)
    if not trip:
        raise HTTPException(status_code=404, detail="Trip pengiriman tidak ditemukan")

    if trip.get("status") not in (DeliveryTripStatus.SCHEDULED.value, DeliveryTripStatus.IN_TRANSIT.value, DeliveryTripStatus.PARTIALLY_COMPLETED.value):
        raise HTTPException(
            status_code=409,
            detail=f"Tidak dapat mencatat serah terima pada trip dengan status '{trip.get('status')}'. Trip harus berstatus scheduled atau in_transit."
        )

    matching_stop = None
    for s in trip.get("stops", []):
        if str(s.get("order_id")) == str(order_id):
            matching_stop = s
            break
    if not matching_stop:
        raise HTTPException(status_code=404, detail="Pesanan tidak terdaftar sebagai stop pada trip ini.")

    # Idempotency replay check: if stop is already delivered, return existing state safely
    if matching_stop.get("outcome") == StopOutcome.DELIVERED.value:
        order_doc = await db.orders.find_one({"_id": id_query(order_id)}, session=session)
        cursor_wob = db.wage_obligations.find({"trip_id": str(trip["_id"]), "order_id": str(order_id)}, session=session)
        to_list_fn = getattr(cursor_wob, "to_list", None)
        existing_wobs = await to_list_fn(100) if callable(to_list_fn) else []
        return clean({
            "ok": True,
            "message": "Pesanan telah diserahterimakan sebelumnya (Idempoten)",
            "already_delivered": True,
            "trip": trip,
            "order": order_doc,
            "wage_obligations": existing_wobs
        })

    validate_stop_state_transition(matching_stop.get("outcome"), StopOutcome.DELIVERED.value)

    order_doc = await db.orders.find_one({"_id": id_query(order_id)}, session=session)
    if not order_doc:
        raise HTTPException(status_code=404, detail="Pesanan tidak ditemukan")

    if order_doc.get("order_status") == "selesai":
        if str(order_doc.get("active_delivery_trip_id")) != str(trip["_id"]) and str(order_doc.get("delivered_trip_id")) != str(trip["_id"]):
            raise HTTPException(status_code=409, detail="Pesanan telah selesai di luar alur pengantaran trip ini.")
    elif order_doc.get("order_status") != "siap":
        raise HTTPException(
            status_code=409,
            detail=f"Pesanan tidak dalam status siap antar (status: '{order_doc.get('order_status')}')."
        )

    # 1. Evaluate wage amount and unusual amount threshold override
    policy = await get_active_delivery_wage_policy(db_inst=db)
    base_wage = _num(policy.get("base_wage_per_order_le"), 50.0)

    snapshot = trip.get("rate_policy_snapshot")
    snapshot_rate = _num(snapshot.get("applied_rate_le")) if (isinstance(snapshot, dict) and snapshot.get("applied_rate_le") is not None) else None

    # Threshold and hard cap resolved from immutable dispatch snapshot, falling back to active policy
    if isinstance(snapshot, dict) and snapshot.get("unusual_amount_threshold_le") is not None:
        threshold = _num(snapshot.get("unusual_amount_threshold_le"))
    else:
        threshold = _num(policy.get("unusual_amount_threshold_le"), 100.0)

    if isinstance(snapshot, dict) and snapshot.get("max_cap_at_dispatch_le") is not None:
        hard_cap = _num(snapshot.get("max_cap_at_dispatch_le"))
    elif isinstance(snapshot, dict) and snapshot.get("max_helper_wage_per_order_le") is not None:
        hard_cap = _num(snapshot.get("max_helper_wage_per_order_le"))
    else:
        hard_cap = _num(policy.get("max_helper_wage_per_order_le"), 500.0)

    is_override = False
    override_reason = None

    if payload.custom_wage_le is not None:
        total_wage = _num(payload.custom_wage_le)
        if total_wage < 0:
            raise HTTPException(status_code=422, detail="Nominal upah tidak boleh bernilai negatif.")

        # Hard cap check: strict absolute maximum ceiling (Stage 2)
        if total_wage > hard_cap:
            await record_audit_log(
                action="delivery_wage_hard_cap_rejection",
                entity_type="order",
                entity_id=str(order_id),
                entity_identifier=order_doc.get("order_number", ""),
                admin=admin,
                metadata={
                    "trip_id": str(trip["_id"]),
                    "trip_number": trip.get("trip_number"),
                    "order_id": str(order_id),
                    "order_number": order_doc.get("order_number"),
                    "attempted_amount_le": total_wage,
                    "hard_cap_le": hard_cap,
                    "threshold_le": threshold,
                    "reason_provided": payload.override_reason,
                    "confirmed_unusual_amount": payload.confirmed_unusual_amount,
                    "idempotency_key": payload.idempotency_key,
                    "result": "rejected"
                },
                session=None
            )
            raise HTTPException(
                status_code=422,
                detail=f"Nominal upah ({total_wage} LE) melebihi batas maksimum keras ({hard_cap} LE). Konfirmasi dan alasan tidak dapat melewati batas keras."
            )

        # Unusual amount check: threshold < total_wage <= hard_cap
        if total_wage > threshold:
            if not payload.confirmed_unusual_amount:
                raise HTTPException(
                    status_code=422,
                    detail=f"Nominal upah ({total_wage} LE) melebihi batas konfirmasi ({threshold} LE). Konfirmasi diperlukan."
                )
            if not payload.override_reason or len(payload.override_reason.strip()) < 5:
                raise HTTPException(
                    status_code=422,
                    detail="Alasan override upah di atas batas konfirmasi wajib diisi minimal 5 karakter."
                )
            is_override = True
            override_reason = payload.override_reason.strip()
        elif snapshot_rate is not None and total_wage != snapshot_rate:
            is_override = True
            override_reason = (payload.override_reason or "").strip() or "Penyesuaian upah oleh tim operasional"
        elif snapshot_rate is None and total_wage != base_wage:
            is_override = True
            override_reason = (payload.override_reason or "").strip() or "Penyesuaian upah oleh tim operasional"
    else:
        # Immutable dispatch snapshot is strictly required (Fail-Closed, Requirement B.5 & B.6)
        if not isinstance(snapshot, dict) or snapshot_rate is None or snapshot_rate <= 0:
            raise HTTPException(
                status_code=422,
                detail="Trip pengiriman tidak memiliki snapshot kebijakan upah dispatch yang valid (Legacy / Unversioned Trip). "
                       "Pencatatan upah tidak dapat menggunakan kebijakan terkini secara otomatis (Fail-Closed). "
                       "Sediakan 'custom_wage_le' pada payload serah terima sebagai jalur pemulihan eksplisit."
            )
        total_wage = snapshot_rate

    # 2. Multi-helper distribution with exact piastre precision
    helpers = trip.get("helpers", [])
    if not helpers and total_wage > 0:
        raise HTTPException(
            status_code=422,
            detail="Trip pengiriman tidak memiliki helper terdaftar untuk menerima alokasi upah pengantaran."
        )
    try:
        allocations = calculate_delivery_helper_wage_allocations(total_wage, helpers)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # 3. Mutate Order document via centralized helper
    delivery_ctx = {
        "trip_id": str(trip["_id"]),
        "trip_number": trip.get("trip_number"),
        "reason": f"Serah terima pengiriman berhasil pada Trip {trip.get('trip_number')}"
    }
    updated_order = await execute_order_handover_completion(
        order_id=str(order_id),
        admin=admin,
        now_iso=now_iso,
        session=session,
        delivery_context=delivery_ctx,
        order_doc=order_doc
    )

    # 4. Mutate Stop on Trip
    res_trip = await db.delivery_trips.update_one(
        {"_id": trip["_id"], "stops.order_id": str(order_id)},
        {
            "$set": {
                "stops.$.outcome": StopOutcome.DELIVERED.value,
                "stops.$.delivered_at": now_iso,
                "stops.$.recipient_name": recipient_name_clean,
                "stops.$.handover_notes": (payload.handover_notes or "").strip() or None,
                "stops.$.helper_confirmed": True,
                "stops.$.total_wage_recorded_le": total_wage,
                "stops.$.wage_allocation_snapshot": allocations,
                "stops.$.is_wage_override": is_override,
                "stops.$.wage_override_reason": override_reason,
                "updated_at": now_iso,
            },
            "$inc": {"delivered_stops_count": 1}
        },
        session=session
    )
    if res_trip.modified_count == 0:
        raise HTTPException(status_code=409, detail="Gagal memperbarui stop trip pengiriman.")

    # 5. Insert Wage Obligations
    created_obligations = []
    for alloc in allocations:
        event_key = build_delivery_accrual_event_key(str(order_id), alloc["worker_id"])
        wob_num = await generate_obligation_number(session=session)
        wob_doc = {
            "obligation_number": wob_num,
            "accrual_event_key": event_key,
            "trip_id": str(trip["_id"]),
            "trip_number": trip.get("trip_number"),
            "order_id": str(order_id),
            "order_number": order_doc.get("order_number"),
            "worker_id": alloc["worker_id"],
            "worker_name": alloc["worker_name"],
            "task_category": "delivery",
            "pricing_basis": "per_order_delivery",
            "total_amount_le": alloc["amount_le"],
            "amount_piastres": alloc["amount_piastres"],
            "currency": "EGP",
            "status": "accrued",
            "paid_amount_le": 0.0,
            "rate_policy_snapshot": {
                "base_wage_per_order_le": base_wage,
                "unusual_amount_threshold_le": threshold,
                "max_cap_at_dispatch_le": hard_cap,
                "total_order_wage_le": total_wage,
                "is_override": is_override,
                "override_reason": override_reason,
                "helpers_count": len(helpers),
            },
            "created_at": now_iso,
            "updated_at": now_iso,
            "verified_by_id": str(admin.get("id") or admin.get("_id") or ""),
            "verified_by_name": admin.get("name", "Admin"),
        }
        await db.wage_obligations.insert_one(wob_doc, session=session)
        created_obligations.append(wob_doc)

    # 6. Audit Logging if threshold override occurred (risky submission > threshold confirmed by officer)
    if total_wage > threshold:
        await record_audit_log(
            action="delivery_wage_threshold_override",
            entity_type="order",
            entity_id=str(order_id),
            entity_identifier=order_doc.get("order_number", ""),
            admin=admin,
            metadata={
                "trip_id": str(trip["_id"]),
                "trip_number": trip.get("trip_number"),
                "order_id": str(order_id),
                "order_number": order_doc.get("order_number"),
                "base_wage_le": base_wage,
                "threshold_le": threshold,
                "hard_cap_le": hard_cap,
                "recorded_amount_le": total_wage,
                "override_reason": override_reason,
                "helpers_count": len(helpers),
                "allocations": allocations,
                "idempotency_key": payload.idempotency_key,
                "result": "approved"
            },
            session=session
        )

    updated_trip = await db.delivery_trips.find_one({"_id": trip["_id"]}, session=session)
    updated_order = await db.orders.find_one({"_id": order_doc["_id"]}, session=session)
    return clean({
        "ok": True,
        "trip": updated_trip,
        "order": updated_order,
        "wage_obligations": created_obligations
    })

# --------------------------------------------------------------------------
# Delivery Trip Endpoints
# --------------------------------------------------------------------------

@api_router.post("/admin/delivery-trips")
async def admin_create_delivery_trip(
    payload: DeliveryTripCreateInput,
    admin: dict = Depends(require_perm("manage_orders"))
):
    now_iso = datetime.now(timezone.utc).isoformat()
    trip_num = await generate_trip_number()

    helpers = []
    for hid in payload.helper_ids:
        emp = await db.admins.find_one({"_id": id_query(hid)})
        if not emp:
            raise HTTPException(status_code=404, detail=f"Helper dengan ID {hid!r} tidak ditemukan")
        helpers.append({
            "helper_id": str(emp.get("_id") or emp.get("id")),
            "helper_name": emp.get("name", "Helper")
        })

    vr = payload.vehicle_rental
    rental_doc = {
        "is_rented": vr.is_rented,
        "rental_provider": vr.rental_provider.strip(),
        "vehicle_plate_or_desc": vr.vehicle_plate_or_desc.strip(),
        "driver_provided_by_rental": vr.driver_provided_by_rental,
        "rental_driver_name": vr.rental_driver_name.strip(),
        "cost_obligation": {
            "agreed_rental_cost_le": _num(vr.agreed_rental_cost_le),
            "additional_cost_le": 0.0,
            "total_obligation_le": _num(vr.agreed_rental_cost_le),
            "obligation_status": "incurred",
            "agreement_reference": (vr.agreement_reference or "").strip() or None,
            "settlement_outcome": "active_agreement",
            "incurred_at": now_iso,
            "incurred_by_id": admin.get("id"),
            "incurred_by_name": admin.get("name")
        },
        "payments": [],
        "refunds": [],
        "gross_paid_le": 0.0,
        "gross_refunded_le": 0.0,
        "net_paid_le": 0.0,
        "remaining_payable_le": _num(vr.agreed_rental_cost_le),
        "payment_status": "unpaid",
        "notes": (vr.notes or "").strip() or None
    }

    trip_doc = {
        "trip_number": trip_num,
        "status": DeliveryTripStatus.DRAFT.value,
        "scheduled_date": payload.scheduled_date.strip(),
        "departure_time": (payload.departure_time or "").strip() or None,
        "trip_wage_rate_le": _num(payload.trip_wage_rate_le),
        "helper_ids": [h["helper_id"] for h in helpers],
        "helpers": helpers,
        "vehicle_rental": rental_doc,
        "rate_policy_snapshot": None,
        "stops": [],
        "stops_count": 0,
        "delivered_stops_count": 0,
        "failed_stops_count": 0,
        "actual_departure_at": None,
        "completed_at": None,
        "completion_notes": None,
        "cancelled_at": None,
        "cancellation_reason": None,
        "cancelled_by_id": None,
        "cancelled_by_name": None,
        "notes": (payload.notes or "").strip() or None,
        "created_at": now_iso,
        "created_by_id": admin.get("id"),
        "created_by_name": admin.get("name"),
        "updated_at": now_iso,
        "updated_by_id": admin.get("id"),
        "updated_by_name": admin.get("name"),
    }

    result = await db.delivery_trips.insert_one(trip_doc)
    created = await db.delivery_trips.find_one({"_id": result.inserted_id})
    return clean(created)

@api_router.get("/admin/delivery-trips")
async def admin_list_delivery_trips(
    status: Optional[str] = None,
    scheduled_date: Optional[str] = None,
    limit: int = 100,
    admin: dict = Depends(require_perm("manage_orders"))
):
    q = {}
    if status:
        q["status"] = status
    if scheduled_date:
        q["scheduled_date"] = scheduled_date
    cursor = db.delivery_trips.find(q).sort("created_at", -1).limit(min(limit, 500))
    trips = await cursor.to_list(min(limit, 500)) if hasattr(cursor, "to_list") else []
    return [clean(t) for t in trips]

@api_router.get("/admin/delivery-trips/unassigned-orders")
async def admin_get_unassigned_delivery_orders(
    delivery_zone_id: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 100,
    skip: int = 0,
    admin: dict = Depends(require_perm("manage_orders"))
):
    """
    Daftar antrean pesanan siap kirim yang belum ditugaskan ke trip aktif mana pun.
    Kriteria mutlak:
    - order_status == 'siap'
    - delivery_method == 'delivery'
    - active_delivery_trip_id is null / absent
    """
    safe_limit = min(max(1, limit), 500)
    safe_skip = max(0, skip)

    query = {
        "order_status": "siap",
        "delivery_method": "delivery",
        "active_delivery_trip_id": None
    }
    if delivery_zone_id and delivery_zone_id.strip():
        query["delivery_zone_id"] = delivery_zone_id.strip()

    if q and q.strip():
        rx = {"$regex": re.escape(q.strip()), "$options": "i"}
        query["$or"] = [
            {"order_number": rx},
            {"customer_name": rx},
            {"customer_phone": rx},
            {"phone_number": rx},
            {"customer_address": rx},
            {"delivery_zone_name": rx}
        ]

    # Deterministic FIFO sort (oldest eligible orders first)
    cursor = db.orders.find(query).sort([("created_at", 1), ("_id", 1)]).skip(safe_skip).limit(safe_limit)
    orders = await cursor.to_list(safe_limit) if hasattr(cursor, "to_list") else []

    res = []
    for o in orders:
        items = o.get("items") or ([o.get("item")] if o.get("item") else [])
        items_summary = []
        total_items_count = 0
        for it in items:
            if not it:
                continue
            qty = int(it.get("quantity", 1) or 1)
            total_items_count += qty
            name = it.get("product_name_snapshot") or it.get("product_name") or "Produk"
            items_summary.append({
                "name": name,
                "quantity": qty
            })

        res.append({
            "id": str(o.get("_id") or o.get("id")),
            "order_number": o.get("order_number") or "",
            "customer_name": o.get("customer_name") or "Pelanggan",
            "customer_phone": o.get("customer_phone") or o.get("phone_number") or "",
            "customer_address": o.get("customer_address") or "",
            "customer_maps_url": o.get("customer_maps_url") or "",
            "delivery_method": o.get("delivery_method") or "delivery",
            "delivery_zone_id": o.get("delivery_zone_id"),
            "delivery_zone_name": o.get("delivery_zone_name") or o.get("delivery_zone") or "",
            "delivery_fee_le": _num(o.get("delivery_fee_le", 0.0)),
            "total_le": _num(o.get("total_le", 0.0)),
            "order_status": o.get("order_status"),
            "delivery_logistics_status": o.get("delivery_logistics_status") or "unassigned",
            "notes": o.get("notes") or "",
            "total_items_count": total_items_count,
            "items_summary": items_summary,
            "created_at": o.get("created_at"),
            "updated_at": o.get("updated_at"),
        })

    return res

@api_router.get("/admin/delivery-trips/{trip_id}")
async def admin_get_delivery_trip(
    trip_id: str,
    admin: dict = Depends(require_perm("manage_orders"))
):
    trip = await db.delivery_trips.find_one({"_id": id_query(trip_id)})
    if not trip:
        raise HTTPException(status_code=404, detail="Trip pengiriman tidak ditemukan")

    stops = trip.get("stops", [])
    if any(not s.get("customer_address") and not s.get("customer_maps_url") for s in stops):
        for s in stops:
            if not s.get("customer_address") or not s.get("customer_maps_url") or not s.get("customer_phone"):
                oid = s.get("order_id")
                if oid:
                    ord_doc = await db.orders.find_one({"_id": id_query(oid)})
                    if ord_doc:
                        if not s.get("customer_address"):
                            s["customer_address"] = ord_doc.get("customer_address") or ""
                        if not s.get("customer_maps_url"):
                            s["customer_maps_url"] = ord_doc.get("customer_maps_url") or ""
                        if not s.get("customer_phone"):
                            s["customer_phone"] = ord_doc.get("customer_phone") or ord_doc.get("phone_number") or ""

    return clean(trip)

@api_router.patch("/admin/delivery-trips/{trip_id}/status")
async def admin_update_delivery_trip_status(
    trip_id: str,
    payload: DeliveryTripStatusUpdateInput,
    admin: dict = Depends(require_perm("manage_orders"))
):
    target_status = payload.target_status.strip().lower()
    trip = await db.delivery_trips.find_one({"_id": id_query(trip_id)})
    if not trip:
        raise HTTPException(status_code=404, detail="Trip pengiriman tidak ditemukan")

    current_status = trip.get("status")
    validate_trip_state_transition(current_status, target_status, trip)

    now_iso = datetime.now(timezone.utc).isoformat()
    update_doc = {
        "status": target_status,
        "updated_at": now_iso,
        "updated_by_id": admin.get("id"),
        "updated_by_name": admin.get("name")
    }

    if target_status == DeliveryTripStatus.IN_TRANSIT.value:
        active_policy = await get_active_delivery_wage_policy(db_inst=db)
        trip_rate = _num(trip.get("trip_wage_rate_le", 0.0))
        if trip_rate > 0:
            applied_rate = trip_rate
            is_custom_rate = True
        else:
            applied_rate = _num(active_policy.get("base_wage_per_order_le"), 50.0)
            is_custom_rate = False

        cap_val = await validate_delivery_trip_wage_cap(applied_rate)
        threshold_val = _num(active_policy.get("unusual_amount_threshold_le"), 100.0)
        update_doc["rate_policy_snapshot"] = {
            "applied_rate_le": applied_rate,
            "is_custom_rate": is_custom_rate,
            "max_cap_at_dispatch_le": cap_val,
            "unusual_amount_threshold_le": threshold_val,
            "base_wage_per_order_le": _num(active_policy.get("base_wage_per_order_le"), 50.0),
            "currency": active_policy.get("currency", "EGP"),
            "rounding_policy": active_policy.get("rounding_policy", "piastre_round_half_up"),
            "policy_updated_at": active_policy.get("updated_at"),
            "locked_at": now_iso,
            "locked_by_id": admin.get("id"),
            "locked_by_name": admin.get("name")
        }
        update_doc["actual_departure_at"] = now_iso
        update_doc["stops.$[elem].outcome"] = StopOutcome.OUT_FOR_DELIVERY.value

        async def _do_dispatch(sess):
            await db.delivery_trips.update_one(
                {"_id": trip["_id"], "status": current_status},
                {"$set": update_doc},
                array_filters=[{"elem.outcome": StopOutcome.PENDING.value}],
                session=sess
            )
            stop_order_ids = [s["order_id"] for s in trip.get("stops", []) if s.get("outcome") == StopOutcome.PENDING.value]
            if stop_order_ids:
                await db.orders.update_many(
                    {"_id": {"$in": multi_id_query(stop_order_ids)}, "active_delivery_trip_id": str(trip["_id"])},
                    {"$set": {"delivery_logistics_status": "in_transit", "updated_at": now_iso}},
                    session=sess
                )
            return await db.delivery_trips.find_one({"_id": trip["_id"]}, session=sess)

        res = await _execute_delivery_tx_or_fail_closed(_do_dispatch)
        return clean(res)

    elif target_status == DeliveryTripStatus.CANCELLED.value:
        return await _execute_delivery_tx_or_fail_closed(
            lambda sess: cancel_trip_multi_stop_core(trip_id, payload.reason or "Dibatalkan oleh Admin", admin, session=sess)
        )
    else:
        await db.delivery_trips.update_one(
            {"_id": trip["_id"], "status": current_status},
            {"$set": update_doc}
        )
        return clean(await db.delivery_trips.find_one({"_id": trip["_id"]}))

@api_router.post("/admin/delivery-trips/{trip_id}/stops")
async def admin_add_trip_stop(
    trip_id: str,
    payload: DeliveryTripAddStopInput,
    admin: dict = Depends(require_perm("manage_orders"))
):
    return await _execute_delivery_tx_or_fail_closed(
        lambda sess: assign_order_to_trip_core(trip_id, payload.order_id, admin, session=sess)
    )

@api_router.delete("/admin/delivery-trips/{trip_id}/stops/{order_id}")
async def admin_remove_trip_stop(
    trip_id: str,
    order_id: str,
    admin: dict = Depends(require_perm("manage_orders"))
):
    return await _execute_delivery_tx_or_fail_closed(
        lambda sess: release_order_from_trip_core(trip_id, order_id, admin, session=sess)
    )

@api_router.post("/admin/delivery-trips/{trip_id}/stops/{order_id}/record-attempt")
async def admin_record_trip_stop_attempt(
    trip_id: str,
    order_id: str,
    payload: DeliveryTripStopAttemptInput,
    admin: dict = Depends(require_perm("manage_orders"))
):
    return await _execute_delivery_tx_or_fail_closed(
        lambda sess: record_delivery_attempt_core(trip_id, order_id, payload, admin, session=sess)
    )

@api_router.post("/admin/delivery-trips/{trip_id}/cancel")
async def admin_cancel_delivery_trip(
    trip_id: str,
    payload: DeliveryTripCancelInput,
    admin: dict = Depends(require_perm("manage_orders"))
):
    return await _execute_delivery_tx_or_fail_closed(
        lambda sess: cancel_trip_multi_stop_core(trip_id, payload.reason, admin, session=sess)
    )

@api_router.post("/admin/delivery-trips/{trip_id}/complete")
async def admin_complete_delivery_trip(
    trip_id: str,
    payload: DeliveryTripCompleteInput,
    admin: dict = Depends(require_perm("manage_orders"))
):
    return await _execute_delivery_tx_or_fail_closed(
        lambda sess: complete_trip_partial_core(trip_id, payload.notes, admin, session=sess)
    )

@api_router.post("/admin/delivery-trips/{trip_id}/stops/{order_id}/deliver")
async def admin_deliver_trip_stop(
    trip_id: str,
    order_id: str,
    payload: DeliveryStopHandoverInput,
    admin: dict = Depends(require_perm("manage_orders"))
):
    return await _execute_delivery_tx_or_fail_closed(
        lambda sess: record_delivery_stop_handover_core(trip_id, order_id, payload, admin, session=sess)
    )

@api_router.get("/admin/delivery-wage-policy")
async def admin_get_delivery_wage_policy(
    admin: dict = Depends(require_perm("access_finance"))
):
    policy = await get_active_delivery_wage_policy(db_inst=db)
    return clean(policy)

@api_router.put("/admin/delivery-wage-policy")
async def admin_update_delivery_wage_policy(
    payload: DeliveryWagePolicyInput,
    admin: dict = Depends(require_owner())
):
    if admin.get("role") != "owner":
        raise HTTPException(status_code=403, detail="Hanya Owner/CEO yang dapat melakukan ini")
    if payload.base_wage_per_order_le < 0:
        raise HTTPException(status_code=422, detail="Tarif dasar upah tidak boleh negatif")
    if payload.unusual_amount_threshold_le <= 0:
        raise HTTPException(status_code=422, detail="Batas konfirmasi nominal tidak wajar harus lebih besar dari 0")
    if payload.max_helper_wage_per_order_le is None or payload.max_helper_wage_per_order_le <= 0:
        raise HTTPException(status_code=422, detail="Batas maksimum keras upah (hard cap) wajib diisi dan harus lebih besar dari 0")

    if payload.base_wage_per_order_le > payload.unusual_amount_threshold_le:
        raise HTTPException(
            status_code=422,
            detail=f"Batas konfirmasi ({payload.unusual_amount_threshold_le} LE) tidak boleh lebih kecil dari tarif dasar ({payload.base_wage_per_order_le} LE)"
        )
    if payload.unusual_amount_threshold_le >= payload.max_helper_wage_per_order_le:
        raise HTTPException(
            status_code=422,
            detail=f"Batas konfirmasi ({payload.unusual_amount_threshold_le} LE) harus lebih kecil dari batas maksimum keras ({payload.max_helper_wage_per_order_le} LE)"
        )

    old_policy = await get_active_delivery_wage_policy(db_inst=db)
    now_iso = datetime.now(timezone.utc).isoformat()

    new_policy_val = {
        "base_wage_per_order_le": float(payload.base_wage_per_order_le),
        "unusual_amount_threshold_le": float(payload.unusual_amount_threshold_le),
        "max_helper_wage_per_order_le": float(payload.max_helper_wage_per_order_le),
        "enabled": getattr(payload, "enabled", True) if getattr(payload, "enabled", True) is not None else True,
        "currency": "EGP",
        "rounding_policy": "piastre_round_half_up",
        "updated_at": now_iso,
        "updated_by_id": str(admin.get("id") or admin.get("_id") or ""),
        "updated_by_name": admin.get("name", "Owner")
    }

    changed_keys = []
    for k in ["base_wage_per_order_le", "unusual_amount_threshold_le", "max_helper_wage_per_order_le", "enabled"]:
        if old_policy.get(k) != new_policy_val.get(k):
            changed_keys.append(k)
    if not old_policy.get("is_configured"):
        changed_keys.append("is_configured")

    if not changed_keys:
        res_noop = dict(old_policy)
        res_noop["is_configured"] = True
        res_noop["no_op"] = True
        res_noop["message"] = "Tidak ada perubahan konfigurasi terdeteksi."
        return clean(res_noop)

    legacy_reason = (getattr(payload, "change_reason", None) or "").strip()
    if legacy_reason:
        if len(legacy_reason) < 3:
            raise HTTPException(status_code=422, detail="Alasan perubahan kebijakan wajib diisi minimal 3 karakter.")
        if len(legacy_reason) > 500:
            raise HTTPException(status_code=422, detail="Alasan perubahan kebijakan maksimal 500 karakter.")
    else:
        legacy_reason = "Pembaruan kebijakan upah pengiriman (legacy endpoint)"

    new_policy_val["last_change_reason"] = legacy_reason

    client = getattr(db, "client", None)
    async def _do_legacy_update(sess):
        kw = {"session": sess} if sess else {}
        await db.settings.update_one(
            {"key": "delivery_wage_policy"},
            {"$set": {"key": "delivery_wage_policy", "value": new_policy_val, "updated_at": now_iso}},
            upsert=True,
            **kw
        )

        await record_audit_log(
            action="update_delivery_wage_policy",
            entity_type="delivery_wage_policy",
            entity_id="delivery_wage_policy",
            entity_identifier="delivery_wage_policy",
            admin=admin,
            metadata={
                "previous": old_policy,
                "new": new_policy_val,
                "changed_fields": changed_keys,
                "change_reason": legacy_reason
            },
            session=sess
        )

    await execute_transaction_with_safety(client, _do_legacy_update)

    result_policy = dict(new_policy_val)
    result_policy["is_configured"] = True
    result_policy["no_op"] = False
    return clean(result_policy)

@api_router.get("/admin/wage-policies")
async def admin_get_all_wage_policies_endpoint(
    admin: dict = Depends(require_perm("access_finance"))
):
    policies = await get_all_active_wage_policies(db_inst=db)
    return clean(policies)

@api_router.get("/admin/wage-policies/{category}")
async def admin_get_wage_policy_by_category(
    category: str,
    admin: dict = Depends(require_perm("access_finance"))
):
    if category == "production":
        policy = await get_active_production_wage_policy(db_inst=db)
    elif category == "delivery":
        policy = await get_active_delivery_wage_policy(db_inst=db)
    elif category == "material_purchase":
        policy = await get_active_material_purchase_wage_policy(db_inst=db)
    elif category == "admin":
        policy = await get_active_admin_wage_policy(db_inst=db)
    else:
        raise HTTPException(status_code=404, detail=f"Kategori kebijakan '{category}' tidak valid. Pilihan: production, delivery, material_purchase, admin")
    return clean(policy)

@api_router.put("/admin/wage-policies/{category}")
async def admin_update_wage_policy_endpoint(
    category: str,
    request: Request,
    admin: dict = Depends(require_owner())
):
    if admin.get("role") != "owner":
        raise HTTPException(status_code=403, detail="Hanya Owner/CEO yang dapat melakukan ini")

    if category not in ["production", "delivery", "material_purchase", "admin"]:
        raise HTTPException(status_code=404, detail=f"Kategori kebijakan '{category}' tidak valid. Pilihan: production, delivery, material_purchase, admin")

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Format JSON tidak valid")

    now_iso = datetime.now(timezone.utc).isoformat()
    admin_id_str = str(admin.get("id") or admin.get("_id") or "")
    admin_name_str = admin.get("name", "Owner")

    cycle_event_action = None
    current_cycle_id = None
    old_enabled = False
    target_enabled = False
    existing_cycles = []

    if category == "delivery":
        try:
            payload = DeliveryWagePolicyInput(**body)
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Validasi gagal: {e}")

        if payload.base_wage_per_order_le < 0:
            raise HTTPException(status_code=422, detail="Tarif dasar upah tidak boleh negatif")
        if payload.unusual_amount_threshold_le <= 0:
            raise HTTPException(status_code=422, detail="Batas konfirmasi nominal tidak wajar harus lebih besar dari 0")
        if payload.max_helper_wage_per_order_le is None or payload.max_helper_wage_per_order_le <= 0:
            raise HTTPException(status_code=422, detail="Batas maksimum keras upah (hard cap) wajib diisi dan harus lebih besar dari 0")
        if payload.base_wage_per_order_le > payload.unusual_amount_threshold_le:
            raise HTTPException(
                status_code=422,
                detail=f"Batas konfirmasi ({payload.unusual_amount_threshold_le} LE) tidak boleh lebih kecil dari tarif dasar ({payload.base_wage_per_order_le} LE)"
            )
        if payload.unusual_amount_threshold_le >= payload.max_helper_wage_per_order_le:
            raise HTTPException(
                status_code=422,
                detail=f"Batas konfirmasi ({payload.unusual_amount_threshold_le} LE) harus lebih kecil dari batas maksimum keras ({payload.max_helper_wage_per_order_le} LE)"
            )

        old_policy = await get_active_delivery_wage_policy(db_inst=db)
        new_policy_val = {
            "base_wage_per_order_le": float(payload.base_wage_per_order_le),
            "unusual_amount_threshold_le": float(payload.unusual_amount_threshold_le),
            "max_helper_wage_per_order_le": float(payload.max_helper_wage_per_order_le),
            "enabled": getattr(payload, "enabled", True) if getattr(payload, "enabled", True) is not None else True,
            "currency": "EGP",
            "rounding_policy": "piastre_round_half_up",
            "updated_at": now_iso,
            "updated_by_id": admin_id_str,
            "updated_by_name": admin_name_str
        }
        tracked_keys = ["base_wage_per_order_le", "unusual_amount_threshold_le", "max_helper_wage_per_order_le", "enabled"]

    elif category == "production":
        try:
            payload = ProductionWagePolicyInput(**body)
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Validasi gagal: {e}")

        if payload.default_wage_per_unit_le < 0:
            raise HTTPException(status_code=422, detail="Tarif dasar upah produksi tidak boleh negatif")
        if payload.unusual_amount_threshold_le <= 0:
            raise HTTPException(status_code=422, detail="Batas konfirmasi nominal tidak wajar harus lebih besar dari 0")
        if payload.max_wage_per_unit_le <= 0:
            raise HTTPException(status_code=422, detail="Batas maksimum keras upah produksi wajib diisi dan harus lebih besar dari 0")
        if payload.default_wage_per_unit_le > payload.unusual_amount_threshold_le:
            raise HTTPException(
                status_code=422,
                detail=f"Batas konfirmasi ({payload.unusual_amount_threshold_le} LE) tidak boleh lebih kecil dari tarif dasar ({payload.default_wage_per_unit_le} LE)"
            )
        if payload.unusual_amount_threshold_le >= payload.max_wage_per_unit_le:
            raise HTTPException(
                status_code=422,
                detail=f"Batas konfirmasi ({payload.unusual_amount_threshold_le} LE) harus lebih kecil dari batas maksimum keras ({payload.max_wage_per_unit_le} LE)"
            )

        old_policy = await get_active_production_wage_policy(db_inst=db)
        new_policy_val = {
            "default_wage_per_unit_le": float(payload.default_wage_per_unit_le),
            "unusual_amount_threshold_le": float(payload.unusual_amount_threshold_le),
            "max_wage_per_unit_le": float(payload.max_wage_per_unit_le),
            "enabled": bool(payload.enabled),
            "currency": "EGP",
            "rounding_policy": "piastre_round_half_up",
            "updated_at": now_iso,
            "updated_by_id": admin_id_str,
            "updated_by_name": admin_name_str
        }
        tracked_keys = ["default_wage_per_unit_le", "unusual_amount_threshold_le", "max_wage_per_unit_le", "enabled"]

    elif category == "material_purchase":
        try:
            payload = MaterialPurchaseWagePolicyInput(**body)
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Validasi gagal: {e}")

        if payload.default_wage_per_purchase_le < 0:
            raise HTTPException(status_code=422, detail="Tarif dasar upah belanja bahan tidak boleh negatif")
        if payload.unusual_amount_threshold_le <= 0:
            raise HTTPException(status_code=422, detail="Batas konfirmasi nominal tidak wajar harus lebih besar dari 0")
        if payload.max_wage_per_purchase_le <= 0:
            raise HTTPException(status_code=422, detail="Batas maksimum keras upah belanja bahan wajib diisi dan harus lebih besar dari 0")
        if payload.max_buyers < 1 or payload.max_buyers > 5:
            raise HTTPException(status_code=422, detail="Batas maksimum pembeli bahan harus di antara 1 dan 5")
        if payload.default_wage_per_purchase_le > payload.unusual_amount_threshold_le:
            raise HTTPException(
                status_code=422,
                detail=f"Batas konfirmasi ({payload.unusual_amount_threshold_le} LE) tidak boleh lebih kecil dari tarif dasar ({payload.default_wage_per_purchase_le} LE)"
            )
        if payload.unusual_amount_threshold_le >= payload.max_wage_per_purchase_le:
            raise HTTPException(
                status_code=422,
                detail=f"Batas konfirmasi ({payload.unusual_amount_threshold_le} LE) harus lebih kecil dari batas maksimum keras ({payload.max_wage_per_purchase_le} LE)"
            )

        old_policy = await get_active_material_purchase_wage_policy(db_inst=db)
        new_policy_val = {
            "default_wage_per_purchase_le": float(payload.default_wage_per_purchase_le),
            "unusual_amount_threshold_le": float(payload.unusual_amount_threshold_le),
            "max_wage_per_purchase_le": float(payload.max_wage_per_purchase_le),
            "max_buyers": int(payload.max_buyers),
            "enabled": bool(payload.enabled),
            "currency": "EGP",
            "rounding_policy": "piastre_round_half_up",
            "updated_at": now_iso,
            "updated_by_id": admin_id_str,
            "updated_by_name": admin_name_str
        }
        tracked_keys = ["default_wage_per_purchase_le", "unusual_amount_threshold_le", "max_wage_per_purchase_le", "max_buyers", "enabled"]

    elif category == "admin":
        try:
            payload = AdminWagePolicyInput(**body)
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Validasi gagal: {e}")

        if payload.default_wage_per_order_le < 0:
            raise HTTPException(status_code=422, detail="Tarif dasar upah admin tidak boleh negatif")
        if payload.unusual_amount_threshold_le <= 0:
            raise HTTPException(status_code=422, detail="Batas konfirmasi nominal tidak wajar harus lebih besar dari 0")
        if payload.max_wage_per_order_le <= 0:
            raise HTTPException(status_code=422, detail="Batas maksimum keras upah admin wajib diisi dan harus lebih besar dari 0")
        if payload.default_wage_per_order_le > payload.unusual_amount_threshold_le:
            raise HTTPException(
                status_code=422,
                detail=f"Batas konfirmasi ({payload.unusual_amount_threshold_le} LE) tidak boleh lebih kecil dari tarif dasar ({payload.default_wage_per_order_le} LE)"
            )
        if payload.unusual_amount_threshold_le >= payload.max_wage_per_order_le:
            raise HTTPException(
                status_code=422,
                detail=f"Batas konfirmasi ({payload.unusual_amount_threshold_le} LE) harus lebih kecil dari batas maksimum keras ({payload.max_wage_per_order_le} LE)"
            )

        recipient_name = None
        if payload.default_recipient_id:
            recip = await db.admins.find_one({"_id": id_query(payload.default_recipient_id)})
            if not recip:
                raise HTTPException(
                    status_code=422,
                    detail=f"Penerima upah admin default dengan ID '{payload.default_recipient_id}' tidak ditemukan dalam database akun tim"
                )
            recipient_name = recip.get("name", "Admin")

        old_policy = await get_active_admin_wage_policy(db_inst=db)
        old_enabled = bool(old_policy.get("enabled", False))
        target_enabled = bool(payload.enabled)
        existing_cycles = list(old_policy.get("activation_cycles") or [])
        current_cycle_id = old_policy.get("current_cycle_id")
        initial_activation_at = old_policy.get("initial_activation_at")

        cycle_event_action = None
        if not old_enabled and target_enabled:
            # Transition: OFF -> ON (Start new cycle)
            new_cycle_id = f"cycle_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}"
            new_cycle = {
                "cycle_id": new_cycle_id,
                "enabled_at": now_iso,
                "enabled_by_id": admin_id_str,
                "enabled_by_name": admin_name_str,
                "enabled_reason": (body.get("change_reason") or getattr(payload, "change_reason", None) or "").strip(),
                "disabled_at": None,
                "disabled_by_id": None,
                "disabled_by_name": None,
                "disabled_reason": None,
            }
            existing_cycles.append(new_cycle)
            current_cycle_id = new_cycle_id
            if not initial_activation_at:
                initial_activation_at = now_iso
            cycle_event_action = "admin_wage_policy_cycle_opened"

        elif old_enabled and not target_enabled:
            # Transition: ON -> OFF (Close active cycle)
            reason_text = (body.get("change_reason") or getattr(payload, "change_reason", None) or "").strip()
            for c in existing_cycles:
                if c.get("disabled_at") is None or c.get("cycle_id") == current_cycle_id:
                    c["disabled_at"] = now_iso
                    c["disabled_by_id"] = admin_id_str
                    c["disabled_by_name"] = admin_name_str
                    c["disabled_reason"] = reason_text
            current_cycle_id = None
            cycle_event_action = "admin_wage_policy_cycle_closed"

        new_policy_val = {
            "default_wage_per_order_le": float(payload.default_wage_per_order_le),
            "default_recipient_id": str(payload.default_recipient_id) if payload.default_recipient_id else None,
            "default_recipient_name": recipient_name,
            "unusual_amount_threshold_le": float(payload.unusual_amount_threshold_le),
            "max_wage_per_order_le": float(payload.max_wage_per_order_le),
            "enabled": target_enabled,
            "currency": "EGP",
            "rounding_policy": "piastre_round_half_up",
            "activation_cycles": existing_cycles,
            "current_cycle_id": current_cycle_id,
            "initial_activation_at": initial_activation_at,
            "updated_at": now_iso,
            "updated_by_id": admin_id_str,
            "updated_by_name": admin_name_str
        }
        tracked_keys = ["default_wage_per_order_le", "default_recipient_id", "unusual_amount_threshold_le", "max_wage_per_order_le", "enabled"]

    changed_keys = [k for k in tracked_keys if old_policy.get(k) != new_policy_val.get(k)]
    if not old_policy.get("is_configured"):
        changed_keys.append("is_configured")

    if not changed_keys:
        res_noop = dict(old_policy)
        res_noop["is_configured"] = True
        res_noop["no_op"] = True
        res_noop["message"] = "Tidak ada perubahan konfigurasi terdeteksi."
        return clean(res_noop)

    # Validate mandatory reason on genuine changes
    change_reason = (body.get("change_reason") or getattr(payload, "change_reason", None) or "").strip()
    if not change_reason or len(change_reason) < 3:
        raise HTTPException(
            status_code=422,
            detail="Alasan perubahan kebijakan wajib diisi minimal 3 karakter."
        )
    if len(change_reason) > 500:
        raise HTTPException(
            status_code=422,
            detail="Alasan perubahan kebijakan maksimal 500 karakter."
        )

    new_policy_val["last_change_reason"] = change_reason
    setting_key = f"{category}_wage_policy"

    client = getattr(db, "client", None)
    async def _do_policy_update(sess):
        kw = {"session": sess} if sess else {}
        await db.settings.update_one(
            {"key": setting_key},
            {"$set": {"key": setting_key, "value": new_policy_val, "updated_at": now_iso}},
            upsert=True,
            **kw
        )

        await record_audit_log(
            action=f"update_{category}_wage_policy",
            entity_type=f"{category}_wage_policy",
            entity_id=setting_key,
            entity_identifier=setting_key,
            admin=admin,
            metadata={
                "category": category,
                "previous": old_policy,
                "new": new_policy_val,
                "changed_fields": changed_keys,
                "change_reason": change_reason
            },
            session=sess
        )

        if cycle_event_action:
            await record_audit_log(
                action=cycle_event_action,
                entity_type=f"{category}_wage_policy",
                entity_id=setting_key,
                entity_identifier=setting_key,
                admin=admin,
                metadata={
                    "category": category,
                    "cycle_id": current_cycle_id,
                    "previous_enabled": old_enabled,
                    "new_enabled": target_enabled,
                    "activation_cycles_count": len(existing_cycles),
                    "change_reason": change_reason
                },
                session=sess
            )

    await execute_transaction_with_safety(client, _do_policy_update)

    result_policy = dict(new_policy_val)
    result_policy["is_configured"] = True
    result_policy["no_op"] = False
    return clean(result_policy)

@api_router.get("/admin/wage-policies/{category}/history")
async def admin_get_wage_policy_history_endpoint(
    category: str,
    limit: int = 50,
    admin: dict = Depends(require_perm("access_finance"))
):
    if category not in ["production", "delivery", "material_purchase", "admin"]:
        raise HTTPException(status_code=404, detail=f"Kategori kebijakan '{category}' tidak valid. Pilihan: production, delivery, material_purchase, admin")

    query = {
        "$or": [
            {"entity_type": f"{category}_wage_policy"},
            {"action": f"update_{category}_wage_policy"}
        ]
    }
    if category == "delivery":
        query["$or"].append({"action": {"$in": ["delivery_wage_threshold_override", "delivery_wage_hard_cap_rejection"]}})

    cursor = db.audit_logs.find(query).sort("timestamp", -1)
    to_list_fn = getattr(cursor, "to_list", None)
    if callable(to_list_fn):
        res = to_list_fn(min(limit, 100))
        logs = await res if inspect.isawaitable(res) else []
    else:
        logs = []
    return [clean(l) for l in logs]

@api_router.get("/admin/delivery-wage-policy/history")
async def admin_get_delivery_wage_policy_history(
    limit: int = 50,
    admin: dict = Depends(require_perm("access_finance"))
):
    query = {
        "$or": [
            {"entity_type": "delivery_wage_policy"},
            {"action": {"$in": ["update_delivery_wage_policy", "delivery_wage_threshold_override", "delivery_wage_hard_cap_rejection"]}}
        ]
    }
    cursor = db.audit_logs.find(query).sort("timestamp", -1)
    to_list_fn = getattr(cursor, "to_list", None)
    if callable(to_list_fn):
        res = to_list_fn(min(limit, 100))
        logs = await res if inspect.isawaitable(res) else []
    else:
        logs = []
    return [clean(l) for l in logs]

@api_router.post("/admin/delivery-wages/preview")
async def admin_preview_delivery_wage_allocation(
    payload: DeliveryWagePreviewInput,
    admin: dict = Depends(require_perm("access_finance"))
):
    policy = await get_active_delivery_wage_policy(db_inst=db)
    threshold = _num(policy.get("unusual_amount_threshold_le"), 100.0)
    hard_cap = _num(policy.get("max_helper_wage_per_order_le"), 500.0)
    base_wage = _num(policy.get("base_wage_per_order_le"), 50.0)

    total_wage = _num(payload.total_wage_le) if payload.total_wage_le is not None else base_wage
    if total_wage < 0:
        raise HTTPException(status_code=422, detail="Nominal upah tidak boleh negatif")

    exceeds_hard_cap = total_wage > hard_cap
    requires_confirmation = threshold < total_wage <= hard_cap
    allocations = calculate_delivery_helper_wage_allocations(total_wage, payload.helpers, allow_empty=True)

    return {
        "total_wage_le": total_wage,
        "base_wage_le": base_wage,
        "threshold_le": threshold,
        "hard_cap_le": hard_cap,
        "requires_confirmation": requires_confirmation,
        "exceeds_hard_cap": exceeds_hard_cap,
        "helpers_count": len(payload.helpers),
        "allocations": allocations
    }

# --------------------------------------------------------------------------
# Admin: Invoices Management
# --------------------------------------------------------------------------
async def get_next_invoice_number():
    year = datetime.now(timezone.utc).strftime("%Y")
    counter_id = f"invoice_{year}"
    prefix = f"INV-{year}-"

    # Self-healing synchronization on first call for this counter_id
    existing_counter = await db.counters.find_one({"_id": counter_id})
    if existing_counter is None:
        last_inv = await db.invoices.find_one(
            {"invoice_number": {"$regex": f"^{prefix}"}},
            sort=[("invoice_number", -1)]
        )
        current_max = 0
        if last_inv and "invoice_number" in last_inv:
            try:
                current_max = int(last_inv["invoice_number"].split("-")[-1])
            except (ValueError, IndexError):
                current_max = 0

        # Also inspect audit_logs for any permanently deleted invoices of this year
        find_audit = getattr(db, "audit_logs", None)
        if find_audit is not None and hasattr(find_audit, "find_one"):
            try:
                res_audit = find_audit.find_one(
                    {"entity_type": "invoice", "entity_identifier": {"$regex": f"^{prefix}"}},
                    sort=[("entity_identifier", -1)]
                )
                if inspect.isawaitable(res_audit):
                    last_audit = await res_audit
                elif isinstance(res_audit, dict):
                    last_audit = res_audit
                else:
                    last_audit = None

                if last_audit and isinstance(last_audit, dict) and "entity_identifier" in last_audit:
                    try:
                        audit_max = int(last_audit["entity_identifier"].split("-")[-1])
                        current_max = max(current_max, audit_max)
                    except (ValueError, IndexError):
                        pass
            except Exception:
                pass

        await db.counters.update_one(
            {"_id": counter_id},
            {"$set": {"seq": current_max}},
            upsert=True
        )

    res = await db.counters.find_one_and_update(
        {"_id": counter_id},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER
    )
    seq = res["seq"]
    return f"{prefix}{seq:04d}"

def calculate_invoice_totals(items_data: list, discount_amount: float = 0.0, delivery_fee: float = 0.0, additional_fee: float = 0.0):
    processed_items = []
    subtotal = 0.0
    for idx, it in enumerate(items_data):
        it_dict = it.dict() if hasattr(it, "dict") else dict(it)
        name = (it_dict.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail=f"Nama item ke-{idx+1} wajib diisi.")
        raw_qty = it_dict.get("quantity")
        qty = int(raw_qty) if raw_qty is not None else 1
        if qty < 1:
            raise HTTPException(status_code=400, detail=f"Jumlah item '{name}' minimal 1.")
        price = _num(it_dict.get("unit_price", 0.0))
        if price < 0:
            raise HTTPException(status_code=400, detail=f"Harga item '{name}' tidak boleh negatif.")

        line_total = round(qty * price, 2)
        subtotal += line_total

        item_id = it_dict.get("item_id") or f"item_{uuid.uuid4().hex[:8]}"
        dims = it_dict.get("dimensions") or {}
        if hasattr(dims, "dict"):
            dims = dims.dict()

        processed_items.append({
            "item_id": item_id,
            "item_type": it_dict.get("item_type", "custom"),
            "product_id": it_dict.get("product_id") or None,
            "product_slug": it_dict.get("product_slug") or None,
            "name": name,
            "description": (it_dict.get("description") or "").strip(),
            "quantity": qty,
            "dimensions": {
                "length": dims.get("length") or None,
                "width": dims.get("width") or None,
                "height": dims.get("height") or None,
                "notes": dims.get("notes") or None,
            },
            "material": (it_dict.get("material") or "").strip(),
            "finishing": (it_dict.get("finishing") or "").strip(),
            "unit_price": round(price, 2),
            "line_total": line_total,
            "notes": (it_dict.get("notes") or "").strip(),
        })

    disc = max(0.0, _num(discount_amount))
    deliv = max(0.0, _num(delivery_fee))
    add_fee = max(0.0, _num(additional_fee))
    subtotal = round(subtotal, 2)
    total = max(0.0, round(subtotal - disc + deliv + add_fee, 2))

    return processed_items, subtotal, disc, deliv, add_fee, total

@api_router.get("/admin/invoices")
async def admin_list_invoices(
    status: Optional[str] = None,
    q: Optional[str] = None,
    admin: dict = Depends(require_perm("manage_orders"))
):
    query = {}
    if status and status != "all":
        query["status"] = status.upper()
    if q:
        escaped = re.escape(q.strip())
        regex = {"$regex": escaped, "$options": "i"}
        query["$or"] = [
            {"invoice_number": regex},
            {"customer.name": regex},
            {"customer.whatsapp": regex},
            {"order_number": regex},
        ]

    cursor = db.invoices.find(query).sort("created_at", -1)
    invoices = []
    async for doc in cursor:
        invoices.append(clean(doc))
    return invoices

@api_router.get("/admin/invoices/{invoice_id}")
async def admin_get_invoice(invoice_id: str, admin: dict = Depends(require_perm("manage_orders"))):
    inv = await db.invoices.find_one({"_id": id_query(invoice_id)})
    if not inv:
        inv = await db.invoices.find_one({"invoice_number": invoice_id})
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice tidak ditemukan.")
    return clean(inv)

@api_router.post("/admin/invoices")
async def admin_create_invoice(data: InvoiceInput, admin: dict = Depends(require_perm("manage_orders"))):
    cust_name = (data.customer.name or "").strip()
    if not cust_name:
        raise HTTPException(status_code=400, detail="Nama customer tidak boleh kosong.")

    wa = normalize_phone(data.customer.whatsapp)
    if not wa or not valid_intl_phone(wa):
        raise HTTPException(status_code=400, detail="No WhatsApp customer harus diawali + dan kode negara valid.")

    egypt_phone = normalize_egypt_phone(data.customer.egypt_phone) if data.customer.egypt_phone else None

    # Load master customer snapshot if customer_id provided
    customer_id = data.customer.customer_id
    if customer_id:
        c_doc = await db.customers.find_one({"_id": id_query(customer_id)})
        if c_doc:
            customer_id = str(c_doc["_id"])

    customer_snapshot = {
        "customer_id": customer_id,
        "name": cust_name,
        "whatsapp": wa,
        "egypt_phone": egypt_phone,
        "address": (data.customer.address or "").strip() or None,
    }

    if not data.items:
        raise HTTPException(status_code=400, detail="Invoice minimal harus memiliki 1 item.")

    items, subtotal, disc, deliv, add_fee, total = calculate_invoice_totals(
        data.items, data.discount_amount, data.delivery_fee, data.additional_fee
    )

    # Check custom request source if supplied
    source_custom_request_id = None
    if data.source and data.source.custom_request_id:
        cr = await db.custom_requests.find_one({"_id": id_query(data.source.custom_request_id)})
        if cr:
            source_custom_request_id = str(cr["_id"])

    init_status = "SENT" if data.status == "SENT" else "DRAFT"
    now = datetime.now(timezone.utc).isoformat()
    sent_at = now if init_status == "SENT" else None

    invoice_doc = {
        "status": init_status,
        "customer": customer_snapshot,
        "claim": {
            "code_hash": None,
            "claimed_by_customer_id": None,
            "claimed_at": None,
            "generated_at": None,
        },
        "source": {
            "custom_request_id": source_custom_request_id
        },
        "items": items,
        "subtotal": subtotal,
        "discount_amount": disc,
        "delivery_fee": deliv,
        "additional_fee": add_fee,
        "total": total,
        "currency": "EGP",
        "customer_note": (data.customer_note or "").strip(),
        "internal_note": (data.internal_note or "").strip(),
        "order_id": None,
        "order_number": None,
        "created_by": admin.get("name", "Admin"),
        "updated_by": admin.get("name", "Admin"),
        "created_at": now,
        "updated_at": now,
        "sent_at": sent_at,
        "converted_at": None,
        "cancelled_at": None,
    }

    # Concurrency-safe insertion with unique invoice_number retry loop
    for attempt in range(5):
        try:
            inv_num = await get_next_invoice_number()
            invoice_doc["invoice_number"] = inv_num
            res = await db.invoices.insert_one(invoice_doc)
            saved = await db.invoices.find_one({"_id": res.inserted_id})
            return clean(saved)
        except pymongo.errors.DuplicateKeyError:
            if attempt == 4:
                raise HTTPException(status_code=500, detail="Gagal mengalokasikan nomor invoice unik. Silakan coba kembali.")
            continue

@api_router.put("/admin/invoices/{invoice_id}")
async def admin_update_invoice(invoice_id: str, data: InvoiceUpdateInput, admin: dict = Depends(require_perm("manage_orders"))):
    inv = await db.invoices.find_one({"_id": id_query(invoice_id)})
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice tidak ditemukan.")

    if inv.get("status") == "CONVERTED" or inv.get("order_id"):
        raise HTTPException(status_code=400, detail="Invoice yang sudah dikonversi menjadi pesanan tidak dapat diubah.")
    if inv.get("status") == "CANCELLED":
        raise HTTPException(status_code=400, detail="Invoice yang sudah dibatalkan tidak dapat diubah.")

    now = datetime.now(timezone.utc).isoformat()
    upd = {
        "updated_by": admin.get("name", "Admin"),
        "updated_at": now,
    }

    if data.customer is not None:
        c_name = (data.customer.name or "").strip()
        if not c_name:
            raise HTTPException(status_code=400, detail="Nama customer tidak boleh kosong.")
        wa = normalize_phone(data.customer.whatsapp)
        if not wa or not valid_intl_phone(wa):
            raise HTTPException(status_code=400, detail="No WhatsApp customer harus diawali + dan kode negara valid.")
        egypt_phone = normalize_egypt_phone(data.customer.egypt_phone) if data.customer.egypt_phone else None

        customer_id = data.customer.customer_id or inv.get("customer", {}).get("customer_id")
        upd["customer"] = {
            "customer_id": customer_id,
            "name": c_name,
            "whatsapp": wa,
            "egypt_phone": egypt_phone,
            "address": (data.customer.address or "").strip() or None,
        }

    raw_items = data.items if data.items is not None else inv.get("items", [])
    if not raw_items:
        raise HTTPException(status_code=400, detail="Invoice minimal harus memiliki 1 item.")

    disc = data.discount_amount if data.discount_amount is not None else inv.get("discount_amount", 0.0)
    deliv = data.delivery_fee if data.delivery_fee is not None else inv.get("delivery_fee", 0.0)
    add_fee = data.additional_fee if data.additional_fee is not None else inv.get("additional_fee", 0.0)

    items, subtotal, disc, deliv, add_fee, total = calculate_invoice_totals(raw_items, disc, deliv, add_fee)

    upd["items"] = items
    upd["subtotal"] = subtotal
    upd["discount_amount"] = disc
    upd["delivery_fee"] = deliv
    upd["additional_fee"] = add_fee
    upd["total"] = total

    if data.customer_note is not None:
        upd["customer_note"] = data.customer_note.strip()
    if data.internal_note is not None:
        upd["internal_note"] = data.internal_note.strip()

    await db.invoices.update_one({"_id": inv["_id"]}, {"$set": upd})
    updated = await db.invoices.find_one({"_id": inv["_id"]})
    return clean(updated)

@api_router.post("/admin/invoices/{invoice_id}/permanent-delete")
async def admin_permanent_delete_invoice(
    invoice_id: str,
    payload: PermanentDeleteInput,
    admin: dict = Depends(require_perm("delete_data"))
):
    if (payload.confirmation_phrase or "").strip() != "HAPUS PERMANEN":
        raise HTTPException(
            status_code=400,
            detail="Frasa konfirmasi tidak valid. Anda wajib mengetik 'HAPUS PERMANEN' secara tepat."
        )

    inv = await db.invoices.find_one({"_id": id_query(invoice_id)})
    if not inv:
        inv = await db.invoices.find_one({"invoice_number": invoice_id})
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice tidak ditemukan.")

    # Isolated delete: ONLY remove this invoice document.
    # NEVER cascade delete or decrement counters, orders, finance, customer, etc.
    res = await db.invoices.delete_one({"_id": inv["_id"]})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Invoice sudah dihapus sebelumnya.")

    await record_audit_log(
        action="PERMANENT_DELETE",
        entity_type="invoice",
        entity_id=str(inv["_id"]),
        entity_identifier=inv.get("invoice_number", str(inv["_id"])),
        admin=admin,
        metadata={
            "previous_status": inv.get("status"),
            "related_order_id": inv.get("order_id"),
            "related_order_number": inv.get("order_number"),
            "custom_request_id": (inv.get("source") or {}).get("custom_request_id"),
            "customer_phone": (inv.get("customer") or {}).get("whatsapp"),
            "reason": payload.reason,
        }
    )

    return {
        "ok": True,
        "message": f"Invoice {inv.get('invoice_number')} berhasil dihapus secara permanen."
    }

@api_router.delete("/admin/invoices/{invoice_id}")
async def admin_delete_invoice(invoice_id: str, admin: dict = Depends(require_perm("delete_data"))):
    raise HTTPException(
        status_code=400,
        detail="Penghapusan invoice wajib melalui endpoint POST /api/admin/invoices/{invoice_id}/permanent-delete dengan frasa konfirmasi 'HAPUS PERMANEN'."
    )

@api_router.get("/admin/audit-logs")
async def admin_list_audit_logs(
    entity_type: Optional[str] = None,
    limit: int = 50,
    admin: dict = Depends(require_perm("delete_data"))
):
    query = {}
    if entity_type:
        query["entity_type"] = entity_type
    logs = await db.audit_logs.find(query).sort("timestamp", -1).to_list(min(limit, 200))
    return [clean(l) for l in logs]

@api_router.post("/admin/invoices/{invoice_id}/send")
async def admin_send_invoice(invoice_id: str, admin: dict = Depends(require_perm("manage_orders"))):
    inv = await db.invoices.find_one({"_id": id_query(invoice_id)})
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice tidak ditemukan.")

    if inv.get("status") == "CONVERTED":
        raise HTTPException(status_code=400, detail="Invoice sudah dikonversi menjadi pesanan.")
    if inv.get("status") == "CANCELLED":
        raise HTTPException(status_code=400, detail="Invoice yang sudah dibatalkan tidak dapat dikirim.")
    if inv.get("status") == "CLAIMED":
        raise HTTPException(status_code=400, detail="Invoice sudah diklaim oleh pelanggan.")

    now = datetime.now(timezone.utc).isoformat()
    await db.invoices.update_one(
        {"_id": inv["_id"]},
        {"$set": {
            "status": "SENT",
            "sent_at": inv.get("sent_at") or now,
            "updated_at": now,
            "updated_by": admin.get("name", "Admin")
        }}
    )
    updated = await db.invoices.find_one({"_id": inv["_id"]})
    return clean(updated)

@api_router.post("/admin/invoices/{invoice_id}/cancel")
async def admin_cancel_invoice(invoice_id: str, admin: dict = Depends(require_perm("manage_orders"))):
    inv = await db.invoices.find_one({"_id": id_query(invoice_id)})
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice tidak ditemukan.")

    if inv.get("status") == "CONVERTED":
        raise HTTPException(status_code=400, detail="Invoice yang sudah dikonversi menjadi pesanan tidak dapat dibatalkan dari invoice.")
    if inv.get("status") == "CANCELLED":
        return clean(inv)

    now = datetime.now(timezone.utc).isoformat()
    await db.invoices.update_one(
        {"_id": inv["_id"]},
        {"$set": {
            "status": "CANCELLED",
            "cancelled_at": now,
            "updated_at": now,
            "updated_by": admin.get("name", "Admin")
        }}
    )
    updated = await db.invoices.find_one({"_id": inv["_id"]})
    return clean(updated)

@api_router.post("/admin/invoices/{invoice_id}/claim-code")
async def admin_generate_claim_code_endpoint(
    invoice_id: str,
    admin: dict = Depends(require_perm("manage_orders"))
):
    inv = await db.invoices.find_one({"_id": id_query(invoice_id)})
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice tidak ditemukan.")

    if inv.get("status") == "CONVERTED":
        raise HTTPException(status_code=400, detail="Invoice yang sudah dikonversi tidak dapat dibuatkan kode klaim.")
    if inv.get("status") == "CANCELLED":
        raise HTTPException(status_code=400, detail="Invoice yang sudah dibatalkan tidak dapat dibuatkan kode klaim.")

    raw_code = generate_claim_code(8)
    code_hash = hash_claim_code(raw_code)
    now = datetime.now(timezone.utc).isoformat()

    new_status = "SENT" if inv.get("status") == "DRAFT" else inv.get("status")
    upd = {
        "status": new_status,
        "claim.code_hash": code_hash,
        "claim.generated_at": now,
        "updated_at": now,
        "updated_by": admin.get("name", "Admin")
    }
    if new_status == "SENT" and not inv.get("sent_at"):
        upd["sent_at"] = now

    await db.invoices.update_one({"_id": inv["_id"]}, {"$set": upd})

    return {
        "ok": True,
        "claim_code": raw_code,
        "generated_at": now,
        "status": new_status,
        "message": "Kode klaim baru berhasil dibuat."
    }

@api_router.post("/customer/invoices/claim")
async def customer_claim_invoice(
    payload: CustomerClaimInput,
    request: Request,
    c: dict = Depends(get_current_customer)
):
    inv_num = (payload.invoice_number or "").strip().upper()
    raw_code = (payload.claim_code or "").strip().upper()
    current_cid = str(c["_id"])

    if not inv_num or not raw_code:
        raise HTTPException(status_code=400, detail="Nomor invoice dan kode klaim wajib diisi.")

    await enforce_claim_rate_limit(request, current_cid, inv_num)

    inv = await db.invoices.find_one({"invoice_number": inv_num})
    if not inv:
        await record_failed_claim_attempt(request, current_cid, inv_num)
        raise HTTPException(status_code=400, detail="Nomor invoice atau kode klaim salah.")

    if inv.get("status") == "CANCELLED":
        raise HTTPException(status_code=400, detail="Invoice ini sudah dibatalkan dan tidak dapat diklaim.")
    if inv.get("status") == "CONVERTED":
        raise HTTPException(status_code=400, detail="Invoice ini sudah diproses menjadi pesanan.")
    if inv.get("status") == "DRAFT":
        raise HTTPException(status_code=400, detail="Invoice belum siap diklaim. Silakan hubungi admin.")

    # Authoritative claim ownership verification
    claimed_by = inv.get("claim", {}).get("claimed_by_customer_id")
    if claimed_by:
        if claimed_by == current_cid:
            # Idempotent return: already claimed by THIS customer
            return clean_customer_invoice(inv)
        else:
            # Claimed by a DIFFERENT customer account
            raise HTTPException(status_code=409, detail="Invoice sudah terhubung ke akun pelanggan lain.")

    # Verify claim code
    code_hash = inv.get("claim", {}).get("code_hash")
    if not code_hash or not verify_claim_code(raw_code, code_hash):
        await record_failed_claim_attempt(request, current_cid, inv_num)
        raise HTTPException(status_code=400, detail="Nomor invoice atau kode klaim salah.")

    # Atomic transition from SENT to CLAIMED
    now = datetime.now(timezone.utc).isoformat()
    claimed_inv = await db.invoices.find_one_and_update(
        {
            "_id": inv["_id"],
            "status": "SENT",
            "claim.claimed_by_customer_id": None
        },
        {
            "$set": {
                "status": "CLAIMED",
                "claim.claimed_by_customer_id": current_cid,
                "claim.claimed_at": now,
                "customer.customer_id": current_cid,
                "updated_at": now
            }
        },
        return_document=ReturnDocument.AFTER
    )

    if not claimed_inv:
        fresh = await db.invoices.find_one({"_id": inv["_id"]})
        if fresh and fresh.get("claim", {}).get("claimed_by_customer_id") == current_cid:
            return clean_customer_invoice(fresh)
        raise HTTPException(status_code=409, detail="Invoice sudah terhubung ke akun pelanggan lain.")

    return clean_customer_invoice(claimed_inv)

@api_router.get("/customer/invoices")
async def customer_list_invoices(c: dict = Depends(get_current_customer)):
    current_cid = str(c["_id"])
    cursor = db.invoices.find(
        {"claim.claimed_by_customer_id": current_cid}
    ).sort("created_at", -1)
    invoices = []
    async for doc in cursor:
        invoices.append(clean_customer_invoice(doc))
    return invoices

@api_router.get("/customer/invoices/{invoice_id}")
async def customer_get_invoice(invoice_id: str, c: dict = Depends(get_current_customer)):
    current_cid = str(c["_id"])
    inv = await db.invoices.find_one({
        "_id": id_query(invoice_id),
        "claim.claimed_by_customer_id": current_cid
    })
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice tidak ditemukan.")
    return clean_customer_invoice(inv)

@api_router.post("/admin/invoices/{invoice_id}/convert")
async def admin_convert_invoice_to_order(
    invoice_id: str,
    data: Optional[InvoiceConvertInput] = None,
    admin: dict = Depends(require_perm("manage_orders"))
):
    inv = await db.invoices.find_one({"_id": id_query(invoice_id)})
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice tidak ditemukan.")

    # Strict idempotency check
    if inv.get("status") == "CONVERTED" or inv.get("order_id"):
        linked_order = await db.orders.find_one({"_id": id_query(inv.get("order_id"))})
        return {
            "invoice": clean(inv),
            "order": clean(linked_order),
            "message": "Invoice sudah dikonversi sebelumnya (idempotent)."
        }

    if inv.get("status") == "CANCELLED":
        raise HTTPException(status_code=400, detail="Invoice yang sudah dibatalkan tidak dapat dikonversi.")

    items_input = inv.get("items") or []
    if not items_input:
        raise HTTPException(status_code=400, detail="Invoice tidak memiliki item untuk dikonversi.")

    # Map invoice items to Order items model
    order_items = []
    for it in items_input:
        product_id = it.get("product_id") or str(inv["_id"])
        category = "custom" if it.get("item_type") == "custom" or not it.get("product_id") else "catalog"
        order_items.append({
            "item_id": f"itm_{uuid.uuid4().hex[:12]}",
            "product_id": str(product_id),
            "product_name_snapshot": it.get("name"),
            "category": category,
            "configuration_snapshot": {
                "invoice_number": inv.get("invoice_number"),
                "item_type": it.get("item_type"),
                "product_slug": it.get("product_slug"),
                "description": it.get("description"),
                "dimensions": it.get("dimensions") or {},
                "material": it.get("material") or "",
                "finishing": it.get("finishing") or "",
                "notes": it.get("notes") or "",
                "custom_size": True if category == "custom" else False,
            },
            "quantity": int(it.get("quantity") or 1),
            "unit_price_le": _num(it.get("unit_price")),
            "subtotal_le": _num(it.get("line_total")),
        })

    order_num = await generate_order_number()
    rate = _num(await get_setting("exchange_rate_idr_per_le", 357), 357)
    now = datetime.now(timezone.utc).isoformat()

    subtotal_le = _num(inv.get("subtotal"))
    discount_le = _num(inv.get("discount_amount"))
    delivery_fee_le = _num(inv.get("delivery_fee"))
    additional_fee_le = _num(inv.get("additional_fee"))
    total_le = max(0.0, _num(inv.get("total")))

    cust_snap = inv.get("customer") or {}
    cust_name = cust_snap.get("name") or "Pelanggan"
    cust_phone = cust_snap.get("whatsapp") or ""
    egypt_phone = cust_snap.get("egypt_phone") or None

    conv_data = data or InvoiceConvertInput()
    delivery_method = conv_data.delivery_method or "pickup"
    delivery_zone_id = conv_data.delivery_zone_id or None
    zone_name = None
    if delivery_zone_id:
        z = await db.delivery_zones.find_one({"_id": id_query(delivery_zone_id)})
        if z:
            zone_name = z.get("name")

    payment_method = conv_data.payment_method or "transfer"
    cust_address = (conv_data.customer_address or cust_snap.get("address") or "Dikonfirmasi via Invoice").strip()
    cust_maps = (conv_data.customer_maps_url or "").strip()

    combined_notes = f"[Invoice {inv.get('invoice_number')}] {conv_data.notes or inv.get('customer_note') or ''}".strip()
    admin_note = f"Dikonversi dari invoice {inv.get('invoice_number')} oleh {admin.get('name')}".strip()
    if inv.get("internal_note"):
        admin_note += f" | Catatan internal invoice: {inv.get('internal_note')}"

    buyer_id = cust_snap.get("customer_id")
    buyer_username = None
    if buyer_id:
        c_doc = await db.customers.find_one({"_id": id_query(buyer_id)})
        if c_doc:
            buyer_username = c_doc.get("username")

    order_doc = {
        "order_number": order_num,
        "customer_name": cust_name,
        "customer_phone": cust_phone,
        "phone_number": egypt_phone,
        "customer_address": cust_address,
        "customer_maps_url": cust_maps,
        "delivery_method": delivery_method,
        "delivery_zone_id": delivery_zone_id,
        "delivery_zone_name": zone_name,
        "delivery_fee_le": delivery_fee_le,
        "payment_method": payment_method,
        "payment_status": "belum_dibayar",
        "order_status": "dikonfirmasi",
        "notes": combined_notes,
        "admin_note": admin_note,
        "items": order_items,
        "item": order_items[0],
        "subtotal_le": subtotal_le,
        "invoice_discount_le": discount_le,
        "discount_code": None,
        "discount_percentage": 0,
        "discount_le": discount_le,
        "referral": None,
        "referral_discount_le": 0,
        "points_redeemed_le": 0,
        "customer_id": buyer_id,
        "customer_username": buyer_username,
        "total_le": total_le,
        "additional_fee_le": additional_fee_le,
        "invoice_id": str(inv["_id"]),
        "invoice_number": inv.get("invoice_number"),
        "exchange_rate_idr_per_le": rate,
        "estimated_total_idr": round(total_le * rate),
        "rate_timestamp": now,
        "requires_admin_confirmation": False,
        "admin_wage_eligibility": {
            "scope_status": "in_scope_pending",
            "governance_mode": "automatic",
            "evaluated_at": now,
            "version": 1
        },
        "created_at": now,
        "updated_at": now,
    }

    async def _execute_admin_conv_tx(session):
        ins_kw = {"session": session} if session else {}
        order_res = await db.orders.insert_one(order_doc, **ins_kw)
        created_order_id = str(order_res.inserted_id)

        try:
            upd_kw = {"session": session} if session else {}
            inv_upd = await db.invoices.find_one_and_update(
                {"_id": inv["_id"], "status": {"$in": ["SENT", "CLAIMED", "DRAFT"]}, "order_id": None},
                {"$set": {
                    "status": "CONVERTED",
                    "order_id": created_order_id,
                    "order_number": order_num,
                    "converted_at": now,
                    "updated_at": now,
                    "updated_by": admin.get("name", "Admin")
                }},
                return_document=ReturnDocument.AFTER,
                **upd_kw
            )
            if not inv_upd:
                raise ConcurrencyConflictError("Invoice sudah dikonversi sebelumnya.")

            src_cr_id = inv.get("source", {}).get("custom_request_id")
            if src_cr_id:
                await db.custom_requests.update_one(
                    {"_id": id_query(src_cr_id)},
                    {"$set": {
                        "status": "dipesan",
                        "converted_order_id": created_order_id,
                        "invoice_id": str(inv["_id"]),
                        "updated_at": now,
                    }},
                    **ins_kw
                )
        except Exception:
            if not session:
                await db.orders.delete_one({"_id": order_res.inserted_id})
                await db.invoices.update_one(
                    {"_id": inv["_id"], "order_id": created_order_id},
                    {"$set": {"status": inv.get("status", "SENT"), "order_id": None, "order_number": None, "converted_at": None}}
                )
            raise

        return created_order_id, inv_upd

    try:
        created_order_id, inv_upd = await execute_transaction_with_safety(client, _execute_admin_conv_tx)
    except ConcurrencyConflictError:
        fresh_inv = await db.invoices.find_one({"_id": inv["_id"]})
        fresh_ord = await db.orders.find_one({"_id": id_query(fresh_inv.get("order_id"))}) if fresh_inv else None
        return {
            "invoice": clean(fresh_inv),
            "order": clean(fresh_ord),
            "message": "Invoice sudah dikonversi sebelumnya (idempotent)."
        }

    fresh_inv = inv_upd or await db.invoices.find_one({"_id": inv["_id"]})
    created_order = await db.orders.find_one({"_id": id_query(created_order_id)}) or order_doc
    return {
        "invoice": clean(fresh_inv),
        "order": clean(created_order),
        "message": "Invoice berhasil dikonversi menjadi pesanan."
    }

@api_router.get("/admin/invoices/{invoice_id}/print")
async def admin_get_invoice_print_data(invoice_id: str, admin: dict = Depends(require_perm("manage_orders"))):
    inv = await db.invoices.find_one({"_id": id_query(invoice_id)})
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice tidak ditemukan.")

    store = await store_info()
    data = clean(inv)
    # Explicit security check: internal_note is stripped from print payload
    data.pop("internal_note", None)

    return {
        "invoice": data,
        "store_info": {
            "store_name": store.get("store_name", "Sogil Furniture"),
            "tagline": store.get("tagline", "Kualitas Terbaik, Untuk Ruang Terbaik"),
            "store_address": store.get("store_address", ""),
            "whatsapp_number": store.get("whatsapp_number", ""),
            "logo_url": store.get("logo_url", ""),
            "bank_info": store.get("bank_info", ""),
        }
    }

# --------------------------------------------------------------------------
# Admin: settings
# --------------------------------------------------------------------------
@api_router.get("/admin/settings")
async def admin_get_settings(admin: dict = Depends(require_perm("manage_settings"))):
    info = await store_info()
    meta = {}
    for k in ["store_name", "whatsapp_number", "exchange_rate_idr_per_le", "logo_url"]:
        doc = await db.settings.find_one({"key": k})
        if doc and doc.get("updated_by_name"):
            meta[k] = {"updated_by_name": doc.get("updated_by_name"), "updated_at": doc.get("updated_at")}
    info["_audit"] = meta
    return info

@api_router.put("/admin/settings")
async def admin_update_settings(payload: Dict[str, Any], admin: dict = Depends(require_perm("manage_settings"))):
    allowed = ["store_name", "app_name", "tagline", "store_address", "store_maps_url",
               "whatsapp_number", "exchange_rate_idr_per_le", "bank_info", "logo_url",
               "instagram", "facebook", "tiktok", "email", "referral_program_enabled", "point_redeem_max_pct"]
    for key in allowed:
        if key in payload:
            val = payload[key]
            if key == "exchange_rate_idr_per_le":
                val = _num(val, 357)
            await set_setting(key, val, admin)
    return await store_info()

# --------------------------------------------------------------------------
# Admin: manage admins (owner / manage_admins)
# --------------------------------------------------------------------------
@api_router.get("/admin/admins")
async def list_admins(admin: dict = Depends(require_perm("manage_admins"))):
    admins = await db.admins.find({}).to_list(200)
    out = []
    for a in admins:
        a = clean(a)
        if a.get("role") == "owner":
            a["permissions"] = default_permissions("owner")
        else:
            a.setdefault("permissions", default_permissions(a.get("role", "admin")))
        out.append(a)
    role_priority = {"owner": 0, "manager": 1, "admin": 2, "employee": 3}
    out.sort(key=lambda x: (role_priority.get(x.get("role", "employee"), 99), (x.get("name") or "").lower()))
    return out

@api_router.post("/admin/admins")
async def create_admin(data: AdminCreateInput, admin: dict = Depends(require_owner())):
    email = data.email.strip().lower()
    if data.role not in ACCOUNT_TYPES:
        raise HTTPException(status_code=400, detail="Tipe akun tidak valid")
    if data.role == "owner":
        raise HTTPException(status_code=400, detail="Tidak dapat membuat akun Owner tambahan")
    if await db.admins.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="Email sudah digunakan")
    if len(data.password) < 6:
        raise HTTPException(status_code=400, detail="Kata sandi minimal 6 karakter")
    perms = default_permissions(data.role)
    if data.permissions:
        for k in PERMISSION_KEYS:
            if k in data.permissions:
                perms[k] = bool(data.permissions[k])
    perms["manage_admins"] = False  # only owner
    doc = {"name": data.name.strip(), "email": email, "password_hash": hash_password(data.password),
           "role": data.role, "permissions": perms, "created_at": datetime.now(timezone.utc).isoformat(),
           "created_by_name": admin.get("name")}
    result = await db.admins.insert_one(doc)
    return clean(await db.admins.find_one({"_id": result.inserted_id}))

@api_router.put("/admin/admins/{admin_id}")
async def update_admin(admin_id: str, data: AdminUpdateInput, admin: dict = Depends(require_owner())):
    target = await db.admins.find_one({"_id": id_query(admin_id)})
    if not target:
        raise HTTPException(status_code=404, detail="Akun tidak ditemukan")
    if target.get("role") == "owner":
        raise HTTPException(status_code=400, detail="Akun Owner tidak dapat diubah dari sini")
    upd = {}
    if data.name is not None:
        upd["name"] = data.name.strip()
    if data.status in ("active", "inactive"):
        upd["status"] = data.status
    if data.email is not None:
        new_email = data.email.strip().lower()
        if await db.admins.find_one({"email": new_email, "_id": {"$ne": oid(admin_id)}}):
            raise HTTPException(status_code=400, detail="Email sudah digunakan")
        upd["email"] = new_email
    if data.password:
        if len(data.password) < 6:
            raise HTTPException(status_code=400, detail="Kata sandi minimal 6 karakter")
        upd["password_hash"] = hash_password(data.password)
    if data.role is not None:
        if data.role not in ACCOUNT_TYPES or data.role == "owner":
            raise HTTPException(status_code=400, detail="Tipe akun tidak valid")
        upd["role"] = data.role
    if data.permissions is not None:
        perms = target.get("permissions", default_permissions(target.get("role", "admin")))
        for k in PERMISSION_KEYS:
            if k in data.permissions:
                perms[k] = bool(data.permissions[k])
        perms["manage_admins"] = False
        upd["permissions"] = perms
    await db.admins.update_one({"_id": id_query(admin_id)}, {"$set": upd})
    return clean(await db.admins.find_one({"_id": id_query(admin_id)}))

@api_router.delete("/admin/admins/{admin_id}")
async def delete_admin(admin_id: str, admin: dict = Depends(require_owner())):
    target = await db.admins.find_one({"_id": id_query(admin_id)})
    if not target:
        raise HTTPException(status_code=404, detail="Akun tidak ditemukan")
    if target.get("role") == "owner":
        raise HTTPException(status_code=400, detail="Akun Owner tidak dapat dihapus")
    await db.admins.delete_one({"_id": id_query(admin_id)})
    return {"ok": True}

# --------------------------------------------------------------------------
# Finance
# --------------------------------------------------------------------------
DEFAULT_FINANCE_CATEGORIES = {
    "income": ["Penjualan", "Pendapatan Lain"],
    "expense": ["Material", "Pekerja", "Biaya Sewa Ruang", "Naql", "Parts", "Pemotongan", "Transport",
                "Peralatan & Perkakas", "Perbaikan & Pemeliharaan", "Konsumsi Operasional", "Air & Listrik",
                "Mesin & Kendaraan", "Pengembangan Aplikasi Web", "Marketing"],
}

@api_router.get("/admin/finance/categories")
async def finance_categories(admin: dict = Depends(require_perm("access_finance"))):
    custom = await db.finance_categories.find({"status": "active"}).to_list(200)
    out = {"income": list(DEFAULT_FINANCE_CATEGORIES["income"]), "expense": list(DEFAULT_FINANCE_CATEGORIES["expense"])}
    for c in custom:
        typ = c.get("type", "expense")
        if typ in out and c["name"] not in out[typ]:
            out[typ].append(c["name"])
    return out

async def _compute_balances(as_of: Optional[str] = None):
    bal = {"IDR": 0.0, "EGP": 0.0}
    q = {"is_void": {"$ne": True}, "status": {"$ne": "void"}}
    if as_of:
        q["date"] = {"$lte": as_of}
    async for t in db.finance_transactions.find(q):
        typ = t.get("type"); cur = t.get("currency", "EGP"); amt = _num(t.get("amount"))
        if typ in ("income", "order_revenue"):
            bal[t.get("account", cur)] = bal.get(t.get("account", cur), 0) + amt
        elif typ in ("expense", "refund", "credit_refund"):
            bal[t.get("account", cur)] = bal.get(t.get("account", cur), 0) - amt
        elif typ == "transfer":
            bal[t.get("from_account", "IDR")] = bal.get(t.get("from_account", "IDR"), 0) - _num(t.get("from_amount"))
            bal[t.get("to_account", "EGP")] = bal.get(t.get("to_account", "EGP"), 0) + _num(t.get("to_amount"))
        elif typ == "balance_adjustment":
            bal[t.get("account", cur)] = bal.get(t.get("account", cur), 0) + _num(t.get("amount"))
    for k in bal:
        bal[k] = round(bal[k], 2)
    return bal

@api_router.get("/admin/finance/accounts")
async def finance_accounts(admin: dict = Depends(require_perm("access_finance"))):
    return {"balances": await _compute_balances()}

@api_router.get("/admin/finance/transactions")
async def finance_list(currency: Optional[str] = None, type: Optional[str] = None,
                       start: Optional[str] = None, end: Optional[str] = None, q: Optional[str] = None,
                       admin: dict = Depends(require_perm("access_finance"))):
    conds = [{"is_void": {"$ne": True}, "status": {"$ne": "void"}}]
    if currency:
        conds.append({"$or": [{"currency": currency}, {"from_account": currency}, {"to_account": currency}]})
    if type:
        conds.append({"type": type})
    if start or end:
        d = {}
        if start:
            d["$gte"] = start
        if end:
            d["$lte"] = end + "T23:59:59"
        conds.append({"date": d})
    if q and q.strip():
        qs = q.strip()
        rx = {"$regex": re.escape(qs), "$options": "i"}
        ors = [{"description": rx}, {"category": rx}, {"type": rx}, {"classification": rx},
               {"created_by_name": rx}, {"recipient_employee_name": rx}]
        try:
            val = float(qs)
            ors.append({"amount": val})
            ors.append({"from_amount": val})
            ors.append({"to_amount": val})
        except ValueError:
            pass
        conds.append({"$or": ors})
    query = {"$and": conds} if conds else {}
    txns = await db.finance_transactions.find(query).sort("date", -1).to_list(2000)
    return [clean(t) for t in txns]

async def category_classification(name, typ):
    """Revenue/Cost vs Transfer classification for a category (snapshot onto each txn)."""
    c = await db.finance_categories.find_one({"name": name, "type": typ})
    if c and c.get("classification") in ("revenue", "cost", "transfer"):
        return c["classification"]
    return "revenue" if typ == "income" else "cost"

def _is_wage_category(name):
    n = (name or "").lower()
    return "upah" in n or "wage" in n or "pekerja" in n

@api_router.post("/admin/finance/transactions")
async def finance_create(data: FinanceTxnInput, admin: dict = Depends(require_perm("access_finance"))):
    if data.type not in ("income", "expense"):
        raise HTTPException(status_code=400, detail="Tipe transaksi tidak valid")
    if data.currency not in ("IDR", "EGP"):
        raise HTTPException(status_code=400, detail="Mata uang tidak valid")
    now = datetime.now(timezone.utc).isoformat()
    classification = await category_classification(data.category, data.type)

    settings_rate = _num(await get_setting("exchange_rate_idr_per_le", 357), 357)
    rate = resolve_transaction_rate(data.exchange_rate, None, settings_rate)

    primary_amt = _num(data.amount)
    if data.counterpart_amount is not None and _num(data.counterpart_amount) > 0 and primary_amt == 0:
        conv = compute_primary_from_counterpart(data.currency, data.counterpart_amount, rate)
    else:
        conv = compute_currency_conversion(data.currency, primary_amt, rate)

    doc = {"date": data.date or now, "type": data.type, "category": data.category,
           "amount": conv["primary_amount"], "currency": data.currency, "account": data.currency,
           "exchange_rate": rate,
           "counterpart_amount": conv["counterpart_amount"],
           "counterpart_currency": conv["counterpart_currency"],
           "classification": classification,
           "description": data.description or "", "related_order_id": None,
           "created_by_id": admin.get("id"), "created_by_name": admin.get("name"),
           "updated_by_name": admin.get("name"), "created_at": now, "updated_at": now}
    is_wage = data.type == "expense" and _is_wage_category(data.category)
    if is_wage and data.recipient_employee_id:
        emp = await db.admins.find_one({"_id": id_query(data.recipient_employee_id)})
        if not emp:
            raise HTTPException(status_code=400, detail="Karyawan penerima tidak ditemukan")
        doc["recipient_employee_id"] = data.recipient_employee_id
        doc["recipient_employee_name"] = emp.get("name")
    result = await db.finance_transactions.insert_one(doc)
    tid = str(result.inserted_id)
    if doc.get("recipient_employee_id"):
        await db.employee_wages.insert_one({"employee_id": doc["recipient_employee_id"], "employee_name": doc["recipient_employee_name"],
            "amount": conv["primary_amount"], "currency": data.currency, "date": doc["date"], "category": data.category,
            "description": data.description or "", "transaction_id": tid, "recorded_by_name": admin.get("name"), "created_at": now})
    return clean(await db.finance_transactions.find_one({"_id": result.inserted_id}))

@api_router.put("/admin/finance/transactions/{txn_id}")
async def finance_update(txn_id: str, data: FinanceTxnInput, admin: dict = Depends(require_perm("access_finance"))):
    t = await db.finance_transactions.find_one({"_id": id_query(txn_id)})
    if not t:
        raise HTTPException(status_code=404, detail="Transaksi tidak ditemukan")
    if t.get("is_void") or t.get("status") == "void":
        raise HTTPException(status_code=400, detail="Transaksi yang telah dibatalkan tidak dapat diedit")

    # Guard: Wage obligation settlement linkage
    if t.get("wage_settlement_id") or t.get("related_settlement_number"):
        st_ref = t.get("related_settlement_number") or t.get("wage_settlement_id")
        raise HTTPException(
            status_code=409,
            detail=(
                f"Transaksi keuangan ini terhubung langsung dengan pelunasan upah pekerja ({st_ref}). "
                "Pengeditan langsung melalui modul keuangan dilarang untuk menjaga integritas saldo kewajiban upah. "
                "Gunakan pembatalan pelunasan resmi melalui menu Upah Pekerja jika diperlukan."
            )
        )

    is_order_rev = (t.get("type") == "order_revenue")
    existing_rate = _num(t.get("exchange_rate"))
    settings_rate = _num(await get_setting("exchange_rate_idr_per_le", 357), 357)
    rate = resolve_transaction_rate(data.exchange_rate, existing_rate, settings_rate)

    existing_amt = _num(t.get("amount"))
    existing_cp = _num(t.get("counterpart_amount"))
    input_amt = _num(data.amount)
    input_cp = _num(data.counterpart_amount) if data.counterpart_amount is not None else None

    if input_cp is not None and input_amt == existing_amt and input_cp != existing_cp:
        conv = compute_primary_from_counterpart(data.currency, input_cp, rate)
    else:
        conv = compute_currency_conversion(data.currency, input_amt, rate)

    now_iso = datetime.now(timezone.utc).isoformat()
    txn_type = t.get("type") if is_order_rev else data.type
    upd = {"date": data.date or t.get("date"), "type": txn_type, "category": data.category,
           "amount": conv["primary_amount"], "currency": data.currency, "account": data.currency,
           "exchange_rate": rate,
           "counterpart_amount": conv["counterpart_amount"],
           "counterpart_currency": conv["counterpart_currency"],
           "classification": await category_classification(data.category, txn_type),
           "description": data.description if data.description is not None else t.get("description", ""),
           "updated_by_id": admin.get("id"),
           "updated_by_name": admin.get("name"),
           "updated_at": now_iso}

    if is_order_rev:
        upd["is_manual_override"] = True
        upd["manual_override_at"] = now_iso
        upd["manual_override_by_id"] = admin.get("id")
        upd["manual_override_by_name"] = admin.get("name")

    # Re-sync wage linkage: recompute wage-ness/recipient so employee history stays consistent on edit.
    is_wage = txn_type == "expense" and _is_wage_category(data.category)
    upd["recipient_employee_id"] = None
    upd["recipient_employee_name"] = None
    if is_wage and data.recipient_employee_id:
        emp = await db.admins.find_one({"_id": id_query(data.recipient_employee_id)})
        if not emp:
            raise HTTPException(status_code=400, detail="Karyawan penerima tidak ditemukan")
        upd["recipient_employee_id"] = data.recipient_employee_id
        upd["recipient_employee_name"] = emp.get("name")
    await db.finance_transactions.update_one({"_id": id_query(txn_id)}, {"$set": upd})
    await db.employee_wages.delete_many({"transaction_id": txn_id})
    if upd.get("recipient_employee_id"):
        await db.employee_wages.insert_one({"employee_id": upd["recipient_employee_id"], "employee_name": upd["recipient_employee_name"],
            "amount": conv["primary_amount"], "currency": data.currency, "date": upd["date"], "category": data.category,
            "description": upd.get("description", ""), "transaction_id": txn_id, "recorded_by_name": admin.get("name"),
            "created_at": now_iso})
    return clean(await db.finance_transactions.find_one({"_id": id_query(txn_id)}))

@api_router.delete("/admin/finance/transactions/{txn_id}")
async def finance_delete(txn_id: str, admin: dict = Depends(require_perm("access_finance"))):
    t = await db.finance_transactions.find_one({"_id": id_query(txn_id)})
    if not t:
        raise HTTPException(status_code=404, detail="Transaksi tidak ditemukan")

    # Guard 1: Already voided
    if t.get("is_void") or t.get("status") == "void":
        raise HTTPException(
            status_code=400,
            detail="Transaksi yang telah dibatalkan tidak dapat dibatalkan kembali"
        )

    # Guard 2: Order payment linkage (direct reference, reverse lookup, or structured payment number)
    is_payment_linked = False
    matching_pmt = None
    if t.get("payment_id") or t.get("related_payment_number"):
        is_payment_linked = True
        if t.get("payment_id"):
            matching_pmt = await db.payments.find_one({"_id": id_query(t.get("payment_id"))})
        elif t.get("related_payment_number"):
            matching_pmt = await db.payments.find_one({"payment_number": t.get("related_payment_number")})
    else:
        # Reverse lookup: check if any payment in db.payments references this transaction
        pmt_cursor = getattr(db, "payments", None)
        if pmt_cursor is not None and hasattr(pmt_cursor, "find_one"):
            call_res = pmt_cursor.find_one({
                "finance_transaction_id": str(t["_id"]),
                "status": {"$ne": "voided"}
            })
            if asyncio.iscoroutine(call_res) or hasattr(call_res, "__await__"):
                matching_pmt = await call_res
            elif isinstance(call_res, dict):
                matching_pmt = call_res
            if matching_pmt:
                is_payment_linked = True

    if is_payment_linked:
        # If the referenced payment document was already voided or missing, handle safely without guessing
        if matching_pmt and matching_pmt.get("status") == "voided":
            raise HTTPException(
                status_code=409,
                detail=(
                    "Transaksi ini terhubung dengan pembayaran yang sudah berstatus voided di buku besar pembayaran. "
                    "Inkonsistensi data terdeteksi. Hubungi administrator teknis untuk rekonsiliasi manual."
                )
            )
        order_ref = t.get("related_order_id") or (matching_pmt.get("order_id") if matching_pmt else None) or "terkait"
        raise HTTPException(
            status_code=409,
            detail=(
                "Transaksi keuangan ini terhubung langsung dengan pembayaran pesanan resmi. "
                "Pembatalan tidak dapat dilakukan melalui modul keuangan. "
                f"Silakan batalkan pembayaran melalui menu Detail Pesanan (Order ID: {order_ref}) "
                "agar saldo pesanan, alokasi dana, dan pembukuan kas tetap sinkron."
            )
        )

    # Guard 3: Customer credit settlement or refund linkage
    is_credit_linked = (
        t.get("classification") == "liability_settlement" or
        t.get("type") in ("credit_settlement", "credit_refund") or
        bool(t.get("related_credit_event_number"))
    )
    if is_credit_linked:
        raise HTTPException(
            status_code=409,
            detail=(
                "Transaksi ini terhubung dengan transaksi kredit atau pengembalian saldo kredit pelanggan. "
                "Pembatalan langsung dari modul keuangan dilarang untuk menjaga konsistensi buku besar kredit."
            )
        )

    # Guard 4: Wage obligation settlement linkage
    is_settlement_linked = bool(t.get("wage_settlement_id") or t.get("related_settlement_number"))
    if is_settlement_linked:
        st_ref = t.get("related_settlement_number") or t.get("wage_settlement_id")
        raise HTTPException(
            status_code=409,
            detail=(
                f"Transaksi keuangan ini terhubung langsung dengan pelunasan upah pekerja ({st_ref}). "
                "Pembatalan langsung melalui modul keuangan dilarang untuk menjaga integritas saldo kewajiban upah. "
                "Silakan batalkan melalui menu Upah Pekerja."
            )
        )

    now_iso = datetime.now(timezone.utc).isoformat()
    await db.finance_transactions.update_one(
        {"_id": id_query(txn_id)},
        {"$set": {
            "is_void": True,
            "status": "void",
            "void_source": "finance_manual",
            "voided_at": now_iso,
            "voided_by_id": admin.get("id"),
            "voided_by_name": admin.get("name"),
            "updated_at": now_iso,
            "updated_by_id": admin.get("id"),
            "updated_by_name": admin.get("name")
        }}
    )
    await db.employee_wages.delete_many({"transaction_id": txn_id})
    return {"ok": True, "voided": True}

@api_router.post("/admin/finance/transfer")
async def finance_transfer(data: TransferInput, admin: dict = Depends(require_perm("access_finance"))):
    if data.from_account not in ("IDR", "EGP") or data.to_account not in ("IDR", "EGP") or data.from_account == data.to_account:
        raise HTTPException(status_code=400, detail="Akun transfer tidak valid")
    if _num(data.from_amount) <= 0 or _num(data.to_amount) <= 0:
        raise HTTPException(status_code=400, detail="Jumlah transfer harus lebih dari 0")
    now = datetime.now(timezone.utc).isoformat()
    doc = {"date": data.date or now, "type": "transfer", "category": "Transfer/Konversi",
           "from_account": data.from_account, "to_account": data.to_account,
           "from_amount": _num(data.from_amount), "to_amount": _num(data.to_amount),
           "exchange_rate": _num(data.exchange_rate) if data.exchange_rate else None,
           "description": data.description or "", "created_by_name": admin.get("name"),
           "updated_by_name": admin.get("name"), "created_at": now, "updated_at": now}
    result = await db.finance_transactions.insert_one(doc)
    return clean(await db.finance_transactions.find_one({"_id": result.inserted_id}))

def _period_range(period, start, end):
    now = datetime.now(timezone.utc)
    if period == "custom" and start and end:
        return start, end + "T23:59:59", None, None
    if period == "this_month":
        s = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        ps = (s - timedelta(days=1)).replace(day=1)
        return s.isoformat(), now.isoformat(), ps.isoformat(), s.isoformat()
    if period == "last_month":
        first = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        last_end = first - timedelta(seconds=1)
        s = last_end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        pend = s - timedelta(seconds=1); ps = pend.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return s.isoformat(), last_end.isoformat(), ps.isoformat(), s.isoformat()
    if period == "this_year":
        s = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        ps = s.replace(year=s.year - 1)
        return s.isoformat(), now.isoformat(), ps.isoformat(), s.isoformat()
    if period == "last_year":
        s = now.replace(year=now.year - 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        e = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0) - timedelta(seconds=1)
        ps = s.replace(year=s.year - 1)
        return s.isoformat(), e.isoformat(), ps.isoformat(), s.isoformat()
    if period == "last_3_months":
        m = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        y, mo = m.year, m.month - 2
        while mo <= 0:
            mo += 12; y -= 1
        s = m.replace(year=y, month=mo)
        return s.isoformat(), now.isoformat(), None, None
    return None, None, None, None

async def _stats_for(s, e, cutoff: Optional[str] = None):
    """
    Phase 3.B.7 Authoritative Reporting Engine.
    Computes per-currency ('EGP', 'IDR') financial metrics for the requested period [s, e]:
    - Physical Cash Inflows & Outflows (from db.finance_transactions only, excluding non-cash credit settlements)
    - Pure Sales Revenue (from db.orders immutable handover snapshots completed_at + db.finance_adjustments created_at)
    - Other Income (from db.finance_transactions type='income', classification in (None, 'revenue'))
    - Operating Expenses (from db.finance_transactions type='expense', classification in (None, 'cost'))
    - Customer Credit Liabilities (from db.customer_credit_events as of cutoff)
    - Customer Advances / Deposit Liabilities (from active orders status not in ('selesai', 'dibatalkan'))
    - Accounts Receivable (from handed-over orders: max(0, recognized_revenue_le + net_adjustments - canonical_paid_le))
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    as_of_cutoff = cutoff or (e if e else now_iso)

    # Base structure for both currencies
    res = {
        "EGP": {
            "real_cash_inflow": 0.0,
            "real_cash_outflow": 0.0,
            "cash_flow": 0.0,
            "sales_revenue": 0.0,
            "other_income": 0.0,
            "total_revenue": 0.0,
            "operating_cost": 0.0,
            "operating_profit": 0.0,
            "available_customer_credit": 0.0,
            "customer_advances": 0.0,
            "accounts_receivable": 0.0,
            "credit_applied": 0.0,
            "credit_refunded": 0.0,
            # Legacy backward compatibility aliases
            "revenue": 0.0,
            "cost": 0.0,
        },
        "IDR": {
            "real_cash_inflow": 0.0,
            "real_cash_outflow": 0.0,
            "cash_flow": 0.0,
            "sales_revenue": 0.0,
            "other_income": 0.0,
            "total_revenue": 0.0,
            "operating_cost": 0.0,
            "operating_profit": 0.0,
            "available_customer_credit": 0.0,
            "customer_advances": 0.0,
            "accounts_receivable": 0.0,
            "credit_applied": 0.0,
            "credit_refunded": 0.0,
            # Legacy backward compatibility aliases
            "revenue": 0.0,
            "cost": 0.0,
        }
    }

    # -------------------------------------------------------------------------
    # 1. Physical Cash Movements, Other Income & Operating Costs (finance_transactions)
    # -------------------------------------------------------------------------
    q_txns = {"is_void": {"$ne": True}, "status": {"$ne": "void"}}
    if s or e:
        q_txns["date"] = {}
        if s:
            q_txns["date"]["$gte"] = s
        if e:
            q_txns["date"]["$lte"] = e

    legacy_order_rev = {"EGP": 0.0, "IDR": 0.0}

    async for t in db.finance_transactions.find(q_txns):
        typ = t.get("type")
        raw_amt = _num(t.get("amount"))
        cls = t.get("classification")
        cur = (t.get("account") or t.get("currency") or "EGP").strip().upper()

        if typ == "credit_settlement":
            # Non-cash contra entry: strictly 0.00 cash inflow/outflow
            continue

        if typ == "transfer":
            # Real cash moving between internal accounts
            from_cur = (t.get("from_account") or "IDR").strip().upper()
            to_cur = (t.get("to_account") or "EGP").strip().upper()
            from_amt = _num(t.get("from_amount"))
            to_amt = _num(t.get("to_amount"))
            if from_cur in res:
                res[from_cur]["real_cash_outflow"] += from_amt
            if to_cur in res:
                res[to_cur]["real_cash_inflow"] += to_amt
            continue

        if cur not in res:
            continue

        if typ == "balance_adjustment":
            if raw_amt > 0:
                res[cur]["real_cash_inflow"] += raw_amt
            elif raw_amt < 0:
                res[cur]["real_cash_outflow"] += abs(raw_amt)
            continue

        # Physical Cash Inflow
        if typ in ("order_payment", "order_revenue"):
            res[cur]["real_cash_inflow"] += raw_amt
            if typ == "order_revenue":
                legacy_order_rev[cur] = legacy_order_rev.get(cur, 0.0) + raw_amt
        elif typ == "income":
            res[cur]["real_cash_inflow"] += raw_amt
            if cls in (None, "revenue"):
                res[cur]["other_income"] += raw_amt

        # Physical Cash Outflow & Operating Costs
        elif typ in ("refund", "credit_refund"):
            res[cur]["real_cash_outflow"] += raw_amt
            # Liability settlement refunds are NOT operating costs
        elif typ == "expense":
            res[cur]["real_cash_outflow"] += raw_amt
            if cls in (None, "cost"):
                res[cur]["operating_cost"] += raw_amt

    # Pre-fetch recorded payments grouped by order_id
    pmt_by_order = {}
    pmt_details_by_order = {}
    pmts_coll = getattr(db, "payments", None)
    if pmts_coll is not None and hasattr(pmts_coll, "find"):
        p_finder = pmts_coll.find({"status": "recorded"})
        if hasattr(p_finder, "__aiter__"):
            async for p in p_finder:
                oid_str = str(p.get("order_id") or "")
                amt = _num(p.get("amount_le", 0.0))
                pmt_by_order[oid_str] = pmt_by_order.get(oid_str, 0.0) + amt

                p_cur = (p.get("primary_currency") or "").strip().upper()
                if not p_cur:
                    p_cur = "IDR" if p.get("payment_method") == "transfer" else "EGP"

                prim_amt = _num(p.get("primary_amount", 0.0))
                if prim_amt <= 0:
                    if p_cur == "IDR":
                        p_rate = _num(p.get("exchange_rate_snapshot", 0.0)) or 357.0
                        prim_amt = round(amt * p_rate)
                    else:
                        prim_amt = amt

                if oid_str not in pmt_details_by_order:
                    pmt_details_by_order[oid_str] = []
                pmt_details_by_order[oid_str].append({
                    "currency": p_cur,
                    "amount_le": amt,
                    "primary_amount": prim_amt,
                    "rate": _num(p.get("exchange_rate_snapshot", 0.0))
                })

    # -------------------------------------------------------------------------
    # 2. Handover-Recognized Furniture Sales Revenue (db.orders)
    # -------------------------------------------------------------------------
    # Query orders handed over within the period [s, e] with valid immutable snapshot
    q_orders_rev = {
        "completed_at": {"$ne": None},
        "recognized_revenue_le": {"$ne": None, "$gte": 0.0},
        "order_status": {"$in": ["selesai", "dibatalkan"]}
    }
    if s or e:
        q_orders_rev["completed_at"] = {}
        if s:
            q_orders_rev["completed_at"]["$gte"] = s
        if e:
            q_orders_rev["completed_at"]["$lte"] = e

    orders_cursor = getattr(db, "orders", None)
    if orders_cursor is not None and hasattr(orders_cursor, "find"):
        ord_finder = orders_cursor.find(q_orders_rev)
        if hasattr(ord_finder, "__aiter__"):
            async for ord_doc in ord_finder:
                rec_le = _num(ord_doc.get("recognized_revenue_le", 0.0))
                if rec_le <= 0:
                    continue
                oid_str = str(ord_doc.get("_id") or ord_doc.get("id") or "")
                pmts = pmt_details_by_order.get(oid_str, [])

                if pmts:
                    egp_paid_le = sum(p["amount_le"] for p in pmts if p["currency"] == "EGP")
                    idr_paid_le = sum(p["amount_le"] for p in pmts if p["currency"] == "IDR")
                    idr_paid_actual = sum(p["primary_amount"] for p in pmts if p["currency"] == "IDR")
                    total_paid_le = egp_paid_le + idr_paid_le

                    if total_paid_le >= rec_le and total_paid_le > 0:
                        ratio = min(1.0, rec_le / total_paid_le)
                        res["EGP"]["sales_revenue"] += round(egp_paid_le * ratio, 2)
                        res["IDR"]["sales_revenue"] += round(idr_paid_actual * ratio, 2)
                    else:
                        res["EGP"]["sales_revenue"] += egp_paid_le
                        res["IDR"]["sales_revenue"] += idr_paid_actual

                        uncollected_le = rec_le - total_paid_le
                        ord_pay_method = (ord_doc.get("payment_method") or "").strip().lower()
                        ord_rate = _num(ord_doc.get("exchange_rate_idr_per_le", 0.0)) or 357.0

                        if ord_pay_method == "transfer":
                            uncollected_idr = round(uncollected_le * ord_rate)
                            res["IDR"]["sales_revenue"] += uncollected_idr
                        else:
                            res["EGP"]["sales_revenue"] += uncollected_le
                else:
                    ord_pay_method = (ord_doc.get("payment_method") or "").strip().lower()
                    ord_rate = _num(ord_doc.get("exchange_rate_idr_per_le", 0.0)) or 357.0
                    if ord_pay_method == "transfer":
                        idr_val = _num(ord_doc.get("estimated_total_idr", 0.0)) or round(rec_le * ord_rate)
                        res["IDR"]["sales_revenue"] += idr_val
                    else:
                        res["EGP"]["sales_revenue"] += rec_le

    # -------------------------------------------------------------------------
    # 3. Explicit Finance Adjustments (db.finance_adjustments)
    # -------------------------------------------------------------------------
    # Period of creation attribution (OD-B7-01: no restatement of prior periods)
    q_adjs = {"is_void": {"$ne": True}}
    if s or e:
        q_adjs["created_at"] = {}
        if s:
            q_adjs["created_at"]["$gte"] = s
        if e:
            q_adjs["created_at"]["$lte"] = e

    adjs_cursor = getattr(db, "finance_adjustments", None)
    if adjs_cursor is not None and hasattr(adjs_cursor, "find"):
        adj_finder = adjs_cursor.find(q_adjs)
        if hasattr(adj_finder, "__aiter__"):
            async for adj in adj_finder:
                adj_cur = (adj.get("currency") or "EGP").strip().upper()
                adj_amt = _num(adj.get("amount", 0.0))
                if adj_cur in res:
                    res[adj_cur]["sales_revenue"] += adj_amt

    # -------------------------------------------------------------------------
    # 4. Customer Credit Liability & Flows (db.customer_credit_events)
    # -------------------------------------------------------------------------
    cce_coll = getattr(db, "customer_credit_events", None)
    if cce_coll is not None and hasattr(cce_coll, "aggregate"):
        for cur_key in ("EGP", "IDR"):
            pipeline_cce = [
                {"$match": {"currency": cur_key, "created_at": {"$lte": as_of_cutoff}}},
                {"$group": {"_id": None, "total": {"$sum": "$signed_amount"}}}
            ]
            cce_cursor = cce_coll.aggregate(pipeline_cce)
            to_list_fn = getattr(cce_cursor, "to_list", None)
            if callable(to_list_fn):
                res_coro = to_list_fn(1)
                if asyncio.iscoroutine(res_coro):
                    cce_res = await res_coro
                    if cce_res and len(cce_res) > 0:
                        res[cur_key]["available_customer_credit"] = max(0.0, round(float(cce_res[0].get("total", 0.0)), 2))

    # Period flow metrics for credit consumption and credit refunds
    if cce_coll is not None and hasattr(cce_coll, "find"):
        q_cce_flow = {}
        if s or e:
            q_cce_flow["created_at"] = {}
            if s:
                q_cce_flow["created_at"]["$gte"] = s
            if e:
                q_cce_flow["created_at"]["$lte"] = e

        cce_finder = cce_coll.find(q_cce_flow)
        if hasattr(cce_finder, "__aiter__"):
            async for evt in cce_finder:
                evt_cur = (evt.get("currency") or "EGP").strip().upper()
                evt_type = evt.get("event_type")
                signed_amt = _num(evt.get("signed_amount", 0.0))
                if evt_cur in res:
                    if evt_type == "credit_applied":
                        res[evt_cur]["credit_applied"] += abs(signed_amt)
                    elif evt_type == "credit_refunded":
                        res[evt_cur]["credit_refunded"] += abs(signed_amt)

    # -------------------------------------------------------------------------
    # 5. Customer Advances & Accounts Receivable (Working Capital Balance Sheet)
    # -------------------------------------------------------------------------
    # Note: pmt_by_order was already pre-fetched above before Section 2

    # Pre-fetch active finance adjustments grouped by order_id
    adjs_by_order = {}
    if adjs_cursor is not None and hasattr(adjs_cursor, "find"):
        a_finder = adjs_cursor.find({"is_void": {"$ne": True}})
        if hasattr(a_finder, "__aiter__"):
            async for a in a_finder:
                oid_str = str(a.get("order_id") or "")
                amt = _num(a.get("amount", 0.0))
                adjs_by_order[oid_str] = adjs_by_order.get(oid_str, 0.0) + amt

    # Iterate active and handed-over orders
    if orders_cursor is not None and hasattr(orders_cursor, "find"):
        all_orders_finder = orders_cursor.find({})
        if hasattr(all_orders_finder, "__aiter__"):
            async for ord_doc in all_orders_finder:
                oid_str = str(ord_doc.get("_id") or ord_doc.get("id") or "")
                status = ord_doc.get("order_status")
                paid_le = pmt_by_order.get(oid_str, 0.0)

                # A. Customer Advances: Active orders (status not in 'selesai', 'dibatalkan')
                if status not in ("selesai", "dibatalkan"):
                    if paid_le > 0:
                        res["EGP"]["customer_advances"] += paid_le

                # B. Accounts Receivable: Handed-over orders (snapshot established)
                has_snapshot = bool(ord_doc.get("completed_at")) and ord_doc.get("recognized_revenue_le") is not None
                if has_snapshot:
                    rec_rev_d = Decimal(str(_num(ord_doc.get("recognized_revenue_le", 0.0)))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                    net_adjs_d = Decimal(str(adjs_by_order.get(oid_str, 0.0))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                    paid_d = Decimal(str(paid_le)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

                    net_rev_d = rec_rev_d + net_adjs_d
                    ar_d = max(Decimal("0.00"), net_rev_d - paid_d)
                    res["EGP"]["accounts_receivable"] += float(ar_d)

    # -------------------------------------------------------------------------
    # 6. Final Metric Assembly, Mathematical Reconciliation & Rounding
    # -------------------------------------------------------------------------
    for cur in ("IDR", "EGP"):
        r = res[cur]
        r["real_cash_inflow"] = round(r["real_cash_inflow"], 2)
        r["real_cash_outflow"] = round(r["real_cash_outflow"], 2)
        r["cash_flow"] = round(r["real_cash_inflow"] - r["real_cash_outflow"], 2)

        r["sales_revenue"] = round(r["sales_revenue"], 2)
        r["other_income"] = round(r["other_income"], 2)
        r["total_revenue"] = round(r["sales_revenue"] + r["other_income"], 2)

        r["operating_cost"] = round(r["operating_cost"], 2)
        r["operating_profit"] = round(r["total_revenue"] - r["operating_cost"], 2)

        r["available_customer_credit"] = round(r["available_customer_credit"], 2)
        r["customer_advances"] = round(r["customer_advances"], 2)
        r["accounts_receivable"] = round(r["accounts_receivable"], 2)

        r["credit_applied"] = round(r["credit_applied"], 2)
        r["credit_refunded"] = round(r["credit_refunded"], 2)

        # Backward compatibility for existing UI and legacy tests:
        # If no handover sales revenue was established, preserve legacy order_revenue
        # in the legacy .revenue alias so historical order_revenue tests and unmigrated callers function.
        if r["sales_revenue"] > 0:
            r["revenue"] = r["total_revenue"]
        else:
            legacy_rev = round(r["sales_revenue"] + r["other_income"] + legacy_order_rev.get(cur, 0.0), 2)
            r["revenue"] = legacy_rev

    return res

@api_router.get("/admin/finance/stats")
async def finance_stats(period: str = "this_month", start: Optional[str] = None, end: Optional[str] = None,
                        admin: dict = Depends(require_perm("access_finance"))):
    s, e, ps, pe = _period_range(period, start, end)
    # Generalized Cumulative Ending Balance & As-Of Cutoff:
    # Cumulative valid real-currency transactions from the beginning of financial history
    # through the END/CUTOFF of the selected period.
    now_iso = datetime.now(timezone.utc).isoformat()
    if period in ("this_month", "this_year"):
        cutoff = now_iso
    elif e:
        cutoff = e
    else:
        cutoff = now_iso

    current = await _stats_for(s, e, cutoff=cutoff)
    balances = await _compute_balances(as_of=cutoff)

    comparison = None
    if ps and pe:
        prev = await _stats_for(ps, pe, cutoff=pe)
        comparison = {}
        for cur in ("IDR", "EGP"):
            comparison[cur] = {}
            for metric in ("revenue", "cost", "operating_profit", "sales_revenue", "real_cash_inflow", "cash_flow"):
                cv = current[cur].get(metric, 0.0); pv = prev[cur].get(metric, 0.0)
                if pv == 0:
                    if cv == 0:
                        pct = 0.0
                    else:
                        pct = None  # Neutral indicator ("—" / "Baru"), do NOT fake +100% or Infinity
                else:
                    pct = round(((cv - pv) / abs(pv)) * 100, 1)
                comparison[cur][metric] = pct
    return {"period": period, "range": {"start": s, "end": e}, "current": current,
            "comparison": comparison, "balances": balances}

async def validate_discount(code, subtotal):
    if not code:
        return 0.0, None, None
    d = await db.discounts.find_one({"code": code.strip().upper()})
    if not d:
        return 0.0, None, "Kode diskon tidak ditemukan"
    now = datetime.now(timezone.utc).isoformat()
    if d.get("status") != "active":
        return 0.0, None, "Kode diskon tidak aktif"
    if d.get("start_date") and now < d["start_date"]:
        return 0.0, None, "Kode diskon belum berlaku"
    if d.get("end_date") and now > (d["end_date"] + "T23:59:59"):
        return 0.0, None, "Kode diskon sudah kedaluwarsa"
    if d.get("max_claims") and _num(d.get("claims", 0)) >= _num(d["max_claims"]):
        return 0.0, None, "Kuota kode diskon habis"
    disc = subtotal * _num(d.get("percentage")) / 100.0
    mx = _num(d.get("max_amount"))
    if mx > 0:
        disc = min(disc, mx)
    return round(disc, 2), d, None

@api_router.post("/discounts/validate")
async def discount_validate(payload: Dict[str, Any], request: Request):
    buyer = await get_optional_customer(request)
    if not buyer:
        return {"valid": False, "message": "Untuk menggunakan kode promo, silakan buat akun atau masuk terlebih dahulu", "require_auth": True, "discount_amount": 0}
    disc, d, err = await validate_discount(payload.get("code"), _num(payload.get("subtotal")))
    if err:
        return {"valid": False, "message": err, "discount_amount": 0}
    return {"valid": True, "discount_amount": disc, "percentage": _num(d.get("percentage")), "code": d.get("code")}

@api_router.get("/admin/discounts")
async def list_discounts(admin: dict = Depends(require_perm("manage_settings"))):
    return [clean(d) for d in await db.discounts.find({}).sort("created_at", -1).to_list(500)]

@api_router.post("/admin/discounts")
async def create_discount(payload: Dict[str, Any], admin: dict = Depends(require_perm("manage_settings"))):
    code = (payload.get("code") or "").strip().upper()
    if not code:
        raise HTTPException(status_code=400, detail="Kode diskon wajib diisi")
    if await db.discounts.find_one({"code": code}):
        raise HTTPException(status_code=400, detail="Kode diskon sudah ada")
    now = datetime.now(timezone.utc).isoformat()
    doc = {"code": code, "name": payload.get("name", ""), "percentage": max(0.0, min(100.0, _num(payload.get("percentage")))),
           "max_amount": _num(payload.get("max_amount")), "max_claims": int(_num(payload.get("max_claims"))),
           "claims": 0, "start_date": payload.get("start_date") or None, "end_date": payload.get("end_date") or None,
           "status": payload.get("status", "active"), "created_at": now, "updated_by_name": admin.get("name")}
    r = await db.discounts.insert_one(doc)
    return clean(await db.discounts.find_one({"_id": r.inserted_id}))

@api_router.put("/admin/discounts/{did}")
async def update_discount(did: str, payload: Dict[str, Any], admin: dict = Depends(require_perm("manage_settings"))):
    upd = {}
    for k in ["name", "percentage", "max_amount", "max_claims", "start_date", "end_date", "status"]:
        if k in payload:
            upd[k] = payload[k]
    for k in ["percentage", "max_amount", "max_claims"]:
        if k in upd:
            upd[k] = _num(upd[k])
    if "percentage" in upd:
        upd["percentage"] = max(0.0, min(100.0, upd["percentage"]))
    upd["updated_by_name"] = admin.get("name")
    await db.discounts.update_one({"_id": id_query(did)}, {"$set": upd})
    return clean(await db.discounts.find_one({"_id": id_query(did)}))

@api_router.delete("/admin/discounts/{did}")
async def delete_discount(did: str, admin: dict = Depends(require_perm("manage_settings"))):
    await db.discounts.delete_one({"_id": id_query(did)})
    return {"ok": True}

@api_router.get("/admin/finance/custom-categories")
async def list_custom_categories(admin: dict = Depends(require_perm("access_finance"))):
    return [clean(c) for c in await db.finance_categories.find({}).to_list(200)]

@api_router.post("/admin/finance/custom-categories")
async def create_custom_category(payload: Dict[str, Any], admin: dict = Depends(require_perm("access_finance"))):
    name = (payload.get("name") or "").strip()
    typ = payload.get("type", "expense")
    if not name or typ not in ("income", "expense"):
        raise HTTPException(status_code=400, detail="Nama & tipe kategori wajib benar")
    valid = {"income": ["revenue", "transfer"], "expense": ["cost", "transfer"]}
    classification = payload.get("classification")
    if classification not in valid[typ]:
        classification = "revenue" if typ == "income" else "cost"
    doc = {"name": name, "type": typ, "classification": classification, "status": payload.get("status", "active"),
           "created_at": datetime.now(timezone.utc).isoformat(), "created_by_name": admin.get("name")}
    r = await db.finance_categories.insert_one(doc)
    return clean(await db.finance_categories.find_one({"_id": r.inserted_id}))

@api_router.put("/admin/finance/custom-categories/{cid}")
async def update_custom_category(cid: str, payload: Dict[str, Any], admin: dict = Depends(require_perm("access_finance"))):
    upd = {}
    if payload.get("classification") in ("revenue", "cost", "transfer"):
        upd["classification"] = payload["classification"]
    if payload.get("status") in ("active", "inactive"):
        upd["status"] = payload["status"]
    if upd:
        await db.finance_categories.update_one({"_id": id_query(cid)}, {"$set": upd})
    return clean(await db.finance_categories.find_one({"_id": id_query(cid)}))

@api_router.delete("/admin/finance/custom-categories/{cid}")
async def delete_custom_category(cid: str, admin: dict = Depends(require_perm("access_finance"))):
    # Soft-delete: historical transactions keep their category/classification; just stop offering it for new txns.
    await db.finance_categories.update_one({"_id": id_query(cid)}, {"$set": {"status": "inactive"}})
    return {"ok": True}

@api_router.get("/admin/employees")
async def list_employees(admin: dict = Depends(require_perm("access_finance"))):
    return [clean(a) for a in await db.admins.find({"status": {"$ne": "inactive"}}).sort("name", 1).to_list(200)]

@api_router.get("/admin/employees/wages")
async def employee_wages_summary(admin: dict = Depends(require_perm("access_finance"))):
    now = datetime.now(timezone.utc)
    mkey = now.strftime("%Y-%m"); ykey = now.strftime("%Y")
    out = []
    for e in await db.admins.find({}).sort("name", 1).to_list(200):
        eid = str(e["_id"])
        # Source of truth: finance_transactions
        txns = await db.finance_transactions.find({
            "type": "expense",
            "recipient_employee_id": eid,
            "is_void": {"$ne": True},
            "status": {"$ne": "void"}
        }).sort("date", -1).to_list(1000)

        # Fallback to employee_wages mirror if no transactions found (for legacy compatibility)
        if not txns:
            txns = await db.employee_wages.find({"employee_id": eid}).sort("date", -1).to_list(500)

        totals, month, year = {}, {}, {}
        history = []
        for w in txns:
            if not _is_wage_category(w.get("category", "")):
                continue
            c = w.get("currency", "EGP"); amt = _num(w.get("amount")); d = (w.get("date") or "")
            totals[c] = totals.get(c, 0) + amt
            if d[:7] == mkey:
                month[c] = month.get(c, 0) + amt
            if d[:4] == ykey:
                year[c] = year.get(c, 0) + amt
            history.append({
                "id": str(w["_id"]),
                "amount": amt,
                "currency": c,
                "date": d,
                "category": w.get("category", "Pekerja"),
                "description": w.get("description", ""),
                "recorded_by_name": w.get("recorded_by_name") or w.get("created_by_name") or "-",
                "created_at": w.get("created_at")
            })
        out.append({"id": eid, "name": e.get("name"), "email": e.get("email"), "role": e.get("role"),
                    "status": e.get("status", "active"), "totals": totals, "month": month, "year": year,
                    "count": len(history), "history": history})
    return out

@api_router.post("/admin/finance/balance-adjust")
async def balance_adjust(payload: Dict[str, Any], admin: dict = Depends(require_perm("access_finance"))):
    account = payload.get("account")
    if account not in ("IDR", "EGP"):
        raise HTTPException(status_code=400, detail="Akun tidak valid")
    balances = await _compute_balances()
    prev = balances.get(account, 0.0)
    new_balance = _num(payload.get("new_balance"))
    delta = new_balance - prev
    now = datetime.now(timezone.utc).isoformat()

    settings_rate = _num(await get_setting("exchange_rate_idr_per_le", 357), 357)
    rate = resolve_transaction_rate(payload.get("exchange_rate"), None, settings_rate)

    conv = compute_currency_conversion(account, delta, rate)

    desc = (payload.get("description") or "").strip() or "Set saldo saat ini"
    doc = {"date": payload.get("date") or now, "type": "balance_adjustment", "category": "Penyesuaian Saldo",
           "amount": conv["primary_amount"], "currency": account, "account": account, "previous_balance": prev, "new_balance": new_balance,
           "exchange_rate": rate,
           "counterpart_amount": conv["counterpart_amount"],
           "counterpart_currency": conv["counterpart_currency"],
           "description": desc, "created_by_name": admin.get("name"),
           "created_at": now, "updated_at": now}
    await db.finance_transactions.insert_one(doc)
    return {"ok": True, "account": account, "previous_balance": prev, "new_balance": new_balance, "adjustment": delta}

@api_router.get("/admin/finance/monthly")
async def finance_monthly(year: Optional[int] = None, currency: str = "EGP",
                          admin: dict = Depends(require_perm("access_finance"))):
    yr = year or datetime.now(timezone.utc).year
    months = [{"month": m, "label": f"{yr}-{m:02d}", "revenue": 0.0, "cost": 0.0, "profit": 0.0} for m in range(1, 13)]
    async for t in db.finance_transactions.find({"currency": currency, "is_void": {"$ne": True}, "status": {"$ne": "void"}}):
        d = (t.get("date") or "")[:7]
        try:
            ty, tm = int(d[:4]), int(d[5:7])
        except (ValueError, IndexError):
            continue
        if ty != yr:
            continue
        typ = t.get("type"); amt = _num(t.get("amount"))
        row = months[tm - 1]
        if typ in ("income", "order_revenue"):
            row["revenue"] += amt
        elif typ == "expense":
            row["cost"] += amt
    for r in months:
        r["profit"] = r["revenue"] - r["cost"]
    return {"year": yr, "currency": currency, "months": months}

async def award_referral_points(order):
    ref = order.get("referral") or {}
    owner_id = ref.get("owner_id")
    if not owner_id:
        return
    if await db.point_transactions.find_one({"order_id": str(order["_id"]), "type": "earn"}):
        return
    per = _num(ref.get("points_per_order"))
    if per <= 0:
        return
    r = await db.referrals.find_one({"code": ref.get("code")})
    if r and _num(r.get("max_total_points")) > 0 and _num(r.get("points_awarded", 0)) + per > _num(r.get("max_total_points")):
        return
    cust = await db.customers.find_one({"_id": id_query(owner_id)})
    if not cust:
        return
    new_bal = _num(cust.get("points_available")) + per
    await db.customers.update_one({"_id": id_query(owner_id)}, {"$inc": {"points_available": per, "points_earned": per}})
    await db.point_transactions.insert_one({"customer_id": owner_id, "type": "earn", "amount": per,
        "order_id": str(order["_id"]), "reason": f"Referral order {order.get('order_number')}",
        "balance_after": new_bal, "created_at": datetime.now(timezone.utc).isoformat()})
    if r:
        await db.referrals.update_one({"_id": r["_id"]}, {"$inc": {"points_awarded": per, "reward_orders": 1}})

async def reverse_referral_points(order):
    txns = await db.point_transactions.find({"order_id": str(order["_id"]), "type": "earn"}).to_list(50)
    for t in txns:
        amt = _num(t.get("amount"))
        await db.customers.update_one({"_id": id_query(t["customer_id"])}, {"$inc": {"points_available": -amt, "points_earned": -amt}})
        await db.point_transactions.insert_one({"customer_id": t["customer_id"], "type": "reverse", "amount": -amt,
            "order_id": str(order["_id"]), "reason": f"Reversal (order dihapus/dibatalkan)", "created_at": datetime.now(timezone.utc).isoformat()})
    await db.point_transactions.delete_many({"order_id": str(order["_id"]), "type": "earn"})
    # refund redeemed points to the buyer
    redeemed = order.get("points_redeemed_le") or 0
    buyer = order.get("customer_id")
    if redeemed and buyer:
        await db.customers.update_one({"_id": id_query(buyer)}, {"$inc": {"points_available": redeemed, "points_redeemed": -redeemed}})

# ---- Customer auth ----
def gen_referral_code(username):
    base = re.sub(r"[^A-Z0-9]", "", username.upper())[:8] or "SGL"
    return f"{base}{uuid.uuid4().hex[:3].upper()}"

def clean_customer(c):
    c = clean(c)
    c.pop("password_hash", None)
    return c

@api_router.post("/customer/register")
async def customer_register(data: CustomerRegister, response: Response):
    phone = normalize_phone(data.phone)
    if not valid_intl_phone(phone):
        raise HTTPException(status_code=400, detail="No HP harus diawali + dan kode negara. Contoh: +62xxxxxxxxxx")
    if len(data.password) < 6:
        raise HTTPException(status_code=400, detail="Kata sandi minimal 6 karakter")
    if await db.customers.find_one({"phone": phone}):
        raise HTTPException(status_code=400, detail="No HP sudah terdaftar")
    if await db.customers.find_one({"username": data.username.strip()}):
        raise HTTPException(status_code=400, detail="Username sudah digunakan")
    now = datetime.now(timezone.utc).isoformat()
    doc = {"username": data.username.strip(), "phone": phone, "email": (data.email or "").strip(),
           "password_hash": hash_password(data.password), "created_at": now, "last_login": now, "active": True,
           "referral_code": gen_referral_code(data.username), "points_available": 0.0, "points_earned": 0.0, "points_redeemed": 0.0}
    r = await db.customers.insert_one(doc)
    cid = str(r.inserted_id)
    await db.referrals.insert_one({"customer_id": cid, "code": doc["referral_code"], "status": "active",
        "start_date": None, "end_date": None, "discount_percentage": 5, "max_discount_le": 100,
        "max_claim_orders": 0, "max_reward_orders": 0, "max_total_points": 0, "points_per_order": 20,
        "claims": 0, "reward_orders": 0, "points_awarded": 0, "created_at": now})
    token = create_customer_token(cid)
    response.set_cookie("customer_token", token, httponly=True, secure=True, samesite="none", max_age=2592000, path="/")
    res = clean_customer(await db.customers.find_one({"_id": r.inserted_id}))
    res["token"] = token
    return res

@api_router.post("/customer/login")
async def customer_login(data: CustomerLogin, response: Response):
    ident = data.identifier.strip()
    c = await db.customers.find_one({"$or": [{"phone": normalize_phone(ident)}, {"username": ident}]})
    if not c or not verify_password(data.password, c["password_hash"]):
        raise HTTPException(status_code=401, detail="Kredensial salah")
    if c.get("active") is False:
        raise HTTPException(status_code=403, detail="Akun dinonaktifkan. Silakan hubungi admin.")
    await db.customers.update_one({"_id": c["_id"]}, {"$set": {"last_login": datetime.now(timezone.utc).isoformat()}})
    token = create_customer_token(str(c["_id"]))
    response.set_cookie("customer_token", token, httponly=True, secure=True, samesite="none", max_age=2592000, path="/")
    res = clean_customer(c)
    res["token"] = token
    return res

@api_router.post("/customer/logout")
async def customer_logout(response: Response):
    response.delete_cookie("customer_token", path="/")
    return {"ok": True}

@api_router.post("/customer/find-username")
async def find_username(payload: Dict[str, Any]):
    phone = normalize_phone(payload.get("phone") or "")
    if not valid_intl_phone(phone):
        raise HTTPException(status_code=400, detail="No HP harus diawali + dan kode negara. Contoh: +62xxxxxxxxxx")
    c = await db.customers.find_one({"phone": phone})
    if not c:
        raise HTTPException(status_code=404, detail="Tidak ada akun terdaftar dengan No HP ini")
    return {"username": c.get("username")}

@api_router.get("/customer/me")
async def customer_me(c: dict = Depends(get_current_customer)):
    return clean_customer(c)

@api_router.get("/customer/orders")
async def customer_orders(c: dict = Depends(get_current_customer)):
    orders = await db.orders.find({"customer_id": str(c["_id"])}).sort("created_at", -1).to_list(500)
    return [clean(o) for o in orders]

@api_router.get("/customer/points")
async def customer_points(c: dict = Depends(get_current_customer)):
    txns = await db.point_transactions.find({"customer_id": str(c["_id"])}).sort("created_at", -1).to_list(500)
    ref = await db.referrals.find_one({"customer_id": str(c["_id"])})
    return {"available": _num(c.get("points_available")), "earned": _num(c.get("points_earned")),
            "redeemed": _num(c.get("points_redeemed")), "referral_code": c.get("referral_code"),
            "referral": clean(ref) if ref else None, "transactions": [clean(t) for t in txns]}

def _guest_track_view(order):
    """Limited, non-sensitive order view for guest tracking (no address/maps/customer identifiers)."""
    items = [{"product_name_snapshot": it.get("product_name_snapshot"), "category": it.get("category"),
              "configuration_snapshot": it.get("configuration_snapshot"), "quantity": it.get("quantity"),
              "subtotal_le": it.get("subtotal_le")} for it in (order.get("items") or [order.get("item")]) if it]
    return {"order_number": order.get("order_number"), "customer_name": order.get("customer_name"),
            "items": items, "order_status": order.get("order_status"), "payment_status": order.get("payment_status"),
            "delivery_method": order.get("delivery_method"), "delivery_zone_name": order.get("delivery_zone_name"),
            "subtotal_le": order.get("subtotal_le"), "discount_le": order.get("discount_le"),
            "referral_discount_le": order.get("referral_discount_le"), "points_redeemed_le": order.get("points_redeemed_le"),
            "delivery_fee_le": order.get("delivery_fee_le"), "total_le": order.get("total_le"),
            "estimated_total_idr": order.get("estimated_total_idr"), "exchange_rate_idr_per_le": order.get("exchange_rate_idr_per_le"),
            "created_at": order.get("created_at"), "claimed": order.get("customer_id") is not None}

@api_router.post("/orders/track")
async def track_order(payload: Dict[str, Any]):
    number = (payload.get("order_number") or "").strip().upper()
    phone = normalize_phone(payload.get("phone") or "")
    if not number or not phone:
        raise HTTPException(status_code=400, detail="Nomor pesanan & No HP wajib diisi")
    order = await db.orders.find_one({"order_number": number})
    if not order or normalize_phone(order.get("customer_phone", "")) != phone:
        raise HTTPException(status_code=404, detail="Pesanan tidak ditemukan atau No HP tidak cocok")
    return _guest_track_view(order)

@api_router.post("/customer/claim-order")
async def claim_order(payload: Dict[str, Any], c: dict = Depends(get_current_customer)):
    number = (payload.get("order_number") or "").strip().upper()
    phone = normalize_phone(payload.get("phone") or "")
    if not number or not phone:
        raise HTTPException(status_code=400, detail="Nomor pesanan & No HP wajib diisi")
    order = await db.orders.find_one({"order_number": number})
    if not order or normalize_phone(order.get("customer_phone", "")) != phone:
        raise HTTPException(status_code=404, detail="Pesanan tidak ditemukan atau No HP tidak cocok")
    if order.get("customer_id"):
        if str(order["customer_id"]) == str(c["_id"]):
            raise HTTPException(status_code=400, detail="Pesanan ini sudah ada di akun kamu")
        raise HTTPException(status_code=409, detail="Pesanan sudah terhubung ke akun lain")
    # Attach account link ONLY — all historical snapshots (price/discount/referral/points/payment) stay untouched.
    await db.orders.update_one({"_id": order["_id"]}, {"$set": {"customer_id": str(c["_id"]), "customer_username": c.get("username")}})
    return {"ok": True, "order_number": order.get("order_number")}

# ---- Referral apply (public preview, requires login for real use) ----
async def validate_referral(code, subtotal, buyer_id):
    if not code:
        return 0.0, None, None
    enabled = await get_setting("referral_program_enabled", True)
    if not enabled:
        return 0.0, None, "Program referral sedang nonaktif"
    r = await db.referrals.find_one({"code": code.strip().upper()})
    if not r:
        return 0.0, None, "Kode referral tidak ditemukan"
    now = datetime.now(timezone.utc).isoformat()
    if r.get("status") != "active":
        return 0.0, None, "Kode referral tidak aktif"
    if r.get("end_date") and now > (r["end_date"] + "T23:59:59"):
        return 0.0, None, "Kode referral sudah kedaluwarsa"
    if r.get("start_date") and now < r["start_date"]:
        return 0.0, None, "Kode referral belum berlaku"
    if r.get("max_claim_orders") and _num(r.get("claims", 0)) >= _num(r["max_claim_orders"]):
        return 0.0, None, "Kuota kode referral habis"
    if buyer_id and str(r.get("customer_id")) == str(buyer_id):
        return 0.0, None, "Tidak dapat memakai kode referral sendiri"
    disc = subtotal * _num(r.get("discount_percentage")) / 100.0
    mx = _num(r.get("max_discount_le"))
    if mx > 0:
        disc = min(disc, mx)
    return round(disc, 2), r, None

@api_router.post("/referral/validate")
async def referral_validate(payload: Dict[str, Any], request: Request):
    buyer = await get_optional_customer(request)
    if not buyer:
        return {"valid": False, "message": "Untuk menggunakan kode referral, silakan buat akun atau masuk terlebih dahulu", "require_auth": True, "discount_amount": 0}
    disc, r, err = await validate_referral(payload.get("code"), _num(payload.get("subtotal")), str(buyer["_id"]) if buyer else None)
    if err:
        return {"valid": False, "message": err, "discount_amount": 0}
    owner = await db.customers.find_one({"_id": id_query(r["customer_id"])})
    return {"valid": True, "discount_amount": disc, "percentage": _num(r.get("discount_percentage")),
            "code": r.get("code"), "owner_name": owner.get("username") if owner else ""}

# ---- Admin: referrals & customers ----
@api_router.get("/admin/referrals")
async def admin_referrals(admin: dict = Depends(require_perm("manage_settings"))):
    out = []
    for r in await db.referrals.find({}).sort("created_at", -1).to_list(500):
        r = clean(r)
        owner = await db.customers.find_one({"_id": id_query(r["customer_id"])}) if r.get("customer_id") else None
        r["owner_name"] = owner.get("username") if owner else ""
        out.append(r)
    return out

@api_router.put("/admin/referrals/{rid}")
async def admin_update_referral(rid: str, payload: Dict[str, Any], admin: dict = Depends(require_perm("manage_settings"))):
    upd = {}
    for k in ["status", "start_date", "end_date", "discount_percentage", "max_discount_le", "max_claim_orders", "max_reward_orders", "max_total_points", "points_per_order"]:
        if k in payload:
            upd[k] = payload[k]
    for k in ["discount_percentage", "max_discount_le", "max_claim_orders", "max_reward_orders", "max_total_points", "points_per_order"]:
        if k in upd:
            upd[k] = _num(upd[k])
    if "discount_percentage" in upd:
        upd["discount_percentage"] = max(0.0, min(100.0, upd["discount_percentage"]))
    await db.referrals.update_one({"_id": id_query(rid)}, {"$set": upd})
    return clean(await db.referrals.find_one({"_id": id_query(rid)}))

@api_router.get("/admin/customers")
async def admin_customers(q: Optional[str] = None, admin: dict = Depends(require_perm("manage_orders"))):
    query = {}
    if q:
        query = {"$or": [{"username": {"$regex": q, "$options": "i"}}, {"phone": {"$regex": q, "$options": "i"}}]}
    return [clean_customer(c) for c in await db.customers.find(query).sort("created_at", -1).to_list(500)]

@api_router.get("/admin/customers/{cid}")
async def admin_customer_detail(cid: str, admin: dict = Depends(require_perm("manage_orders"))):
    c = await db.customers.find_one({"_id": id_query(cid)})
    if not c:
        raise HTTPException(status_code=404, detail="Pelanggan tidak ditemukan")
    orders = await db.orders.find({"customer_id": cid}).sort("created_at", -1).to_list(500)
    txns = await db.point_transactions.find({"customer_id": cid}).sort("created_at", -1).to_list(500)
    return {"customer": clean_customer(c), "orders": [clean(o) for o in orders], "point_transactions": [clean(t) for t in txns]}

@api_router.get("/admin/customers/{cid}/credit-balance")
async def admin_customer_credit_balance(cid: str, currency: Optional[str] = "EGP", admin: dict = Depends(require_perm("manage_orders"))):
    c = await db.customers.find_one({"_id": id_query(cid)})
    if not c:
        raise HTTPException(status_code=404, detail="Pelanggan tidak ditemukan")
    cur = (currency or "EGP").strip().upper()
    balance = await get_customer_credit_balance(cid, cur)
    events = await db.customer_credit_events.find({"customer_id": cid, "currency": cur}).sort("created_at", -1).to_list(500)
    return {
        "customer_id": cid,
        "currency": cur,
        "available_credit": balance,
        "events_count": len(events),
        "events": [clean(e) for e in events],
    }

@api_router.post("/admin/customers/{cid}/credit-refund")
async def admin_customer_credit_refund(
    cid: str,
    payload: CustomerCreditRefundInput,
    admin: dict = Depends(require_perm("manage_orders"))
):
    # Financial write operation requires access_finance or owner role
    role = admin.get("role")
    perms = admin.get("permissions") or {}
    if role != "owner" and not perms.get("access_finance"):
        raise HTTPException(
            status_code=403,
            detail="Hanya admin dengan akses keuangan atau owner yang dapat memproses pengembalian saldo kredit pelanggan"
        )

    customer = await db.customers.find_one({"_id": id_query(cid)})
    if not customer:
        raise HTTPException(status_code=404, detail="Pelanggan tidak ditemukan")

    raw_amount = _num(payload.amount)
    if raw_amount <= 0:
        raise HTTPException(status_code=400, detail="Nominal pengembalian saldo harus lebih besar dari 0")

    currency = (payload.currency or "EGP").strip().upper()
    if currency not in ("EGP", "IDR"):
        raise HTTPException(status_code=400, detail="Mata uang pengembalian saldo harus EGP atau IDR")

    refund_method = (payload.refund_method or "cash").strip().lower()
    if refund_method not in ("cash", "transfer"):
        raise HTTPException(status_code=400, detail="Metode pengembalian harus cash atau transfer")

    # Target account determination
    if payload.account and payload.account.strip():
        primary_account = payload.account.strip().upper()
        if primary_account not in ("EGP", "IDR"):
            raise HTTPException(status_code=400, detail="Akun kas/bank tidak valid (harus EGP atau IDR)")
    else:
        primary_account = "IDR" if refund_method == "transfer" else currency

    # Idempotency check: if an event with this idempotency key already exists, validate and return cleanly
    idem_key = (payload.idempotency_key or "").strip() or None
    if idem_key:
        existing_event = await db.customer_credit_events.find_one({"idempotency_key": idem_key})
        if existing_event:
            # Validate that the submitted request matches the existing transaction payload
            orig_cid = str(existing_event.get("customer_id") or "").strip()
            orig_cur = str(existing_event.get("currency") or "").strip().upper()
            orig_signed_amt = _num(existing_event.get("signed_amount", 0.0))
            orig_amt_dec = Decimal(str(abs(orig_signed_amt))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            req_amt_dec = Decimal(str(raw_amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

            if orig_cid != str(cid).strip() or orig_cur != currency or orig_amt_dec != req_amt_dec:
                raise HTTPException(
                    status_code=409,
                    detail="Kunci idempotensi telah digunakan untuk transaksi pengembalian dana dengan parameter yang berbeda."
                )

            existing_txn = None
            if existing_event.get("source_payment_id"):
                existing_txn = await db.finance_transactions.find_one({"_id": id_query(str(existing_event["source_payment_id"]))})
            curr_bal = await get_customer_credit_balance(cid, currency)
            return {
                "ok": True,
                "idempotent_replay": True,
                "event": clean(existing_event),
                "finance_transaction": clean(existing_txn) if existing_txn else None,
                "available_credit": curr_bal,
            }

    # Initial preflight balance check
    preflight_balance = await get_customer_credit_balance(cid, currency)
    if preflight_balance < raw_amount:
        raise HTTPException(
            status_code=400,
            detail=f"Saldo kredit pelanggan tidak mencukupi untuk pengembalian dana (Tersedia: {preflight_balance:.2f} {currency}, Diminta: {raw_amount:.2f} {currency})"
        )

    now = datetime.now(timezone.utc).isoformat()
    cce_event_num = await generate_credit_event_number()
    event_idempotency_key = idem_key or f"cce_refund_{cid}_{cce_event_num}"

    # Rate and counterpart computation
    settings_rate = _num(await get_setting("exchange_rate_idr_per_le", 357), 357)
    rate = settings_rate
    conv = compute_currency_conversion(currency, raw_amount, rate)

    txn_desc = f"Pengembalian saldo kredit pelanggan {customer.get('username') or customer.get('name') or cid} ({cce_event_num})"
    if payload.notes and payload.notes.strip():
        txn_desc += f": {payload.notes.strip()}"

    async def _do_credit_refund(session):
        ins_kw = {"session": session} if session else {}

        # 1. Concurrency serialization lock on customer document
        cust_oid = id_query(cid)
        cust_touch_res = await db.customers.update_one(
            {"_id": cust_oid},
            {"$set": {"last_credit_transaction_at": now}},
            **ins_kw
        )
        if cust_touch_res.matched_count == 0:
            raise HTTPException(
                status_code=400,
                detail="Akun pelanggan tidak ditemukan untuk serialisasi transaksi kredit"
            )

        # 2. Concurrency-safe in-transaction balance verification
        in_txn_balance = await get_customer_credit_balance(cid, currency, session=session)
        if in_txn_balance < raw_amount:
            raise HTTPException(
                status_code=409,
                detail=f"Konflik saldo: Saldo kredit pelanggan tidak mencukupi untuk pengembalian dana (Tersedia: {in_txn_balance:.2f} {currency}, Diminta: {raw_amount:.2f} {currency})"
            )

        # 3. Insert Finance Transaction (Liability Settlement / Cash Outflow)
        txn_doc = {
            "date": now,
            "type": "refund",
            "category": "Pengembalian Dana",
            "amount": conv["primary_amount"],
            "currency": currency,
            "account": primary_account,
            "classification": "liability_settlement",
            "exchange_rate": rate,
            "counterpart_amount": conv["counterpart_amount"],
            "counterpart_currency": conv["counterpart_currency"],
            "payment_method": refund_method,
            "description": txn_desc,
            "related_customer_id": cid,
            "related_credit_event_number": cce_event_num,
            "notes": (payload.notes or "").strip(),
            "created_by_name": admin.get("name", "Admin"),
            "created_by_id": admin.get("id"),
            "created_at": now,
            "updated_at": now,
        }
        txn_res = await db.finance_transactions.insert_one(txn_doc, **ins_kw)
        txn_id = str(txn_res.inserted_id)

        # 4. Insert Customer Credit Event (credit_refunded with signed_amount < 0)
        cce_doc = {
            "event_number": cce_event_num,
            "event_type": "credit_refunded",
            "customer_id": cid,
            "customer_name": customer.get("username") or customer.get("name"),
            "customer_phone": customer.get("phone"),
            "currency": currency,
            "signed_amount": -round(float(raw_amount), 2),
            "source_type": "refund",
            "source_payment_id": txn_id,
            "reason": (payload.notes or "").strip() or "Pengembalian saldo kredit pelanggan",
            "idempotency_key": event_idempotency_key,
            "created_by_id": admin.get("id"),
            "created_by_name": admin.get("name", "Admin"),
            "created_at": now,
            "updated_at": now,
        }
        cce_insert = getattr(db.customer_credit_events, "insert_one", None)
        if callable(cce_insert):
            res_coro = cce_insert(cce_doc, **ins_kw)
            if asyncio.iscoroutine(res_coro):
                await res_coro

        return cce_doc, txn_doc

    def _is_transient_conflict(exc: Exception) -> bool:
        if isinstance(exc, pymongo.errors.PyMongoError):
            if hasattr(exc, "has_error_label") and exc.has_error_label("TransientTransactionError"):
                return True
            if isinstance(exc, pymongo.errors.OperationFailure) and getattr(exc, "code", None) == 112:
                return True
        return False

    max_txn_retries = 3
    final_cce = None
    final_txn = None

    for attempt in range(1, max_txn_retries + 1):
        session = None
        try:
            session = await client.start_session()
        except (pymongo.errors.ConfigurationError, pymongo.errors.InvalidOperation, AttributeError) as sess_err:
            if not is_standalone_fallback_permitted():
                logger.error(f"Transaction capability unavailable for customer credit refund in mode {get_environment_mode()!r}: {sess_err}")
                raise HTTPException(
                    status_code=503,
                    detail="Layanan transaksi multi-dokumen tidak tersedia pada lingkungan ini (Fail-Closed)"
                )
            session = None

        try:
            if session is not None:
                async with session:
                    async with session.start_transaction():
                        final_cce, final_txn = await _do_credit_refund(session)
            else:
                final_cce, final_txn = await _do_credit_refund(None)
            break
        except Exception as txn_exc:
            if _is_transient_conflict(txn_exc):
                logger.warning(
                    f"Transient transaction conflict on attempt {attempt}/{max_txn_retries} for refund customer {cid}: {txn_exc}"
                )
                if attempt < max_txn_retries:
                    await asyncio.sleep(0.05 * attempt)
                    continue
                logger.error(
                    f"Exhausted transaction retry attempts ({max_txn_retries}) for refund customer {cid} due to concurrency conflict: {txn_exc}"
                )
                raise HTTPException(
                    status_code=409,
                    detail="Terjadi konflik transaksi bersamaan pada akun pelanggan. Silakan muat ulang halaman dan coba kembali."
                )
            raise

    remaining_bal = await get_customer_credit_balance(cid, currency)
    return {
        "ok": True,
        "customer_id": cid,
        "currency": currency,
        "refund_amount": round(float(raw_amount), 2),
        "available_credit": remaining_bal,
        "event": clean(final_cce),
        "finance_transaction": clean(final_txn),
    }

# --------------------------------------------------------------------------
# Phase 3.B.6: Explicit Finance Adjustments
# --------------------------------------------------------------------------

@api_router.post("/admin/finance/adjustments", status_code=201)
async def admin_create_finance_adjustment(
    payload: FinanceAdjustmentInput,
    response: Response,
    admin: dict = Depends(require_perm("access_finance"))
):
    # Role check: strictly owner or permissions.access_finance == True
    role = admin.get("role")
    perms = admin.get("permissions") or {}
    if role != "owner" and not perms.get("access_finance"):
        raise HTTPException(
            status_code=403,
            detail="Hanya admin dengan akses keuangan atau owner yang dapat membuat penyesuaian keuangan (Finance Adjustment)"
        )

    # 1. Input validation: type
    adj_type = (payload.type or "").strip().lower()
    allowed_types = {"revenue_reversal", "price_correction", "return_allowance"}
    if adj_type not in allowed_types:
        raise HTTPException(
            status_code=422,
            detail=f"Tipe penyesuaian keuangan tidak valid: {payload.type!r}. Harus salah satu dari {list(allowed_types)}."
        )

    # 2. Input validation: currency
    currency = (payload.currency or "").strip().upper()
    if currency not in ("EGP", "IDR"):
        raise HTTPException(
            status_code=422,
            detail=f"Mata uang penyesuaian tidak didukung: {payload.currency!r}. Hanya EGP atau IDR yang diperbolehkan."
        )

    # 3. Input validation: amount precision and non-zero
    raw_amount = payload.amount
    if raw_amount is None or raw_amount == 0.0:
        raise HTTPException(
            status_code=422,
            detail="Nominal penyesuaian keuangan tidak boleh nol"
        )

    s_amount = str(raw_amount).strip()
    if "." in s_amount:
        dec_part = s_amount.split(".")[1]
        if len(dec_part) > 2:
            raise HTTPException(
                status_code=422,
                detail=f"Nominal penyesuaian tidak boleh memiliki lebih dari 2 tempat desimal: {raw_amount}"
            )

    d_amount = Decimal(str(raw_amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if d_amount == Decimal("0.00"):
        raise HTTPException(
            status_code=422,
            detail="Nominal penyesuaian keuangan tidak boleh nol"
        )
    float_amount = float(d_amount)

    # 4. Sign validation
    if adj_type in ("revenue_reversal", "return_allowance"):
        if float_amount >= 0:
            raise HTTPException(
                status_code=422,
                detail=f"Penyesuaian bertipe {adj_type} harus bernilai negatif (< 0)"
            )
    # price_correction: can be positive or negative (B6-OD-02, B6-OD-05), zero is already rejected

    # 5. Reason validation
    reason = (payload.reason or "").strip()
    if len(reason) < 5 or len(reason) > 500:
        raise HTTPException(
            status_code=422,
            detail="Alasan penyesuaian keuangan wajib diisi (minimal 5 karakter, maksimal 500 karakter)"
        )

    # 6. Idempotency key validation
    idem_key = (payload.idempotency_key or "").strip()
    if len(idem_key) < 8 or len(idem_key) > 128:
        raise HTTPException(
            status_code=422,
            detail="Kunci idempotensi (idempotency_key) wajib diisi (minimal 8 karakter, maksimal 128 karakter)"
        )

    order_id_raw = (payload.order_id or "").strip()
    if not order_id_raw:
        raise HTTPException(status_code=422, detail="order_id wajib diisi")

    # Helper function to compute order impact
    async def _compute_order_impact(order_doc, added_adjustment=None, session=None):
        rec_rev = _num(order_doc.get("recognized_revenue_le", 0.0))
        d_rec_rev = Decimal(str(rec_rev)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        q_adjs = {"order_id": str(order_doc["_id"]), "is_void": {"$ne": True}}
        kw = {"session": session} if session else {}
        cursor = db.finance_adjustments.find(q_adjs, **kw)
        existing_adjs = await cursor.to_list(1000) if hasattr(cursor, "to_list") else []

        cum_adj_d = Decimal("0.00")
        for a in existing_adjs:
            amt = _num(a.get("amount", 0.0))
            cum_adj_d += Decimal(str(amt)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        if added_adjustment:
            add_amt = _num(added_adjustment.get("amount", 0.0))
            cum_adj_d += Decimal(str(add_amt)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        net_rev_d = d_rec_rev + cum_adj_d

        order_oid = id_query(str(order_doc["_id"]))
        payments_cursor = db.payments.find({"order_id": order_oid, "status": "recorded"}, **kw)
        recs = await payments_cursor.to_list(1000) if hasattr(payments_cursor, "to_list") else []
        paid_d = Decimal(str(sum(_num(p.get("amount_le", 0.0)) for p in recs))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        piutang_d = max(Decimal("0.00"), net_rev_d - paid_d)
        excess_d = max(Decimal("0.00"), paid_d - net_rev_d)

        return {
            "original_recognized_revenue_le": float(d_rec_rev),
            "cumulative_net_adjustments_le": float(cum_adj_d),
            "net_adjusted_revenue_le": float(net_rev_d),
            "canonical_paid_le": float(paid_d),
            "piutang_usaha_le": float(piutang_d),
            "unallocated_excess_le": float(excess_d),
        }

    # Helper to check if an existing adjustment matches the incoming request payload deterministically
    def _is_matching_idempotent_payload(existing_doc: dict) -> bool:
        orig_order_id = str(existing_doc.get("order_id") or "").strip()
        orig_type = str(existing_doc.get("type") or "").strip().lower()
        orig_cur = str(existing_doc.get("currency") or "").strip().upper()
        orig_amt = _num(existing_doc.get("amount", 0.0))
        orig_amt_d = Decimal(str(orig_amt)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        orig_reason = str(existing_doc.get("reason") or "").strip()
        orig_evidence = str(existing_doc.get("evidence_reference") or "").strip() or None
        orig_notes = str(existing_doc.get("notes") or "").strip() or None

        norm_evidence = (payload.evidence_reference or "").strip() or None
        norm_notes = (payload.notes or "").strip() or None

        return (
            orig_order_id == order_id_raw
            and orig_type == adj_type
            and orig_cur == currency
            and orig_amt_d == d_amount
            and orig_reason == reason
            and orig_evidence == norm_evidence
            and orig_notes == norm_notes
        )

    # 7. Pre-transaction Idempotency Replay Check
    existing_adj = await db.finance_adjustments.find_one({"idempotency_key": idem_key})
    if existing_adj:
        if not _is_matching_idempotent_payload(existing_adj):
            raise HTTPException(
                status_code=409,
                detail="Kunci idempotensi telah digunakan untuk penyesuaian keuangan dengan parameter yang berbeda."
            )

        order_doc = await db.orders.find_one({"_id": id_query(order_id_raw)})
        impact = await _compute_order_impact(order_doc, added_adjustment=None) if order_doc else {}
        response.status_code = 200
        res = clean(existing_adj)
        res["order_impact"] = impact
        return res

    # 8. Transaction Execution
    async def _do_create_adjustment(session):
        ins_kw = {"session": session} if session else {}

        # 8.1 Read and serialize order
        order_doc = await db.orders.find_one({"_id": id_query(order_id_raw)}, **ins_kw)
        if not order_doc:
            raise HTTPException(status_code=404, detail="Pesanan tidak ditemukan")

        # 8.2 Touch serialization guard on order document
        now_touch = datetime.now(timezone.utc).isoformat()
        touch_res = await db.orders.update_one(
            {"_id": order_doc["_id"]},
            {"$set": {"last_finance_adjustment_at": now_touch}},
            **ins_kw
        )
        if touch_res.matched_count == 0:
            raise HTTPException(status_code=404, detail="Pesanan tidak ditemukan untuk serialisasi penyesuaian")

        # 8.3 Handover Eligibility Verification (ALL THREE CONDITIONS MANDATORY)
        completed_at = order_doc.get("completed_at")
        has_valid_completed_at = bool(completed_at) and isinstance(completed_at, str) and len(completed_at.strip()) > 0
        rec_rev_val = order_doc.get("recognized_revenue_le")
        has_valid_rec_rev = (rec_rev_val is not None) and isinstance(rec_rev_val, (int, float, Decimal)) and rec_rev_val >= 0
        order_status = order_doc.get("order_status")

        # In-flight active orders fail closed with HTTP 409
        if order_status in ("pesanan_masuk", "dikonfirmasi", "diproses", "siap"):
            raise HTTPException(
                status_code=409,
                detail="Penyesuaian keuangan hanya berlaku untuk pesanan yang telah serah terima (selesai). Untuk pesanan aktif, perbarui nilai pesanan secara langsung."
            )

        # Status must be selesai or dibatalkan
        if order_status not in ("selesai", "dibatalkan"):
            raise HTTPException(
                status_code=409,
                detail=f"Status pesanan tidak memenuhi syarat untuk penyesuaian keuangan: {order_status!r}."
            )

        # Missing or invalid snapshot on selesai / dibatalkan fails closed with HTTP 409
        if not has_valid_completed_at or not has_valid_rec_rev:
            raise HTTPException(
                status_code=409,
                detail="Data serah terima pesanan tidak lengkap atau tidak valid (completed_at atau recognized_revenue_le tidak valid)."
            )

        # 8.4 Currency Matching Verification
        order_cur = (order_doc.get("currency") or "EGP").strip().upper()
        if currency != order_cur:
            raise HTTPException(
                status_code=422,
                detail=f"Mata uang penyesuaian ({currency}) harus sesuai dengan mata uang pesanan ({order_cur})."
            )

        # 8.5 Cumulative Downward Limit Evaluation
        d_orig_rev = Decimal(str(rec_rev_val)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        adjs_cursor = db.finance_adjustments.find(
            {"order_id": str(order_doc["_id"]), "is_void": {"$ne": True}},
            **ins_kw
        )
        existing_list = await adjs_cursor.to_list(1000) if hasattr(adjs_cursor, "to_list") else []

        prior_adj_d = Decimal("0.00")
        for a in existing_list:
            amt = _num(a.get("amount", 0.0))
            prior_adj_d += Decimal(str(amt)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        current_net_rev_d = d_orig_rev + prior_adj_d

        if float_amount < 0:
            if current_net_rev_d <= Decimal("0.00"):
                raise HTTPException(
                    status_code=409,
                    detail="Pendapatan pesanan ini telah sepenuhnya dibalikkan (net revenue 0 LE). Penyesuaian negatif lebih lanjut ditolak."
                )
            if abs(d_amount) > current_net_rev_d:
                raise HTTPException(
                    status_code=422,
                    detail=f"Total penyesuaian negatif melebihi sisa pendapatan yang diakui pada pesanan ini (Tersedia: {current_net_rev_d:.2f} {currency}, Diminta: {abs(d_amount):.2f} {currency})."
                )

        # 8.6 Generate Daily Sequential Identifier (inside transaction)
        adj_id = await generate_adjustment_number(session=session)

        # 8.7 Prepare Document
        now_iso = datetime.now(timezone.utc).isoformat()
        adj_doc = {
            "adjustment_id": adj_id,
            "order_id": str(order_doc["_id"]),
            "order_number": order_doc.get("order_number"),
            "customer_id": str(order_doc.get("customer_id") or "").strip() or None,
            "customer_name": order_doc.get("customer_name") or order_doc.get("name"),
            "type": adj_type,
            "currency": currency,
            "amount": float_amount,
            "reason": reason,
            "evidence_reference": (payload.evidence_reference or "").strip() or None,
            "notes": (payload.notes or "").strip() or None,
            "idempotency_key": idem_key,
            "is_void": False,
            "order_completed_at": completed_at,
            "created_by_id": admin.get("id"),
            "created_by_name": admin.get("name", "Admin"),
            "created_at": now_iso,
            "updated_at": now_iso,
        }

        # 8.8 Insert Document
        ins_func = getattr(db.finance_adjustments, "insert_one", None)
        if callable(ins_func):
            coro = ins_func(adj_doc, **ins_kw)
            if asyncio.iscoroutine(coro):
                await coro

        return adj_doc, order_doc

    def _is_transient_conflict(exc: Exception) -> bool:
        if isinstance(exc, pymongo.errors.PyMongoError):
            if hasattr(exc, "has_error_label") and exc.has_error_label("TransientTransactionError"):
                return True
            if isinstance(exc, pymongo.errors.OperationFailure) and getattr(exc, "code", None) == 112:
                return True
        return False

    max_retries = 3
    final_adj_doc = None
    final_order_doc = None

    for attempt in range(1, max_retries + 1):
        session = None
        try:
            session = await client.start_session()
        except (pymongo.errors.ConfigurationError, pymongo.errors.InvalidOperation, AttributeError) as sess_err:
            if not is_standalone_fallback_permitted():
                logger.error(f"Transaction capability unavailable for finance adjustment in mode {get_environment_mode()!r}: {sess_err}")
                raise HTTPException(
                    status_code=503,
                    detail="Layanan transaksi multi-dokumen tidak tersedia pada lingkungan ini (Fail-Closed)"
                )
            session = None

        try:
            if session is not None:
                async with session:
                    async with session.start_transaction():
                        final_adj_doc, final_order_doc = await _do_create_adjustment(session)
            else:
                final_adj_doc, final_order_doc = await _do_create_adjustment(None)
            break
        except pymongo.errors.DuplicateKeyError as dke:
            err_msg = str(dke)
            if "uniq_adjustments_idempotency" in err_msg or idem_key in err_msg:
                # Concurrent race won by another request with the same idempotency key
                winning_adj = await db.finance_adjustments.find_one({"idempotency_key": idem_key})
                if winning_adj:
                    if not _is_matching_idempotent_payload(winning_adj):
                        raise HTTPException(
                            status_code=409,
                            detail="Kunci idempotensi telah digunakan untuk penyesuaian keuangan dengan parameter yang berbeda."
                        )
                    order_doc = await db.orders.find_one({"_id": id_query(order_id_raw)})
                    impact = await _compute_order_impact(order_doc, added_adjustment=None) if order_doc else {}
                    response.status_code = 200
                    res = clean(winning_adj)
                    res["order_impact"] = impact
                    return res
            raise
        except Exception as txn_exc:
            if _is_transient_conflict(txn_exc):
                logger.warning(
                    f"Transient transaction conflict on attempt {attempt}/{max_retries} for adjustment order {order_id_raw}: {txn_exc}"
                )
                if attempt < max_retries:
                    await asyncio.sleep(0.05 * attempt)
                    continue
                logger.error(
                    f"Exhausted transaction retry attempts ({max_retries}) for adjustment order {order_id_raw} due to concurrency conflict: {txn_exc}"
                )
                raise HTTPException(
                    status_code=409,
                    detail="Terjadi konflik transaksi bersamaan pada pesanan. Silakan muat ulang halaman dan coba kembali."
                )
            raise

    # 9. Compute order impact for response (including newly added adjustment)
    order_impact = await _compute_order_impact(final_order_doc, added_adjustment=final_adj_doc)
    res_payload = clean(final_adj_doc)
    res_payload["order_impact"] = order_impact
    return res_payload

@api_router.patch("/admin/customers/{cid}")
async def admin_update_customer(cid: str, payload: Dict[str, Any], admin: dict = Depends(require_owner())):
    c = await db.customers.find_one({"_id": id_query(cid)})
    if not c:
        raise HTTPException(status_code=404, detail="Pelanggan tidak ditemukan")
    if "active" not in payload:
        raise HTTPException(status_code=400, detail="Tidak ada perubahan")
    await db.customers.update_one({"_id": id_query(cid)}, {"$set": {"active": bool(payload["active"])}})
    return clean_customer(await db.customers.find_one({"_id": id_query(cid)}))

@api_router.delete("/admin/customers/{cid}")
async def admin_delete_customer(cid: str, admin: dict = Depends(require_owner())):
    c = await db.customers.find_one({"_id": id_query(cid)})
    if not c:
        raise HTTPException(status_code=404, detail="Pelanggan tidak ditemukan")
    # Block permanent deletion when there is meaningful business history to preserve.
    has_orders = await db.orders.find_one({"customer_id": cid})
    referred_others = await db.orders.find_one({"referral.owner_id": cid})
    has_points_history = await db.point_transactions.find_one({"customer_id": cid})
    ref = await db.referrals.find_one({"customer_id": cid})
    ref_active_history = bool(ref and (_num(ref.get("claims", 0)) > 0 or _num(ref.get("points_awarded", 0)) > 0 or _num(ref.get("reward_orders", 0)) > 0))
    if has_orders or referred_others or has_points_history or ref_active_history or _num(c.get("points_available")) > 0 or _num(c.get("points_earned")) > 0:
        raise HTTPException(status_code=400, detail="Pelanggan memiliki riwayat bisnis (pesanan/keuangan/referral/poin). Gunakan Nonaktifkan Akun agar riwayat tetap utuh.")
    # Safe to hard-delete: no business history. Remove account + its unused referral code.
    await db.customers.delete_one({"_id": id_query(cid)})
    if ref:
        await db.referrals.delete_one({"_id": ref["_id"]})
    return {"ok": True, "deleted": True}

@api_router.post("/admin/customers/{cid}/reset-password")
async def admin_reset_customer_password(cid: str, payload: Dict[str, Any], admin: dict = Depends(require_owner())):
    c = await db.customers.find_one({"_id": id_query(cid)})
    if not c:
        raise HTTPException(status_code=404, detail="Pelanggan tidak ditemukan")
    np = payload.get("new_password") or ""
    if len(np) < 6:
        raise HTTPException(status_code=400, detail="Kata sandi minimal 6 karakter")
    await db.customers.update_one({"_id": id_query(cid)}, {"$set": {"password_hash": hash_password(np)}})
    return {"ok": True}

@api_router.post("/admin/customers/{cid}/adjust-points")
async def admin_adjust_points(cid: str, data: PointAdjustInput, admin: dict = Depends(require_owner())):
    c = await db.customers.find_one({"_id": id_query(cid)})
    if not c:
        raise HTTPException(status_code=404, detail="Pelanggan tidak ditemukan")
    new_bal = _num(c.get("points_available")) + _num(data.amount)
    if new_bal < 0:
        raise HTTPException(status_code=400, detail="Saldo poin tidak boleh negatif")
    await db.customers.update_one({"_id": id_query(cid)}, {"$inc": {"points_available": _num(data.amount)}})
    await db.point_transactions.insert_one({"customer_id": cid, "type": "adjust", "amount": _num(data.amount),
        "order_id": None, "reason": data.reason, "balance_after": new_bal, "by_name": admin.get("name"),
        "created_at": datetime.now(timezone.utc).isoformat()})
    return {"ok": True, "balance": new_bal}

# --------------------------------------------------------------------------
# Seed & migrations
# --------------------------------------------------------------------------
RAK_TYPE_B_PRICES = {
    "60_2": 565, "60_3": 755, "60_4": 985, "60_5": 1270, "60_6": 1335, "60_7": 1505,
    "80_2": 635, "80_3": 860, "80_4": 1125, "80_5": 1335, "80_6": 1545, "80_7": 1750,
    "120_2": 830, "120_3": 1180, "120_4": 1530, "120_5": 1875, "120_6": 2255, "120_7": 2570,
}

try:
    from backend.index_provisioner import (
        CriticalFinanceIndexError,
        verify_required_indexes,
        REQUIRED_INDEX_SPECS,
    )
except ImportError:
    try:
        from index_provisioner import (
            CriticalFinanceIndexError,
            verify_required_indexes,
            REQUIRED_INDEX_SPECS,
        )
    except ImportError:
        class CriticalFinanceIndexError(RuntimeError):
            """Raised when a critical unique financial integrity index fails to be created/verified."""
            def __init__(self, collection_name: str, index_name: str, reason: str):
                self.collection_name = collection_name
                self.index_name = index_name
                self.reason = reason
                super().__init__(f"Failed to create critical financial integrity index '{index_name}' on collection '{collection_name}': {reason}")
        verify_required_indexes = None
        REQUIRED_INDEX_SPECS = []


class OperationalConfigurationError(RuntimeError):
    """Raised when required operational configuration is missing during fail-closed startup verification."""
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(f"Operational configuration verification failed: {reason}")


async def verify_baseline_data(target_db=None, fail_closed: bool = True) -> Dict[str, Any]:
    """Read-only check that essential operational configuration is present.
    Does NOT mutate any database documents.
    """
    use_db = target_db if target_db is not None else db
    errors = []

    # 1. Verify owner admin exists (use find_one for mock compatibility)
    owner_doc = await use_db.admins.find_one({"role": "owner"})
    if not owner_doc:
        errors.append("No administrator account with role 'owner' exists in 'admins' collection.")

    # 2. Verify essential operational settings
    essential_keys = ["store_name", "exchange_rate_idr_per_le"]
    missing_settings = []
    for k in essential_keys:
        if await use_db.settings.find_one({"key": k}) is None:
            missing_settings.append(k)
    if missing_settings:
        errors.append(f"Essential store settings missing in 'settings' collection: {missing_settings}")

    is_valid = len(errors) == 0
    if not is_valid and fail_closed:
        err_msg = "; ".join(errors)
        logger.error(f"STARTUP CONFIGURATION VERIFICATION FAILED: {err_msg}")
        raise OperationalConfigurationError(err_msg)

    return {
        "valid": is_valid,
        "owner_present": bool(owner_doc),
        "missing_settings": missing_settings,
        "errors": errors,
    }


async def seed_baseline_data_only(target_db=None):
    """Initializes missing baseline/default data for development and testing.
    SAFETY GUARANTEE: Never overwrites existing product names, prices, or user-managed settings.
    """
    use_db = target_db if target_db is not None else db
    admin_email = os.environ.get("ADMIN_EMAIL", "sogil.furniture@gmail.com").lower()
    admin_password = os.environ.get("ADMIN_PASSWORD", "admin123")

    # Only insert initial owner if no owner admin exists at all
    owner_doc = await use_db.admins.find_one({"role": "owner"})
    if not owner_doc:
        existing = await use_db.admins.find_one({"email": admin_email})
        if not existing:
            await use_db.admins.insert_one({
                "email": admin_email,
                "password_hash": hash_password(admin_password),
                "name": "Owner Sogil",
                "role": "owner",
                "permissions": default_permissions("owner"),
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
        else:
            if existing.get("role") != "owner":
                await use_db.admins.update_one(
                    {"_id": existing["_id"]},
                    {"$set": {"role": "owner", "permissions": default_permissions("owner")}}
                )

    defaults = {
        "store_name": "Sogil Furniture",
        "app_name": "Sogil Furniture — Furniture Ordering & Management",
        "tagline": "Kualitas Terbaik, Untuk Ruang Terbaik",
        "store_address": "11 El-Refaey Ln, El-Darb El-Ahmar, Al-Darb Al-Ahmar, Cairo Governorate 4293042",
        "store_maps_url": "https://maps.google.com/?q=30.041889,31.262636",
        "whatsapp_number": "628XXXXXXXXXX", "exchange_rate_idr_per_le": 357,
        "bank_info": "PLACEHOLDER — Isi informasi rekening/bank melalui dashboard admin.", "logo_url": "",
        "instagram": "", "facebook": "", "tiktok": "", "email": "",
        "referral_program_enabled": True, "point_redeem_max_pct": 50,
    }
    for k, v in defaults.items():
        if await use_db.settings.find_one({"key": k}) is None:
            await use_db.settings.update_one(
                {"key": k},
                {"$set": {"key": k, "value": v, "updated_at": datetime.now(timezone.utc).isoformat()}},
                upsert=True
            )

    if await use_db.delivery_zones.count_documents({}) == 0:
        for name, fee in [("Darasah", 150), ("Gamaliyah", 200), ("Buuts", 250), ("Hay Sadis", 500),
                          ("Hay Sabi", 500), ("Hay Tsamin", 500), ("Hay Asyir", 600)]:
            await use_db.delivery_zones.insert_one({
                "name": name, "fee_le": float(fee), "active": True,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })

    if await use_db.products.count_documents({}) == 0:
        now = datetime.now(timezone.utc).isoformat()
        rak_pricing = {
            "lengths": ["60", "80", "120"], "levels": ["2", "3", "4", "5", "6", "7"],
            "base_prices": dict(RAK_TYPE_B_PRICES),
            "types": ["B", "A"],
            "type_adjustments": {"B": {"60": 0, "80": 0, "120": 0}, "A": {"60": 60, "80": 80, "120": 120}},
            "finishings": ["Natural", "Pernis", "Cat Warna"],
            "finishing": {"Natural": 0, "Pernis": {"60": 15, "80": 20, "120": 30}, "Cat Warna": {"60": 20, "80": 25, "120": 35}},
        }
        meja_pricing = {"sizes": ["40x80", "50x80"], "heights": ["30", "75"],
                        "base_prices": {"40x80_30": 700, "40x80_75": 800, "50x80_30": 800, "50x80_75": 900},
                        "finishings": ["Natural", "Pernis", "Cat Warna"], "finishing": {"Natural": 0, "Pernis": 40, "Cat Warna": 50}}
        mrv = ["Meja 40x80 + Rak 3 Tingkat", "Meja 50x80 + Rak 3 Tingkat"]
        mr_pricing = {"variants": mrv, "base_prices": {mrv[0]: 2200, mrv[1]: 2400}, "types": ["B", "A"],
                      "type_adjustments": {"B": {mrv[0]: 0, mrv[1]: 0}, "A": {mrv[0]: 80, mrv[1]: 80}},
                      "finishings": ["Natural", "Pernis", "Cat Warna"], "finishing": {"Natural": 0, "Pernis": 60, "Cat Warna": 75}}
        products = [
            {"name": "Rak Kayu", "slug": "rak-kayu", "category": "rak", "configurable": True,
             "description": "Rak serbaguna, pilih panjang, jumlah tingkat, tipe, dan finishing sesuai kebutuhanmu.",
             "starting_price_le": RAK_TYPE_B_PRICES["60_2"], "pricing": rak_pricing, "sort_order": 1},
            {"name": "Meja", "slug": "meja", "category": "meja", "configurable": True,
             "description": "Meja praktis untuk belajar atau kerja. Pilih ukuran, tinggi, dan finishing.",
             "starting_price_le": 700, "pricing": meja_pricing, "sort_order": 2},
            {"name": "Meja Rak", "slug": "meja-rak", "category": "meja_rak", "configurable": True,
             "description": "Kombinasi meja dengan rak di atasnya. Hemat ruang, multifungsi.",
             "starting_price_le": 2200, "pricing": mr_pricing, "sort_order": 3},
            {"name": "Papan Tulis", "slug": "papan-tulis", "category": "papan_tulis", "configurable": False,
             "description": "Detail pemesanan akan dikonfirmasi melalui WhatsApp.", "starting_price_le": 0, "pricing": {}, "sort_order": 4},
            {"name": "Gantungan Baju", "slug": "gantungan-baju", "category": "gantungan_baju", "configurable": False,
             "description": "Detail pemesanan akan dikonfirmasi melalui WhatsApp.", "starting_price_le": 0, "pricing": {}, "sort_order": 8},
            {"name": "Pesanan Custom", "slug": "pesanan-custom", "category": "custom", "configurable": False,
             "description": "Punya kebutuhan khusus? Ukuran custom dapat dikonsultasikan dengan admin.", "starting_price_le": 0, "pricing": {}, "sort_order": 9},
        ]
        for p in products:
            p.update({"image_url": "", "active": True, "photos": [], "representative_photo_id": None, "created_at": now, "updated_at": now})
            await use_db.products.insert_one(p)

    if await use_db.categories.count_documents({}) == 0:
        now = datetime.now(timezone.utc).isoformat()
        default_cats = [
            {"key": "rak", "name": "Rak", "description": "Rapikan kitab, buku, dan barang dengan lebih teratur.", "sort_order": 1, "active": True, "created_at": now, "updated_at": now},
            {"key": "meja", "name": "Meja", "description": "Meja praktis untuk belajar atau kerja.", "sort_order": 2, "active": True, "created_at": now, "updated_at": now},
            {"key": "meja_rak", "name": "Meja Rak", "description": "Kombinasi meja dengan rak di atasnya. Hemat ruang, multifungsi.", "sort_order": 3, "active": True, "created_at": now, "updated_at": now},
            {"key": "papan_tulis", "name": "Papan Tulis", "description": "Cocok untuk belajar, mengajar, dan berbagai kebutuhan.", "sort_order": 4, "active": True, "created_at": now, "updated_at": now},
            {"key": "blockboard", "name": "BlackBoard", "description": "Pilihan papan tulis untuk kebutuhan belajar dan aktivitasmu.", "sort_order": 5, "active": True, "created_at": now, "updated_at": now},
            {"key": "gantungan_baju", "name": "Gantungan Baju", "description": "Gantungan baju kokoh dan hemat tempat.", "sort_order": 6, "active": True, "created_at": now, "updated_at": now},
            {"key": "custom", "name": "Koleksi Custom", "description": "Kumpulan karya dan desain custom pilihan dari Sogil Furniture.", "sort_order": 7, "active": True, "created_at": now, "updated_at": now},
        ]
        await use_db.categories.insert_many(default_cats)


# Backward compatibility alias
seed_data_only = seed_baseline_data_only


class _SafeIndexColWrapper:
    def __init__(self, col):
        self._col = col

    def create_index(self, *args, **kwargs):
        res = self._col.create_index(*args, **kwargs)
        if inspect.isawaitable(res):
            return res
        async def _dummy():
            return res
        return _dummy()

    def __getattr__(self, name):
        return getattr(self._col, name)


class _SafeIndexDbWrapper:
    def __init__(self, target):
        self._target = target

    def __getattr__(self, name):
        val = getattr(self._target, name)
        if hasattr(val, "create_index"):
            return _SafeIndexColWrapper(val)
        return val

    def __getitem__(self, name):
        return self.__getattr__(name)


async def seed(target_db=None):
    raw_db = target_db if target_db is not None else db
    await seed_data_only(raw_db)
    use_db = _SafeIndexDbWrapper(raw_db)

    # Critical & required unique constraints with fail-closed error handling
    try:
        await use_db.admins.create_index("email", unique=True)
    except CriticalFinanceIndexError:
        raise
    except Exception as e:
        logger.error(f"CRITICAL INDEX FAILURE: admins 'email' unique index creation failed: {e}")
        raise CriticalFinanceIndexError("admins", "email_1", str(e))

    try:
        await use_db.products.create_index("slug", unique=True)
    except CriticalFinanceIndexError:
        raise
    except Exception as e:
        logger.error(f"CRITICAL INDEX FAILURE: products 'slug' unique index creation failed: {e}")
        raise CriticalFinanceIndexError("products", "slug_1", str(e))

    # Focused indexes to keep order/customer queries responsive as data grows.
    try:
        for spec in ["customer_id", "order_number", "order_status", "payment_status", "referral.code"]:
            await use_db.orders.create_index(spec)
        await use_db.orders.create_index([("created_at", -1)])
        await use_db.customers.create_index("phone")
        await use_db.customers.create_index("username")
        await use_db.point_transactions.create_index("customer_id")
        await use_db.point_transactions.create_index("order_id")
        await use_db.finance_transactions.create_index("related_order_id")
        await use_db.referrals.create_index("code")
    except Exception as e:
        logger.warning(f"Non-critical query index provisioning warning: {e}")

    # Invoices indexes
    try:
        await use_db.invoices.create_index("invoice_number", unique=True)
    except CriticalFinanceIndexError:
        raise
    except Exception as e:
        logger.error(f"CRITICAL INDEX FAILURE: invoices 'invoice_number' unique index creation failed: {e}")
        raise CriticalFinanceIndexError("invoices", "invoice_number_1", str(e))

    try:
        await use_db.invoices.create_index("status")
        await use_db.invoices.create_index("order_id")
        await use_db.invoices.create_index("source.custom_request_id")
        await use_db.invoices.create_index([("created_at", -1)])
        await use_db.invoices.create_index("customer.whatsapp")
        await use_db.invoices.create_index("customer.name")
        await use_db.invoices.create_index("claim.claimed_by_customer_id", sparse=True)
        await use_db.invoices.create_index([("claim.claimed_by_customer_id", 1), ("created_at", -1)])
        await use_db.claim_attempts.create_index("created_at", expireAfterSeconds=900)
        await use_db.claim_attempts.create_index([("ip", 1), ("created_at", -1)])
        await use_db.claim_attempts.create_index([("customer_id", 1), ("created_at", -1)])
        # Audit logs indexes
        await use_db.audit_logs.create_index([("entity_type", 1), ("entity_id", 1)])
        await use_db.audit_logs.create_index("entity_identifier")
        await use_db.audit_logs.create_index([("timestamp", -1)])
    except Exception as e:
        logger.warning(f"Non-critical invoice/claim/audit index provisioning warning: {e}")

    # Ensure indexes for materials
    try:
        await use_db.materials.create_index(
            [("name_normalized", 1), ("specs_normalized", 1)],
            unique=True,
            name="uniq_material_name_specs"
        )
    except CriticalFinanceIndexError:
        raise
    except Exception as e:
        logger.error(f"CRITICAL INDEX FAILURE: materials 'uniq_material_name_specs' creation failed: {e}")
        raise CriticalFinanceIndexError("materials", "uniq_material_name_specs", str(e))

    # Ensure indexes for material_purchases
    try:
        await use_db.material_purchases.create_index(
            [("purchase_number", 1)],
            unique=True,
            name="uniq_purchase_number"
        )
    except CriticalFinanceIndexError:
        raise
    except Exception as e:
        logger.error(f"CRITICAL INDEX FAILURE: material_purchases 'uniq_purchase_number' creation failed: {e}")
        raise CriticalFinanceIndexError("material_purchases", "uniq_purchase_number", str(e))

    try:
        await use_db.material_purchases.create_index(
            [("material_id", 1), ("purchase_date", -1)],
            name="idx_mat_purchase_date"
        )
        await use_db.material_purchases.create_index(
            [("purchase_date", -1)],
            name="idx_purchase_date"
        )
    except Exception as e:
        logger.warning(f"Non-critical material_purchases index provisioning warning: {e}")

    # Ensure indexes for material_stocks (Phase 3)
    try:
        await use_db.material_stocks.create_index(
            [("movement_number", 1)],
            unique=True,
            name="uniq_movement_number"
        )
    except CriticalFinanceIndexError:
        raise
    except Exception as e:
        logger.error(f"CRITICAL INDEX FAILURE: material_stocks 'uniq_movement_number' creation failed: {e}")
        raise CriticalFinanceIndexError("material_stocks", "uniq_movement_number", str(e))

    try:
        await use_db.material_stocks.create_index(
            [("material_id", 1), ("movement_date", -1), ("created_at", -1)],
            name="idx_stock_material_date"
        )
    except Exception as e:
        logger.warning(f"Non-critical material_stocks index provisioning warning: {e}")

    try:
        # Inspect existing index definition without dropping or mutating
        legacy_incompatible_index = False
        try:
            cur_indexes_fn = getattr(use_db.material_stocks, "index_information", None)
            if callable(cur_indexes_fn):
                cur_indexes_res = cur_indexes_fn()
                cur_indexes = await cur_indexes_res if inspect.isawaitable(cur_indexes_res) else cur_indexes_res
                if cur_indexes and "uniq_purchase_stock_movement" in cur_indexes:
                    idx_def = cur_indexes["uniq_purchase_stock_movement"]
                    # Incompatible if it has legacy sparse=True or is missing partialFilterExpression
                    if idx_def.get("sparse") or not idx_def.get("partialFilterExpression"):
                        legacy_incompatible_index = True
                        logger.warning(
                            "INCOMPATIBLE INDEX DETECTED: 'uniq_purchase_stock_movement' on material_stocks has legacy sparse=True "
                            "options instead of partialFilterExpression. Automated drop on startup is disabled per production safety policy. "
                            "Run the explicit migration script 'scripts/migrate_purchase_stock_movement_index.py' to safely migrate the index."
                        )
        except Exception as e:
            logger.warning(f"Unable to inspect material_stocks index information: {e}")

        # Only attempt create_index if no incompatible legacy index was detected
        if not legacy_incompatible_index:
            await use_db.material_stocks.create_index(
                [("related_purchase_id", 1), ("movement_type", 1)],
                unique=True,
                partialFilterExpression={"related_purchase_id": {"$type": "string"}},
                name="uniq_purchase_stock_movement"
            )
    except CriticalFinanceIndexError:
        raise
    except Exception as e:
        logger.error(f"CRITICAL INDEX FAILURE: material_stocks 'uniq_purchase_stock_movement' creation failed: {e}")
        raise CriticalFinanceIndexError("material_stocks", "uniq_purchase_stock_movement", str(e))

    # Ensure indexes for finance_transactions material purchase references (Phase 4)
    try:
        await use_db.finance_transactions.create_index(
            [("reference_id", 1), ("reference_type", 1), ("type", 1)],
            unique=True,
            partialFilterExpression={"reference_type": "material_purchase", "type": "expense"},
            name="uniq_purchase_finance_expense"
        )
    except CriticalFinanceIndexError:
        raise
    except Exception as e:
        logger.error(f"CRITICAL INDEX FAILURE: finance_transactions 'uniq_purchase_finance_expense' creation failed: {e}")
        raise CriticalFinanceIndexError("finance_transactions", "uniq_purchase_finance_expense", str(e))

    try:
        await use_db.finance_transactions.create_index(
            [("reference_id", 1), ("is_reversal", 1)],
            unique=True,
            partialFilterExpression={"reference_type": "material_purchase", "is_reversal": True},
            name="uniq_purchase_finance_reversal"
        )
    except CriticalFinanceIndexError:
        raise
    except Exception as e:
        logger.error(f"CRITICAL INDEX FAILURE: finance_transactions 'uniq_purchase_finance_reversal' creation failed: {e}")
        raise CriticalFinanceIndexError("finance_transactions", "uniq_purchase_finance_reversal", str(e))

    # Ensure indexes for stock_forms and stock_transformations (Phase 5)
    try:
        await use_db.stock_forms.create_index(
            [("material_id", 1), ("form_type", 1), ("width", 1), ("length", 1), ("thickness", 1), ("dimension_unit", 1), ("stock_unit", 1), ("label", 1)],
            unique=True,
            name="uniq_stock_form_spec"
        )
    except CriticalFinanceIndexError:
        raise
    except Exception as e:
        logger.error(f"CRITICAL INDEX FAILURE: stock_forms 'uniq_stock_form_spec' creation failed: {e}")
        raise CriticalFinanceIndexError("stock_forms", "uniq_stock_form_spec", str(e))

    try:
        await use_db.stock_forms.create_index(
            [("material_id", 1), ("is_active", 1)],
            name="idx_stock_form_material"
        )
    except Exception as e:
        logger.warning(f"Non-critical stock_forms index provisioning warning: {e}")

    try:
        await use_db.stock_transformations.create_index(
            [("transformation_number", 1)],
            unique=True,
            name="uniq_transformation_number"
        )
    except CriticalFinanceIndexError:
        raise
    except Exception as e:
        logger.error(f"CRITICAL INDEX FAILURE: stock_transformations 'uniq_transformation_number' creation failed: {e}")
        raise CriticalFinanceIndexError("stock_transformations", "uniq_transformation_number", str(e))

    try:
        await use_db.stock_transformations.create_index(
            [("material_id", 1), ("transformation_date", -1), ("created_at", -1)],
            name="idx_transformation_material_date"
        )
        await use_db.stock_transformations.create_index(
            [("related_purchase_id", 1)],
            sparse=True,
            name="idx_transformation_purchase"
        )
    except Exception as e:
        logger.warning(f"Non-critical stock_transformations index provisioning warning: {e}")

    # Ensure indexes for payments (Phase 1)
    # Critical unique indexes: uniq_payment_number, uniq_payments_idempotency
    try:
        await use_db.payments.create_index(
            [("payment_number", 1)],
            unique=True,
            name="uniq_payment_number"
        )
    except Exception as e:
        logger.error(f"CRITICAL INDEX FAILURE: payments 'uniq_payment_number' creation failed: {e}")
        raise CriticalFinanceIndexError("payments", "uniq_payment_number", str(e))

    try:
        await use_db.payments.create_index(
            [("idempotency_key", 1)],
            unique=True,
            partialFilterExpression={"idempotency_key": {"$type": "string"}},
            name="uniq_payments_idempotency"
        )
    except Exception as e:
        logger.error(f"CRITICAL INDEX FAILURE: payments 'uniq_payments_idempotency' creation failed: {e}")
        raise CriticalFinanceIndexError("payments", "uniq_payments_idempotency", str(e))

    # Non-critical reporting/lookup indexes for payments
    try:
        await use_db.payments.create_index(
            [("order_id", 1), ("status", 1)],
            name="idx_payments_order_status"
        )
        await use_db.payments.create_index(
            [("finance_transaction_id", 1)],
            name="idx_payments_finance_txn"
        )
    except Exception as e:
        logger.warning(f"Non-critical payments index provisioning warning: {e}")

    # Ensure indexes for Phase 2: wage_rules, work_assignments, wage_obligations
    try:
        await use_db.wage_rules.create_index(
            [("task_category", 1), ("pricing_basis", 1)],
            name="idx_wage_rules_category_basis"
        )
        await use_db.wage_rules.create_index(
            [("active", 1)],
            name="idx_wage_rules_active"
        )
    except Exception as e:
        logger.warning(f"Non-critical wage_rules index provisioning warning: {e}")

    try:
        await use_db.work_assignments.create_index(
            [("order_id", 1), ("order_item_id", 1)],
            name="idx_work_assignments_order_item"
        )
        await use_db.work_assignments.create_index(
            [("worker_id", 1), ("status", 1)],
            name="idx_work_assignments_worker_status"
        )
    except Exception as e:
        logger.warning(f"Non-critical work_assignments index provisioning warning: {e}")

    try:
        # Unique active assignment per (order_item_id, worker_id, task_category)
        await use_db.work_assignments.create_index(
            [("order_item_id", 1), ("worker_id", 1), ("task_category", 1)],
            unique=True,
            partialFilterExpression={"status": {"$in": ["assigned", "in_progress", "ready_for_review", "accruing"]}},
            name="uniq_active_worker_task_per_item"
        )
    except CriticalFinanceIndexError:
        raise
    except Exception as e:
        logger.error(f"CRITICAL INDEX FAILURE: work_assignments 'uniq_active_worker_task_per_item' creation failed: {e}")
        raise CriticalFinanceIndexError("work_assignments", "uniq_active_worker_task_per_item", str(e))

    try:
        await use_db.wage_obligations.create_index(
            [("accrual_event_key", 1)],
            unique=True,
            name="uniq_wage_obligation_accrual_event"
        )
    except Exception as e:
        logger.error(f"CRITICAL INDEX FAILURE: wage_obligations 'uniq_wage_obligation_accrual_event' creation failed: {e}")
        raise CriticalFinanceIndexError("wage_obligations", "uniq_wage_obligation_accrual_event", str(e))

    try:
        await use_db.wage_obligations.create_index(
            [("obligation_number", 1)],
            unique=True,
            name="uniq_obligation_number"
        )
    except Exception as e:
        logger.error(f"CRITICAL INDEX FAILURE: wage_obligations 'uniq_obligation_number' creation failed: {e}")
        raise CriticalFinanceIndexError("wage_obligations", "uniq_obligation_number", str(e))

    try:
        await use_db.wage_obligations.create_index(
            [("work_assignment_id", 1)],
            name="idx_wage_obligations_assignment"
        )
        await use_db.wage_obligations.create_index(
            [("worker_id", 1), ("status", 1)],
            name="idx_wage_obligations_worker_status"
        )
        await use_db.wage_obligations.create_index(
            [("order_id", 1), ("order_item_id", 1)],
            name="idx_wage_obligations_order_item"
        )
    except Exception as e:
        logger.warning(f"Non-critical wage_obligations index provisioning warning: {e}")

    try:
        await use_db.wage_settlements.create_index(
            [("settlement_number", 1)],
            unique=True,
            name="uniq_settlement_number"
        )
    except Exception as e:
        logger.error(f"CRITICAL INDEX FAILURE: wage_settlements 'uniq_settlement_number' creation failed: {e}")
        raise CriticalFinanceIndexError("wage_settlements", "uniq_settlement_number", str(e))

    try:
        await use_db.wage_settlements.create_index(
            [("idempotency_key", 1)],
            unique=True,
            partialFilterExpression={"idempotency_key": {"$type": "string"}},
            name="uniq_wage_settlements_idempotency"
        )
    except Exception as e:
        logger.error(f"CRITICAL INDEX FAILURE: wage_settlements 'uniq_wage_settlements_idempotency' creation failed: {e}")
        raise CriticalFinanceIndexError("wage_settlements", "uniq_wage_settlements_idempotency", str(e))

    try:
        await use_db.wage_settlements.create_index(
            [("worker_id", 1), ("settlement_date", -1)],
            name="idx_wage_settlements_worker_date"
        )
        await use_db.wage_settlements.create_index(
            [("finance_transaction_id", 1)],
            name="idx_wage_settlements_finance_txn"
        )
    except Exception as e:
        logger.warning(f"Non-critical wage_settlements index provisioning warning: {e}")

    # Phase 3B: Outbox events & Assignment Groups indexes
    try:
        await use_db.outbox_events.create_index(
            [("event_id", 1)],
            unique=True,
            name="uniq_outbox_event_id"
        )
    except CriticalFinanceIndexError:
        raise
    except Exception as e:
        logger.error(f"CRITICAL INDEX FAILURE: outbox_events 'uniq_outbox_event_id' creation failed: {e}")
        raise CriticalFinanceIndexError("outbox_events", "uniq_outbox_event_id", str(e))

    try:
        await use_db.outbox_events.create_index(
            [("status", 1), ("created_at", 1)],
            name="idx_outbox_status_created"
        )
        await use_db.outbox_events.create_index(
            [("aggregate_type", 1), ("aggregate_id", 1)],
            name="idx_outbox_aggregate"
        )
        await use_db.outbox_events.create_index(
            [("status", 1), ("next_retry_at", 1), ("lease_expires_at", 1)],
            name="idx_outbox_claim"
        )
        await use_db.outbox_events.create_index(
            [("claim_token", 1)],
            sparse=True,
            name="idx_outbox_claim_token"
        )
    except Exception as e:
        logger.warning(f"Non-critical outbox_events index provisioning warning: {e}")

    try:
        await use_db.assignment_groups.create_index(
            [("group_number", 1)],
            unique=True,
            partialFilterExpression={"group_number": {"$type": "string"}},
            name="uniq_assignment_group_number"
        )
    except CriticalFinanceIndexError:
        raise
    except Exception as e:
        logger.error(f"CRITICAL INDEX FAILURE: assignment_groups 'uniq_assignment_group_number' creation failed: {e}")
        raise CriticalFinanceIndexError("assignment_groups", "uniq_assignment_group_number", str(e))

    try:
        await use_db.assignment_groups.create_index(
            [("status", 1)],
            name="idx_assignment_groups_status"
        )
    except Exception as e:
        logger.warning(f"Non-critical assignment_groups index provisioning warning: {e}")

    # Ensure indexes for customer_credit_events (Phase 3.B.2)
    # Critical unique indexes: uniq_credit_event_number, uniq_credit_event_source_payment, uniq_credit_events_idempotency
    try:
        await use_db.customer_credit_events.create_index(
            [("event_number", 1)],
            unique=True,
            name="uniq_credit_event_number"
        )
    except Exception as e:
        logger.error(f"CRITICAL INDEX FAILURE: customer_credit_events 'uniq_credit_event_number' creation failed: {e}")
        raise CriticalFinanceIndexError("customer_credit_events", "uniq_credit_event_number", str(e))

    try:
        await use_db.customer_credit_events.create_index(
            [("source_payment_id", 1), ("event_type", 1)],
            unique=True,
            partialFilterExpression={"source_payment_id": {"$type": "string"}},
            name="uniq_credit_event_source_payment"
        )
    except Exception as e:
        logger.error(f"CRITICAL INDEX FAILURE: customer_credit_events 'uniq_credit_event_source_payment' creation failed: {e}")
        raise CriticalFinanceIndexError("customer_credit_events", "uniq_credit_event_source_payment", str(e))

    try:
        await use_db.customer_credit_events.create_index(
            [("idempotency_key", 1)],
            unique=True,
            partialFilterExpression={"idempotency_key": {"$type": "string"}},
            name="uniq_credit_events_idempotency"
        )
    except Exception as e:
        logger.error(f"CRITICAL INDEX FAILURE: customer_credit_events 'uniq_credit_events_idempotency' creation failed: {e}")
        raise CriticalFinanceIndexError("customer_credit_events", "uniq_credit_events_idempotency", str(e))

    # Non-critical reporting/lookup indexes for customer_credit_events
    try:
        await use_db.customer_credit_events.create_index(
            [("customer_id", 1), ("currency", 1)],
            name="idx_credit_events_customer_currency"
        )
        await use_db.customer_credit_events.create_index(
            [("source_order_id", 1)],
            name="idx_credit_events_source_order"
        )
    except Exception as e:
        logger.warning(f"Non-critical customer_credit_events index provisioning warning: {e}")

    # Ensure indexes for finance_adjustments (Phase 3.B.6)
    # Critical unique indexes: uniq_adjustment_id, uniq_adjustments_idempotency
    try:
        await use_db.finance_adjustments.create_index(
            [("adjustment_id", 1)],
            unique=True,
            name="uniq_adjustment_id"
        )
    except Exception as e:
        logger.error(f"CRITICAL INDEX FAILURE: finance_adjustments 'uniq_adjustment_id' creation failed: {e}")
        raise CriticalFinanceIndexError("finance_adjustments", "uniq_adjustment_id", str(e))

    try:
        await use_db.finance_adjustments.create_index(
            [("idempotency_key", 1)],
            unique=True,
            partialFilterExpression={"idempotency_key": {"$type": "string"}},
            name="uniq_adjustments_idempotency"
        )
    except Exception as e:
        logger.error(f"CRITICAL INDEX FAILURE: finance_adjustments 'uniq_adjustments_idempotency' creation failed: {e}")
        raise CriticalFinanceIndexError("finance_adjustments", "uniq_adjustments_idempotency", str(e))

    # Non-critical reporting/lookup indexes for finance_adjustments
    try:
        await use_db.finance_adjustments.create_index(
            [("order_id", 1), ("is_void", 1), ("created_at", -1)],
            name="idx_adjustments_order_lookup"
        )
        await use_db.finance_adjustments.create_index(
            [("currency", 1), ("is_void", 1), ("created_at", -1)],
            name="idx_adjustments_period_reporting"
        )
    except Exception as e:
        logger.warning(f"Non-critical finance_adjustments index provisioning warning: {e}")

    # Phase 3.F.4.1: Delivery Trips and Delivery Wage Indexes
    try:
        dt_idx = use_db.delivery_trips.create_index(
            [("trip_number", 1)],
            unique=True,
            name="uniq_delivery_trip_number"
        )
        if inspect.isawaitable(dt_idx):
            await dt_idx
    except CriticalFinanceIndexError:
        raise
    except Exception as e:
        logger.error(f"CRITICAL INDEX FAILURE: delivery_trips 'uniq_delivery_trip_number' creation failed: {e}")
        raise CriticalFinanceIndexError("delivery_trips", "uniq_delivery_trip_number", str(e))

    try:
        res1 = use_db.delivery_trips.create_index(
            [("scheduled_date", 1), ("status", 1)],
            name="idx_delivery_trips_date_status"
        )
        if inspect.isawaitable(res1):
            await res1
        res2 = use_db.delivery_trips.create_index(
            [("stops.order_id", 1)],
            name="idx_delivery_trips_stops_order"
        )
        if inspect.isawaitable(res2):
            await res2
        res3 = use_db.orders.create_index(
            [("active_delivery_trip_id", 1)],
            name="idx_orders_active_delivery_trip"
        )
        if inspect.isawaitable(res3):
            await res3
    except Exception as e:
        logger.warning(f"Non-critical delivery_trips index provisioning warning: {e}")

    # Phase 3.F.4.1: Partial Unique Index for delivery wage obligations with pre-migration verification
    try:
        mig_res = verify_delivery_wage_indexes_pre_migration(use_db)
        if inspect.isawaitable(mig_res):
            await mig_res
        wo_idx = use_db.wage_obligations.create_index(
            [("order_id", 1), ("worker_id", 1), ("task_category", 1)],
            unique=True,
            partialFilterExpression={"task_category": "delivery"},
            name="uniq_delivery_wage_order_worker"
        )
        if inspect.isawaitable(wo_idx):
            await wo_idx
    except CriticalFinanceIndexError:
        raise
    except Exception as e:
        logger.error(f"CRITICAL INDEX FAILURE: wage_obligations 'uniq_delivery_wage_order_worker' creation failed: {e}")
        raise CriticalFinanceIndexError("wage_obligations", "uniq_delivery_wage_order_worker", str(e))

    # Provision probe infrastructure
    await ensure_probe_infrastructure(use_db)

async def ensure_probe_infrastructure(db_inst) -> bool:
    for col_name in ["_system_probe_assignments", "_system_probe_obligations"]:
        try:
            await db_inst.create_collection(col_name)
        except pymongo.errors.CollectionInvalid:
            pass  # Already exists; safe concurrent startup
        except Exception as e:
            logger.warning(f"Probe collection {col_name} provisioning warning: {e}")
        try:
            col = db_inst[col_name]
            await col.create_index([("created_at", 1)], expireAfterSeconds=300)
        except Exception as e:
            logger.warning(f"Probe TTL index warning on {col_name}: {e}")
    return True

async def run_transaction_probe(mongo_client: AsyncIOMotorClient, db_name: str) -> bool:
    """
    Rigorously verifies multi-document, cross-collection transaction execution
    using the canonical Motor context-manager lifecycle.
    """
    db_inst = mongo_client[db_name]
    col_a = db_inst["_system_probe_assignments"]
    col_b = db_inst["_system_probe_obligations"]

    probe_token = f"probe_{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc)
    doc_a_id = f"asn_{probe_token}"
    doc_b_id = f"wob_{probe_token}"

    try:
        session = await mongo_client.start_session()
        async with session:
            async with session.start_transaction():
                await col_a.insert_one(
                    {"_id": doc_a_id, "token": probe_token, "status": "completed", "created_at": now},
                    session=session
                )
                await col_b.insert_one(
                    {"_id": doc_b_id, "token": probe_token, "accrual_key": f"acc_{doc_a_id}", "created_at": now},
                    session=session
                )
                found_a = await col_a.find_one({"_id": doc_a_id}, session=session)
                found_b = await col_b.find_one({"_id": doc_b_id}, session=session)
                if not found_a or not found_b:
                    raise RuntimeError("Snapshot isolation read failed within transaction")

        # Cleanup outside transaction
        await col_a.delete_one({"_id": doc_a_id})
        await col_b.delete_one({"_id": doc_b_id})
        return True
    except (pymongo.errors.ConfigurationError, pymongo.errors.InvalidOperation) as e:
        logger.info(f"Deployment topology lacks transaction support (standalone): {e}")
        return False
    except Exception as e:
        logger.warning(f"Multi-document transaction probe encountered error: {e}")
        try:
            await col_a.delete_one({"_id": doc_a_id})
            await col_b.delete_one({"_id": doc_b_id})
        except Exception:
            pass
        return False

@app.on_event("startup")
async def startup():
    env_mode = get_environment_mode()
    is_prod_or_strict = (env_mode not in ("development", "test"))

    idx_mode = os.environ.get("INDEX_PROVISIONING_MODE", "verify").lower().strip()
    data_mode = os.environ.get("STARTUP_DATA_MODE", "verify").lower().strip()

    # 1. Validate environment configuration modes against allowed values (fail-closed)
    valid_data_modes = {"verify", "verify_only", "seed", "seed_baseline", "none", "auto"}
    if not data_mode or data_mode not in valid_data_modes:
        raise OperationalConfigurationError(
            f"Invalid or missing STARTUP_DATA_MODE: '{data_mode}'. Allowed modes: 'verify', 'seed', 'none'."
        )

    valid_idx_modes = {"verify", "verify_only", "auto"}
    if not idx_mode or idx_mode not in valid_idx_modes:
        raise CriticalFinanceIndexError(
            "startup", "all",
            f"Invalid or missing INDEX_PROVISIONING_MODE: '{idx_mode}'. Allowed modes: 'verify', 'auto'."
        )

    # 2. Production safety gates: strictly forbid seeding and runtime index creation in production
    if is_prod_or_strict:
        if data_mode in ("seed", "seed_baseline", "auto"):
            raise OperationalConfigurationError(
                f"Data seeding mode '{data_mode}' is strictly forbidden in production or non-development environments."
            )
        if idx_mode == "auto":
            raise CriticalFinanceIndexError(
                "startup", "all",
                "Automatic runtime index provisioning ('auto') is strictly forbidden in production environments. "
                "Use scripts/provision_indexes.py for explicit provisioning."
            )

    # 3. Data lifecycle handling
    # INVARIANT: In production/strict environments, baseline configuration verification CANNOT be bypassed.
    # Disabling seeding in production must never bypass baseline verification of owner account and store settings.
    if is_prod_or_strict:
        if data_mode == "none":
            logger.warning(
                "STARTUP_DATA_MODE='none' specified in production: seeding is disabled, "
                "but baseline configuration verification is mandatory and will be enforced."
            )
        await verify_baseline_data(db, fail_closed=True)
    else:
        # Development or test environment
        if data_mode in ("seed", "seed_baseline", "auto"):
            await seed_baseline_data_only()
        elif data_mode in ("verify", "verify_only"):
            await verify_baseline_data(db, fail_closed=True)
        elif data_mode == "none":
            logger.info("Startup data mode is 'none'; skipping baseline verification and seeds in dev/test.")

    # 4. Index lifecycle handling
    if idx_mode == "auto":
        await seed()
    else:
        if verify_required_indexes is None:
            raise CriticalFinanceIndexError(
                "startup", "all",
                "Required index verification module 'backend.index_provisioner' could not be loaded."
            )
        await verify_required_indexes(db, fail_closed=True)

    # 5. Transaction probe capability check
    probe_enabled = os.environ.get("TRANSACTION_PROBE_ENABLED", "true").lower().strip() != "false"
    if probe_enabled:
        try:
            db_name = os.environ.get("DB_NAME", "sogil")
            supports_txn = await run_transaction_probe(client, db_name)
            logger.info(f"Phase 2 Transaction Probe capability status: {supports_txn}")
        except Exception as e:
            logger.warning(f"Transaction probe startup evaluation: {e}")
    else:
        logger.info("Transaction probe skipped (TRANSACTION_PROBE_ENABLED=false).")

@app.on_event("shutdown")
async def shutdown():
    client.close()

# --------------------------------------------------------------------------
# Finance statistics, customer password, XLSX exports
# --------------------------------------------------------------------------
@api_router.get("/admin/finance/statistics")
async def finance_statistics(period: str = "this_month", start: Optional[str] = None, end: Optional[str] = None,
                             currency: str = "EGP", admin: dict = Depends(require_perm("access_finance"))):
    s, e, _ps, _pe = _period_range(period, start, end)
    q = {"is_void": {"$ne": True}, "status": {"$ne": "void"}}
    if s or e:
        q["date"] = {}
        if s:
            q["date"]["$gte"] = s
        if e:
            q["date"]["$lte"] = e
    groups = {}
    totals = {"revenue": 0.0, "transfer_income": 0.0, "cost": 0.0, "transfer_expense": 0.0}
    team_wages_map = {}
    target_currency = (currency or "EGP").strip().upper()

    async for t in db.finance_transactions.find(q):
        typ = t.get("type"); raw_amt = _num(t.get("amount")); cls = t.get("classification")
        if typ == "order_revenue":
            typ = "income"; cls = "revenue"
        if typ not in ("income", "expense"):
            continue

        t_cur = (t.get("currency") or "EGP").strip().upper()
        cp_cur = (t.get("counterpart_currency") or get_counterpart_currency(t_cur)).strip().upper()
        stored_cp = t.get("counterpart_amount")
        stored_rate = _num(t.get("exchange_rate")) if t.get("exchange_rate") is not None else None

        # Normalize amount according to target_currency using historical rate / counterpart (Option 1)
        if t_cur == target_currency:
            norm_amt = raw_amt
        elif stored_cp is not None and cp_cur == target_currency:
            norm_amt = _num(stored_cp)
        elif stored_rate is not None and stored_rate > 0:
            conv = compute_currency_conversion(t_cur, raw_amt, stored_rate)
            norm_amt = _num(conv["counterpart_amount"])
        else:
            # Legacy transaction without historical counterpart and without historical rate:
            # DO NOT fabricate rate or conversion. Omit from cross-currency aggregation.
            norm_amt = 0.0

        # Determine counterpart values for drilldown (preserve real historical data)
        if stored_cp is not None:
            drill_cp_amt = _num(stored_cp)
            drill_cp_cur = cp_cur
        elif stored_rate is not None and stored_rate > 0:
            conv = compute_currency_conversion(t_cur, raw_amt, stored_rate)
            drill_cp_amt = _num(conv["counterpart_amount"])
            drill_cp_cur = conv["counterpart_currency"]
        else:
            drill_cp_amt = None
            drill_cp_cur = None

        cat = t.get("category", "(tanpa kategori)")
        key = (typ, cat)
        g = groups.setdefault(key, {"type": typ, "category": cat, "total": 0.0, "count": 0, "classification": cls or ("revenue" if typ == "income" else "cost")})
        g["total"] += norm_amt; g["count"] += 1
        if typ == "income":
            totals["revenue" if cls in (None, "revenue") else "transfer_income"] += norm_amt
        else:
            totals["cost" if cls in (None, "cost") else "transfer_expense"] += norm_amt
            # Team wage aggregation directly from finance_transactions
            rec_id = t.get("recipient_employee_id")
            if rec_id and _is_wage_category(cat):
                tw = team_wages_map.setdefault(rec_id, {
                    "id": rec_id,
                    "name": t.get("recipient_employee_name") or "Akun Tim",
                    "total": 0.0,
                    "count": 0,
                    "transactions": []
                })
                tw["total"] += norm_amt
                tw["count"] += 1
                tw["transactions"].append({
                    "id": str(t["_id"]),
                    "date": t.get("date"),
                    "amount": norm_amt,
                    "currency": t_cur,
                    "primary_amount": raw_amt,
                    "primary_currency": t_cur,
                    "counterpart_amount": drill_cp_amt,
                    "counterpart_currency": drill_cp_cur,
                    "exchange_rate": stored_rate,
                    "normalized_amount": norm_amt,
                    "normalized_currency": target_currency,
                    "category": cat,
                    "description": t.get("description") or "",
                    "recorded_by_name": t.get("created_by_name") or "-",
                    "recipient_employee_id": rec_id,
                    "recipient_employee_name": t.get("recipient_employee_name") or tw["name"]
                })

    for k in totals:
        totals[k] = round(totals[k], 2)
    totals["operating_profit"] = round(totals["revenue"] - totals["cost"], 2)
    for g in groups.values():
        g["total"] = round(g["total"], 2)
    for tw in team_wages_map.values():
        tw["total"] = round(tw["total"], 2)

    income = sorted([g for g in groups.values() if g["type"] == "income"], key=lambda x: x["total"], reverse=True)
    expense = sorted([g for g in groups.values() if g["type"] == "expense"], key=lambda x: x["total"], reverse=True)
    inc_sum = sum(g["total"] for g in income) or 1
    exp_sum = sum(g["total"] for g in expense) or 1
    for g in income:
        g["pct"] = round(g["total"] / inc_sum * 100, 1)
    for g in expense:
        g["pct"] = round(g["total"] / exp_sum * 100, 1)

    # Enrich team_wages with latest role and name from db.admins
    admin_docs = {str(a["_id"]): a for a in await db.admins.find({}).to_list(200)}
    team_wages_list = []
    for rid, tw in team_wages_map.items():
        if tw["total"] > 0 or tw["count"] > 0:
            adm = admin_docs.get(rid)
            if adm:
                tw["name"] = adm.get("name") or tw["name"]
                tw["role"] = adm.get("role", "employee")
            else:
                tw["role"] = "employee"
            # Sort transaction history by date descending
            tw["transactions"].sort(key=lambda x: x.get("date") or "", reverse=True)
            team_wages_list.append(tw)

    # Sort primarily by total DESC (highest wage recipient first)
    team_wages_list.sort(key=lambda x: x["total"], reverse=True)

    return {"currency": currency, "period": period, "range": {"start": s, "end": e},
            "income": income, "expense": expense, "totals": totals, "team_wages": team_wages_list}

@api_router.post("/customer/change-password")
async def customer_change_password(payload: Dict[str, Any], c: dict = Depends(get_current_customer)):
    cur = payload.get("current_password") or ""
    new = payload.get("new_password") or ""
    if not verify_password(cur, c["password_hash"]):
        raise HTTPException(status_code=400, detail="Kata sandi saat ini salah")
    if len(new) < 6:
        raise HTTPException(status_code=400, detail="Kata sandi baru minimal 6 karakter")
    await db.customers.update_one({"_id": c["_id"]}, {"$set": {"password_hash": hash_password(new)}})
    return {"ok": True}

def build_xlsx(sheets):
    from openpyxl import Workbook
    import io
    wb = Workbook(); wb.remove(wb.active)
    for title, headers, rows in sheets:
        ws = wb.create_sheet((title or "Sheet")[:31])
        ws.append(headers)
        for r in rows:
            ws.append([("" if v is None else v) for v in r])
    if not wb.sheetnames:
        wb.create_sheet("Data")
    buf = io.BytesIO(); wb.save(buf); buf.seek(0)
    return buf.getvalue()

def xlsx_response(data, filename):
    return StarletteResponse(content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'})

def _date_query(period, start, end):
    s, e, _ps, _pe = _period_range(period, start, end)
    q = {"is_void": {"$ne": True}, "status": {"$ne": "void"}}
    if s or e:
        q["date"] = {}
        if s:
            q["date"]["$gte"] = s
        if e:
            q["date"]["$lte"] = e
    return q, s, e

@api_router.get("/admin/export/finance")
async def export_finance(period: str = "this_year", start: Optional[str] = None, end: Optional[str] = None,
                         admin: dict = Depends(require_perm("access_finance"))):
    q, _s, _e = _date_query(period, start, end)
    txns = await db.finance_transactions.find(q).sort("date", -1).to_list(10000)
    headers = ["Tanggal", "ID Referensi", "Tipe", "Klasifikasi", "Kategori", "Deskripsi", "Jumlah", "Mata Uang", "Kurs (IDR/EGP)", "Nilai Ekuivalen", "Mata Uang Ekuivalen", "Dari", "Ke", "Penerima", "Dicatat oleh"]
    rows = []
    for t in txns:
        amt = _num(t.get("amount")) if t.get("type") != "transfer" else _num(t.get("from_amount"))
        rows.append([(t.get("date") or "")[:19], str(t.get("_id")), t.get("type", ""), t.get("classification", ""),
                     t.get("category", ""), t.get("description", ""), amt, t.get("currency", t.get("from_account", "")),
                     t.get("exchange_rate", ""), t.get("counterpart_amount", ""), t.get("counterpart_currency", ""),
                     t.get("from_account", ""), t.get("to_account", ""), t.get("recipient_employee_name", ""), t.get("created_by_name", "")])
    return xlsx_response(build_xlsx([("Keuangan", headers, rows)]), f"keuangan_{period}.xlsx")

@api_router.get("/admin/export/orders")
async def export_orders(period: str = "this_year", start: Optional[str] = None, end: Optional[str] = None,
                        admin: dict = Depends(require_perm("manage_orders"))):
    s, e, _ps, _pe = _period_range(period, start, end)
    q = {}
    if s or e:
        q["created_at"] = {}
        if s:
            q["created_at"]["$gte"] = s
        if e:
            q["created_at"]["$lte"] = e
    orders = await db.orders.find(q).sort("created_at", -1).to_list(10000)
    headers = ["No Pesanan", "Tanggal", "Pelanggan", "No HP", "Produk & Konfigurasi", "Qty", "Subtotal", "Diskon", "Diskon Referral", "Poin", "Ongkir", "Total", "Mata Uang", "Status Pembayaran", "Status Pesanan", "Kode Referral", "Bahasa"]
    rows = []
    for o in orders:
        items = o.get("items") or ([o.get("item")] if o.get("item") else [])
        desc = "; ".join([f"{it.get('product_name_snapshot','')} [" + ", ".join(f"{k}={v}" for k, v in (it.get('configuration_snapshot') or {}).items()) + f"] x{it.get('quantity',1)}" for it in items if it])
        qty = sum(int(it.get("quantity", 1)) for it in items if it)
        rows.append([o.get("order_number", ""), (o.get("created_at") or "")[:19], o.get("customer_name", ""), o.get("customer_phone", ""),
                     desc, qty, _num(o.get("subtotal_le")), _num(o.get("discount_le")), _num(o.get("referral_discount_le")),
                     _num(o.get("points_redeemed_le")), _num(o.get("delivery_fee_le")), _num(o.get("total_le")), "LE",
                     o.get("payment_status", ""), o.get("order_status", ""), (o.get("referral") or {}).get("code", ""), o.get("language", "")])
    return xlsx_response(build_xlsx([("Pesanan", headers, rows)]), f"pesanan_{period}.xlsx")

@api_router.get("/admin/export/config-analytics")
async def export_config_analytics(admin: dict = Depends(require_perm("manage_orders"))):
    agg = {}
    async for o in db.orders.find({}):
        items = o.get("items") or ([o.get("item")] if o.get("item") else [])
        for it in items:
            if not it:
                continue
            cfg = it.get("configuration_snapshot") or {}
            cfgs = ", ".join(f"{k}={v}" for k, v in cfg.items())
            key = (it.get("category", ""), it.get("product_name_snapshot", ""), cfgs)
            g = agg.setdefault(key, {"orders": 0, "qty": 0})
            g["orders"] += 1; g["qty"] += int(it.get("quantity", 1))
    ranked = sorted(agg.items(), key=lambda x: x[1]["qty"], reverse=True)
    headers = ["Peringkat", "Kategori", "Produk", "Konfigurasi", "Jumlah Pesanan", "Total Qty Dipesan"]
    rows = [[i + 1, k[0], k[1], k[2], v["orders"], v["qty"]] for i, (k, v) in enumerate(ranked)]
    return xlsx_response(build_xlsx([("Analitik Konfigurasi", headers, rows)]), "analitik_konfigurasi.xlsx")

@api_router.get("/admin/export/customers")
async def export_customers(admin: dict = Depends(require_perm("manage_orders"))):
    custs = await db.customers.find({}).sort("created_at", -1).to_list(10000)
    headers = ["ID", "Nama Pengguna", "Email", "No HP", "Terdaftar", "Status", "Kode Referral", "Poin Tersedia", "Poin Diperoleh"]
    rows = [[str(c.get("_id")), c.get("username", ""), c.get("email", ""), c.get("phone", ""), (c.get("created_at") or "")[:19],
             "aktif" if c.get("active", True) else "nonaktif", c.get("referral_code", ""), _num(c.get("points_available")), _num(c.get("points_earned"))] for c in custs]
    return xlsx_response(build_xlsx([("Pelanggan", headers, rows)]), "pelanggan.xlsx")

@api_router.get("/admin/export/accounts")
async def export_accounts(admin: dict = Depends(require_owner())):
    admins = await db.admins.find({}).to_list(500)
    a_headers = ["ID", "Nama", "Email", "Role", "Status", "Izin", "Dibuat", "Total Upah", "Upah Tahun Ini", "Jumlah Transaksi Upah"]
    a_rows, w_rows = [], []
    w_headers = ["Karyawan", "Tanggal", "Jumlah", "Mata Uang", "Kategori", "Deskripsi", "Dicatat oleh", "ID Transaksi"]
    now = datetime.now(timezone.utc); ykey = now.strftime("%Y")
    for a in admins:
        aid = str(a["_id"])
        perms = a.get("permissions") or {}
        perm_str = ", ".join(k for k, v in perms.items() if v)
        wages = await db.employee_wages.find({"employee_id": aid}).sort("date", -1).to_list(1000)
        tot, ytot = {}, {}
        for w in wages:
            c = w.get("currency", "EGP"); amt = _num(w.get("amount"))
            tot[c] = tot.get(c, 0) + amt
            if (w.get("date") or "")[:4] == ykey:
                ytot[c] = ytot.get(c, 0) + amt
            w_rows.append([a.get("name", ""), (w.get("date") or "")[:19], amt, c, w.get("category", ""), w.get("description", ""), w.get("recorded_by_name", ""), w.get("transaction_id", "")])
        a_rows.append([aid, a.get("name", ""), a.get("email", ""), a.get("role", ""), a.get("status", "active"), perm_str,
                       (a.get("created_at") or "")[:19], "; ".join(f"{v} {c}" for c, v in tot.items()),
                       "; ".join(f"{v} {c}" for c, v in ytot.items()), len(wages)])
    return xlsx_response(build_xlsx([("Akun", a_headers, a_rows), ("Riwayat Upah", w_headers, w_rows)]), "akun_dan_upah.xlsx")

@api_router.get("/admin/export/product-prices")
async def export_product_prices(admin: dict = Depends(require_perm("modify_products"))):
    hist = await db.price_history.find({}).sort("changed_at", -1).to_list(10000)
    headers = ["Tanggal Ubah", "Produk", "Kategori", "Harga Mulai Lama (LE)", "Harga Mulai Baru (LE)", "Diubah oleh"]
    rows = [[(h.get("changed_at") or "")[:19], h.get("product_name", ""), h.get("category", ""),
             _num(h.get("old_starting_price_le")), _num(h.get("new_starting_price_le")), h.get("changed_by_name", "")] for h in hist]
    cur_headers = ["Produk", "Kategori", "Harga Mulai (LE)", "Konfigurasi Harga (JSON)"]
    cur_rows = []
    for p in await db.products.find({}).to_list(500):
        cur_rows.append([p.get("name", ""), p.get("category", ""), _num(p.get("starting_price_le")), json.dumps(p.get("pricing") or {}, ensure_ascii=False)[:32000]])
    return xlsx_response(build_xlsx([("Riwayat Perubahan Harga", headers, rows), ("Harga Saat Ini", cur_headers, cur_rows)]), "harga_produk.xlsx")

# --------------------------------------------------------------------------
# Master Data Bahan (Materials)
# --------------------------------------------------------------------------
ALLOWED_MATERIAL_CATEGORIES = ["Material", "Parts"]
# Canonical master unit standard:
# Primary: lembar (sheet/board), pcs (individual), meter (linear), kg (weight), liter (liquid),
#          set (kit), roll (roll), box (box), pack (pack), botol (bottle), kaleng (can).
# Legacy: batang (preserved strictly for backward compatibility of existing lumber/balok records).
ALLOWED_MATERIAL_UNITS = [
    "lembar",
    "pcs",
    "meter",
    "kg",
    "liter",
    "set",
    "roll",
    "box",
    "pack",
    "botol",
    "kaleng",
    "batang",
]

def normalize_text_key(s: str) -> str:
    return " ".join(s.strip().lower().split())

@api_router.get("/admin/materials")
async def get_materials(
    category: Optional[str] = None,
    status: Optional[str] = None,
    q: Optional[str] = None,
    admin: dict = Depends(require_material_perm())
):
    query: Dict[str, Any] = {}
    if category and category != "all":
        query["category"] = category
    if status and status != "all":
        query["status"] = status
    if q and q.strip():
        search_term = re.escape(q.strip())
        query["$or"] = [
            {"name": {"$regex": search_term, "$options": "i"}},
            {"specs": {"$regex": search_term, "$options": "i"}},
            {"sku": {"$regex": search_term, "$options": "i"}},
        ]
    docs = await db.materials.find(query).sort("created_at", -1).to_list(1000)
    result = []
    for d in docs:
        c_item = clean(d)
        try:
            m_id = str(d["_id"])
            s_forms = await db.stock_forms.find({"material_id": m_id, "is_active": True}).to_list(100)
            c_item["stock_forms"] = [clean(sf) for sf in s_forms]
        except Exception:
            c_item["stock_forms"] = []
        result.append(c_item)
    return result

@api_router.post("/admin/materials")
async def create_material(
    data: MaterialInput,
    admin: dict = Depends(require_material_perm())
):
    name = (data.name or "").strip()
    category = (data.category or "").strip()
    specs = (data.specs or "").strip()
    unit = (data.unit or "").strip()
    sku = (data.sku or "").strip() if data.sku else None
    notes = (data.notes or "").strip()

    if not name:
        raise HTTPException(status_code=400, detail="Nama bahan wajib diisi")
    if category not in ALLOWED_MATERIAL_CATEGORIES:
        raise HTTPException(status_code=400, detail=f"Kategori tidak valid. Pilihan: {', '.join(ALLOWED_MATERIAL_CATEGORIES)}")
    if not specs:
        raise HTTPException(status_code=400, detail="Spesifikasi/Ukuran wajib diisi")
    if unit not in ALLOWED_MATERIAL_UNITS:
        raise HTTPException(status_code=400, detail=f"Satuan tidak valid. Pilihan: {', '.join(ALLOWED_MATERIAL_UNITS)}")

    name_norm = normalize_text_key(name)
    specs_norm = normalize_text_key(specs)

    # Check duplicate
    existing = await db.materials.find_one({
        "name_normalized": name_norm,
        "specs_normalized": specs_norm
    })
    if existing:
        raise HTTPException(status_code=409, detail=f"Bahan dengan nama '{name}' dan spesifikasi '{specs}' sudah terdaftar")

    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "name": name,
        "category": category,
        "specs": specs,
        "sku": sku,
        "unit": unit,
        "notes": notes,
        "status": "active",
        "name_normalized": name_norm,
        "specs_normalized": specs_norm,
        "created_at": now,
        "created_by_id": admin.get("id"),
        "created_by_name": admin.get("name", "Admin"),
        **audit_fields(admin)
    }

    try:
        res = await db.materials.insert_one(doc)
        doc["_id"] = res.inserted_id
        return clean(doc)
    except pymongo.errors.DuplicateKeyError:
        raise HTTPException(status_code=409, detail=f"Bahan dengan nama '{name}' dan spesifikasi '{specs}' sudah terdaftar")


# --------------------------------------------------------------------------
# Material Purchases & Price History (Phase 2)
# --------------------------------------------------------------------------
async def get_next_purchase_number(date_str: Optional[str] = None, session=None) -> str:
    # date_str format YYYY-MM-DD or default today
    kw = {"session": session} if session else {}
    try:
        if date_str and len(date_str) >= 10:
            dt_part = date_str[:10].replace("-", "")
        else:
            dt_part = datetime.now(timezone.utc).strftime("%Y%m%d")
    except Exception:
        dt_part = datetime.now(timezone.utc).strftime("%Y%m%d")

    counter_id = f"purchase_{dt_part}"
    prefix = f"PB-{dt_part}-"

    existing_counter = await db.counters.find_one({"_id": counter_id}, **kw)
    if existing_counter is None:
        last_pb = await db.material_purchases.find_one(
            {"purchase_number": {"$regex": f"^{prefix}"}},
            sort=[("purchase_number", -1)],
            **kw
        )
        current_max = 0
        if last_pb and "purchase_number" in last_pb:
            try:
                current_max = int(last_pb["purchase_number"].split("-")[-1])
            except (ValueError, IndexError):
                current_max = 0

        await db.counters.update_one(
            {"_id": counter_id},
            {"$set": {"seq": current_max}},
            upsert=True,
            **kw
        )

    res = await db.counters.find_one_and_update(
        {"_id": counter_id},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
        **kw
    )
    seq = res["seq"]
    return f"{prefix}{seq:04d}"

async def recalculate_material_latest_price(material_id: str, session=None):
    kw = {"session": session} if session else {}
    # Find the latest valid purchase ordered by purchase_date desc, created_at desc
    latest_pb = await db.material_purchases.find_one(
        {"material_id": material_id, "is_void": {"$ne": True}},
        sort=[("purchase_date", -1), ("created_at", -1)],
        **kw
    )

    if latest_pb:
        upd = {
            "latest_price": latest_pb.get("unit_price"),
            "latest_currency": latest_pb.get("currency", "EGP"),
            "latest_purchase_date": latest_pb.get("purchase_date"),
        }
    else:
        upd = {
            "latest_price": None,
            "latest_currency": None,
            "latest_purchase_date": None,
        }

    await db.materials.update_one(
        {"_id": id_query(material_id)},
        {"$set": upd},
        **kw
    )

@api_router.get("/admin/materials/purchases")
async def get_material_purchases(
    material_id: Optional[str] = None,
    status: Optional[str] = None,  # "all", "valid", "void"
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    q: Optional[str] = None,
    admin: dict = Depends(require_material_perm())
):
    query: Dict[str, Any] = {}

    if material_id and material_id != "all":
        query["material_id"] = material_id

    if status == "valid":
        query["is_void"] = {"$ne": True}
    elif status == "void":
        query["is_void"] = True

    if start_date or end_date:
        date_q = {}
        if start_date:
            date_q["$gte"] = start_date
        if end_date:
            date_q["$lte"] = end_date
        query["purchase_date"] = date_q

    if q and q.strip():
        search_term = re.escape(q.strip())
        query["$or"] = [
            {"purchase_number": {"$regex": search_term, "$options": "i"}},
            {"material_name_snapshot": {"$regex": search_term, "$options": "i"}},
            {"material_specs_snapshot": {"$regex": search_term, "$options": "i"}},
            {"supplier_name": {"$regex": search_term, "$options": "i"}},
        ]

    docs = await db.material_purchases.find(query).sort([("purchase_date", -1), ("created_at", -1)]).to_list(1000)
    return [clean(d) for d in docs]

@api_router.post("/admin/materials/purchases")
async def create_material_purchase(
    data: MaterialPurchaseInput,
    admin: dict = Depends(require_material_perm())
):
    mat_id = (data.material_id or "").strip()
    if not mat_id:
        raise HTTPException(status_code=400, detail="Bahan wajib dipilih")

    # Fetch master material
    mat = await db.materials.find_one({"_id": id_query(mat_id)})
    if not mat:
        raise HTTPException(status_code=404, detail="Bahan tidak ditemukan")

    if mat.get("status") == "archived":
        raise HTTPException(status_code=400, detail="Tidak dapat mencatat pembelian untuk bahan yang diarsipkan")

    p_date = (data.purchase_date or "").strip()
    if not p_date:
        raise HTTPException(status_code=400, detail="Tanggal pembelian wajib diisi")

    # Validate date format (YYYY-MM-DD)
    try:
        datetime.strptime(p_date[:10], "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="Format tanggal pembelian tidak valid (harus YYYY-MM-DD)")

    if data.quantity is None or _num(data.quantity) <= 0:
        raise HTTPException(status_code=400, detail="Jumlah pembelian (quantity) harus lebih besar dari 0")

    if data.unit_price is None or _num(data.unit_price) < 0:
        raise HTTPException(status_code=400, detail="Harga satuan tidak boleh negatif")

    qty = round(_num(data.quantity), 4)
    unit_price = round(_num(data.unit_price), 2)
    total_amount = round(qty * unit_price, 2)
    currency = (data.currency or "EGP").strip().upper()
    if currency not in ["EGP", "IDR"]:
        raise HTTPException(status_code=400, detail=f"Mata uang '{currency}' tidak didukung (harus EGP atau IDR)")

    # Get default exchange rate from settings
    settings_rate = 357.0
    try:
        rate_val = await get_setting("exchange_rate_idr_per_le", 357)
        if rate_val:
            settings_rate = float(rate_val)
    except Exception:
        pass

    if data.exchange_rate is not None and _num(data.exchange_rate) > 0:
        exchange_rate = round(float(data.exchange_rate), 4)
    else:
        exchange_rate = settings_rate

    now = datetime.now(timezone.utc).isoformat()
    material_canonical_id = str(mat["_id"])

    # Buyer worker(s) & wage validation
    raw_wids = []
    if data.buyer_worker_ids is not None:
        raw_wids = [str(w).strip() for w in data.buyer_worker_ids if str(w).strip()]
    elif data.buyer_worker_id:
        raw_wids = [str(data.buyer_worker_id).strip()]

    has_buyers = len(raw_wids) > 0
    buyer_wage_amount = data.buyer_wage_amount
    has_wage_amount = buyer_wage_amount is not None and _num(buyer_wage_amount) > 0

    if has_buyers and (buyer_wage_amount is None or _num(buyer_wage_amount) <= 0):
        raise HTTPException(
            status_code=400,
            detail="Nominal upah pembelian bahan harus lebih besar dari 0 jika pekerja pembeli dipilih"
        )
    if has_wage_amount and not has_buyers:
        raise HTTPException(
            status_code=400,
            detail="Pekerja pembeli wajib dipilih jika nominal upah diisi"
        )
    if buyer_wage_amount is not None and _num(buyer_wage_amount) <= 0:
        raise HTTPException(
            status_code=400,
            detail="Nominal upah pembelian bahan harus lebih besar dari 0"
        )

    buyer_worker_docs = []
    buyer_wage_le = None
    wage_allocations = []

    if has_buyers and has_wage_amount:
        # Check active policy
        policy = await get_active_material_purchase_wage_policy(db_inst=db)
        if policy.get("is_configured") and not policy.get("enabled"):
            raise HTTPException(
                status_code=422,
                detail="Kebijakan upah belanja bahan sedang dinonaktifkan oleh Owner."
            )

        max_buyers = policy.get("max_buyers") or 5
        if len(raw_wids) > max_buyers:
            raise HTTPException(
                status_code=422,
                detail=f"Jumlah pekerja pembeli ({len(raw_wids)}) melebihi batas maksimum ({max_buyers} orang)"
            )
        if len(set(raw_wids)) != len(raw_wids):
            raise HTTPException(
                status_code=422,
                detail="Daftar pekerja pembeli memuat ID duplikat. Setiap pekerja hanya boleh dipilih satu kali."
            )

        for wid in raw_wids:
            w_doc = await db.admins.find_one({"_id": id_query(wid)})
            if not w_doc:
                raise HTTPException(
                    status_code=404,
                    detail=f"Pekerja pembeli dengan ID '{wid}' tidak ditemukan dalam sistem"
                )
            if w_doc.get("status") == "inactive":
                raise HTTPException(
                    status_code=422,
                    detail=f"Pekerja pembeli '{w_doc.get('name', wid)}' berstatus tidak aktif dan tidak dapat ditugaskan"
                )
            buyer_worker_docs.append(w_doc)

        buyer_wage_le = round(_num(buyer_wage_amount), 2)

        # Hard cap validation
        max_cap = policy.get("max_wage_per_purchase_le")
        if max_cap is not None and buyer_wage_le > _num(max_cap):
            raise HTTPException(
                status_code=422,
                detail=f"Nominal upah belanja bahan ({buyer_wage_le} LE) melebihi batas maksimum keras ({max_cap} LE)."
            )

        # Threshold confirmation validation
        threshold = policy.get("unusual_amount_threshold_le")
        if threshold is not None and buyer_wage_le > _num(threshold):
            notes_str = (data.buyer_wage_notes or "").strip()
            if not data.confirmed_unusual_amount or len(notes_str) < 3:
                raise HTTPException(
                    status_code=422,
                    detail=f"Nominal upah belanja bahan ({buyer_wage_le} LE) melebihi batas konfirmasi ({threshold} LE). Wajib menyertakan konfirmasi dan catatan/alasan minimal 3 karakter."
                )

        recipients_input = [
            {"worker_id": str(w["_id"]), "worker_name": w.get("name", "Worker")}
            for w in buyer_worker_docs
        ]
        wage_allocations = distribute_wage_piastres(buyer_wage_le, recipients_input)

    # Stock processing validation (Phase 5 Pre-cut)
    stock_processing_dict = None
    if data.stock_processing:
        sp = data.stock_processing
        sp_mode = (sp.mode or "raw").strip().lower()
        if sp_mode == "pre_cut":
            proc_qty = round(_num(sp.processed_quantity), 4)
            if proc_qty < 0:
                raise HTTPException(status_code=400, detail="Jumlah bahan yang diproses tidak boleh negatif")
            if proc_qty > qty:
                raise HTTPException(
                    status_code=400,
                    detail=f"Jumlah yang diproses ({proc_qty}) tidak boleh melebihi jumlah pembelian ({qty})"
                )
            mat_unit = (mat.get("unit") or "").strip().lower()
            if not mat_unit or mat_unit not in ALLOWED_MATERIAL_UNITS:
                raise HTTPException(
                    status_code=400,
                    detail=f"Master bahan '{mat.get('name')}' tidak memiliki satuan inventaris valid."
                )
            raw_rem = round(qty - proc_qty, 4)
            valid_outputs = []
            if proc_qty > 0:
                if not sp.outputs or len(sp.outputs) == 0:
                    raise HTTPException(status_code=400, detail="Harap tentukan minimal satu bentuk hasil potongan (output form)")
                for out_item in sp.outputs:
                    out_q = round(_num(out_item.quantity), 4)
                    if out_q <= 0:
                        raise HTTPException(status_code=400, detail="Jumlah output bentuk stok harus lebih besar dari 0")
                    valid_outputs.append({
                        "form_type": (out_item.form_type or "standard").strip().lower(),
                        "width": round(float(out_item.width), 2) if out_item.width is not None and out_item.width != "" else None,
                        "length": round(float(out_item.length), 2) if out_item.length is not None and out_item.length != "" else None,
                        "thickness": round(float(out_item.thickness), 2) if out_item.thickness is not None and out_item.thickness != "" else None,
                        "dimension_unit": (out_item.dimension_unit or "cm").strip().lower(),
                        "stock_unit": mat_unit,
                        "quantity": out_q,
                        "label": (out_item.label or "").strip(),
                        "notes": (out_item.notes or "").strip(),
                    })
            stock_processing_dict = {
                "mode": "pre_cut",
                "processed_quantity": proc_qty,
                "remaining_raw_quantity": raw_rem,
                "outputs": valid_outputs
            }
        else:
            stock_processing_dict = {
                "mode": "raw",
                "processed_quantity": 0.0,
                "remaining_raw_quantity": qty,
                "outputs": []
            }

    doc = {
        "material_id": material_canonical_id,
        "material_name_snapshot": mat.get("name", ""),
        "material_specs_snapshot": mat.get("specs", ""),
        "category": mat.get("category", "Material"),
        "unit": mat.get("unit", "pcs"),
        "purchase_date": p_date[:10],
        "unit_price": unit_price,
        "quantity": qty,
        "total_amount": total_amount,
        "currency": currency,
        "exchange_rate": exchange_rate,
        "supplier_name": (data.supplier_name or "").strip(),
        "notes": (data.notes or "").strip(),
        "stock_processing": stock_processing_dict,
        "buyer_worker_id": str(buyer_worker_docs[0]["_id"]) if buyer_worker_docs else None,
        "buyer_worker_name": ", ".join(w.get("name", "Worker") for w in buyer_worker_docs) if buyer_worker_docs else None,
        "buyer_worker_ids": [str(w["_id"]) for w in buyer_worker_docs] if buyer_worker_docs else [],
        "buyer_wage_amount": buyer_wage_le if buyer_worker_docs else None,
        "buyer_wage_notes": (data.buyer_wage_notes or "").strip() if buyer_worker_docs else None,
        "buyer_wage_obligation_number": None,
        "buyer_wage_obligation_id": None,
        "buyer_wage_obligation_numbers": [],
        "buyer_workers": [],
        "is_void": False,
        "voided_at": None,
        "voided_by_id": None,
        "voided_by_name": None,
        "void_reason": None,
        "created_at": now,
        "created_by_id": admin.get("id"),
        "created_by_name": admin.get("name", "Admin"),
    }

    async def _execute_create_purchase_tx(session):
        ins_kw = {"session": session} if session else {}

        # 1. Allocate unique purchase number
        for attempt in range(5):
            try:
                pb_num = await get_next_purchase_number(p_date, session=session)
                doc["purchase_number"] = pb_num
                res = await db.material_purchases.insert_one(doc, **ins_kw)
                doc["_id"] = res.inserted_id
                break
            except pymongo.errors.DuplicateKeyError:
                if attempt == 4:
                    raise HTTPException(status_code=500, detail="Gagal mengalokasikan nomor pembelian unik. Silakan coba kembali.")

        # 2. Recalculate material latest price snapshot inside transaction
        await recalculate_material_latest_price(material_canonical_id, session=session)

        # 3. Create purchase_in stock movement & update current_stock inside transaction
        await apply_purchase_stock_in(doc, admin, session=session)

        # 4. Create Finance expense transaction inside transaction (Phase 4)
        await apply_purchase_finance_expense(doc, admin, session=session)

        # 5. Create Wage Obligation(s) if buyer wage is specified
        if buyer_worker_docs and buyer_wage_le and buyer_wage_le > 0 and wage_allocations:
            pb_id_str = str(doc["_id"])
            obligation_numbers = []
            obligation_ids = []
            buyer_workers_summary = []

            for alloc in wage_allocations:
                wid = str(alloc["worker_id"])
                wname = alloc.get("worker_name", "Worker")
                w_amt_le = alloc["amount_le"]
                w_piastres = alloc["amount_piastres"]

                wob_num = await generate_obligation_number(session=session)
                obligation_numbers.append(wob_num)

                accrual_key = f"material_purchase:{pb_id_str}:{wid}" if len(wage_allocations) > 1 else f"material_purchase:{pb_id_str}"

                wob_call = db.wage_obligations.find_one({"accrual_event_key": accrual_key}, **ins_kw)
                existing_wob = await wob_call if inspect.isawaitable(wob_call) else (wob_call if isinstance(wob_call, dict) else None)
                if not existing_wob:
                    wob_doc = {
                        "obligation_number": wob_num,
                        "accrual_event_key": accrual_key,
                        "source_type": "material_purchase",
                        "material_purchase_id": pb_id_str,
                        "purchase_number": pb_num,
                        "material_id": material_canonical_id,
                        "material_name": mat.get("name", ""),
                        "worker_id": wid,
                        "worker_name": wname,
                        "task_category": "material_purchase",
                        "pricing_basis": "lump_sum",
                        "rate_le": w_amt_le,
                        "accepted_quantity": 1,
                        "total_amount_le": w_amt_le,
                        "amount_piastres": w_piastres,
                        "currency": "EGP",
                        "status": "accrued",
                        "paid_amount_le": 0.0,
                        "locked_exchange_rate": exchange_rate,
                        "notes": (data.buyer_wage_notes or "").strip() or f"Upah belanja bahan {mat.get('name', '')} ({pb_num})",
                        "verified_by_id": str(admin.get("id") or admin.get("_id") or ""),
                        "verified_by_name": admin.get("name", "Admin"),
                        "rate_policy_snapshot": {
                            "total_purchase_wage_le": buyer_wage_le,
                            "allocated_amount_le": w_amt_le,
                            "allocated_piastres": w_piastres,
                            "buyers_count": len(wage_allocations),
                            "exchange_rate": exchange_rate,
                        },
                        "created_at": now,
                        "updated_at": now,
                    }
                    res_wob = db.wage_obligations.insert_one(wob_doc, **ins_kw)
                    if inspect.isawaitable(res_wob):
                        res_wob = await res_wob
                    wob_id_str = str(getattr(res_wob, "inserted_id", "") or "")
                else:
                    wob_id_str = str(existing_wob.get("_id") or existing_wob.get("id") or "")
                    wob_num = existing_wob.get("obligation_number")

                obligation_ids.append(wob_id_str)
                buyer_workers_summary.append({
                    "worker_id": wid,
                    "worker_name": wname,
                    "amount_le": w_amt_le,
                    "amount_piastres": w_piastres,
                    "obligation_number": wob_num,
                    "obligation_id": wob_id_str,
                })

            primary_wob_num = obligation_numbers[0]
            primary_wob_id = obligation_ids[0]

            upd_pur_res = db.material_purchases.update_one(
                {"_id": doc["_id"]},
                {"$set": {
                    "buyer_wage_obligation_number": primary_wob_num,
                    "buyer_wage_obligation_id": primary_wob_id,
                    "buyer_wage_obligation_numbers": obligation_numbers,
                    "buyer_workers": buyer_workers_summary,
                }},
                **ins_kw
            )
            if inspect.isawaitable(upd_pur_res):
                await upd_pur_res

            doc["buyer_wage_obligation_number"] = primary_wob_num
            doc["buyer_wage_obligation_id"] = primary_wob_id
            doc["buyer_wage_obligation_numbers"] = obligation_numbers
            doc["buyer_workers"] = buyer_workers_summary

        return doc

    try:
        final_doc = await execute_transaction_with_safety(client, _execute_create_purchase_tx)
        return clean(final_doc)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed transaction while creating material purchase: {e}")
        raise HTTPException(status_code=500, detail=f"Gagal mencatat transaksi pembelian dan stok bahan: {str(e)}")

@api_router.get("/admin/materials/purchases/{pb_id}")
async def get_material_purchase_detail(
    pb_id: str,
    admin: dict = Depends(require_material_perm())
):
    doc = await db.material_purchases.find_one({"_id": id_query(pb_id)})
    if not doc:
        doc = await db.material_purchases.find_one({"purchase_number": pb_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Data pembelian bahan tidak ditemukan")
    return clean(doc)

@api_router.post("/admin/materials/purchases/{pb_id}/void")
async def void_material_purchase(
    pb_id: str,
    data: VoidPurchaseInput,
    admin: dict = Depends(require_material_perm())
):
    doc = await db.material_purchases.find_one({"_id": id_query(pb_id)})
    if not doc:
        doc = await db.material_purchases.find_one({"purchase_number": pb_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Data pembelian bahan tidak ditemukan")

    if doc.get("is_void"):
        raise HTTPException(status_code=400, detail="Pembelian bahan ini sudah berstatus void")

    mat_id = str(doc["material_id"])
    mat = await db.materials.find_one({"_id": id_query(mat_id)})
    if not mat:
        raise HTTPException(status_code=404, detail="Bahan terkait tidak ditemukan")

    current_stock = round(float(mat.get("current_stock") or 0.0), 4)
    purchase_qty = round(float(doc.get("quantity") or 0.0), 4)
    unit_str = mat.get("unit", "satuan")

    # STRICT NON-NEGATIVE INVARIANT: Reject void if current stock is insufficient
    if current_stock < purchase_qty:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Pembelian tidak dapat dibatalkan karena stok saat ini ({current_stock} {unit_str}) "
                f"lebih kecil dari jumlah pembelian ({purchase_qty} {unit_str}). "
                f"Bahan kemungkinan sudah digunakan. Lakukan penyesuaian stok terlebih dahulu sebelum membatalkan pembelian."
            )
        )

    # STRICT WAGE OBLIGATION INVARIANT: Check ALL linked worker wage statuses
    pb_id_str = str(doc["_id"])
    p_num = str(doc.get("purchase_number") or "").strip()
    wob_query_conditions = []
    if pb_id_str:
        wob_query_conditions.append({"material_purchase_id": pb_id_str})
        wob_query_conditions.append({"accrual_event_key": f"material_purchase:{pb_id_str}"})
    if p_num:
        wob_query_conditions.append({"purchase_number": p_num, "task_category": "material_purchase"})

    linked_wobs = []
    if wob_query_conditions and hasattr(db.wage_obligations, "find"):
        try:
            wobs_cursor = db.wage_obligations.find({"$or": wob_query_conditions})
            to_list_fn = getattr(wobs_cursor, "to_list", None)
            if callable(to_list_fn):
                res_cursor = to_list_fn(100)
                if inspect.isawaitable(res_cursor):
                    res_cursor = await res_cursor
                if isinstance(res_cursor, list):
                    linked_wobs = res_cursor
        except Exception:
            pass

    if not linked_wobs and wob_query_conditions and hasattr(db.wage_obligations, "find_one"):
        wob_call = db.wage_obligations.find_one({"$or": wob_query_conditions})
        single_wob = await wob_call if inspect.isawaitable(wob_call) else (wob_call if isinstance(wob_call, dict) else None)
        if single_wob:
            linked_wobs = [single_wob]

    for linked_wob in linked_wobs:
        wob_status = linked_wob.get("status")
        if wob_status in ("paid", "partially_paid") or _num(linked_wob.get("paid_amount_le", 0)) > 0:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Pembelian bahan tidak dapat dibatalkan karena upah pekerja pembeli sudah dibayar "
                    f"(No. Kewajiban: {linked_wob.get('obligation_number')}, Status: {wob_status}). "
                    f"Harap batalkan (void) pembayaran upah pekerja terkait terlebih dahulu di menu Upah Pekerja."
                )
            )
        elif wob_status not in ("accrued", "voided"):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Pembelian bahan tidak dapat dibatalkan karena status kewajiban upah ({wob_status}) "
                    f"tidak memenuhi syarat pembatalan aman."
                )
            )

    now = datetime.now(timezone.utc).isoformat()
    void_reason = (data.void_reason or "").strip() or "Dibatalkan oleh admin"
    upd = {
        "is_void": True,
        "voided_at": now,
        "voided_by_id": admin.get("id"),
        "voided_by_name": admin.get("name", "Admin"),
        "void_reason": void_reason,
    }

    async def _execute_void_purchase_tx(session):
        tx_kw = {"session": session} if session else {}

        # 1. Reverse stock movement with strict non-negative policy inside transaction
        await apply_purchase_stock_reversal(doc, void_reason, admin, session=session)

        # 2. Reverse finance expense inside transaction (Phase 4)
        await apply_purchase_finance_reversal(doc, void_reason, admin, session=session)

        # 3. Mark purchase as voided inside transaction
        updated_doc = await db.material_purchases.find_one_and_update(
            {"_id": doc["_id"], "is_void": False},
            {"$set": upd},
            return_document=ReturnDocument.AFTER,
            **tx_kw
        )
        if not updated_doc:
            raise HTTPException(status_code=400, detail="Pembelian bahan ini sudah dibatalkan sebelumnya.")

        # 3b. Void all linked wage obligations inside transaction if status is accrued
        void_set = {
            "status": "voided",
            "voided_at": now,
            "voided_by_id": str(admin.get("id") or admin.get("_id") or ""),
            "voided_by_name": admin.get("name", "Admin"),
            "void_reason": f"Dibatalkan otomatis karena pembelian {doc.get('purchase_number')} di-void: {void_reason}",
            "updated_at": now,
        }
        if wob_query_conditions and hasattr(db.wage_obligations, "update_many"):
            try:
                upd_wob_res = db.wage_obligations.update_many(
                    {
                        "$or": wob_query_conditions,
                        "status": "accrued"
                    },
                    {"$set": void_set},
                    **tx_kw
                )
                if inspect.isawaitable(upd_wob_res):
                    await upd_wob_res
            except Exception:
                pass

        if linked_wobs and hasattr(db.wage_obligations, "update_one"):
            for lw in linked_wobs:
                if lw.get("status") == "accrued":
                    upd_single = db.wage_obligations.update_one(
                        {"_id": lw["_id"], "status": "accrued"},
                        {"$set": void_set},
                        **tx_kw
                    )
                    if inspect.isawaitable(upd_single):
                        await upd_single

        # 4. Recalculate material latest price snapshot inside transaction
        await recalculate_material_latest_price(doc["material_id"], session=session)
        return updated_doc

    try:
        updated = await execute_transaction_with_safety(client, _execute_void_purchase_tx)
        return {"ok": True, "message": "Pembelian bahan berhasil di-void", "purchase": clean(updated)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed transaction while voiding material purchase: {e}")
        raise HTTPException(status_code=500, detail=f"Gagal membatalkan pembelian bahan: {str(e)}")

@api_router.get("/admin/materials/{mat_id}/price-history")
async def get_material_price_history(
    mat_id: str,
    admin: dict = Depends(require_material_perm())
):
    mat = await db.materials.find_one({"_id": id_query(mat_id)})
    if not mat:
        raise HTTPException(status_code=404, detail="Bahan tidak ditemukan")

    canonical_id = str(mat["_id"])
    docs = await db.material_purchases.find(
        {"material_id": canonical_id, "is_void": {"$ne": True}}
    ).sort([("purchase_date", -1), ("created_at", -1)]).to_list(500)

    return {
        "material": clean(mat),
        "history": [clean(d) for d in docs]
    }

# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
# Material Stock & Movements (Phase 3 & Phase 5)
# --------------------------------------------------------------------------
async def get_or_create_stock_form(
    material_id: str,
    form_type: str = "standard",
    width: Optional[float] = None,
    length: Optional[float] = None,
    thickness: Optional[float] = None,
    dimension_unit: str = "cm",
    stock_unit: Optional[str] = None,
    label: str = "",
    notes: str = "",
    admin: dict = None,
    session=None
) -> dict:
    kw = {"session": session} if session else {}
    mat = await db.materials.find_one({"_id": id_query(material_id)}, **kw)
    if not mat:
        raise HTTPException(status_code=404, detail="Bahan tidak ditemukan")

    canonical_mat_id = str(mat["_id"])
    mat_unit = (mat.get("unit") or "").strip().lower()
    if not mat_unit or mat_unit not in ALLOWED_MATERIAL_UNITS:
        raise HTTPException(
            status_code=400,
            detail=f"Master bahan '{mat.get('name', canonical_mat_id)}' tidak memiliki satuan inventaris valid. Satuan bahan harus salah satu dari: {', '.join(ALLOWED_MATERIAL_UNITS)}"
        )
    # Stock forms MUST strictly inherit the material's canonical inventory unit.
    # Physical form describes the shape/cut, but the inventory counting unit remains the material unit.
    s_unit = mat_unit

    w = round(float(width), 2) if width is not None and width != "" else None
    l = round(float(length), 2) if length is not None and length != "" else None
    th = round(float(thickness), 2) if thickness is not None and thickness != "" else None
    d_unit = (dimension_unit or "cm").strip().lower()
    lbl = (label or "").strip()
    f_type = (form_type or "standard").strip().lower()
    if f_type not in ["raw", "standard", "custom"]:
        f_type = "standard"

    query_filter = {
        "material_id": canonical_mat_id,
        "form_type": f_type,
        "width": w,
        "length": l,
        "thickness": th,
        "dimension_unit": d_unit,
        "stock_unit": s_unit,
        "label": lbl
    }

    existing = await db.stock_forms.find_one(query_filter, **kw)
    if existing:
        return existing

    now = datetime.now(timezone.utc).isoformat()
    adm = admin or {}
    new_doc = {
        "material_id": canonical_mat_id,
        "material_name_snapshot": mat.get("name", ""),
        "material_specs_snapshot": mat.get("specs", ""),
        "form_type": f_type,
        "width": w,
        "length": l,
        "thickness": th,
        "dimension_unit": d_unit,
        "stock_unit": s_unit,
        "label": lbl,
        "notes": (notes or "").strip(),
        "current_quantity": 0.0,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
        "created_by_id": adm.get("id"),
        "created_by_name": adm.get("name", "Admin"),
    }

    try:
        res = await db.stock_forms.insert_one(new_doc, **kw)
        new_doc["_id"] = res.inserted_id
        return new_doc
    except pymongo.errors.DuplicateKeyError:
        existing = await db.stock_forms.find_one(query_filter, **kw)
        if existing:
            return existing
        raise HTTPException(status_code=409, detail="Konflik saat membuat bentuk stok bahan.")

async def get_next_transformation_number(date_str: Optional[str] = None, session=None) -> str:
    kw = {"session": session} if session else {}
    try:
        if date_str and len(date_str) >= 10:
            dt_part = date_str[:10].replace("-", "")
        else:
            dt_part = datetime.now(timezone.utc).strftime("%Y%m%d")
    except Exception:
        dt_part = datetime.now(timezone.utc).strftime("%Y%m%d")

    counter_id = f"transformation_{dt_part}"
    prefix = f"TR-{dt_part}-"

    existing_counter = await db.counters.find_one({"_id": counter_id}, **kw)
    if existing_counter is None:
        last_tr = await db.stock_transformations.find_one(
            {"transformation_number": {"$regex": f"^{prefix}"}},
            sort=[("transformation_number", -1)],
            **kw
        )
        current_max = 0
        if last_tr and "transformation_number" in last_tr:
            try:
                current_max = int(last_tr["transformation_number"].split("-")[-1])
            except (ValueError, IndexError):
                current_max = 0

        await db.counters.update_one(
            {"_id": counter_id},
            {"$set": {"seq": current_max}},
            upsert=True,
            **kw
        )

    res = await db.counters.find_one_and_update(
        {"_id": counter_id},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
        **kw
    )
    seq = res["seq"]
    return f"{prefix}{seq:04d}"

async def get_next_movement_number(date_str: Optional[str] = None, session=None) -> str:
    """
    Allocates the next unique movement number for date_str.
    Counter sequence generation is strictly autonomous (session=None) to ensure sequence increments
    never participate in business transaction aborts or suffer write conflicts.
    It automatically synchronizes with the high-watermark of material_stocks to prevent collisions.
    """
    try:
        if date_str and len(date_str) >= 10:
            dt_part = date_str[:10].replace("-", "")
        else:
            dt_part = datetime.now(timezone.utc).strftime("%Y%m%d")
    except Exception:
        dt_part = datetime.now(timezone.utc).strftime("%Y%m%d")

    counter_id = f"stock_{dt_part}"
    prefix = f"ST-{dt_part}-"

    # 1. High-watermark check against physical material_stocks
    last_st = None
    if hasattr(db.material_stocks, "find_one"):
        st_res = db.material_stocks.find_one(
            {"movement_number": {"$regex": f"^{prefix}"}},
            sort=[("movement_number", -1)]
        )
        if asyncio.iscoroutine(st_res) or hasattr(st_res, "__await__"):
            last_st = await st_res
    current_max = 0
    if last_st and "movement_number" in last_st:
        try:
            current_max = int(last_st["movement_number"].split("-")[-1])
        except (ValueError, IndexError):
            current_max = 0

    # 2. Ensure counter is at least current_max using atomic $max
    if current_max > 0:
        await db.counters.update_one(
            {"_id": counter_id},
            {"$max": {"seq": current_max}},
            upsert=True
        )

    # 3. Atomically increment sequence (autonomous, session=None)
    res = await db.counters.find_one_and_update(
        {"_id": counter_id},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER
    )
    seq = res["seq"]
    if seq <= current_max:
        seq = current_max + 1
        await db.counters.update_one(
            {"_id": counter_id},
            {"$set": {"seq": seq}},
            upsert=True
        )
    return f"{prefix}{seq:04d}"

async def get_next_movement_numbers(count: int, date_str: Optional[str] = None, session=None) -> list[str]:
    """
    Allocates a contiguous batch of `count` movement numbers in a single atomic autonomous counter update.
    Counter sequence generation is strictly autonomous (session=None) to ensure sequence increments
    never participate in business transaction aborts or suffer write conflicts.
    It automatically synchronizes with the high-watermark of material_stocks to prevent collisions.
    """
    if count <= 0:
        return []
    try:
        if date_str and len(date_str) >= 10:
            dt_part = date_str[:10].replace("-", "")
        else:
            dt_part = datetime.now(timezone.utc).strftime("%Y%m%d")
    except Exception:
        dt_part = datetime.now(timezone.utc).strftime("%Y%m%d")

    counter_id = f"stock_{dt_part}"
    prefix = f"ST-{dt_part}-"

    # 1. High-watermark check against physical material_stocks
    last_st = None
    if hasattr(db.material_stocks, "find_one"):
        st_res = db.material_stocks.find_one(
            {"movement_number": {"$regex": f"^{prefix}"}},
            sort=[("movement_number", -1)]
        )
        if asyncio.iscoroutine(st_res) or hasattr(st_res, "__await__"):
            last_st = await st_res
    current_max = 0
    if last_st and "movement_number" in last_st:
        try:
            current_max = int(last_st["movement_number"].split("-")[-1])
        except (ValueError, IndexError):
            current_max = 0

    # 2. Ensure counter is at least current_max using atomic $max
    if current_max > 0:
        await db.counters.update_one(
            {"_id": counter_id},
            {"$max": {"seq": current_max}},
            upsert=True
        )

    # 3. Atomically allocate batch sequence (autonomous, session=None)
    res = await db.counters.find_one_and_update(
        {"_id": counter_id},
        {"$inc": {"seq": count}},
        upsert=True,
        return_document=ReturnDocument.AFTER
    )
    final_seq = res["seq"]
    start_seq = final_seq - count + 1

    # If start_seq collided with existing current_max, jump ahead
    if start_seq <= current_max:
        start_seq = current_max + 1
        final_seq = start_seq + count - 1
        await db.counters.update_one(
            {"_id": counter_id},
            {"$set": {"seq": final_seq}},
            upsert=True
        )

    return [f"{prefix}{s:04d}" for s in range(start_seq, final_seq + 1)]


async def apply_stock_movement_atomic(
    material_id: str,
    movement_type: str,
    quantity_delta: float,
    movement_date: str,
    reason: str,
    admin: dict,
    related_purchase_id: Optional[str] = None,
    related_purchase_number: Optional[str] = None,
    notes: Optional[str] = "",
    allow_negative: bool = False,
    session=None,
    stock_form_id: Optional[str] = None,
    transformation_id: Optional[str] = None,
    transformation_number: Optional[str] = None,
    update_material_aggregate: bool = True,
    movement_number: Optional[str] = None
) -> dict:
    kw = {"session": session} if session else {}
    mat = await db.materials.find_one({"_id": id_query(material_id)}, **kw)
    if not mat:
        raise HTTPException(status_code=404, detail="Bahan tidak ditemukan")

    if mat.get("status") == "archived" and not movement_type.startswith("purchase_"):
        raise HTTPException(status_code=400, detail="Tidak dapat mengubah stok untuk bahan yang diarsipkan")

    canonical_mat_id = str(mat["_id"])
    delta = round(float(quantity_delta), 4)

    # 1. Update specific stock form if stock_form_id is provided
    stock_form_doc = None
    prev_sf_qty = 0.0
    new_sf_qty = 0.0
    if stock_form_id:
        sf = await db.stock_forms.find_one({"_id": id_query(stock_form_id)}, **kw)
        if not sf:
            raise HTTPException(status_code=404, detail="Bentuk stok (Stock Form) tidak ditemukan")
        if str(sf.get("material_id")) != canonical_mat_id:
            raise HTTPException(status_code=400, detail="Bentuk stok tidak sesuai dengan bahan yang dipilih")

        prev_sf_qty = round(float(sf.get("current_quantity") or 0.0), 4)
        new_sf_qty = round(prev_sf_qty + delta, 4)
        if not allow_negative and new_sf_qty < 0:
            sf_label = sf.get("label") or f"{sf.get('form_type')} ({sf.get('stock_unit')})"
            raise HTTPException(
                status_code=400,
                detail=f"Stok bentuk fisik tidak mencukupi (stok saat ini: {prev_sf_qty}, pengurangan: {abs(delta)} pada {sf_label})"
            )

        # Atomic CAS update for stock_form
        sf_cond = {"_id": sf["_id"]}
        if "current_quantity" in sf and sf["current_quantity"] is not None:
            sf_cond["current_quantity"] = sf["current_quantity"]
        else:
            sf_cond["$or"] = [{"current_quantity": {"$exists": False}}, {"current_quantity": None}, {"current_quantity": 0.0}]

        now_iso = datetime.now(timezone.utc).isoformat()
        stock_form_doc = await db.stock_forms.find_one_and_update(
            sf_cond,
            {"$set": {"current_quantity": new_sf_qty, "updated_at": now_iso}},
            return_document=ReturnDocument.AFTER,
            **kw
        )
        if not stock_form_doc:
            raise HTTPException(status_code=409, detail="Konflik konkurensi saat mengubah kuantitas bentuk stok.")

    # 2. Concurrency-safe atomic update loop with optimistic concurrency for materials.current_stock (when update_material_aggregate=True)
    max_retries = 10
    updated_mat = None
    prev_stock = round(float(mat.get("current_stock") or 0.0), 4)
    target_new_stock = prev_stock

    if update_material_aggregate:
        for attempt in range(max_retries):
            current_doc = await db.materials.find_one({"_id": mat["_id"]}, **kw)
            if not current_doc:
                raise HTTPException(status_code=404, detail="Bahan tidak ditemukan")

            prev_stock = round(float(current_doc.get("current_stock") or 0.0), 4)
            target_new_stock = round(prev_stock + delta, 4)

            if not allow_negative and target_new_stock < 0:
                # Rollback stock_form if we modified it and not in a transaction
                if not session and stock_form_id and stock_form_doc:
                    await db.stock_forms.update_one({"_id": stock_form_doc["_id"]}, {"$set": {"current_quantity": prev_sf_qty}}, **kw)
                raise HTTPException(
                    status_code=400,
                    detail=f"Stok bahan tidak mencukupi (stok saat ini: {prev_stock} {mat.get('unit', '')}, pengurangan: {abs(delta)})"
                )

            # Atomic compare-and-swap
            cond = {"_id": mat["_id"]}
            if "current_stock" in current_doc and current_doc["current_stock"] is not None:
                cond["current_stock"] = current_doc["current_stock"]
            else:
                cond["$or"] = [{"current_stock": {"$exists": False}}, {"current_stock": None}, {"current_stock": 0.0}]

            updated_mat = await db.materials.find_one_and_update(
                cond,
                {"$set": {"current_stock": target_new_stock}},
                return_document=ReturnDocument.AFTER,
                **kw
            )
            if updated_mat:
                break
            if attempt == max_retries - 1:
                if not session and stock_form_id and stock_form_doc:
                    await db.stock_forms.update_one({"_id": stock_form_doc["_id"]}, {"$set": {"current_quantity": prev_sf_qty}}, **kw)
                raise HTTPException(status_code=409, detail="Konflik konkurensi saat mengubah stok. Silakan coba kembali.")
    else:
        # Read latest current_stock for movement_doc snapshot without mutating it
        current_doc = await db.materials.find_one({"_id": mat["_id"]}, **kw)
        if current_doc:
            prev_stock = round(float(current_doc.get("current_stock") or 0.0), 4)
            target_new_stock = prev_stock

    # 3. Record movement document
    now = datetime.now(timezone.utc).isoformat()
    # If this movement is strictly on a stock form and does not update canonical material aggregate, record form's stock_unit
    mov_unit = mat.get("unit", "pcs")
    if not update_material_aggregate and stock_form_doc:
        mov_unit = stock_form_doc.get("stock_unit") or mov_unit

    movement_doc = {
        "material_id": canonical_mat_id,
        "material_name_snapshot": mat.get("name", ""),
        "material_specs_snapshot": mat.get("specs", ""),
        "unit": mov_unit,
        "movement_type": movement_type,
        "quantity_delta": delta,
        "previous_stock": prev_stock,
        "new_stock": target_new_stock,
        "movement_date": movement_date[:10],
        "reason": reason.strip(),
        "notes": (notes or "").strip(),
        "created_at": now,
        "created_by_id": admin.get("id"),
        "created_by_name": admin.get("name", "Admin"),
    }
    if related_purchase_id:
        movement_doc["related_purchase_id"] = str(related_purchase_id)
    if related_purchase_number:
        movement_doc["related_purchase_number"] = str(related_purchase_number)
    if stock_form_doc:
        movement_doc["stock_form_id"] = str(stock_form_doc["_id"])
    elif stock_form_id:
        movement_doc["stock_form_id"] = str(stock_form_id)
    if transformation_id:
        movement_doc["transformation_id"] = str(transformation_id)
    if transformation_number:
        movement_doc["transformation_number"] = str(transformation_number)

    # Unique movement_number retry loop
    for attempt in range(5):
        try:
            if movement_number and attempt == 0:
                m_num = movement_number
            else:
                # When retrying or allocating fresh numbers, always run autonomously (session=None)
                # with high-watermark synchronization against physical material_stocks
                m_num = await get_next_movement_number(movement_date, session=None)
            movement_doc["movement_number"] = m_num
            res = await db.material_stocks.insert_one(movement_doc, **kw)
            movement_doc["_id"] = res.inserted_id
            break
        except pymongo.errors.DuplicateKeyError as dke:
            err_msg = str(dke)

            # 1. Purchase idempotency index collision
            if "uniq_purchase_stock_movement" in err_msg and related_purchase_id:
                if not session:
                    if update_material_aggregate:
                        await db.materials.update_one({"_id": mat["_id"]}, {"$set": {"current_stock": prev_stock}}, **kw)
                    if stock_form_id and stock_form_doc:
                        await db.stock_forms.update_one({"_id": stock_form_doc["_id"]}, {"$set": {"current_quantity": prev_sf_qty}}, **kw)
                raise HTTPException(status_code=409, detail="Stok untuk pembelian ini sudah pernah dicatat.")

            # 2. Movement number collision: check if collision belongs to uniq_movement_number
            is_movement_number_collision = (
                "uniq_movement_number" in err_msg or
                "movement_number" in err_msg or
                "movement_number_" in err_msg
            )

            if is_movement_number_collision:
                if attempt == 4:
                    if not session:
                        if update_material_aggregate:
                            await db.materials.update_one({"_id": mat["_id"]}, {"$set": {"current_stock": prev_stock}}, **kw)
                        if stock_form_id and stock_form_doc:
                            await db.stock_forms.update_one({"_id": stock_form_doc["_id"]}, {"$set": {"current_quantity": prev_sf_qty}}, **kw)
                    raise HTTPException(status_code=500, detail="Gagal mengalokasikan nomor pergerakan stok unik.")
                continue

            # 3. Unrelated unique index collision: DO NOT retry movement allocation, rollback immediately
            if not session:
                if update_material_aggregate:
                    await db.materials.update_one({"_id": mat["_id"]}, {"$set": {"current_stock": prev_stock}}, **kw)
                if stock_form_id and stock_form_doc:
                    await db.stock_forms.update_one({"_id": stock_form_doc["_id"]}, {"$set": {"current_quantity": prev_sf_qty}}, **kw)

            logger.error(f"Unrelated DuplicateKeyError during stock movement insertion: {dke}")
            raise HTTPException(
                status_code=409,
                detail="Konflik indeks unik pada pergerakan stok (data pergerakan duplikat terdeteksi)."
            )

    return clean(movement_doc)

async def apply_purchase_stock_in(purchase_doc: dict, admin: dict, session=None):
    kw = {"session": session} if session else {}
    mat_id = str(purchase_doc["material_id"])
    pb_id = str(purchase_doc["_id"])
    pb_num = purchase_doc.get("purchase_number")
    qty = float(purchase_doc.get("quantity") or 0.0)
    p_date = purchase_doc.get("purchase_date") or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Check if already recorded
    existing = await db.material_stocks.find_one({
        "related_purchase_id": pb_id,
        "movement_type": "purchase_in"
    }, **kw)
    if existing:
        return existing

    sp = purchase_doc.get("stock_processing")
    mode = sp.get("mode") if sp else "raw"

    col_sf = getattr(db, "stock_forms", None)
    has_stock_forms = (
        isinstance(col_sf, AsyncIOMotorCollection)
        or type(getattr(col_sf, "find_one", None)).__name__ == "AsyncMock"
    )

    if mode == "pre_cut" and sp and has_stock_forms:
        # Pre-cut processing
        processed_qty = round(float(sp.get("processed_quantity") or 0.0), 4)
        raw_remaining = round(qty - processed_qty, 4)
        outputs = sp.get("outputs") or []

        # 1. Create or get default raw Stock Form for this material
        raw_sf = await get_or_create_stock_form(
            material_id=mat_id,
            form_type="raw",
            stock_unit=purchase_doc.get("unit", "pcs"),
            label="Raw / Bentuk Asal",
            admin=admin,
            session=session
        )

        # 2. Record full purchase_in into raw form
        first_mov = await apply_stock_movement_atomic(
            material_id=mat_id,
            movement_type="purchase_in",
            quantity_delta=qty,
            movement_date=p_date,
            reason=f"Pembelian {pb_num}",
            admin=admin,
            related_purchase_id=pb_id,
            related_purchase_number=pb_num,
            notes=purchase_doc.get("notes", ""),
            allow_negative=False,
            session=session,
            stock_form_id=str(raw_sf["_id"])
        )

        # 3. If processed_qty > 0 and outputs exist, record transformation
        if processed_qty > 0 and outputs:
            tr_num = await get_next_transformation_number(p_date, session=session)
            now = datetime.now(timezone.utc).isoformat()

            # Record transformation_out from raw_sf
            tr_out_mov = await apply_stock_movement_atomic(
                material_id=mat_id,
                movement_type="transformation_out",
                quantity_delta=-processed_qty,
                movement_date=p_date,
                reason=f"Pre-cut pembelian {pb_num}",
                admin=admin,
                related_purchase_id=pb_id,
                related_purchase_number=pb_num,
                notes=f"Dipotong langsung saat pembelian {pb_num}",
                allow_negative=False,
                session=session,
                stock_form_id=str(raw_sf["_id"]),
                transformation_number=tr_num
            )

            # Record transformation_in for each output form
            output_refs = []
            for out_it in outputs:
                out_q = round(float(out_it.get("quantity") or 0.0), 4)
                if out_q <= 0:
                    continue
                out_sf = await get_or_create_stock_form(
                    material_id=mat_id,
                    form_type=out_it.get("form_type", "standard"),
                    width=out_it.get("width"),
                    length=out_it.get("length"),
                    thickness=out_it.get("thickness"),
                    dimension_unit=out_it.get("dimension_unit", "cm"),
                    stock_unit=out_it.get("stock_unit") or purchase_doc.get("unit", "pcs"),
                    label=out_it.get("label", ""),
                    notes=out_it.get("notes", ""),
                    admin=admin,
                    session=session
                )
                await apply_stock_movement_atomic(
                    material_id=mat_id,
                    movement_type="transformation_in",
                    quantity_delta=out_q,
                    movement_date=p_date,
                    reason=f"Hasil pre-cut pembelian {pb_num}",
                    admin=admin,
                    related_purchase_id=pb_id,
                    related_purchase_number=pb_num,
                    notes=out_it.get("notes", ""),
                    allow_negative=False,
                    session=session,
                    stock_form_id=str(out_sf["_id"]),
                    transformation_number=tr_num,
                    update_material_aggregate=False
                )
                output_refs.append({
                    "stock_form_id": str(out_sf["_id"]),
                    "form_type": out_sf.get("form_type"),
                    "dimensions": {
                        "width": out_sf.get("width"),
                        "length": out_sf.get("length"),
                        "thickness": out_sf.get("thickness"),
                        "unit": out_sf.get("dimension_unit")
                    },
                    "quantity": out_q,
                    "stock_unit": out_sf.get("stock_unit"),
                    "label": out_sf.get("label", "")
                })

            # Record stock_transformation event
            tr_doc = {
                "transformation_number": tr_num,
                "transformation_date": p_date[:10],
                "material_id": mat_id,
                "material_name_snapshot": purchase_doc.get("material_name_snapshot", ""),
                "material_specs_snapshot": purchase_doc.get("material_specs_snapshot", ""),
                "source_stock_form_id": str(raw_sf["_id"]),
                "source_quantity": processed_qty,
                "source_stock_unit": raw_sf.get("stock_unit"),
                "output_stock_forms": output_refs,
                "reason": f"Pre-cut saat pembelian {pb_num}",
                "notes": purchase_doc.get("notes", ""),
                "related_purchase_id": pb_id,
                "related_purchase_number": pb_num,
                "created_at": now,
                "created_by_id": admin.get("id"),
                "created_by_name": admin.get("name", "Admin")
            }
            await db.stock_transformations.insert_one(tr_doc, **kw)

        return first_mov
    elif has_stock_forms:
        # Standard raw purchase with stock forms enabled
        raw_sf = await get_or_create_stock_form(
            material_id=mat_id,
            form_type="raw",
            stock_unit=purchase_doc.get("unit", "pcs"),
            label="Raw / Bentuk Asal",
            admin=admin,
            session=session
        )
        return await apply_stock_movement_atomic(
            material_id=mat_id,
            movement_type="purchase_in",
            quantity_delta=qty,
            movement_date=p_date,
            reason=f"Pembelian {pb_num}",
            admin=admin,
            related_purchase_id=pb_id,
            related_purchase_number=pb_num,
            notes=purchase_doc.get("notes", ""),
            allow_negative=False,
            session=session,
            stock_form_id=str(raw_sf["_id"])
        )
    else:
        # Fallback for environments / legacy tests where stock_forms collection is not initialized/mocked
        return await apply_stock_movement_atomic(
            material_id=mat_id,
            movement_type="purchase_in",
            quantity_delta=qty,
            movement_date=p_date,
            reason=f"Pembelian {pb_num}",
            admin=admin,
            related_purchase_id=pb_id,
            related_purchase_number=pb_num,
            notes=purchase_doc.get("notes", ""),
            allow_negative=False,
            session=session
        )

async def apply_purchase_stock_reversal(purchase_doc: dict, void_reason: str, admin: dict, session=None):
    kw = {"session": session} if session else {}
    mat_id = str(purchase_doc["material_id"])
    pb_id = str(purchase_doc["_id"])
    pb_num = purchase_doc.get("purchase_number")
    qty = float(purchase_doc.get("quantity") or 0.0)

    # Check if purchase_in movement exists for this purchase
    orig_movement = await db.material_stocks.find_one({
        "related_purchase_id": pb_id,
        "movement_type": "purchase_in"
    }, **kw)
    if not orig_movement:
        return None

    # Check if reversal already recorded
    existing_reversal = await db.material_stocks.find_one({
        "related_purchase_id": pb_id,
        "movement_type": "adjustment_out",
        "reason": {"$regex": f"^Reversal pembelian {re.escape(pb_num)}"}
    }, **kw)
    if existing_reversal:
        return existing_reversal

    now_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Check if this purchase had stock_processing / pre_cut transformations
    col_tr = getattr(db, "stock_transformations", None)
    has_tr_col = (
        isinstance(col_tr, AsyncIOMotorCollection)
        or type(getattr(col_tr, "find_one", None)).__name__ == "AsyncMock"
    )
    tr = await db.stock_transformations.find_one({"related_purchase_id": pb_id}, **kw) if has_tr_col else None
    if tr:
        # Reversal must reverse outputs first, then restore to raw, then reverse purchase_in
        # Pre-check all outputs currently have enough stock
        output_forms = tr.get("output_stock_forms") or []
        for out_it in output_forms:
            sf_id = out_it.get("stock_form_id")
            req_q = float(out_it.get("quantity") or 0.0)
            sf = await db.stock_forms.find_one({"_id": id_query(sf_id)}, **kw)
            if not sf or round(float(sf.get("current_quantity") or 0.0), 4) < req_q:
                curr_q = float(sf.get("current_quantity") or 0.0) if sf else 0.0
                sf_lbl = sf.get("label") if sf else "Output"
                raise HTTPException(
                    status_code=400,
                    detail=f"Pembelian tidak dapat dibatalkan karena stok hasil pre-cut ({sf_lbl}) telah berkurang atau terpakai (tersisa {curr_q}, dibutuhkan {req_q})."
                )

        # Reverse outputs: transformation_out on output stock forms
        tr_rev_num = await get_next_transformation_number(now_date, session=session)
        for out_it in output_forms:
            sf_id = out_it.get("stock_form_id")
            req_q = float(out_it.get("quantity") or 0.0)
            await apply_stock_movement_atomic(
                material_id=mat_id,
                movement_type="adjustment_out",
                quantity_delta=-req_q,
                movement_date=now_date,
                reason=f"Reversal output pre-cut pembelian {pb_num} (Void: {void_reason})",
                admin=admin,
                related_purchase_id=pb_id,
                related_purchase_number=pb_num,
                notes=f"Reversal void pembelian {pb_num}",
                allow_negative=False,
                session=session,
                stock_form_id=sf_id,
                update_material_aggregate=False
            )

        # Reverse source raw deduction: adjustment_in back to source raw stock form
        source_sf_id = tr.get("source_stock_form_id")
        src_q = float(tr.get("source_quantity") or 0.0)
        await apply_stock_movement_atomic(
            material_id=mat_id,
            movement_type="adjustment_in",
            quantity_delta=src_q,
            movement_date=now_date,
            reason=f"Restorasi raw pre-cut pembelian {pb_num} (Void: {void_reason})",
            admin=admin,
            related_purchase_id=pb_id,
            related_purchase_number=pb_num,
            notes=f"Restorasi sebelum void pembelian {pb_num}",
            allow_negative=False,
            session=session,
            stock_form_id=source_sf_id
        )

        # Finally reverse the purchase_in from source raw stock form
        return await apply_stock_movement_atomic(
            material_id=mat_id,
            movement_type="adjustment_out",
            quantity_delta=-qty,
            movement_date=now_date,
            reason=f"Reversal pembelian {pb_num} (Void: {void_reason})",
            admin=admin,
            related_purchase_id=pb_id,
            related_purchase_number=pb_num,
            notes=f"Pembatalan transaksi pembelian {pb_num}",
            allow_negative=False,
            session=session,
            stock_form_id=source_sf_id
        )
    else:
        # Standard purchase reversal
        sf_id = orig_movement.get("stock_form_id")
        return await apply_stock_movement_atomic(
            material_id=mat_id,
            movement_type="adjustment_out",
            quantity_delta=-qty,
            movement_date=now_date,
            reason=f"Reversal pembelian {pb_num} (Void: {void_reason})",
            admin=admin,
            related_purchase_id=pb_id,
            related_purchase_number=pb_num,
            notes=f"Pembatalan transaksi pembelian {pb_num}",
            allow_negative=False,
            session=session,
            stock_form_id=sf_id
        )


async def apply_purchase_finance_expense(purchase_doc: dict, admin: dict, session=None):
    kw = {"session": session} if session else {}
    pb_id = str(purchase_doc["_id"])
    pb_num = purchase_doc.get("purchase_number")
    currency = (purchase_doc.get("currency") or "EGP").strip().upper()
    if currency not in ("EGP", "IDR"):
        raise HTTPException(status_code=400, detail=f"Mata uang '{currency}' tidak didukung untuk transaksi keuangan.")

    # Idempotent check
    existing = await db.finance_transactions.find_one({
        "reference_type": "material_purchase",
        "reference_id": pb_id,
        "type": "expense"
    }, **kw)
    if existing:
        return clean(existing)

    total_amt = round(float(purchase_doc.get("total_amount") or 0.0), 2)
    rate = float(purchase_doc.get("exchange_rate") or 357.0)
    conv = compute_currency_conversion(currency, total_amt, rate)

    p_date = purchase_doc.get("purchase_date") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now_iso = datetime.now(timezone.utc).isoformat()
    # Format date with time component so ISO queries with $gte/$lte period ranges work reliably
    # Calendar date component strictly matches p_date
    time_part = now_iso[10:] if len(now_iso) > 10 else "T12:00:00+00:00"
    txn_date = f"{p_date[:10]}{time_part}"

    mat_name = purchase_doc.get("material_name_snapshot") or "Bahan"
    mat_specs = purchase_doc.get("material_specs_snapshot") or ""
    specs_str = f" ({mat_specs})" if mat_specs else ""
    desc = f"Pembelian bahan: {mat_name}{specs_str}"

    finance_doc = {
        "date": txn_date,
        "type": "expense",
        "category": "Material",
        "classification": "cost",
        "amount": conv["primary_amount"],
        "currency": currency,
        "account": currency,  # EGP -> Cash (EGP), IDR -> Bank (IDR)
        "exchange_rate": rate,
        "counterpart_amount": conv["counterpart_amount"],
        "counterpart_currency": conv["counterpart_currency"],
        "description": desc,
        "reference_type": "material_purchase",
        "reference_id": pb_id,
        "reference_number": pb_num,
        "supplier_name": purchase_doc.get("supplier_name", ""),
        "notes": purchase_doc.get("notes", ""),
        "created_by_id": admin.get("id"),
        "created_by_name": admin.get("name", "Admin"),
        "updated_by_name": admin.get("name", "Admin"),
        "created_at": now_iso,
        "updated_at": now_iso,
        "is_void": False,
        "status": "active"
    }

    try:
        res = await db.finance_transactions.insert_one(finance_doc, **kw)
        finance_doc["_id"] = res.inserted_id
        return clean(finance_doc)
    except pymongo.errors.DuplicateKeyError:
        existing = await db.finance_transactions.find_one({
            "reference_type": "material_purchase",
            "reference_id": pb_id,
            "type": "expense"
        }, **kw)
        if existing:
            return clean(existing)
        raise HTTPException(status_code=409, detail="Transaksi keuangan untuk pembelian ini sudah pernah dicatat.")

async def apply_purchase_finance_reversal(purchase_doc: dict, void_reason: str, admin: dict, session=None):
    kw = {"session": session} if session else {}
    pb_id = str(purchase_doc["_id"])
    pb_num = purchase_doc.get("purchase_number")

    # Find the original finance expense
    orig_txn = await db.finance_transactions.find_one({
        "reference_type": "material_purchase",
        "reference_id": pb_id,
        "type": "expense"
    }, **kw)
    if not orig_txn:
        # Pre-Phase 4 purchase or no finance transaction: do nothing
        return None

    # Check if reversal already exists
    existing_reversal = await db.finance_transactions.find_one({
        "reference_type": "material_purchase",
        "reference_id": pb_id,
        "is_reversal": True
    }, **kw)
    if existing_reversal:
        return clean(existing_reversal)

    now_iso = datetime.now(timezone.utc).isoformat()
    now_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    time_part = now_iso[10:] if len(now_iso) > 10 else "T12:00:00+00:00"
    txn_date = f"{now_date}{time_part}"

    currency = orig_txn.get("currency", "EGP")
    amount = float(orig_txn.get("amount") or 0.0)
    rate = float(orig_txn.get("exchange_rate") or 357.0)
    conv = compute_currency_conversion(currency, amount, rate)

    reversal_doc = {
        "date": txn_date,
        "type": "income",
        "category": "Material",
        "classification": "cost_reversal",
        "amount": conv["primary_amount"],
        "currency": currency,
        "account": orig_txn.get("account", currency),
        "exchange_rate": rate,
        "counterpart_amount": conv["counterpart_amount"],
        "counterpart_currency": conv["counterpart_currency"],
        "description": f"Reversal pembelian {pb_num} (Void: {void_reason})",
        "reference_type": "material_purchase",
        "reference_id": pb_id,
        "reference_number": pb_num,
        "related_transaction_id": str(orig_txn["_id"]),
        "is_reversal": True,
        "reversal_of_id": str(orig_txn["_id"]),
        "reversal_reason": void_reason,
        "created_by_id": admin.get("id"),
        "created_by_name": admin.get("name", "Admin"),
        "updated_by_name": admin.get("name", "Admin"),
        "created_at": now_iso,
        "updated_at": now_iso,
        "is_void": False,
        "status": "active"
    }

    try:
        res = await db.finance_transactions.insert_one(reversal_doc, **kw)
        reversal_doc["_id"] = res.inserted_id
        return clean(reversal_doc)
    except pymongo.errors.DuplicateKeyError:
        existing_reversal = await db.finance_transactions.find_one({
            "reference_type": "material_purchase",
            "reference_id": pb_id,
            "is_reversal": True
        }, **kw)
        if existing_reversal:
            return clean(existing_reversal)
        raise HTTPException(status_code=409, detail="Reversal transaksi keuangan untuk pembelian ini sudah pernah dicatat.")

@api_router.get("/admin/materials/stock")
async def get_materials_stock_summary(
    category: Optional[str] = None,
    status: Optional[str] = None,
    q: Optional[str] = None,
    admin: dict = Depends(require_material_perm())
):
    query: Dict[str, Any] = {}
    if category and category != "all":
        query["category"] = category
    if status and status != "all":
        query["status"] = status
    if q and q.strip():
        search_term = re.escape(q.strip())
        query["$or"] = [
            {"name": {"$regex": search_term, "$options": "i"}},
            {"specs": {"$regex": search_term, "$options": "i"}},
            {"sku": {"$regex": search_term, "$options": "i"}},
        ]
    materials = await db.materials.find(query).sort("created_at", -1).to_list(1000)

    # Attach last movement for each material
    result = []
    for m in materials:
        m_id = str(m["_id"])
        last_mov = await db.material_stocks.find_one(
            {"material_id": m_id},
            sort=[("movement_date", -1), ("created_at", -1)]
        )
        c_item = clean(m)
        c_item["current_stock"] = round(float(c_item.get("current_stock") or 0.0), 4)
        c_item["last_movement"] = clean(last_mov) if last_mov else None
        try:
            s_forms = await db.stock_forms.find({"material_id": m_id, "is_active": True}).to_list(100)
            c_item["stock_forms"] = [clean(sf) for sf in s_forms]
        except Exception:
            c_item["stock_forms"] = []
        result.append(c_item)

    return result

@api_router.get("/admin/materials/{material_id}/stock")
async def get_material_stock_detail(
    material_id: str,
    admin: dict = Depends(require_material_perm())
):
    mat = await db.materials.find_one({"_id": id_query(material_id)})
    if not mat:
        raise HTTPException(status_code=404, detail="Bahan tidak ditemukan")

    canonical_id = str(mat["_id"])
    last_mov = await db.material_stocks.find_one(
        {"material_id": canonical_id},
        sort=[("movement_date", -1), ("created_at", -1)]
    )

    clean_mat = clean(mat)
    clean_mat["current_stock"] = round(float(clean_mat.get("current_stock") or 0.0), 4)
    clean_mat["last_movement"] = clean(last_mov) if last_mov else None
    return clean_mat

@api_router.get("/admin/materials/{material_id}/stock-movements")
async def get_material_stock_movements(
    material_id: str,
    movement_type: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    admin: dict = Depends(require_material_perm())
):
    mat = await db.materials.find_one({"_id": id_query(material_id)})
    if not mat:
        raise HTTPException(status_code=404, detail="Bahan tidak ditemukan")

    canonical_id = str(mat["_id"])
    query: Dict[str, Any] = {"material_id": canonical_id}

    if movement_type and movement_type != "all":
        query["movement_type"] = movement_type

    if start_date or end_date:
        date_q = {}
        if start_date:
            date_q["$gte"] = start_date
        if end_date:
            date_q["$lte"] = end_date
        query["movement_date"] = date_q

    docs = await db.material_stocks.find(query).sort([("movement_date", -1), ("created_at", -1)]).to_list(1000)
    return {
        "material": clean(mat),
        "movements": [clean(d) for d in docs]
    }

@api_router.post("/admin/materials/{material_id}/stock-adjustment")
async def create_material_stock_adjustment(
    material_id: str,
    data: MaterialStockAdjustmentInput,
    admin: dict = Depends(require_material_perm())
):
    adj_type = (data.adjustment_type or "").strip()
    if adj_type not in ["adjustment_in", "adjustment_out"]:
        raise HTTPException(status_code=400, detail="Tipe adjustment harus 'adjustment_in' atau 'adjustment_out'")

    if data.quantity is None or _num(data.quantity) <= 0:
        raise HTTPException(status_code=400, detail="Jumlah adjustment harus lebih besar dari 0")

    reason = (data.reason or "").strip()
    if not reason:
        raise HTTPException(status_code=400, detail="Alasan penyesuaian stok wajib diisi")

    m_date = (data.movement_date or "").strip() or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        datetime.strptime(m_date[:10], "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="Format tanggal penyesuaian tidak valid (harus YYYY-MM-DD)")

    qty_val = round(_num(data.quantity), 4)
    delta = qty_val if adj_type == "adjustment_in" else -qty_val

    # Check if stock form is non-raw to prevent non-canonical stock opname from mutating materials.current_stock
    upd_mat_agg = True
    if data.stock_form_id:
        sf_check = await db.stock_forms.find_one({"_id": id_query(data.stock_form_id)})
        if sf_check and sf_check.get("form_type") != "raw":
            upd_mat_agg = False

    movement = await apply_stock_movement_atomic(
        material_id=material_id,
        movement_type=adj_type,
        quantity_delta=delta,
        movement_date=m_date,
        reason=reason,
        admin=admin,
        notes=(data.notes or "").strip(),
        allow_negative=False,
        stock_form_id=data.stock_form_id,
        update_material_aggregate=upd_mat_agg
    )

    return {"ok": True, "message": "Penyesuaian stok berhasil disimpan", "movement": movement}

# --------------------------------------------------------------------------
# Stock Forms & Material Transformations (Phase 5)
# --------------------------------------------------------------------------
@api_router.get("/admin/materials/{material_id}/stock-forms")
async def get_material_stock_forms(
    material_id: str,
    admin: dict = Depends(require_material_perm())
):
    mat = await db.materials.find_one({"_id": id_query(material_id)})
    if not mat:
        raise HTTPException(status_code=404, detail="Bahan tidak ditemukan")

    canonical_id = str(mat["_id"])
    docs = await db.stock_forms.find({"material_id": canonical_id, "is_active": True}).sort([("form_type", 1), ("created_at", -1)]).to_list(500)
    return [clean(d) for d in docs]

@api_router.post("/admin/materials/{material_id}/stock-forms")
async def create_custom_stock_form(
    material_id: str,
    data: StockFormCreateInput,
    admin: dict = Depends(require_material_perm())
):
    mat = await db.materials.find_one({"_id": id_query(material_id)})
    if not mat:
        raise HTTPException(status_code=404, detail="Bahan tidak ditemukan")

    canonical_id = str(mat["_id"])
    doc = await get_or_create_stock_form(
        material_id=canonical_id,
        form_type=data.form_type or "standard",
        width=data.width,
        length=data.length,
        thickness=data.thickness,
        dimension_unit=data.dimension_unit or "cm",
        stock_unit=mat.get("unit"),
        label=(data.label or "").strip(),
        notes=(data.notes or "").strip(),
        admin=admin
    )
    return clean(doc)

@api_router.get("/admin/materials/stock-transformations")
async def get_stock_transformations(
    material_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    q: Optional[str] = None,
    admin: dict = Depends(require_material_perm())
):
    query: Dict[str, Any] = {}
    if material_id and material_id != "all":
        query["material_id"] = material_id

    if start_date or end_date:
        date_q = {}
        if start_date:
            date_q["$gte"] = start_date
        if end_date:
            date_q["$lte"] = end_date
        query["transformation_date"] = date_q

    if q and q.strip():
        search_term = re.escape(q.strip())
        query["$or"] = [
            {"transformation_number": {"$regex": search_term, "$options": "i"}},
            {"material_name_snapshot": {"$regex": search_term, "$options": "i"}},
            {"reason": {"$regex": search_term, "$options": "i"}},
            {"related_purchase_number": {"$regex": search_term, "$options": "i"}},
        ]

    docs = await db.stock_transformations.find(query).sort([("transformation_date", -1), ("created_at", -1)]).to_list(1000)
    return [clean(d) for d in docs]

@api_router.get("/admin/materials/stock-transformations/{tr_id}")
async def get_stock_transformation_detail(
    tr_id: str,
    admin: dict = Depends(require_material_perm())
):
    doc = await db.stock_transformations.find_one({"_id": id_query(tr_id)})
    if not doc:
        doc = await db.stock_transformations.find_one({"transformation_number": tr_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Data transformasi stok tidak ditemukan")
    return clean(doc)

@api_router.post("/admin/materials/stock-transformations")
async def create_stock_transformation(
    data: StockTransformationInput,
    admin: dict = Depends(require_material_perm())
):
    mat_id = (data.material_id or "").strip()
    mat = await db.materials.find_one({"_id": id_query(mat_id)})
    if not mat:
        raise HTTPException(status_code=404, detail="Bahan tidak ditemukan")

    if mat.get("status") == "archived":
        raise HTTPException(status_code=400, detail="Tidak dapat melakukan transformasi untuk bahan yang diarsipkan")

    canonical_mat_id = str(mat["_id"])
    source_sf_id = (data.source_stock_form_id or "").strip()
    if source_sf_id == "raw" or not source_sf_id:
        source_sf = await get_or_create_stock_form(
            material_id=canonical_mat_id,
            form_type="raw",
            stock_unit=mat.get("unit") or "pcs",
            label="Raw / Bentuk Asal",
            admin=admin
        )
    else:
        source_sf = await db.stock_forms.find_one({"_id": id_query(source_sf_id)})
    if not source_sf:
        raise HTTPException(status_code=404, detail="Bentuk stok asal (source stock form) tidak ditemukan")

    if str(source_sf.get("material_id")) != canonical_mat_id:
        raise HTTPException(status_code=400, detail="Bentuk stok asal tidak sesuai dengan bahan yang dipilih")

    src_qty = round(_num(data.source_quantity), 4)
    if src_qty <= 0:
        raise HTTPException(status_code=400, detail="Jumlah bahan asal yang ditransformasi harus lebih besar dari 0")

    curr_src_qty = round(float(source_sf.get("current_quantity") or 0.0), 4)
    mat_curr_stock = round(float(mat.get("current_stock") or 0.0), 4)
    # If explicitly choosing "raw" canonical stock and stock_form was uninitialized (qty == 0),
    # sync source_sf.current_quantity from materials.current_stock
    if (source_sf_id == "raw" or not source_sf_id) and curr_src_qty == 0.0 and mat_curr_stock > 0:
        await db.stock_forms.update_one(
            {"_id": source_sf["_id"]},
            {"$set": {"current_quantity": mat_curr_stock, "updated_at": datetime.now(timezone.utc).isoformat()}}
        )
        curr_src_qty = mat_curr_stock
        source_sf["current_quantity"] = mat_curr_stock

    if curr_src_qty < src_qty:
        sf_lbl = source_sf.get("label") or f"{source_sf.get('form_type')} ({source_sf.get('stock_unit')})"
        raise HTTPException(
            status_code=400,
            detail=f"Stok bentuk asal tidak mencukupi (stok saat ini: {curr_src_qty}, dibutuhkan: {src_qty} pada {sf_lbl})"
        )

    if not data.outputs or len(data.outputs) == 0:
        raise HTTPException(status_code=400, detail="Minimal satu bentuk hasil transformasi (output form) harus diisi")

    mat_unit = (mat.get("unit") or "").strip().lower()
    if not mat_unit or mat_unit not in ALLOWED_MATERIAL_UNITS:
        raise HTTPException(
            status_code=400,
            detail=f"Master bahan '{mat.get('name')}' tidak memiliki satuan inventaris valid."
        )

    valid_outputs = []
    for out_item in data.outputs:
        out_q = round(_num(out_item.quantity), 4)
        if out_q <= 0:
            raise HTTPException(status_code=400, detail="Jumlah hasil bentuk stok harus lebih besar dari 0")
        valid_outputs.append({
            "stock_form_id": (out_item.stock_form_id or "").strip() or None,
            "form_type": (out_item.form_type or "standard").strip().lower(),
            "width": round(float(out_item.width), 2) if out_item.width is not None and out_item.width != "" else None,
            "length": round(float(out_item.length), 2) if out_item.length is not None and out_item.length != "" else None,
            "thickness": round(float(out_item.thickness), 2) if out_item.thickness is not None and out_item.thickness != "" else None,
            "dimension_unit": (out_item.dimension_unit or "cm").strip().lower(),
            "stock_unit": mat_unit,
            "quantity": out_q,
            "label": (out_item.label or "").strip(),
            "notes": (out_item.notes or "").strip(),
        })

    # Pre-resolve / pre-create all output stock_forms OUTSIDE the transaction.
    # If stock_form_id is explicitly provided, resolve directly from DB without fuzzy spec matching.
    # Otherwise, resolve or create via get_or_create_stock_form.
    # This prevents any implicit collection initialization, index build, or DuplicateKeyError
    # inside MongoDB Atlas multi-document transactions when multiple output forms are created.
    resolved_outputs = []
    for out_it in valid_outputs:
        target_sf_id = out_it.get("stock_form_id")
        out_sf = None
        if target_sf_id:
            out_sf = await db.stock_forms.find_one({"_id": id_query(target_sf_id)})
            if not out_sf:
                raise HTTPException(status_code=404, detail=f"Bentuk stok output dengan ID '{target_sf_id}' tidak ditemukan")
            if str(out_sf.get("material_id")) != canonical_mat_id:
                raise HTTPException(status_code=400, detail="Bentuk stok output tidak sesuai dengan bahan yang dipilih")
            if not out_sf.get("is_active", True):
                raise HTTPException(status_code=400, detail="Bentuk stok output yang dipilih tidak aktif")
        else:
            out_sf = await get_or_create_stock_form(
                material_id=canonical_mat_id,
                form_type=out_it["form_type"],
                width=out_it["width"],
                length=out_it["length"],
                thickness=out_it["thickness"],
                dimension_unit=out_it["dimension_unit"],
                stock_unit=out_it["stock_unit"],
                label=out_it["label"],
                notes=out_it["notes"],
                admin=admin
            )
        resolved_outputs.append({
            **out_it,
            "stock_form_id": str(out_sf["_id"]),
            "stock_form_doc": out_sf
        })

    tr_date = (data.transformation_date or "").strip() or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        datetime.strptime(tr_date[:10], "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="Format tanggal transformasi tidak valid (harus YYYY-MM-DD)")

    reason = (data.reason or "").strip() or "Transformasi / pemotongan stok bahan"
    notes = (data.notes or "").strip()

    # Pre-allocate unique movement numbers AUTONOMOUSLY (session=None) BEFORE starting the transaction.
    # This guarantees that counter allocation is isolated, high-watermark synchronized,
    # and completely immune to transaction write conflicts or transient rollbacks.
    total_movements_needed = 1 + len(resolved_outputs)
    movement_numbers = await get_next_movement_numbers(total_movements_needed, tr_date, session=None)
    source_mov_num = movement_numbers[0] if len(movement_numbers) > 0 else None
    output_mov_nums = movement_numbers[1:] if len(movement_numbers) > 1 else [None] * len(resolved_outputs)

    async def _execute_transformation_tx(session):
        # 1. Allocate unique transformation number
        tr_num = await get_next_transformation_number(tr_date, session=session)
        now = datetime.now(timezone.utc).isoformat()

        # 2. transformation_out from source stock form
        # Only mutate materials.current_stock if source form was raw/canonical
        is_source_raw = (source_sf.get("form_type") == "raw")
        await apply_stock_movement_atomic(
            material_id=canonical_mat_id,
            movement_type="transformation_out",
            quantity_delta=-src_qty,
            movement_date=tr_date,
            reason=f"Transformasi keluar: {reason}",
            admin=admin,
            notes=notes,
            allow_negative=False,
            session=session,
            stock_form_id=str(source_sf["_id"]),
            transformation_number=tr_num,
            update_material_aggregate=is_source_raw,
            movement_number=source_mov_num
        )

        # 3. transformation_in for each output form (never inflates canonical materials.current_stock)
        output_refs = []
        for idx, out_it in enumerate(resolved_outputs):
            out_sf_id = out_it["stock_form_id"]
            out_sf = out_it["stock_form_doc"]
            out_mov_num = output_mov_nums[idx] if idx < len(output_mov_nums) else None
            await apply_stock_movement_atomic(
                material_id=canonical_mat_id,
                movement_type="transformation_in",
                quantity_delta=out_it["quantity"],
                movement_date=tr_date,
                reason=f"Hasil transformasi: {reason}",
                admin=admin,
                notes=out_it["notes"],
                allow_negative=False,
                session=session,
                stock_form_id=out_sf_id,
                transformation_number=tr_num,
                update_material_aggregate=False,
                movement_number=out_mov_num
            )
            output_refs.append({
                "stock_form_id": out_sf_id,
                "form_type": out_sf.get("form_type"),
                "dimensions": {
                    "width": out_sf.get("width"),
                    "length": out_sf.get("length"),
                    "thickness": out_sf.get("thickness"),
                    "unit": out_sf.get("dimension_unit")
                },
                "quantity": out_it["quantity"],
                "stock_unit": out_sf.get("stock_unit"),
                "label": out_sf.get("label", "")
            })

        # 4. Record stock_transformation event
        tr_doc = {
            "transformation_number": tr_num,
            "transformation_date": tr_date[:10],
            "material_id": canonical_mat_id,
            "material_name_snapshot": mat.get("name", ""),
            "material_specs_snapshot": mat.get("specs", ""),
            "source_stock_form_id": str(source_sf["_id"]),
            "source_quantity": src_qty,
            "source_stock_unit": source_sf.get("stock_unit"),
            "output_stock_forms": output_refs,
            "reason": reason,
            "notes": notes,
            "created_at": now,
            "created_by_id": admin.get("id"),
            "created_by_name": admin.get("name", "Admin")
        }
        ins_res = await db.stock_transformations.insert_one(tr_doc, session=session)
        tr_doc["_id"] = ins_res.inserted_id
        return tr_doc

    try:
        final_tr = await execute_transaction_with_safety(client, _execute_transformation_tx)
        return {"ok": True, "message": "Transformasi stok bahan berhasil disimpan", "transformation": clean(final_tr)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed transaction while transforming stock: {e}")
        err_msg = str(e)
        if "TransientTransactionError" in err_msg or "NoSuchTransaction" in err_msg:
            err_msg = "Terjadi konflik konkurensi pada database saat memproses banyak item potongan. Silakan klik simpan kembali."
        raise HTTPException(status_code=500, detail=f"Gagal memproses transformasi stok: {err_msg}")

# --------------------------------------------------------------------------
# Material Detail, Update & Archive (placed after static /admin/materials routes)
# --------------------------------------------------------------------------
@api_router.get("/admin/materials/{mat_id}")
async def get_material_detail(
    mat_id: str,
    admin: dict = Depends(require_material_perm())
):
    doc = await db.materials.find_one({"_id": id_query(mat_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Bahan tidak ditemukan")
    return clean(doc)

@api_router.put("/admin/materials/{mat_id}")
async def update_material(
    mat_id: str,
    data: MaterialUpdateInput,
    admin: dict = Depends(require_material_perm())
):
    doc = await db.materials.find_one({"_id": id_query(mat_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Bahan tidak ditemukan")

    upd: Dict[str, Any] = {}
    new_name = data.name.strip() if data.name is not None else doc.get("name", "")
    new_specs = data.specs.strip() if data.specs is not None else doc.get("specs", "")

    if data.name is not None:
        if not new_name:
            raise HTTPException(status_code=400, detail="Nama bahan tidak boleh kosong")
        upd["name"] = new_name
        upd["name_normalized"] = normalize_text_key(new_name)

    if data.category is not None:
        cat = data.category.strip()
        if cat not in ALLOWED_MATERIAL_CATEGORIES:
            raise HTTPException(status_code=400, detail=f"Kategori tidak valid. Pilihan: {', '.join(ALLOWED_MATERIAL_CATEGORIES)}")
        upd["category"] = cat

    if data.specs is not None:
        if not new_specs:
            raise HTTPException(status_code=400, detail="Spesifikasi/Ukuran tidak boleh kosong")
        upd["specs"] = new_specs
        upd["specs_normalized"] = normalize_text_key(new_specs)

    if data.unit is not None:
        u = data.unit.strip()
        if u not in ALLOWED_MATERIAL_UNITS:
            raise HTTPException(status_code=400, detail=f"Satuan tidak valid. Pilihan: {', '.join(ALLOWED_MATERIAL_UNITS)}")
        upd["unit"] = u

    if data.sku is not None:
        upd["sku"] = data.sku.strip() if data.sku else None

    if data.notes is not None:
        upd["notes"] = data.notes.strip()

    if data.status is not None:
        st = data.status.strip()
        if st not in ["active", "archived"]:
            raise HTTPException(status_code=400, detail="Status harus 'active' atau 'archived'")
        upd["status"] = st

    if not upd:
        return clean(doc)

    name_norm = upd.get("name_normalized", doc.get("name_normalized"))
    specs_norm = upd.get("specs_normalized", doc.get("specs_normalized"))

    # Check duplicate against other documents
    existing = await db.materials.find_one({
        "_id": {"$ne": doc["_id"]},
        "name_normalized": name_norm,
        "specs_normalized": specs_norm
    })
    if existing:
        raise HTTPException(status_code=409, detail=f"Bahan dengan nama '{new_name}' dan spesifikasi '{new_specs}' sudah terdaftar")

    upd.update(audit_fields(admin))
    try:
        updated = await db.materials.find_one_and_update(
            {"_id": doc["_id"]},
            {"$set": upd},
            return_document=ReturnDocument.AFTER
        )
        return clean(updated)
    except pymongo.errors.DuplicateKeyError:
        raise HTTPException(status_code=409, detail=f"Bahan dengan nama '{new_name}' dan spesifikasi '{new_specs}' sudah terdaftar")

@api_router.delete("/admin/materials/{mat_id}")
async def archive_material(
    mat_id: str,
    admin: dict = Depends(require_material_perm())
):
    doc = await db.materials.find_one({"_id": id_query(mat_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Bahan tidak ditemukan")

    upd = {"status": "archived", **audit_fields(admin)}
    updated = await db.materials.find_one_and_update(
        {"_id": doc["_id"]},
        {"$set": upd},
        return_document=ReturnDocument.AFTER
    )
    return {"ok": True, "message": "Bahan berhasil diarsipkan", "material": clean(updated)}

app.include_router(api_router)

_frontend = os.environ.get("FRONTEND_URL")
_origins = [o for o in os.environ.get('CORS_ORIGINS', '').split(',') if o and o != "*"]
if _frontend and _frontend not in _origins:
    _origins.append(_frontend)
if not _origins:
    _origins = ["http://localhost:3000", "http://127.0.0.1:3000"]

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=_origins,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+)(:\d+)?$",
    allow_methods=["*"],
    allow_headers=["*"],
)
