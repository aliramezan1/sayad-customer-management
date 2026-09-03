"""
Main FastAPI Web Application for Customer & Cheque Management System.
"""
import os
import io
import logging
from typing import Optional, List
from fastapi import FastAPI, HTTPException, Query, BackgroundTasks, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
import openpyxl

from app.database import get_db, init_db
from app.schemas import (
    CustomerCreate, CustomerUpdate,
    ChequeCreate, ChequeUpdate,
    PasargadInquiryRequest, BatchInquiryRequest
)
from app.services.pasargad import record_pasargad_inquiry, query_pasargad_bounced_cheques
from app.services.scheduler import scheduler_instance

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("app.main")

# Initialize app
app = FastAPI(
    title="سامانه جامع مدیریت مشتریان و چک‌های صیادی",
    description="وب‌اپلیکیشن مدیریت پروفایل مشتریان، استعلام صیادی بانک مرکزی و استعلام اعتباری بانک پاسارگاد",
    version="2.0.0"
)

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

# ─────────────────────────────────────────────────────────────
# 📊 Dashboard & Stats API
# ─────────────────────────────────────────────────────────────
@app.get("/api/stats")
def get_dashboard_stats():
    """Get aggregated metrics and dashboard stats."""
    conn = get_db()
    cursor = conn.cursor()

    # Total counts
    cursor.execute("SELECT COUNT(*) FROM customers")
    total_customers = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*), COALESCE(SUM(amount), 0) FROM cheques")
    ch_row = cursor.fetchone()
    total_cheques = ch_row[0]
    total_amount = ch_row[1]

    # Pasargad inquiries sum
    cursor.execute("""
    SELECT 
        COALESCE(SUM(in_transit_amount), 0),
        COALESCE(SUM(cleared_amount), 0),
        COALESCE(SUM(bounced_amount), 0),
        COALESCE(SUM(bounced_count), 0)
    FROM pasargad_inquiries
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
    return {
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
        COUNT(ch.id) as cheque_count,
        COALESCE(SUM(ch.amount), 0) as total_cheque_amount,
        COALESCE(SUM(pi.in_transit_amount), 0) as in_transit_total,
        COALESCE(SUM(pi.bounced_amount), 0) as bounced_total
    FROM customers c
    LEFT JOIN cheques ch ON c.id = ch.customer_id
    LEFT JOIN pasargad_inquiries pi ON ch.sayadi_id = pi.sayadi_id
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
            ch.sayadi_id LIKE ? OR
            ch.cheque_number LIKE ?
        )"""
        params.extend([search_term, search_term, search_term, search_term, search_term, search_term])

    if color and color.strip() and color != "all":
        query += " AND c.credit_color = ?"
        params.append(color.strip())

    query += " GROUP BY c.id ORDER BY total_cheque_amount DESC, c.id DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    cursor.execute(query, params)
    customers = [dict(row) for row in cursor.fetchall()]
    conn.close()

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
    WHERE pi.customer_id = ?
    ORDER BY pi.id DESC
    LIMIT 20
    """, (customer_id,))
    inquiries = [dict(row) for row in cursor.fetchall()]

    conn.close()
    return {
        "customer": customer_dict,
        "cheques": cheques,
        "inquiries": inquiries,
        "summary": {
            "cheque_count": len(cheques),
            "total_amount": total_amount,
            "total_in_transit": total_in_transit,
            "total_bounced": total_bounced,
            "total_cleared": total_cleared
        }
    }

@app.post("/api/customers")
def create_customer(data: CustomerCreate):
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
        return {"status": "success", "customer_id": customer_id, "message": "مشتری با موفقیت ثبت شد."}
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=400, detail=f"خطا در ثبت مشتری: {str(e)}")

@app.put("/api/customers/{customer_id}")
def update_customer(customer_id: int, data: CustomerUpdate):
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
    cursor.execute(query, params)
    conn.commit()
    conn.close()

    return {"status": "success", "message": "اطلاعات مشتری با موفقیت به‌روزرسانی شد."}

@app.delete("/api/customers/{customer_id}")
def delete_customer(customer_id: int):
    """Delete a customer and unbind their cheques."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE cheques SET customer_id = NULL WHERE customer_id = ?", (customer_id,))
    cursor.execute("DELETE FROM customers WHERE id = ?", (customer_id,))
    conn.commit()
    conn.close()
    return {"status": "success", "message": "مشتری با موفقیت حذف شد."}

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
def create_cheque(data: ChequeCreate):
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
        return {"status": "success", "cheque_id": cheque_id, "message": "چک جدید با موفقیت ثبت گردید."}
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=400, detail=f"خطا در ثبت چک: {str(e)}")

@app.put("/api/cheques/{cheque_id}")
def update_cheque(cheque_id: int, data: ChequeUpdate):
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
    cursor.execute(query, params)
    conn.commit()
    conn.close()

    return {"status": "success", "message": "اطلاعات چک با موفقیت به‌روزرسانی شد."}

@app.delete("/api/cheques/{cheque_id}")
def delete_cheque(cheque_id: int):
    """Delete a cheque."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM cheques WHERE id = ?", (cheque_id,))
    conn.commit()
    conn.close()
    return {"status": "success", "message": "چک با موفقیت حذف گردید."}

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
def inquiry_pasargad(data: PasargadInquiryRequest):
    """Execute live Pasargad inquiry for a Sayadi ID and save results."""
    result = record_pasargad_inquiry(
        sayadi_id=data.sayadi_id,
        holder_id=data.holder_id,
        customer_id=data.customer_id
    )
    if result.get("status") != "success":
        raise HTTPException(status_code=400, detail=result.get("message", "خطا در استعلام"))
    return result

# ─────────────────────────────────────────────────────────────
# 🏛️ Central Bank of Iran (CBI) Inquiries API
# ─────────────────────────────────────────────────────────────
@app.get("/api/inquiries/cbi")
def inquiry_cbi(sayadi_id: str):
    """Execute Central Bank (CBI) inquiry for Sayadi ID."""
    from app.services.cbi import query_cbi_sayad_cheque
    result = query_cbi_sayad_cheque(sayadi_id)
    return result

@app.post("/api/inquiries/dual")
def inquiry_dual(data: PasargadInquiryRequest):
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
    
    return {
        "status": "success",
        "sayadi_id": data.sayadi_id,
        "pasargad": pasargad_res,
        "cbi": cbi_res,
        "message": "استعلام دوگانه بانک مرکزی و بانک پاسارگاد با موفقیت انجام شد."
    }


# ─────────────────────────────────────────────────────────────
# ⏰ Background Scheduler API
# ─────────────────────────────────────────────────────────────
@app.get("/api/scheduler/status")
def get_scheduler_status():
    """Get daily scheduler status and recent execution logs."""
    return scheduler_instance.get_status()

@app.post("/api/scheduler/run-now")
def run_scheduler_now(background_tasks: BackgroundTasks, holder_id: int = 1):
    """Trigger on-demand batch inquiry for all cheques in background."""
    background_tasks.add_task(scheduler_instance.run_batch_inquiry, holder_id)
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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
