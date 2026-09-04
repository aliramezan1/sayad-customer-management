"""
Main FastAPI Web Application for Customer & Cheque Management System.
"""
import os
import io
import logging
import time
from threading import Lock
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException, Query, BackgroundTasks, Response, Request, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse, JSONResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
import pandas as pd
import openpyxl

from app.database import get_db, init_db
from app.schemas import (
    CustomerCreate, CustomerUpdate,
    ChequeCreate, ChequeUpdate,
    PasargadInquiryRequest, BatchInquiryRequest
)
from app.services.pasargad import record_pasargad_inquiry, query_pasargad_bounced_cheques, check_pasargad_health
from app.services.scheduler import scheduler_instance
from app.services.smart_logger import smart_logger
from app.services.risk_engine import (
    calculate_customer_fhs,
    get_cash_flow_forecast,
    get_risk_matrix,
    get_near_maturity_alerts,
    get_all_customers_fhs
)
from pydantic import BaseModel

class TTLCache:
    """
    Thread-safe in-memory cache with Time-To-Live (TTL) expiration.
    Used for accelerating heavy dashboard aggregated queries (/api/stats).
    """
    def __init__(self, ttl: float = 300.0, maxsize: int = 64):
        self.ttl = ttl
        self.maxsize = maxsize
        self._data: Dict[str, Any] = {}
        self._expires: Dict[str, float] = {}
        self._lock = Lock()

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            if key in self._data:
                if time.monotonic() < self._expires.get(key, 0):
                    return self._data[key]
                self._data.pop(key, None)
                self._expires.pop(key, None)
            return default

    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        with self._lock:
            if len(self._data) >= self.maxsize and key not in self._data:
                now = time.monotonic()
                expired = [k for k, exp in self._expires.items() if exp <= now]
                for k in expired:
                    self._data.pop(k, None)
                    self._expires.pop(k, None)
                if len(self._data) >= self.maxsize:
                    oldest = next(iter(self._data))
                    self._data.pop(oldest, None)
                    self._expires.pop(oldest, None)

            self._data[key] = value
            self._expires[key] = time.monotonic() + (ttl if ttl is not None else self.ttl)

    def invalidate(self, key: Optional[str] = None) -> None:
        with self._lock:
            if key is None:
                self._data.clear()
                self._expires.clear()
            else:
                self._data.pop(key, None)
                self._expires.pop(key, None)

    def clear(self) -> None:
        self.invalidate()

# Dashboard stats in-memory cache (5 minutes = 300 seconds TTL)
stats_cache = TTLCache(ttl=300.0, maxsize=32)

def invalidate_stats_cache():
    """Invalidate dashboard metrics cache upon data mutations."""
    stats_cache.invalidate()
    logger.debug("Dashboard stats cache invalidated.")

class ClientLogRequest(BaseModel):
    level: str = "INFO"
    tag: str = "CLIENT"
    message: str
    details: Optional[Dict[str, Any]] = None
    sayadi_id: Optional[str] = None
    customer_name: Optional[str] = None


# ─────────────────────────────────────────────────────────────
# 🛡️ 3-Tier Role-Based Access Control (RBAC) Architecture
# ─────────────────────────────────────────────────────────────
ROLE_ADMIN = "admin"
ROLE_OPERATOR = "operator"
ROLE_AUDITOR = "auditor"

ROLES_INFO = {
    ROLE_ADMIN: {
        "role": ROLE_ADMIN,
        "title": "مدیر ارشد سامانه (علی رمضانزاده)",
        "user_name": "علی رمضانزاده",
        "permissions": {
            "can_read": True,
            "can_write": True,
            "can_delete": True,
            "can_inquire": True,
            "can_backup": True,
            "can_restore": True,
            "can_manage_system": True
        },
        "description": "دسترسی کامل و نامحدود به تمامی بخش‌ها، ثبت، ویرایش، حذف رکوردها، بازگردانی پایگاه داده و مدیریت سامانه"
    },
    ROLE_OPERATOR: {
        "role": ROLE_OPERATOR,
        "title": "اپراتور سامانه",
        "user_name": "اپراتور صیاد",
        "permissions": {
            "can_read": True,
            "can_write": True,
            "can_delete": False,
            "can_inquire": True,
            "can_backup": True,
            "can_restore": False,
            "can_manage_system": False
        },
        "description": "ثبت و ویرایش مشتریان و چک‌ها، استعلام بانکی و ایجاد پشتیبان (فاقد دسترسی به حذف رکورد یا بازگردانی دیتابیس)"
    },
    ROLE_AUDITOR: {
        "role": ROLE_AUDITOR,
        "title": "ناظر و حسابرس مالی",
        "user_name": "ناظر اعتباری",
        "permissions": {
            "can_read": True,
            "can_write": False,
            "can_delete": False,
            "can_inquire": False,
            "can_backup": False,
            "can_restore": False,
            "can_manage_system": False
        },
        "description": "دسترسی صرفاً خواندنی به داشبورد، گزارش‌ها، لاگ‌ها و دانلود پشتیبان‌ها (فاقد ثبت، ویرایش، حذف، استعلام یا بازگردانی)"
    }
}

# Default active system role
current_system_role: str = ROLE_ADMIN

class SwitchRoleRequest(BaseModel):
    role: str

class BackupCreateRequest(BaseModel):
    tag: Optional[str] = "manual"

def get_request_role(request: Request) -> str:
    """
    Extracts caller role:
    1. Checks header 'X-Role' or 'X-User-Role'.
    2. Checks cookie 'sayad_role'.
    3. Defaults to current_system_role (default: admin).
    """
    header_role = request.headers.get("X-Role") or request.headers.get("X-User-Role")
    if header_role:
        return header_role.strip().lower()
    cookie_role = request.cookies.get("sayad_role")
    if cookie_role:
        return cookie_role.strip().lower()
    return current_system_role

def require_role(allowed_roles: List[str]):
    """
    Dependency to enforce RBAC permissions.
    Raises HTTP 403 Forbidden with clear Persian messages if access is denied.
    """
    def _role_checker(request: Request):
        role = get_request_role(request)
        if role not in allowed_roles:
            if role == ROLE_OPERATOR:
                detail = "دسترسی غیرمجاز: نقش اپراتور مجاز به حذف اطلاعات یا بازگردانی پایگاه داده نیست."
            elif role == ROLE_AUDITOR:
                detail = "دسترسی غیرمجاز: نقش ناظر/حسابرس فقط دسترسی خواندنی داشته و مجاز به تغییر داده‌ها، ثبت، حذف، بازگردانی یا اجرای استعلام نیست."
            else:
                detail = f"دسترسی غیرمجاز: نقش فعال '{role}' مجوز لازم برای این عملیات را ندارد."
            raise HTTPException(status_code=403, detail=detail)
        return role
    return Depends(_role_checker)


# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("app.main")

# Initialize app
app = FastAPI(
    title="سامانه جامع مدیریت مشتریان و چک‌های صیادی",
    description="وب‌اپلیکیشن مدیریت پروفایل مشتریان، استعلام صیادی بانک مرکزی و استعلام اعتباری بانک پاسارگاد",
    version="2.0.0"
)

# GZip compression middleware (compress responses >= 1000 bytes)
app.add_middleware(GZipMiddleware, minimum_size=1000)

# CORS middleware with Private Network Access support for Hybrid Cloud Bridge
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_private_network_header(request, call_next):
    """Add Access-Control-Allow-Private-Network for Chromium PNA preflight."""
    if request.method == "OPTIONS":
        response = Response()
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "*"
        response.headers["Access-Control-Allow-Private-Network"] = "true"
        return response
    
    response = await call_next(request)
    response.headers["Access-Control-Allow-Private-Network"] = "true"
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response


# Mount static files
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(BASE_DIR, "app", "static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

if not os.path.exists(STATIC_DIR):
    os.makedirs(STATIC_DIR, exist_ok=True)
if not os.path.exists(TEMPLATES_DIR):
    os.makedirs(TEMPLATES_DIR, exist_ok=True)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Mount subpaths so relative links (css/..., js/..., data/...) work identically
css_dir = os.path.join(STATIC_DIR, "css")
js_dir = os.path.join(STATIC_DIR, "js")
data_dir = os.path.join(STATIC_DIR, "data")
if os.path.exists(css_dir):
    app.mount("/css", StaticFiles(directory=css_dir), name="css")
if os.path.exists(js_dir):
    app.mount("/js", StaticFiles(directory=js_dir), name="js")
if os.path.exists(data_dir):
    app.mount("/data", StaticFiles(directory=data_dir), name="data")


@app.on_event("startup")
def startup_event():
    """Initialize DB and start background scheduler on startup."""
    init_db()
    scheduler_instance.start()
    logger.info("FastAPI Server and Background Services Started.")

# ─────────────────────────────────────────────────────────────
# 📄 Page Routes
# ─────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
def index_page():
    """Render main Single Page Application."""
    index_file = os.path.join(TEMPLATES_DIR, "index.html")
    if os.path.exists(index_file):
        with open(index_file, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>سامانه مدیریت مشتریان و چک‌های صیادی در حال بارگذاری است...</h1>"

@app.get("/manifest.json")
def get_manifest():
    """Serve PWA Web App Manifest."""
    manifest_path = os.path.join(STATIC_DIR, "manifest.json")
    if os.path.exists(manifest_path):
        return FileResponse(manifest_path, media_type="application/manifest+json")
    raise HTTPException(status_code=404, detail="فایل منیفست PWA یافت نشد.")

@app.get("/sw.js")
def get_service_worker():
    """Serve PWA Service Worker with root scope authorization."""
    sw_path = os.path.join(STATIC_DIR, "sw.js")
    if os.path.exists(sw_path):
        return FileResponse(
            sw_path,
            media_type="application/javascript",
            headers={"Service-Worker-Allowed": "/"}
        )
    raise HTTPException(status_code=404, detail="فایل سرویس ورکر PWA یافت نشد.")

# ─────────────────────────────────────────────────────────────
# 📊 Dashboard & Stats API
# ─────────────────────────────────────────────────────────────
@app.get("/api/stats")
def get_dashboard_stats():
    """Get aggregated metrics and dashboard stats with TTLCache acceleration."""
    cached_stats = stats_cache.get("dashboard_stats")
    if cached_stats is not None:
        return cached_stats

    conn = get_db()
    cursor = conn.cursor()

    # Total counts
    cursor.execute("SELECT COUNT(*) FROM customers")
    total_customers = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*), COALESCE(SUM(amount), 0) FROM cheques")
    ch_row = cursor.fetchone()
    total_cheques = ch_row[0]
    total_amount = ch_row[1]

    # Pasargad inquiries sum based on latest inquiry per distinct sayadi_id
    cursor.execute("""
    SELECT 
        COALESCE(SUM(in_transit_amount), 0),
        COALESCE(SUM(cleared_amount), 0),
        COALESCE(SUM(bounced_amount), 0),
        COALESCE(SUM(bounced_count), 0)
    FROM pasargad_inquiries
    WHERE id IN (
        SELECT MAX(id) FROM pasargad_inquiries GROUP BY sayadi_id
    )
    """)
    pasargad_row = cursor.fetchone()
    in_transit_sum = pasargad_row[0]
    cleared_sum = pasargad_row[1]
    bounced_sum = pasargad_row[2]
    bounced_count = pasargad_row[3]

    # Credit Color Distribution
    cursor.execute("""
    SELECT credit_color, COUNT(*) FROM customers
    WHERE credit_color IS NOT NULL AND credit_color != ''
    GROUP BY credit_color
    """)
    colors = {row[0]: row[1] for row in cursor.fetchall()}

    # Recent inquiries
    cursor.execute("""
    SELECT 
        pi.id, pi.sayadi_id, pi.inquiry_time, pi.in_transit_amount, pi.bounced_amount,
        h.full_name as holder_name,
        c.full_name as customer_name
    FROM pasargad_inquiries pi
    LEFT JOIN holders h ON pi.holder_id = h.id
    LEFT JOIN customers c ON pi.customer_id = c.id
    ORDER BY pi.id DESC LIMIT 6
    """)
    recent_inquiries = [dict(row) for row in cursor.fetchall()]

    conn.close()
    stats_data = {
        "total_customers": total_customers,
        "total_cheques": total_cheques,
        "total_amount": total_amount,
        "in_transit_amount": in_transit_sum,
        "cleared_amount": cleared_sum,
        "bounced_amount": bounced_sum,
        "bounced_count": bounced_count,
        "credit_colors": colors,
        "recent_inquiries": recent_inquiries
    }
    stats_cache.set("dashboard_stats", stats_data)
    return stats_data

# ─────────────────────────────────────────────────────────────
# 📈 Fintech Intelligence & Risk Analytics API (Phase 4)
# ─────────────────────────────────────────────────────────────
@app.get("/api/analytics/cash-flow")
def get_cash_flow_analytics(
    days: int = Query(90, ge=7, le=365, description="افق پیش‌بینی بر حسب روز"),
    role: str = require_role([ROLE_ADMIN, ROLE_OPERATOR, ROLE_AUDITOR])
):
    """
    Risk-Weighted Predictive Cash Flow Analytics.
    Returns nominal vs realizable inflows, shortfall, and maturity timeline.
    Accelerated with TTLCache and accessible by admin, operator, and auditor.
    """
    cache_key = f"analytics_cash_flow_{days}"
    cached = stats_cache.get(cache_key)
    if cached is not None:
        return cached

    forecast = get_cash_flow_forecast(days=days)
    stats_cache.set(cache_key, forecast, ttl=180.0)
    return forecast


@app.get("/api/analytics/risk-matrix")
def get_risk_matrix_analytics(
    role: str = require_role([ROLE_ADMIN, ROLE_OPERATOR, ROLE_AUDITOR])
):
    """
    2D Fintech Risk Matrix Analytics.
    Returns 4-quadrant customer segmentation (Stars, Opportunities, Watchlist, Critical).
    Accelerated with TTLCache and accessible by admin, operator, and auditor.
    """
    cache_key = "analytics_risk_matrix"
    cached = stats_cache.get(cache_key)
    if cached is not None:
        return cached

    matrix = get_risk_matrix()
    stats_cache.set(cache_key, matrix, ttl=180.0)
    return matrix


@app.get("/api/analytics/customer-fhs/{customer_id}")
def get_customer_fhs_analytics(
    customer_id: int,
    role: str = require_role([ROLE_ADMIN, ROLE_OPERATOR, ROLE_AUDITOR])
):
    """
    Calculates detailed Financial Health Score (FHS: 0-100) and risk factors for a specific customer.
    """
    try:
        return calculate_customer_fhs(customer_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error computing FHS for customer {customer_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="خطا در محاسبه شاخص سلامت مالی مشتری.")


@app.get("/api/analytics/alerts/near-maturity")
def get_near_maturity_alerts_api(
    days: int = Query(7, ge=1, le=30),
    role: str = require_role([ROLE_ADMIN, ROLE_OPERATOR, ROLE_AUDITOR])
):
    """
    Retrieves cheques maturing within the specified upcoming days (default 7 days).
    """
    cache_key = f"analytics_alerts_near_maturity_{days}"
    cached = stats_cache.get(cache_key)
    if cached is not None:
        return cached

    alerts = get_near_maturity_alerts(days_threshold=days)
    result = {"count": len(alerts), "alerts": alerts}
    stats_cache.set(cache_key, result, ttl=120.0)
    return result

# ─────────────────────────────────────────────────────────────
# 👥 Customer CRUD & Profiles API
# ─────────────────────────────────────────────────────────────
@app.get("/api/customers")
def list_customers(
    q: Optional[str] = None,
    color: Optional[str] = None,
    limit: int = 100,
    offset: int = 0
):
    """List all customers with search and filters."""
    conn = get_db()
    cursor = conn.cursor()

    query = """
    SELECT 
        c.id, c.full_name, c.national_id, c.phone, c.address, c.notes,
        c.credit_color, c.risk_score, c.original_name_alias, c.created_at,
        (SELECT COUNT(*) FROM cheques WHERE customer_id = c.id) as cheque_count,
        (SELECT COALESCE(SUM(amount), 0) FROM cheques WHERE customer_id = c.id) as total_cheque_amount,
        (SELECT COALESCE(SUM(pi.in_transit_amount), 0) FROM pasargad_inquiries pi WHERE (pi.sayadi_id IN (SELECT sayadi_id FROM cheques WHERE customer_id = c.id) OR (pi.customer_id = c.id AND pi.sayadi_id NOT IN (SELECT sayadi_id FROM cheques))) AND pi.id IN (SELECT MAX(id) FROM pasargad_inquiries GROUP BY sayadi_id)) as in_transit_total,
        (SELECT COALESCE(SUM(pi.bounced_amount), 0) FROM pasargad_inquiries pi WHERE (pi.sayadi_id IN (SELECT sayadi_id FROM cheques WHERE customer_id = c.id) OR (pi.customer_id = c.id AND pi.sayadi_id NOT IN (SELECT sayadi_id FROM cheques))) AND pi.id IN (SELECT MAX(id) FROM pasargad_inquiries GROUP BY sayadi_id)) as bounced_total
    FROM customers c
    WHERE 1=1
    """
    params = []

    if q and q.strip():
        search_term = f"%{q.strip()}%"
        query += """ AND (
            c.full_name LIKE ? OR 
            c.national_id LIKE ? OR 
            c.phone LIKE ? OR 
            c.original_name_alias LIKE ? OR
            EXISTS (SELECT 1 FROM cheques ch WHERE ch.customer_id = c.id AND (ch.sayadi_id LIKE ? OR ch.cheque_number LIKE ?))
        )"""
        params.extend([search_term, search_term, search_term, search_term, search_term, search_term])

    if color and color.strip() and color != "all":
        query += " AND c.credit_color = ?"
        params.append(color.strip())

    query += " ORDER BY total_cheque_amount DESC, c.id DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    cursor.execute(query, params)
    customers = [dict(row) for row in cursor.fetchall()]
    conn.close()

    # Pre-calculate FHS metrics for quick badge display
    try:
        all_fhs = get_all_customers_fhs()
        fhs_lookup = {f["customer_id"]: f for f in all_fhs}
        for c in customers:
            f = fhs_lookup.get(c["id"])
            if f:
                c["fhs_score"] = f["fhs_score"]
                c["fhs_level"] = f["level"]
                c["fhs_color"] = f["color"]
                c["fhs_bg_class"] = f["bg_class"]
            else:
                c["fhs_score"] = 50.0
                c["fhs_level"] = "متوسط"
                c["fhs_color"] = "#f59e0b"
                c["fhs_bg_class"] = "bg-amber-500/10 text-amber-400 border-amber-500/30"
    except Exception as e:
        logger.warning(f"Could not load FHS batch for customers: {e}")

    return {"customers": customers, "count": len(customers)}


@app.get("/api/customers/{customer_id}")
def get_customer_profile(customer_id: int):
    """Get dedicated customer profile, associated cheques, and inquiry history."""
    conn = get_db()
    cursor = conn.cursor()

    # Customer info
    cursor.execute("SELECT * FROM customers WHERE id = ?", (customer_id,))
    customer = cursor.fetchone()
    if not customer:
        conn.close()
        raise HTTPException(status_code=404, detail="مشتری یافت نشد.")

    customer_dict = dict(customer)

    # Cheques for this customer
    cursor.execute("""
    SELECT 
        ch.id, ch.customer_id, ch.sayadi_id, ch.cheque_number, ch.amount,
        ch.cheque_date, ch.bank_name, ch.holder_id, ch.status, ch.notes,
        ch.created_at,
        h.full_name as holder_name,
        h.national_id as holder_national_id,
        (SELECT in_transit_amount FROM pasargad_inquiries WHERE sayadi_id = ch.sayadi_id ORDER BY id DESC LIMIT 1) as last_in_transit,
        (SELECT cleared_amount FROM pasargad_inquiries WHERE sayadi_id = ch.sayadi_id ORDER BY id DESC LIMIT 1) as last_cleared,
        (SELECT bounced_amount FROM pasargad_inquiries WHERE sayadi_id = ch.sayadi_id ORDER BY id DESC LIMIT 1) as last_bounced,
        (SELECT inquiry_time FROM pasargad_inquiries WHERE sayadi_id = ch.sayadi_id ORDER BY id DESC LIMIT 1) as last_inquiry_time
    FROM cheques ch
    LEFT JOIN holders h ON ch.holder_id = h.id
    WHERE ch.customer_id = ?
    ORDER BY ch.cheque_date ASC, ch.id DESC
    """, (customer_id,))
    cheques = [dict(row) for row in cursor.fetchall()]

    # Financial Summary
    total_amount = sum(c["amount"] or 0 for c in cheques)
    total_in_transit = sum(c["last_in_transit"] or 0 for c in cheques)
    total_bounced = sum(c["last_bounced"] or 0 for c in cheques)
    total_cleared = sum(c["last_cleared"] or 0 for c in cheques)

    # Inquiries history
    cursor.execute("""
    SELECT 
        pi.id, pi.sayadi_id, pi.holder_id, pi.in_transit_amount, pi.cleared_amount,
        pi.bounced_amount, pi.bounced_count, pi.inquiry_time, pi.status,
        h.full_name as holder_name
    FROM pasargad_inquiries pi
    LEFT JOIN holders h ON pi.holder_id = h.id
    WHERE (pi.customer_id = ? OR pi.sayadi_id IN (SELECT sayadi_id FROM cheques WHERE customer_id = ?))
    ORDER BY pi.id DESC
    LIMIT 50
    """, (customer_id, customer_id))
    inquiries = [dict(row) for row in cursor.fetchall()]

    conn.close()

    fhs_data = None
    try:
        fhs_data = calculate_customer_fhs(customer_id)
    except Exception as e:
        logger.warning(f"Failed to calculate FHS in profile for {customer_id}: {e}")

    return {
        "customer": customer_dict,
        "cheques": cheques,
        "inquiries": inquiries,
        "fhs": fhs_data,
        "summary": {
            "cheque_count": len(cheques),
            "total_amount": total_amount,
            "total_in_transit": total_in_transit,
            "total_bounced": total_bounced,
            "total_cleared": total_cleared
        }
    }

@app.post("/api/customers")
def create_customer(
    data: CustomerCreate,
    role: str = require_role([ROLE_ADMIN, ROLE_OPERATOR])
):
    """Add a new customer profile."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("""
        INSERT INTO customers (full_name, national_id, phone, address, notes, credit_color, risk_score)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            data.full_name.strip(),
            data.national_id,
            data.phone,
            data.address,
            data.notes,
            data.credit_color or "نامشخص",
            data.risk_score or 0
        ))
        conn.commit()
        customer_id = cursor.lastrowid
        conn.close()
        invalidate_stats_cache()
        return {"status": "success", "customer_id": customer_id, "message": "مشتری با موفقیت ثبت شد."}
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=400, detail=f"خطا در ثبت مشتری: {str(e)}")

@app.put("/api/customers/{customer_id}")
def update_customer(
    customer_id: int,
    data: CustomerUpdate,
    role: str = require_role([ROLE_ADMIN, ROLE_OPERATOR])
):
    """Update an existing customer profile."""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM customers WHERE id = ?", (customer_id,))
    if not cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="مشتری یافت نشد.")

    updates = []
    params = []
    if data.full_name is not None:
        updates.append("full_name = ?")
        params.append(data.full_name.strip())
    if data.national_id is not None:
        updates.append("national_id = ?")
        params.append(data.national_id.strip())
    if data.phone is not None:
        updates.append("phone = ?")
        params.append(data.phone.strip())
    if data.address is not None:
        updates.append("address = ?")
        params.append(data.address.strip())
    if data.notes is not None:
        updates.append("notes = ?")
        params.append(data.notes.strip())
    if data.credit_color is not None:
        updates.append("credit_color = ?")
        params.append(data.credit_color)
    if data.risk_score is not None:
        updates.append("risk_score = ?")
        params.append(data.risk_score)

    if not updates:
        conn.close()
        return {"status": "success", "message": "تغییری اعمال نشد."}

    updates.append("updated_at = datetime('now', 'localtime')")
    params.append(customer_id)

    query = f"UPDATE customers SET {', '.join(updates)} WHERE id = ?"
    try:
        cursor.execute(query, params)
        conn.commit()
        conn.close()
        invalidate_stats_cache()
        return {"status": "success", "message": "اطلاعات مشتری با موفقیت به‌روزرسانی شد."}
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=400, detail=f"خطا در به‌روزرسانی مشتری: {str(e)}")

@app.delete("/api/customers/{customer_id}")
def delete_customer(
    customer_id: int,
    role: str = require_role([ROLE_ADMIN])
):
    """Delete a customer and unbind their cheques."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE cheques SET customer_id = NULL WHERE customer_id = ?", (customer_id,))
        cursor.execute("DELETE FROM customers WHERE id = ?", (customer_id,))
        conn.commit()
        conn.close()
        invalidate_stats_cache()
        return {"status": "success", "message": "مشتری با موفقیت حذف شد."}
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=400, detail=f"خطا در حذف مشتری: {str(e)}")

# ─────────────────────────────────────────────────────────────
# 📑 Cheques CRUD API
# ─────────────────────────────────────────────────────────────
@app.get("/api/cheques")
def list_cheques(
    customer_id: Optional[int] = None,
    sayadi_id: Optional[str] = None,
    status: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 100,
    offset: int = 0
):
    """List cheques with filters."""
    conn = get_db()
    cursor = conn.cursor()

    query = """
    SELECT 
        ch.id, ch.customer_id, ch.sayadi_id, ch.cheque_number, ch.amount,
        ch.cheque_date, ch.bank_name, ch.holder_id, ch.status, ch.notes,
        ch.created_at,
        c.full_name as customer_name,
        c.credit_color as customer_credit_color,
        h.full_name as holder_name,
        (SELECT in_transit_amount FROM pasargad_inquiries WHERE sayadi_id = ch.sayadi_id ORDER BY id DESC LIMIT 1) as in_transit_amount,
        (SELECT bounced_amount FROM pasargad_inquiries WHERE sayadi_id = ch.sayadi_id ORDER BY id DESC LIMIT 1) as bounced_amount
    FROM cheques ch
    LEFT JOIN customers c ON ch.customer_id = c.id
    LEFT JOIN holders h ON ch.holder_id = h.id
    WHERE 1=1
    """
    params = []

    if customer_id:
        query += " AND ch.customer_id = ?"
        params.append(customer_id)
    if sayadi_id:
        query += " AND ch.sayadi_id LIKE ?"
        params.append(f"%{sayadi_id.strip()}%")
    if status and status != "all":
        query += " AND ch.status = ?"
        params.append(status)
    if q and q.strip():
        term = f"%{q.strip()}%"
        query += " AND (ch.sayadi_id LIKE ? OR ch.cheque_number LIKE ? OR c.full_name LIKE ? OR ch.bank_name LIKE ?)"
        params.extend([term, term, term, term])

    query += " ORDER BY ch.id DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    cursor.execute(query, params)
    cheques = [dict(row) for row in cursor.fetchall()]
    conn.close()

    return {"cheques": cheques, "count": len(cheques)}

@app.post("/api/cheques")
def create_cheque(
    data: ChequeCreate,
    role: str = require_role([ROLE_ADMIN, ROLE_OPERATOR])
):
    """Create a new cheque for a customer."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("""
        INSERT INTO cheques (customer_id, sayadi_id, cheque_number, amount, cheque_date, bank_name, holder_id, status, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data.customer_id,
            data.sayadi_id.strip(),
            data.cheque_number,
            data.amount,
            data.cheque_date,
            data.bank_name,
            data.holder_id,
            data.status or "pending",
            data.notes
        ))
        conn.commit()
        cheque_id = cursor.lastrowid
        conn.close()
        invalidate_stats_cache()
        return {"status": "success", "cheque_id": cheque_id, "message": "چک جدید با موفقیت ثبت گردید."}
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=400, detail=f"خطا در ثبت چک: {str(e)}")

@app.put("/api/cheques/{cheque_id}")
def update_cheque(
    cheque_id: int,
    data: ChequeUpdate,
    role: str = require_role([ROLE_ADMIN, ROLE_OPERATOR])
):
    """Update an existing cheque."""
    conn = get_db()
    cursor = conn.cursor()

    updates = []
    params = []
    if data.customer_id is not None:
        updates.append("customer_id = ?")
        params.append(data.customer_id)
    if data.sayadi_id is not None:
        updates.append("sayadi_id = ?")
        params.append(data.sayadi_id.strip())
    if data.cheque_number is not None:
        updates.append("cheque_number = ?")
        params.append(data.cheque_number)
    if data.amount is not None:
        updates.append("amount = ?")
        params.append(data.amount)
    if data.cheque_date is not None:
        updates.append("cheque_date = ?")
        params.append(data.cheque_date)
    if data.bank_name is not None:
        updates.append("bank_name = ?")
        params.append(data.bank_name)
    if data.holder_id is not None:
        updates.append("holder_id = ?")
        params.append(data.holder_id)
    if data.status is not None:
        updates.append("status = ?")
        params.append(data.status)
    if data.notes is not None:
        updates.append("notes = ?")
        params.append(data.notes)

    if not updates:
        conn.close()
        return {"status": "success", "message": "تغییری اعمال نشد."}

    updates.append("updated_at = datetime('now', 'localtime')")
    params.append(cheque_id)

    query = f"UPDATE cheques SET {', '.join(updates)} WHERE id = ?"
    try:
        cursor.execute(query, params)
        conn.commit()
        conn.close()
        invalidate_stats_cache()
        return {"status": "success", "message": "اطلاعات چک با موفقیت به‌روزرسانی شد."}
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=400, detail=f"خطا در به‌روزرسانی چک: {str(e)}")

@app.delete("/api/cheques/{cheque_id}")
def delete_cheque(
    cheque_id: int,
    role: str = require_role([ROLE_ADMIN])
):
    """Delete a cheque."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM cheques WHERE id = ?", (cheque_id,))
        conn.commit()
        conn.close()
        invalidate_stats_cache()
        return {"status": "success", "message": "چک با موفقیت حذف گردید."}
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=400, detail=f"خطا در حذف چک: {str(e)}")

# ─────────────────────────────────────────────────────────────
# 🏦 Predefined 9 Holders API
# ─────────────────────────────────────────────────────────────
@app.get("/api/holders")
def get_holders():
    """Get the 9 predefined holders list."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM holders WHERE is_active = 1 ORDER BY id ASC")
    holders = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return {"holders": holders}

# ─────────────────────────────────────────────────────────────
# 💳 Pasargad Bank Inquiries API
# ─────────────────────────────────────────────────────────────
@app.post("/api/inquiries/pasargad")
def inquiry_pasargad(
    data: PasargadInquiryRequest,
    role: str = require_role([ROLE_ADMIN, ROLE_OPERATOR])
):
    """Execute live Pasargad inquiry for a Sayadi ID and save results."""
    result = record_pasargad_inquiry(
        sayadi_id=data.sayadi_id,
        holder_id=data.holder_id,
        customer_id=data.customer_id
    )
    invalidate_stats_cache()
    return result

# ─────────────────────────────────────────────────────────────
# 🏛️ Central Bank of Iran (CBI) Inquiries API
# ─────────────────────────────────────────────────────────────
@app.get("/api/inquiries/cbi")
def inquiry_cbi(
    sayadi_id: str,
    role: str = require_role([ROLE_ADMIN, ROLE_OPERATOR])
):
    """Execute Central Bank (CBI) inquiry for Sayadi ID."""
    from app.services.cbi import query_cbi_sayad_cheque
    result = query_cbi_sayad_cheque(sayadi_id)
    return result

@app.post("/api/inquiries/dual")
def inquiry_dual(
    data: PasargadInquiryRequest,
    role: str = require_role([ROLE_ADMIN, ROLE_OPERATOR])
):
    """Execute Dual Inquiry: CBI Central Bank + Pasargad Bank in parallel."""
    from app.services.cbi import query_cbi_sayad_cheque
    
    # Run Pasargad
    pasargad_res = record_pasargad_inquiry(
        sayadi_id=data.sayadi_id,
        holder_id=data.holder_id,
        customer_id=data.customer_id
    )
    
    # Run CBI
    cbi_res = query_cbi_sayad_cheque(data.sayadi_id)
    
    invalidate_stats_cache()
    return {
        "status": "success",
        "sayadi_id": data.sayadi_id,
        "pasargad": pasargad_res,
        "cbi": cbi_res,
        "message": "استعلام دوگانه بانک مرکزی و بانک پاسارگاد با موفقیت انجام شد."
    }

@app.get("/api/inquiries")
def list_inquiries(
    sayadi_id: Optional[str] = None,
    customer_id: Optional[int] = None,
    limit: int = 3000,
    offset: int = 0
):
    """List pasargad inquiries history with optional filters."""
    conn = get_db()
    cursor = conn.cursor()
    query = """
    SELECT id, sayadi_id, holder_id, customer_id, in_transit_count, in_transit_amount,
           cleared_count, cleared_amount, bounced_count, bounced_amount, raw_response,
           status, inquiry_time
    FROM pasargad_inquiries
    WHERE 1=1
    """
    params = []
    if sayadi_id:
        query += " AND sayadi_id LIKE ?"
        params.append(f"%{sayadi_id.strip()}%")
    if customer_id:
        query += " AND customer_id = ?"
        params.append(customer_id)
    query += " ORDER BY id DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    
    cursor.execute(query, params)
    inquiries = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return {"inquiries": inquiries, "count": len(inquiries)}


# ─────────────────────────────────────────────────────────────
# 📊 Smart Multi-Tier Logging & Diagnostics API
# ─────────────────────────────────────────────────────────────
@app.get("/api/health")
def get_system_health():
    """Live health check for backend, database, and Pasargad bank gateway."""
    pasargad_health = check_pasargad_health()
    return {
        "status": "healthy",
        "database": "connected",
        "pasargad_gateway": pasargad_health
    }

@app.get("/api/logs")
def get_logs_endpoint(
    level: Optional[str] = None,
    tag: Optional[str] = None,
    search: Optional[str] = None,
    sayadi_id: Optional[str] = None,
    limit: int = 150,
    offset: int = 0
):
    """Query smart logger buffer with filters."""
    return smart_logger.get_logs(
        level=level,
        tag=tag,
        search=search,
        sayadi_id=sayadi_id,
        limit=limit,
        offset=offset
    )

@app.post("/api/logs/client")
def create_client_log(data: ClientLogRequest):
    """Receive client-side log events from frontend."""
    entry = smart_logger.log(
        level=data.level,
        tag=data.tag or "CLIENT",
        message=data.message,
        details=data.details,
        sayadi_id=data.sayadi_id,
        customer_name=data.customer_name
    )
    return {"status": "success", "entry": entry}

@app.get("/api/logs/export")
def export_logs_endpoint(format: str = "json"):
    """Export logs as JSON or plain text."""
    logs_data = smart_logger.get_logs(limit=2000)["logs"]
    if format == "json":
        from fastapi.responses import JSONResponse
        return JSONResponse(
            content={"logs": logs_data},
            headers={"Content-Disposition": "attachment; filename=sayad_system_logs.json"}
        )
    else:
        from fastapi.responses import PlainTextResponse
        lines = []
        for e in logs_data:
            sayad_str = f" [Sayad: {e.get('sayadi_id', '')}]" if e.get('sayadi_id') else ""
            lines.append(f"[{e['jalali_time']}] [{e['level']:<7}] [{e['tag']:<9}] {e['message']}{sayad_str}")
        return PlainTextResponse(
            content="\n".join(lines),
            headers={"Content-Disposition": "attachment; filename=sayad_system_logs.txt"}
        )

@app.delete("/api/logs")
def clear_logs_endpoint(
    role: str = require_role([ROLE_ADMIN])
):
    """Clear memory log buffer."""
    smart_logger.clear()
    return {"status": "success", "message": "بافر لاگ‌ها با موفقیت پاکسازی شد."}




# ─────────────────────────────────────────────────────────────
# ⏰ Background Scheduler API
# ─────────────────────────────────────────────────────────────
@app.get("/api/scheduler/status")
def get_scheduler_status():
    """Get daily scheduler status and recent execution logs."""
    return scheduler_instance.get_status()

@app.post("/api/scheduler/run-now")
def run_scheduler_now(
    background_tasks: BackgroundTasks,
    holder_id: int = 1,
    role: str = require_role([ROLE_ADMIN, ROLE_OPERATOR])
):
    """Trigger on-demand batch inquiry for all cheques in background."""
    def _run_batch_and_invalidate(h_id: int):
        scheduler_instance.run_batch_inquiry(h_id)
        invalidate_stats_cache()

    background_tasks.add_task(_run_batch_and_invalidate, holder_id)
    return {"status": "success", "message": "عملیات استعلام دسته‌ای در پس‌زمینه آغاز شد."}

# ─────────────────────────────────────────────────────────────
# 📊 Excel Export API
# ─────────────────────────────────────────────────────────────
@app.get("/api/export/excel")
def export_excel():
    """Generate and download latest comprehensive Excel report."""
    conn = get_db()
    query = """
    SELECT 
        c.full_name as "نام مشتری",
        c.credit_color as "وضعیت اعتباری (رنگ)",
        ch.sayadi_id as "شناسه صیادی",
        ch.cheque_number as "شماره چک",
        ch.amount as "مبلغ (ریال)",
        ch.cheque_date as "تاریخ سررسید",
        ch.bank_name as "بانک صادرکننده",
        h.full_name as "دارنده چک (هولدر)",
        (SELECT in_transit_amount FROM pasargad_inquiries WHERE sayadi_id = ch.sayadi_id ORDER BY id DESC LIMIT 1) as "مبلغ چک در راه (پاسارگاد)",
        (SELECT cleared_amount FROM pasargad_inquiries WHERE sayadi_id = ch.sayadi_id ORDER BY id DESC LIMIT 1) as "مبلغ رفع سوءاثر (پاسارگاد)",
        (SELECT bounced_amount FROM pasargad_inquiries WHERE sayadi_id = ch.sayadi_id ORDER BY id DESC LIMIT 1) as "مبلغ برگشتی (پاسارگاد)"
    FROM cheques ch
    LEFT JOIN customers c ON ch.customer_id = c.id
    LEFT JOIN holders h ON ch.holder_id = h.id
    ORDER BY c.full_name ASC, ch.cheque_date ASC
    """
    df = pd.read_sql_query(query, conn)
    conn.close()

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='گزارش جامع مشتریان و چک‌ها', index=False)
        ws = writer.sheets['گزارش جامع مشتریان و چک‌ها']
        ws.views.sheetView[0].rightToLeft = True

    output.seek(0)
    headers = {
        'Content-Disposition': 'attachment; filename="sayad_customers_full_report.xlsx"'
    }
    return StreamingResponse(output, headers=headers, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

# ─────────────────────────────────────────────────────────────
# 🔐 RBAC Identity & Role Management API
# ─────────────────────────────────────────────────────────────
@app.get("/api/auth/current-role")
def get_current_role_endpoint(request: Request):
    """Get active role and comprehensive permission map."""
    role = get_request_role(request)
    return ROLES_INFO.get(role, ROLES_INFO[ROLE_ADMIN])

@app.post("/api/auth/switch-role")
def switch_role_endpoint(data: SwitchRoleRequest, response: Response):
    """Switch active system role between admin, operator, and auditor."""
    global current_system_role
    target = data.role.strip().lower()
    if target not in ROLES_INFO:
        raise HTTPException(
            status_code=400,
            detail=f"نقش نامعتبر است. نقش‌های مجاز: {', '.join(ROLES_INFO.keys())}"
        )
    current_system_role = target
    response.set_cookie("sayad_role", target, max_age=86400 * 30, httponly=False)
    role_info = ROLES_INFO[target]
    smart_logger.log(
        level="INFO",
        tag="SYSTEM",
        message=f"نقش کاربری سیستم به '{role_info['title']}' تغییر یافت.",
        details={"new_role": target, "user_name": role_info["user_name"]}
    )
    return {
        "status": "success",
        "message": f"نقش سیستم با موفقیت به '{role_info['title']}' تغییر یافت.",
        "current_role": target,
        "role_info": role_info
    }


# ─────────────────────────────────────────────────────────────
# 🛡️ Encrypted Backup & Restore Vault API
# ─────────────────────────────────────────────────────────────
@app.get("/api/backup/list")
def list_backups_endpoint(request: Request):
    """List all encrypted database backups (Admin, Operator, Auditor)."""
    from app.services.backup_service import list_backups
    backups = list_backups()
    return {
        "status": "success",
        "backups": backups,
        "count": len(backups)
    }

@app.post("/api/backup/create")
def create_backup_endpoint(
    data: Optional[BackupCreateRequest] = None,
    role: str = require_role([ROLE_ADMIN, ROLE_OPERATOR])
):
    """Create a new online encrypted zero-downtime backup (Admin and Operator)."""
    from app.services.backup_service import create_backup
    tag = (data.tag if data and data.tag else "manual").strip()
    try:
        result = create_backup(tag=tag)
        return {
            "status": "success",
            "message": "پشتیبان‌گیری آنلاین رمزنگاری‌شده با موفقیت انجام شد.",
            "backup": result
        }
    except Exception as e:
        logger.error(f"Backup creation error: {e}")
        raise HTTPException(status_code=500, detail=f"خطا در ایجاد نسخه پشتیبان: {str(e)}")

@app.get("/api/backup/download/{filename}")
def download_backup_endpoint(filename: str, request: Request):
    """Download encrypted backup file (.enc) (Admin, Operator, Auditor)."""
    from app.services.backup_service import get_backup_file_path
    try:
        file_path = get_backup_file_path(filename)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="فایل پشتیبان مورد نظر یافت نشد.")

    return FileResponse(
        path=file_path,
        media_type="application/octet-stream",
        filename=os.path.basename(file_path)
    )

@app.post("/api/backup/restore/{filename}")
def restore_backup_endpoint(
    filename: str,
    role: str = require_role([ROLE_ADMIN])
):
    """Safely restore database from an encrypted backup file (Admin ONLY)."""
    from app.services.backup_service import restore_backup
    try:
        result = restore_backup(filename)
        invalidate_stats_cache()
        return result
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"خطا در اعتبارسنجی پشتیبان: {str(e)}")
    except Exception as e:
        logger.error(f"Database restore failed: {e}")
        raise HTTPException(status_code=500, detail=f"خطا در بازگردانی پایگاه داده: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
