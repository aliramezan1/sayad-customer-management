"""
Database management, schema creation, and migration for Customer & Cheque Management Web App.
"""
import sqlite3
import os
import logging
from datetime import datetime

logger = logging.getLogger("app.database")

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "customers.db")

# 9 Predefined Holders as requested by the user
PREDEFINED_HOLDERS = [
    {"national_id": "0921974061", "full_name": "علی رمضانزاده", "relationship": "خودم (دارنده اصلی)"},
    {"national_id": "0923812032", "full_name": "عادل رمضانزاده", "relationship": "داداش علی رمضانزاده"},
    {"national_id": "0922236992", "full_name": "محمد ضیافتی", "relationship": "شریک"},
    {"national_id": "6430028593", "full_name": "علیرضا ضیافتی", "relationship": "داداش محمد ضیافتی"},
    {"national_id": "0941503771", "full_name": "مهدی زمانزاده", "relationship": "دایی مهدی"},
    {"national_id": "0945800711", "full_name": "احسان ارم", "relationship": "رفیق علی رمضانزاده"},
    {"national_id": "1064128033", "full_name": "حمیدرضا حصاری", "relationship": "فروشنده تیگو ۷"},
    {"national_id": "0923706348", "full_name": "محمدرضا ذکاییان", "relationship": "رفیق عادل"},
    {"national_id": "0934491186", "full_name": "فاطمه زمانزاده", "relationship": "مادر"},
]

def get_db():
    """Get database connection with row factory enabled."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initialize database tables and run migration."""
    conn = get_db()
    cursor = conn.cursor()

    # 1. Holders Table (9 preset holders)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS holders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        national_id TEXT UNIQUE NOT NULL,
        full_name TEXT NOT NULL,
        relationship TEXT,
        is_active INTEGER DEFAULT 1,
        created_at TEXT DEFAULT (datetime('now', 'localtime'))
    )
    """)

    # 2. Customers Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS customers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        full_name TEXT UNIQUE NOT NULL,
        national_id TEXT,
        phone TEXT,
        address TEXT,
        notes TEXT,
        credit_color TEXT DEFAULT 'نامشخص',
        risk_score INTEGER DEFAULT 0,
        original_name_alias TEXT,
        created_at TEXT DEFAULT (datetime('now', 'localtime')),
        updated_at TEXT DEFAULT (datetime('now', 'localtime'))
    )
    """)

    # 3. Cheques Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS cheques (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id INTEGER,
        sayadi_id TEXT NOT NULL,
        cheque_number TEXT,
        amount REAL DEFAULT 0,
        cheque_date TEXT,
        bank_name TEXT,
        holder_id INTEGER,
        status TEXT DEFAULT 'pending',
        notes TEXT,
        created_at TEXT DEFAULT (datetime('now', 'localtime')),
        updated_at TEXT DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (customer_id) REFERENCES customers (id) ON DELETE SET NULL,
        FOREIGN KEY (holder_id) REFERENCES holders (id) ON DELETE SET NULL
    )
    """)

    # 4. Pasargad Inquiries Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS pasargad_inquiries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sayadi_id TEXT NOT NULL,
        holder_id INTEGER,
        customer_id INTEGER,
        in_transit_count INTEGER DEFAULT 0,
        in_transit_amount REAL DEFAULT 0,
        cleared_count INTEGER DEFAULT 0,
        cleared_amount REAL DEFAULT 0,
        bounced_count INTEGER DEFAULT 0,
        bounced_amount REAL DEFAULT 0,
        raw_response TEXT,
        status TEXT DEFAULT 'success',
        inquiry_time TEXT DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (holder_id) REFERENCES holders (id) ON DELETE SET NULL,
        FOREIGN KEY (customer_id) REFERENCES customers (id) ON DELETE CASCADE
    )
    """)

    # 5. CBI Inquiries Table (for keeping Central Bank raw logs)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS cbi_inquiries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sayadi_id TEXT NOT NULL,
        full_name TEXT,
        credit_color TEXT,
        raw_response TEXT,
        inquiry_date TEXT DEFAULT (datetime('now', 'localtime'))
    )
    """)

    # 6. Scheduler Logs Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS scheduler_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_name TEXT NOT NULL,
        status TEXT NOT NULL,
        details TEXT,
        items_processed INTEGER DEFAULT 0,
        run_time TEXT DEFAULT (datetime('now', 'localtime'))
    )
    """)

    conn.commit()

    # Seed predefined 9 holders
    for h in PREDEFINED_HOLDERS:
        cursor.execute("""
        INSERT INTO holders (national_id, full_name, relationship)
        VALUES (?, ?, ?)
        ON CONFLICT(national_id) DO UPDATE SET
            full_name = excluded.full_name,
            relationship = excluded.relationship
        """, (h["national_id"], h["full_name"], h["relationship"]))

    conn.commit()

    # Run Data Migration from existing raw tables if needed
    _migrate_existing_data(conn)

    conn.close()
    logger.info("Database initialized & verified successfully.")

def _migrate_existing_data(conn):
    """Migrate legacy cheques and inquiry_results into the relational customers and cheques schema."""
    cursor = conn.cursor()

    # Ensure required columns exist on customers table
    cursor.execute("PRAGMA table_info(customers)")
    cust_cols = [row[1] for row in cursor.fetchall()]
    if "national_id" not in cust_cols:
        cursor.execute("ALTER TABLE customers ADD COLUMN national_id TEXT")
    if "phone" not in cust_cols:
        cursor.execute("ALTER TABLE customers ADD COLUMN phone TEXT")
    if "address" not in cust_cols:
        cursor.execute("ALTER TABLE customers ADD COLUMN address TEXT")
    if "notes" not in cust_cols:
        cursor.execute("ALTER TABLE customers ADD COLUMN notes TEXT")
    if "credit_color" not in cust_cols:
        cursor.execute("ALTER TABLE customers ADD COLUMN credit_color TEXT DEFAULT 'نامشخص'")
    if "risk_score" not in cust_cols:
        cursor.execute("ALTER TABLE customers ADD COLUMN risk_score INTEGER DEFAULT 0")
    if "original_name_alias" not in cust_cols:
        cursor.execute("ALTER TABLE customers ADD COLUMN original_name_alias TEXT")
    if "updated_at" not in cust_cols:
        cursor.execute("ALTER TABLE customers ADD COLUMN updated_at TEXT")

    # Ensure required columns exist on cheques table
    cursor.execute("PRAGMA table_info(cheques)")
    existing_cols = [row[1] for row in cursor.fetchall()]
    
    if "customer_id" not in existing_cols:
        cursor.execute("ALTER TABLE cheques ADD COLUMN customer_id INTEGER")
    if "holder_id" not in existing_cols:
        cursor.execute("ALTER TABLE cheques ADD COLUMN holder_id INTEGER")
    if "status" not in existing_cols:
        cursor.execute("ALTER TABLE cheques ADD COLUMN status TEXT DEFAULT 'pending'")
    if "notes" not in existing_cols:
        cursor.execute("ALTER TABLE cheques ADD COLUMN notes TEXT")
    if "created_at" not in existing_cols:
        cursor.execute("ALTER TABLE cheques ADD COLUMN created_at TEXT")
    if "updated_at" not in existing_cols:
        cursor.execute("ALTER TABLE cheques ADD COLUMN updated_at TEXT")

    conn.commit()

    # Check if legacy inquiry_results table exists
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='inquiry_results'")
    if not cursor.fetchone():
        return

    # Check if cheques already have customer_id assigned
    cursor.execute("SELECT COUNT(*) FROM cheques WHERE customer_id IS NOT NULL")
    existing_linked = cursor.fetchone()[0]

    # If already migrated and customers exist, skip
    cursor.execute("SELECT COUNT(*) FROM customers")
    cust_count = cursor.fetchone()[0]
    if existing_linked > 0 and cust_count > 0:
        return

    logger.info("Migrating existing CBI inquiries and cheques into relational customer profiles...")

    # 1. Fetch all distinct customers from inquiry_results
    import re
    cursor.execute("""
    SELECT DISTINCT 
        COALESCE(NULLIF(ir.full_name, ''), c.original_name, 'مشتری نامشخص') as cust_name,
        ir.raw_response,
        c.original_name
    FROM cheques c
    LEFT JOIN inquiry_results ir ON c.sayadi_id = ir.sayadi_id
    WHERE c.sayadi_id IS NOT NULL AND c.sayadi_id != ''
    """)
    rows = cursor.fetchall()

    for r in rows:
        cust_name = (r[0] or 'مشتری نامشخص').strip()
        raw_resp = r[1] or ''
        original_alias = r[2] or ''

        # Extract color from raw_response
        color_match = re.search(r'در وضعیت\s+([^\n\r<]+?)\s+در پایگاه داده', raw_resp)
        credit_color = color_match.group(1).strip() if color_match else 'سفید'

        # Map color to risk score
        risk_map = {'سفید': 5, 'زرد': 20, 'نارنجی': 50, 'قهوه ای': 75, 'قهوه‌ای': 75, 'قرمز': 95}
        risk_score = risk_map.get(credit_color, 10)

        cursor.execute("""
        INSERT INTO customers (full_name, credit_color, risk_score, original_name_alias)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(full_name) DO UPDATE SET
            credit_color = COALESCE(excluded.credit_color, customers.credit_color),
            risk_score = excluded.risk_score
        """, (cust_name, credit_color, risk_score, original_alias))

    conn.commit()

    # 2. Link each cheque to its customer_id
    cursor.execute("""
    SELECT c.id, c.sayadi_id, ir.full_name, c.original_name
    FROM cheques c
    LEFT JOIN inquiry_results ir ON c.sayadi_id = ir.sayadi_id
    """)
    cheque_rows = cursor.fetchall()

    for crow in cheque_rows:
        cid = crow[0]
        c_fullname = (crow[2] or '').strip()
        c_orig = (crow[3] or '').strip()
        target_name = c_fullname if c_fullname else (c_orig if c_orig else 'مشتری نامشخص')

        # Find customer ID
        cursor.execute("SELECT id FROM customers WHERE full_name = ?", (target_name,))
        cust_res = cursor.fetchone()
        if cust_res:
            customer_db_id = cust_res[0]
            cursor.execute("UPDATE cheques SET customer_id = ? WHERE id = ?", (customer_db_id, cid))

    conn.commit()
    logger.info("Data migration completed successfully.")
