# -*- coding: utf-8 -*-
"""
Comprehensive Zero-Downtime Encrypted Backup Vault Service for Sayad System.
Features:
- Online zero-downtime backup using sqlite3.backup API (non-blocking).
- Gzip stream compression (level 9) for maximum storage efficiency.
- Standard symmetric Fernet AES-256 encryption from cryptography.fernet.
- Secure key management with auto-generation stored in .backup_key at project root.
- Encrypted backup repository in backups/ folder with .enc extension.
- Multi-tier integrity verification: Decryption + Decompression + Header (SQLite format 3) + PRAGMA integrity_check.
- Safe atomic restore: creates an emergency snapshot before applying any restore.
- Automated retention policy: keeps 7 daily and 4 weekly backups, pruning older excess files safely.
- Rich integration with SmartLogger and Persian Jalali datetime formatting.
"""
import os
import re
import gzip
import sqlite3
import logging
import tempfile
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from cryptography.fernet import Fernet, InvalidToken

from app.services.smart_logger import smart_logger, get_jalali_timestamp

logger = logging.getLogger("app.services.backup")

# Paths & Directories
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KEY_FILE = os.path.join(BASE_DIR, ".backup_key")
BACKUPS_DIR = os.path.join(BASE_DIR, "backups")
DEFAULT_DB_PATH = os.path.join(BASE_DIR, "customers.db")

# Ensure backups directory exists
os.makedirs(BACKUPS_DIR, exist_ok=True)


def format_file_size(size_bytes: int) -> str:
    """Format bytes into human-readable Persian/English units."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.2f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.2f} MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def get_or_create_key() -> bytes:
    """
    Retrieve existing Fernet key from .backup_key or securely generate a new one.
    Guarantees a valid 32-byte url-safe base64-encoded Fernet key.
    """
    if os.path.exists(KEY_FILE):
        try:
            with open(KEY_FILE, "rb") as f:
                key = f.read().strip()
                if key and len(key) == 44:
                    Fernet(key)  # Validation check
                    return key
        except Exception as e:
            logger.warning(f"Existing .backup_key could not be loaded: {e}. Generating new key.")

    # Generate new secure key
    key = Fernet.generate_key()
    try:
        with open(KEY_FILE, "wb") as f:
            f.write(key)
        try:
            os.chmod(KEY_FILE, 0o600)
        except Exception:
            pass
        logger.info("Generated new Fernet backup encryption key in .backup_key")
    except Exception as e:
        logger.error(f"Failed to persist .backup_key: {e}")

    return key


def get_backup_file_path(filename: str) -> str:
    """
    Safely resolves and sanitizes a backup file path inside backups/,
    protecting against directory traversal attacks.
    """
    clean_name = os.path.basename(filename)
    if not clean_name.endswith(".enc"):
        clean_name += ".enc"
    abs_backups = os.path.abspath(BACKUPS_DIR)
    resolved_path = os.path.abspath(os.path.join(abs_backups, clean_name))
    if not resolved_path.startswith(abs_backups):
        raise ValueError("مسیر فایل نامعتبر است و دسترسی خارج از مخزن پشتیبان مجاز نمی‌باشد.")
    return resolved_path


def parse_backup_filename(filename: str) -> Tuple[str, Optional[datetime]]:
    """
    Extracts tag and datetime from filename format:
    backup_{tag}_{YYYYMMDD}_{HHMMSS}.enc
    """
    m = re.match(r"^backup_(.+)__?(\d{8})_(\d{6})\.enc$", filename)
    if not m:
        m = re.match(r"^backup_(.+)_(\d{8})_(\d{6})\.enc$", filename)

    if m:
        tag = m.group(1)
        dt_str = f"{m.group(2)}_{m.group(3)}"
        try:
            dt = datetime.strptime(dt_str, "%Y%m%d_%H%M%S")
            return tag, dt
        except ValueError:
            pass
    return "unknown", None


def verify_backup_integrity(filename_or_path: str, custom_key: Optional[bytes] = None) -> Dict[str, Any]:
    """
    Comprehensive multi-tier integrity verification:
    1. Decrypt Fernet AES-256 payload using active key or custom key.
    2. Decompress Gzip stream.
    3. Verify standard SQLite 3 magic header (b"SQLite format 3\x00").
    4. Connect to temporary database and execute 'PRAGMA integrity_check;'.
    5. Count critical business records (customers, cheques, holders) to assure structural sanity.
    """
    if os.path.isabs(filename_or_path):
        file_path = filename_or_path
    else:
        file_path = get_backup_file_path(filename_or_path)

    if not os.path.exists(file_path):
        return {"is_valid": False, "error": f"فایل پشتیبان در مسیر {file_path} یافت نشد."}

    temp_path = None
    try:
        with open(file_path, "rb") as f:
            encrypted_data = f.read()

        if len(encrypted_data) == 0:
            return {"is_valid": False, "error": "فایل پشتیبان خالی (۰ بایت) است."}

        # 1. Decryption
        key = custom_key or get_or_create_key()
        fernet = Fernet(key)
        try:
            decrypted_compressed = fernet.decrypt(encrypted_data)
        except InvalidToken:
            return {"is_valid": False, "error": "رمزگشایی ناموفق بود: کلید رمزنگاری نامعتبر است یا محتوای فایل مخدوش شده است."}

        # 2. Decompression
        try:
            decompressed_bytes = gzip.decompress(decrypted_compressed)
        except Exception as e:
            return {"is_valid": False, "error": f"خطا در استخراج فایل از حالت فشرده (GZip): {str(e)}"}

        # 3. Magic Header Check
        magic_header = decompressed_bytes[:16]
        if magic_header != b"SQLite format 3\x00":
            return {
                "is_valid": False,
                "error": f"هدر فایل نامعتبر است ({magic_header}). فایل پشتیبان با ساختار استاندارد SQLite مطابقت ندارد."
            }

        # 4. SQLite PRAGMA integrity_check
        temp_fd, temp_path = tempfile.mkstemp(suffix=".db")
        os.close(temp_fd)

        with open(temp_path, "wb") as f:
            f.write(decompressed_bytes)

        conn = sqlite3.connect(temp_path)
        cur = conn.cursor()
        cur.execute("PRAGMA integrity_check;")
        row = cur.fetchone()
        if not row or row[0] != "ok":
            conn.close()
            return {"is_valid": False, "error": f"بررسی PRAGMA integrity_check دیتابیس با شکست مواجه شد: {row}"}

        # 5. Business Table Record Audit
        cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [r[0] for r in cur.fetchall()]
        table_counts = {}
        for tbl in ["customers", "cheques", "holders", "pasargad_inquiries"]:
            if tbl in tables:
                cur.execute(f"SELECT COUNT(*) FROM {tbl}")
                table_counts[tbl] = cur.fetchone()[0]

        conn.close()

        return {
            "is_valid": True,
            "header": "SQLite format 3",
            "decompressed_size": len(decompressed_bytes),
            "formatted_decompressed_size": format_file_size(len(decompressed_bytes)),
            "compressed_size": len(encrypted_data),
            "formatted_compressed_size": format_file_size(len(encrypted_data)),
            "table_counts": table_counts,
            "integrity_status": "ok"
        }

    except Exception as e:
        logger.error(f"Integrity check failed for {file_path}: {e}")
        return {"is_valid": False, "error": str(e)}
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except Exception:
                pass


def create_backup(tag: str = "manual", db_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Creates an online zero-downtime encrypted and compressed backup of the active database.
    - Zero downtime: uses sqlite3.backup from active DB to memory without blocking active transactions.
    - Compression: gzip maximum level 9.
    - Encryption: Fernet symmetric AES-256 with project root .backup_key.
    - File storage: backups/backup_{tag}_{YYYYMMDD}_{HHMMSS}.enc
    - Immediate integrity check before finishing.
    - Automatic retention enforcement (7 daily, 4 weekly).
    """
    source_db = db_path or DEFAULT_DB_PATH
    if not os.path.exists(source_db):
        raise FileNotFoundError(f"فایل پایگاه داده اصلی در مسیر '{source_db}' یافت نشد.")

    start_time = datetime.now()

    # 1. Zero-downtime Online Backup using sqlite3.backup API
    src_conn = sqlite3.connect(source_db, timeout=30.0)
    mem_dest = sqlite3.connect(":memory:")

    try:
        src_conn.backup(mem_dest, pages=250, sleep=0.001)
        raw_bytes = mem_dest.serialize()
    finally:
        mem_dest.close()
        src_conn.close()

    if not raw_bytes.startswith(b"SQLite format 3\x00"):
        raise ValueError("نسخه‌برداری درون‌حافظه‌ای از دیتابیس با شکست مواجه شد (هدر معتبر یافت نشد).")

    raw_size = len(raw_bytes)

    # 2. Gzip Stream Compression (Level 9 - Maximum)
    compressed_bytes = gzip.compress(raw_bytes, compresslevel=9)

    # 3. Fernet AES-256 Symmetric Encryption
    key = get_or_create_key()
    fernet = Fernet(key)
    encrypted_bytes = fernet.encrypt(compressed_bytes)
    encrypted_size = len(encrypted_bytes)

    # 4. Save to backups/ directory
    clean_tag = "".join(c for c in tag if c.isalnum() or c in ("-", "_")).lower() or "manual"
    now = datetime.now()
    timestamp_str = now.strftime("%Y%m%d_%H%M%S")
    filename = f"backup_{clean_tag}_{timestamp_str}.enc"
    file_path = os.path.join(BACKUPS_DIR, filename)

    with open(file_path, "wb") as f:
        f.write(encrypted_bytes)

    # 5. Immediate Verification of newly created backup
    verification = verify_backup_integrity(file_path)
    if not verification.get("is_valid"):
        if os.path.exists(file_path):
            os.remove(file_path)
        raise ValueError(f"راستی‌آزمایی فایل پشتیبان جدید شکست خورد: {verification.get('error')}")

    # 6. Apply Retention Policy (unless this is an internal emergency snapshot)
    retention_result = {}
    if tag != "emergency_pre_restore":
        retention_result = apply_retention_policy()

    # Calculate compression performance
    savings_pct = round((1 - (encrypted_size / raw_size)) * 100, 1) if raw_size > 0 else 0
    duration_ms = (datetime.now() - start_time).total_seconds() * 1000

    result = {
        "filename": filename,
        "file_path": file_path,
        "tag": tag,
        "created_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "jalali_created_at": get_jalali_timestamp(now),
        "size_bytes": encrypted_size,
        "formatted_size": format_file_size(encrypted_size),
        "raw_size_bytes": raw_size,
        "formatted_raw_size": format_file_size(raw_size),
        "compression_savings": f"{savings_pct}%",
        "is_encrypted": True,
        "integrity_verified": True,
        "table_counts": verification.get("table_counts", {}),
        "retention_pruned_count": retention_result.get("pruned_count", 0),
        "duration_ms": round(duration_ms, 2)
    }

    # Log to smart_logger
    smart_logger.log(
        level="INFO",
        tag="BACKUP",
        message=f"پشتیبان‌گیری آنلاین رمزنگاری‌شده با موفقیت انجام شد: {filename} ({format_file_size(encrypted_size)}, صرفه‌جویی فشرده‌سازی {savings_pct}%)",
        details=result,
        duration_ms=duration_ms
    )

    return result


def list_backups() -> List[Dict[str, Any]]:
    """
    Returns an inventory list of all encrypted backups in backups/ with metadata,
    sorted chronologically (newest first).
    """
    if not os.path.exists(BACKUPS_DIR):
        return []

    files = [f for f in os.listdir(BACKUPS_DIR) if f.endswith(".enc")]
    backups = []

    for f in files:
        path = os.path.join(BACKUPS_DIR, f)
        tag, dt = parse_backup_filename(f)
        size = os.path.getsize(path)
        mtime = os.path.getmtime(path)
        if not dt:
            dt = datetime.fromtimestamp(mtime)

        backups.append({
            "filename": f,
            "tag": tag,
            "size_bytes": size,
            "formatted_size": format_file_size(size),
            "created_at": dt.strftime("%Y-%m-%d %H:%M:%S"),
            "jalali_created_at": get_jalali_timestamp(dt),
            "timestamp": dt.timestamp(),
            "is_encrypted": True,
            "is_emergency": (tag == "emergency_pre_restore")
        })

    backups.sort(key=lambda x: x["timestamp"], reverse=True)
    return backups


def restore_backup(filename: str, db_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Safely restores the database from an encrypted backup file:
    1. Comprehensive integrity & sanity check on the backup before touching the live database.
    2. Takes an automatic emergency snapshot of current active database (tag="emergency_pre_restore").
    3. Decrypts and decompresses backup data into a temporary verified database.
    4. Restores verified state safely to active DB via sqlite3.backup.
    5. Records full audit logs.
    """
    file_path = get_backup_file_path(filename)
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"فایل پشتیبان '{filename}' در مخزن پشتیبان یافت نشد.")

    # 1. Pre-restore Integrity Verification
    verification = verify_backup_integrity(file_path)
    if not verification.get("is_valid"):
        raise ValueError(f"فایل پشتیبان نامعتبر یا آسیب‌دیده است: {verification.get('error')}")

    target_db = db_path or DEFAULT_DB_PATH

    # 2. Emergency Snapshot before any modification
    emergency_backup = None
    if os.path.exists(target_db):
        emergency_backup = create_backup(tag="emergency_pre_restore", db_path=target_db)

    # 3. Decrypt and Decompress
    with open(file_path, "rb") as f:
        encrypted_data = f.read()

    key = get_or_create_key()
    fernet = Fernet(key)
    decompressed_bytes = gzip.decompress(fernet.decrypt(encrypted_data))

    # 4. Atomic Restore via temp connection to live target DB
    temp_fd, temp_path = tempfile.mkstemp(suffix=".db")
    os.close(temp_fd)

    try:
        with open(temp_path, "wb") as f:
            f.write(decompressed_bytes)

        src_conn = sqlite3.connect(temp_path)
        dest_conn = sqlite3.connect(target_db, timeout=30.0)
        
        dest_conn.execute("PRAGMA journal_mode = WAL;")
        dest_conn.execute("PRAGMA busy_timeout = 10000;")
        
        src_conn.backup(dest_conn)
        dest_conn.commit()

        dest_conn.close()
        src_conn.close()
    finally:
        if os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except Exception:
                pass

    # 5. Log Restore Event
    smart_logger.log(
        level="WARN",
        tag="BACKUP",
        message=f"عملیات بازیابی پایگاه داده از فایل {filename} با موفقیت کامل انجام گردید.",
        details={
            "restored_file": filename,
            "emergency_snapshot": emergency_backup["filename"] if emergency_backup else None,
            "table_counts": verification.get("table_counts", {})
        }
    )

    return {
        "status": "success",
        "message": f"پایگاه داده با موفقیت از فایل '{filename}' بازیابی شد.",
        "restored_file": filename,
        "emergency_backup": emergency_backup["filename"] if emergency_backup else None,
        "restored_records": verification.get("table_counts", {})
    }


def apply_retention_policy(keep_daily: int = 7, keep_weekly: int = 4) -> Dict[str, Any]:
    """
    Retention Policy Engine:
    Maintains 7 daily and 4 weekly backups. Older surplus files are pruned.
    Rules:
    - Emergency snapshots (tag="emergency_pre_restore") are protected.
    - Files created within the last 24 hours are kept to safeguard active sessions.
    - Daily backups: up to 7 distinct days retain their latest backup.
    - Weekly backups: up to 4 distinct ISO calendar weeks retain their latest backup.
    - All other older surplus files are deleted.
    """
    if not os.path.exists(BACKUPS_DIR):
        return {"pruned_count": 0, "pruned_files": []}

    files = [f for f in os.listdir(BACKUPS_DIR) if f.endswith(".enc")]
    if not files:
        return {"pruned_count": 0, "pruned_files": []}

    now = datetime.now()
    cutoff_24h = now - timedelta(hours=24)

    items = []
    for f in files:
        path = os.path.join(BACKUPS_DIR, f)
        tag, dt = parse_backup_filename(f)
        if not dt:
            dt = datetime.fromtimestamp(os.path.getmtime(path))
        items.append({
            "filename": f,
            "path": path,
            "tag": tag,
            "dt": dt,
            "day_key": dt.strftime("%Y-%m-%d"),
            "week_key": f"{dt.year}-W{dt.isocalendar()[1]:02d}"
        })

    # Sort descending by date (newest first)
    items.sort(key=lambda x: x["dt"], reverse=True)

    keep_set = set()

    # Rule 1: Protect emergency snapshots
    for it in items:
        if it["tag"] == "emergency_pre_restore":
            keep_set.add(it["filename"])

    # Rule 2: Keep backups within 24 hours
    for it in items:
        if it["dt"] >= cutoff_24h:
            keep_set.add(it["filename"])

    # Rule 3: 7 Daily retention slots (newest backup of each distinct day)
    days_seen = set()
    for it in items:
        if it["day_key"] not in days_seen:
            days_seen.add(it["day_key"])
            keep_set.add(it["filename"])
            if len(days_seen) >= keep_daily:
                break

    # Rule 4: 4 Weekly retention slots (newest backup of each distinct ISO week)
    weeks_seen = set()
    for it in items:
        if it["week_key"] not in weeks_seen:
            weeks_seen.add(it["week_key"])
            keep_set.add(it["filename"])
            if len(weeks_seen) >= keep_weekly:
                break

    # Execute Pruning
    pruned_files = []
    for it in items:
        if it["filename"] not in keep_set:
            try:
                os.remove(it["path"])
                pruned_files.append(it["filename"])
                logger.info(f"Retention policy pruned surplus backup: {it['filename']}")
            except Exception as e:
                logger.error(f"Error removing surplus backup {it['filename']}: {e}")

    if pruned_files:
        smart_logger.log(
            level="INFO",
            tag="BACKUP",
            message=f"سیاست نگهداشت اجرا شد: {len(pruned_files)} نسخه پشتیبان مازاد پاکسازی شد.",
            details={"pruned_files": pruned_files}
        )

    return {
        "pruned_count": len(pruned_files),
        "pruned_files": pruned_files,
        "kept_count": len(files) - len(pruned_files)
    }
