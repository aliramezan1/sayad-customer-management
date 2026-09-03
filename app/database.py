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
        original_name TEXT,
        row_number INTEGER,
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

    # Seed data from initial_dataset.json if customers or cheques table is empty
    cursor.execute("SELECT COUNT(*) FROM customers")
    cust_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM cheques")
    cheque_count = cursor.fetchone()[0]

    if cust_count == 0 or cheque_count == 0:
        _seed_from_initial_dataset(conn)

    # Run Data Migration from existing raw tables if needed
    _migrate_existing_data(conn)

    conn.close()
    logger.info("Database initialized & verified successfully.")

def _seed_from_initial_dataset(conn):
    """Seed customers, cheques, holders, and inquiries from bundled JSON dataset."""
    import json
    candidate_paths = [
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "initial_dataset.json"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "data", "initial_dataset.json"),
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "data", "initial_dataset.json"),
    ]
    json_path = None
    for p in candidate_paths:
        if os.path.exists(p):
            json_path = p
            break

    if not json_path:
        logger.warning("No initial_dataset.json found to seed.")
        return

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        cursor = conn.cursor()
        
        # Customers
        for cust in data.get("customers", []):
            cursor.execute("""
            INSERT INTO customers (id, full_name, national_id, phone, address, notes, credit_color, risk_score, original_name_alias, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(full_name) DO UPDATE SET
                national_id = COALESCE(excluded.national_id, customers.national_id),
                credit_color = excluded.credit_color,
                risk_score = excluded.risk_score
            """, (
                cust.get("id"),
                cust.get("full_name"),
                cust.get("national_id"),
                cust.get("phone"),
                cust.get("address"),
                cust.get("notes"),
                cust.get("credit_color", "سفید"),
                cust.get("risk_score", 5),
                cust.get("original_name_alias"),
                cust.get("created_at"),
                cust.get("updated_at")
            ))

        # Cheques
        for ch in data.get("cheques", []):
            cursor.execute("""
            INSERT OR IGNORE INTO cheques (id, customer_id, sayadi_id, cheque_number, amount, cheque_date, bank_name, original_name, row_number, holder_id, status, notes, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                ch.get("id"),
                ch.get("customer_id"),
                ch.get("sayadi_id"),
                ch.get("cheque_number"),
                ch.get("amount", 0),
                ch.get("cheque_date"),
                ch.get("bank_name"),
                ch.get("original_name"),
                ch.get("row_number"),
                ch.get("holder_id", 1),
                ch.get("status", "pending"),
                ch.get("notes"),
                ch.get("created_at"),
                ch.get("updated_at")
            ))

        # Inquiries
        for inq in data.get("inquiries", []):
            cursor.execute("""
            INSERT OR IGNORE INTO pasargad_inquiries (id, sayadi_id, holder_id, customer_id, in_transit_count, in_transit_amount, cleared_count, cleared_amount, bounced_count, bounced_amount, raw_response, status, inquiry_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                inq.get("id"),
                inq.get("sayadi_id"),
                inq.get("holder_id", 1),
                inq.get("customer_id"),
                inq.get("in_transit_count", 0),
                inq.get("in_transit_amount", 0),
                inq.get("cleared_count", 0),
                inq.get("cleared_amount", 0),
                inq.get("bounced_count", 0),
                inq.get("bounced_amount", 0),
                inq.get("raw_response"),
                inq.get("status", "success"),
                inq.get("inquiry_time")
            ))

        conn.commit()
        logger.info(f"Seeded database successfully from {json_path}")
    except Exception as e:
        logger.error(f"Error seeding database from initial_dataset.json: {e}")

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
    if "original_name" not in existing_cols:
        cursor.execute("ALTER TABLE cheques ADD COLUMN original_name TEXT")
    if "row_number" not in existing_cols:
        cursor.execute("ALTER TABLE cheques ADD COLUMN row_number INTEGER")
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

