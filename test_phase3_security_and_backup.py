# -*- coding: utf-8 -*-
"""
Automated Test Suite for Phase 3:
Security, Encrypted Backup Vault, and 3-Tier Role-Based Access Control (RBAC).
"""
import os
import sys
import shutil
import sqlite3
import tempfile
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from cryptography.fernet import Fernet

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from app.main import app, current_system_role
from app.services.backup_service import (
    create_backup,
    list_backups,
    restore_backup,
    verify_backup_integrity,
    get_backup_file_path,
    apply_retention_policy,
    get_or_create_key,
    KEY_FILE,
    BACKUPS_DIR,
    DEFAULT_DB_PATH
)

client = TestClient(app)

created_test_backups = []


def test_1_key_generation_and_storage():
    """Verify cryptographic key creation and storage in .backup_key."""
    key = get_or_create_key()
    assert key is not None
    assert len(key) == 44  # Base64 Fernet 32-byte key
    assert os.path.exists(KEY_FILE)
    with open(KEY_FILE, "rb") as f:
        file_content = f.read().strip()
    assert file_content == key
    # Ensure Fernet accepts key
    fernet = Fernet(key)
    enc = fernet.encrypt(b"test_crypto_security")
    dec = fernet.decrypt(enc)
    assert dec == b"test_crypto_security"
    print("PASS: test_1_key_generation_and_storage -> Valid 256-bit Fernet key persisted.")


def test_2_encrypted_online_backup_creation():
    """Verify online zero-downtime backup, Gzip compression, and Fernet AES-256 encryption."""
    result = create_backup(tag="phase3_verify")
    filename = result["filename"]
    created_test_backups.append(filename)

    file_path = os.path.join(BACKUPS_DIR, filename)
    assert os.path.exists(file_path)
    assert result["is_encrypted"] is True
    assert result["integrity_verified"] is True
    assert result["size_bytes"] > 0
    assert result["size_bytes"] < result["raw_size_bytes"]  # Compression savings

    # Check that raw content on disk is completely encrypted and NOT plaintext SQLite
    with open(file_path, "rb") as f:
        raw_binary = f.read()

    assert b"SQLite format 3" not in raw_binary, "CRITICAL: Backup file on disk contains plaintext SQLite header!"
    assert b"CREATE TABLE" not in raw_binary, "CRITICAL: Database schema visible in plaintext!"
    # Fernet tokens start with version byte 0x80 (base64 'gAAAAA')
    assert raw_binary.startswith(b"gAAAAA"), "Fernet token header signature verified."

    print(f"PASS: test_2_encrypted_online_backup_creation -> {filename} created ({result['formatted_size']}, savings: {result['compression_savings']}). Binary is 100% encrypted.")


def test_3_backup_integrity_verification():
    """Verify multi-tier integrity verification (Decryption + Decompression + Header + PRAGMA)."""
    assert len(created_test_backups) > 0
    filename = created_test_backups[-1]

    verification = verify_backup_integrity(filename)
    assert verification["is_valid"] is True
    assert verification["header"] == "SQLite format 3"
    assert verification["integrity_status"] == "ok"
    assert "customers" in verification["table_counts"]
    assert verification["table_counts"]["customers"] == 52
    assert verification["table_counts"]["cheques"] == 147
    assert verification["table_counts"]["holders"] == 9
    print(f"PASS: test_3_backup_integrity_verification -> SQLite header, PRAGMA check, and 52 customers verified.")


def test_4_tampering_and_unauthorized_decryption_prevention():
    """Verify that tampering or wrong encryption keys are immediately detected and rejected."""
    assert len(created_test_backups) > 0
    filename = created_test_backups[-1]
    file_path = os.path.join(BACKUPS_DIR, filename)

    # 1. Decrypt with unauthorized rogue key
    rogue_key = Fernet.generate_key()
    rogue_check = verify_backup_integrity(filename, custom_key=rogue_key)
    assert rogue_check["is_valid"] is False
    assert "رمزگشایی ناموفق بود" in rogue_check["error"]

    # 2. Corrupted bytes in backup
    temp_corrupted = os.path.join(BACKUPS_DIR, "backup_corrupted_test_20260905_000000.enc")
    try:
        with open(file_path, "rb") as f:
            data = f.read()
        # Alter middle bytes
        corrupted_data = data[:100] + b"CORRUPTED_BYTES_INJECTION" + data[150:]
        with open(temp_corrupted, "wb") as f:
            f.write(corrupted_data)

        corrupt_check = verify_backup_integrity(temp_corrupted)
        assert corrupt_check["is_valid"] is False
        print("PASS: test_4_tampering_and_unauthorized_decryption_prevention -> Rogue keys and byte corruption safely rejected.")
    finally:
        if os.path.exists(temp_corrupted):
            os.remove(temp_corrupted)


def test_5_safe_restore_with_emergency_snapshot():
    """Verify safe atomic restore and automatic emergency snapshot creation."""
    assert len(created_test_backups) > 0
    source_backup = created_test_backups[-1]

    # Create temporary database to test restore safely
    temp_target = "test_target_restore.db"
    if os.path.exists(temp_target):
        os.remove(temp_target)

    # Create dummy initial state
    init_conn = sqlite3.connect(temp_target)
    init_conn.execute("CREATE TABLE customers (id INTEGER PRIMARY KEY, full_name TEXT);")
    init_conn.execute("INSERT INTO customers VALUES (1, 'مشتری آزمایشی موقت');")
    init_conn.commit()
    init_conn.close()

    try:
        restore_result = restore_backup(source_backup, db_path=temp_target)
        assert restore_result["status"] == "success"
        assert restore_result["emergency_backup"] is not None
        assert "emergency_pre_restore" in restore_result["emergency_backup"]
        created_test_backups.append(restore_result["emergency_backup"])

        # Check that target database now has full restored 52 customers
        verify_conn = sqlite3.connect(temp_target)
        count = verify_conn.execute("SELECT count(*) FROM customers").fetchone()[0]
        cheque_count = verify_conn.execute("SELECT count(*) FROM cheques").fetchone()[0]
        verify_conn.close()

        assert count == 52
        assert cheque_count == 147
        print(f"PASS: test_5_safe_restore_with_emergency_snapshot -> Emergency snapshot '{restore_result['emergency_backup']}' taken and 52 customers restored successfully.")
    finally:
        if os.path.exists(temp_target):
            os.remove(temp_target)


def test_6_retention_policy_7_daily_4_weekly():
    """Verify Grandfather-Father-Son retention policy (7 daily, 4 weekly) prunes surplus files."""
    test_sandbox = os.path.join(BACKUPS_DIR, "sandbox_retention")
    os.makedirs(test_sandbox, exist_ok=True)

    try:
        # Generate 15 simulated backup files across 15 different days (spanning 5 weeks)
        now = datetime.now()
        simulated_files = []
        for i in range(15):
            past_date = now - timedelta(days=i * 2 + 2)  # older than 24 hours
            tag = "auto" if i % 2 == 0 else "manual"
            ts_str = past_date.strftime("%Y%m%d_%H%M%S")
            fname = f"backup_{tag}_{ts_str}.enc"
            fpath = os.path.join(test_sandbox, fname)
            with open(fpath, "wb") as f:
                f.write(b"SIMULATED_BACKUP_BYTES")
            simulated_files.append(fname)

        # Also add an emergency snapshot from 10 days ago (must NOT be pruned)
        em_date = now - timedelta(days=10)
        em_fname = f"backup_emergency_pre_restore_{em_date.strftime('%Y%m%d_%H%M%S')}.enc"
        with open(os.path.join(test_sandbox, em_fname), "wb") as f:
            f.write(b"EMERGENCY_BYTES")
        simulated_files.append(em_fname)

        # Temporary patch BACKUPS_DIR to test sandbox
        import app.services.backup_service
        orig_dir = app.services.backup_service.BACKUPS_DIR
        app.services.backup_service.BACKUPS_DIR = test_sandbox

        try:
            report = apply_retention_policy(keep_daily=7, keep_weekly=4)
            remaining = [f for f in os.listdir(test_sandbox) if f.endswith(".enc")]

            # Emergency snapshot must be kept
            assert em_fname in remaining, "Emergency backup must never be pruned!"
            # Oldest excess files must be pruned
            assert report["pruned_count"] > 0
            assert len(remaining) <= 12  # 7 daily + 4 weekly + 1 emergency
            print(f"PASS: test_6_retention_policy_7_daily_4_weekly -> {report['pruned_count']} surplus backups pruned, {len(remaining)} retained.")
        finally:
            app.services.backup_service.BACKUPS_DIR = orig_dir

    finally:
        if os.path.exists(test_sandbox):
            shutil.rmtree(test_sandbox, ignore_errors=True)


def test_7_path_traversal_protection():
    """Verify security prevention against path traversal attacks."""
    dangerous_names = [
        "../../../../windows/system32/cmd.exe",
        "..\\..\\boot.ini",
        "nested/sub/../../etc/passwd",
        "/absolute/path/attack.enc"
    ]
    for d in dangerous_names:
        resolved = get_backup_file_path(d)
        assert os.path.dirname(resolved) == os.path.abspath(BACKUPS_DIR)
        assert not resolved.endswith("cmd.exe")
    print("PASS: test_7_path_traversal_protection -> Path traversal attacks properly sanitized.")


def test_8_rbac_admin_full_privileges():
    """Verify 'admin' role has 100% full privileges across all sensitive APIs."""
    headers = {"X-Role": "admin"}

    # 1. Identity
    res = client.get("/api/auth/current-role", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["role"] == "admin"
    assert data["permissions"]["can_delete"] is True
    assert data["permissions"]["can_restore"] is True

    # 2. Customer Create & Delete
    new_cust = {"full_name": "تست دسترسی مدیر ارشد", "phone": "09120000000"}
    res_c = client.post("/api/customers", json=new_cust, headers=headers)
    assert res_c.status_code == 200
    cust_id = res_c.json()["customer_id"]

    res_del = client.delete(f"/api/customers/{cust_id}", headers=headers)
    assert res_del.status_code == 200
    assert "حذف شد" in res_del.json()["message"]

    # 3. Create & List Backups
    res_b = client.post("/api/backup/create", json={"tag": "admin_test"}, headers=headers)
    assert res_b.status_code == 200
    created_test_backups.append(res_b.json()["backup"]["filename"])

    res_lst = client.get("/api/backup/list", headers=headers)
    assert res_b.status_code == 200
    assert res_lst.json()["count"] >= 1

    print("PASS: test_8_rbac_admin_full_privileges -> Admin successfully created, deleted customer and managed backups.")


def test_9_rbac_operator_permissions_and_forbidden_blocks():
    """Verify 'operator' role can write/inquire/backup, but CANNOT delete or restore (HTTP 403)."""
    headers = {"X-Role": "operator"}

    # 1. Identity
    res = client.get("/api/auth/current-role", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["role"] == "operator"
    assert data["permissions"]["can_write"] is True
    assert data["permissions"]["can_delete"] is False
    assert data["permissions"]["can_restore"] is False

    # 2. Allowed: Create customer
    res_c = client.post("/api/customers", json={"full_name": "مشتری ثبت شده توسط اپراتور"}, headers=headers)
    assert res_c.status_code == 200
    cust_id = res_c.json()["customer_id"]

    # 3. Allowed: Create backup
    res_b = client.post("/api/backup/create", json={"tag": "operator_backup"}, headers=headers)
    assert res_b.status_code == 200
    created_test_backups.append(res_b.json()["backup"]["filename"])

    # 4. FORBIDDEN: Operator CANNOT delete customer (403 Forbidden)
    res_del = client.delete(f"/api/customers/{cust_id}", headers=headers)
    assert res_del.status_code == 403
    assert "نقش اپراتور مجاز به حذف اطلاعات یا بازگردانی پایگاه داده نیست" in res_del.json()["detail"]

    # 5. FORBIDDEN: Operator CANNOT delete cheque (403 Forbidden)
    res_del_ch = client.delete("/api/cheques/1", headers=headers)
    assert res_del_ch.status_code == 403
    assert "نقش اپراتور مجاز به حذف" in res_del_ch.json()["detail"]

    # 6. FORBIDDEN: Operator CANNOT restore database (403 Forbidden)
    res_rest = client.post(f"/api/backup/restore/{created_test_backups[-1]}", headers=headers)
    assert res_rest.status_code == 403
    assert "نقش اپراتور مجاز به حذف اطلاعات یا بازگردانی پایگاه داده نیست" in res_rest.json()["detail"]

    # 7. FORBIDDEN: Operator CANNOT clear logs (403 Forbidden)
    res_log = client.delete("/api/logs", headers=headers)
    assert res_log.status_code == 403

    # Clean up customer using Admin
    client.delete(f"/api/customers/{cust_id}", headers={"X-Role": "admin"})

    print("PASS: test_9_rbac_operator_permissions_and_forbidden_blocks -> Operator permitted for writes & backup; strictly blocked from DELETE & RESTORE (403).")


def test_10_rbac_auditor_read_only_and_forbidden_blocks():
    """Verify 'auditor' role has strictly read-only access and cannot write, delete, inquire or restore."""
    headers = {"X-Role": "auditor"}

    # 1. Identity
    res = client.get("/api/auth/current-role", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["role"] == "auditor"
    assert data["permissions"]["can_read"] is True
    assert data["permissions"]["can_write"] is False
    assert data["permissions"]["can_delete"] is False
    assert data["permissions"]["can_inquire"] is False
    assert data["permissions"]["can_restore"] is False

    # 2. Allowed: Read Dashboard Stats
    res_stats = client.get("/api/stats", headers=headers)
    assert res_stats.status_code == 200

    # 3. Allowed: Read Customers & Cheques
    res_cust = client.get("/api/customers", headers=headers)
    assert res_cust.status_code == 200
    res_chq = client.get("/api/cheques", headers=headers)
    assert res_chq.status_code == 200

    # 4. Allowed: List & Download Backups
    res_b_list = client.get("/api/backup/list", headers=headers)
    assert res_b_list.status_code == 200
    target_backup = created_test_backups[-1]
    res_dl = client.get(f"/api/backup/download/{target_backup}", headers=headers)
    assert res_dl.status_code == 200
    assert len(res_dl.content) > 0

    # 5. FORBIDDEN: Auditor CANNOT create customer (403)
    res_post_c = client.post("/api/customers", json={"full_name": "تست ناظر"}, headers=headers)
    assert res_post_c.status_code == 403
    assert "نقش ناظر/حسابرس فقط دسترسی خواندنی داشته" in res_post_c.json()["detail"]

    # 6. FORBIDDEN: Auditor CANNOT update customer (403)
    res_put_c = client.put("/api/customers/1", json={"notes": "تغییر غیرمجاز"}, headers=headers)
    assert res_put_c.status_code == 403

    # 7. FORBIDDEN: Auditor CANNOT delete customer (403)
    res_del_c = client.delete("/api/customers/1", headers=headers)
    assert res_del_c.status_code == 403

    # 8. FORBIDDEN: Auditor CANNOT create backup (403)
    res_make_b = client.post("/api/backup/create", json={"tag": "auditor_illegal"}, headers=headers)
    assert res_make_b.status_code == 403

    # 9. FORBIDDEN: Auditor CANNOT restore database (403)
    res_rest = client.post(f"/api/backup/restore/{target_backup}", headers=headers)
    assert res_rest.status_code == 403

    # 10. FORBIDDEN: Auditor CANNOT run inquiries (403)
    res_inq = client.post("/api/inquiries/pasargad", json={"sayadi_id": "1234567890123456"}, headers=headers)
    assert res_inq.status_code == 403

    print("PASS: test_10_rbac_auditor_read_only_and_forbidden_blocks -> Auditor read-only verified; all mutation/inquiry/restore blocked with 403.")


def test_11_role_switching_and_cookie_persistence():
    """Verify /api/auth/switch-role endpoint transitions roles smoothly."""
    # Switch to Operator
    res1 = client.post("/api/auth/switch-role", json={"role": "operator"})
    assert res1.status_code == 200
    assert res1.json()["current_role"] == "operator"

    # Verify active role without header is now operator
    res_check = client.get("/api/auth/current-role")
    assert res_check.json()["role"] == "operator"

    # Switch to Auditor
    res2 = client.post("/api/auth/switch-role", json={"role": "auditor"})
    assert res2.status_code == 200
    assert res2.json()["current_role"] == "auditor"

    # Switch back to Admin
    res3 = client.post("/api/auth/switch-role", json={"role": "admin"})
    assert res3.status_code == 200
    assert res3.json()["current_role"] == "admin"

    # Invalid role test
    res_inv = client.post("/api/auth/switch-role", json={"role": "super_hacker"})
    assert res_inv.status_code == 400
    assert "نقش نامعتبر است" in res_inv.json()["detail"]

    print("PASS: test_11_role_switching_and_cookie_persistence -> Dynamic role switching and state persistence verified.")


def cleanup_test_artifacts():
    """Remove temporary test backup files created during test run."""
    cleaned = 0
    for fname in created_test_backups:
        fpath = os.path.join(BACKUPS_DIR, fname)
        if os.path.exists(fpath):
            try:
                os.remove(fpath)
                cleaned += 1
            except Exception:
                pass
    print(f"Cleaned up {cleaned} test backup files.")


if __name__ == "__main__":
    print("=" * 70)
    print("RUNNING PHASE 3 AUTOMATED TEST SUITE: SECURITY, ENCRYPTED BACKUP & RBAC")
    print("=" * 70)
    try:
        test_1_key_generation_and_storage()
        test_2_encrypted_online_backup_creation()
        test_3_backup_integrity_verification()
        test_4_tampering_and_unauthorized_decryption_prevention()
        test_5_safe_restore_with_emergency_snapshot()
        test_6_retention_policy_7_daily_4_weekly()
        test_7_path_traversal_protection()
        test_8_rbac_admin_full_privileges()
        test_9_rbac_operator_permissions_and_forbidden_blocks()
        test_10_rbac_auditor_read_only_and_forbidden_blocks()
        test_11_role_switching_and_cookie_persistence()
        print("=" * 70)
        print("ALL 11 TEST CASES IN PHASE 3 PASSED 100% PERFECTLY!")
        print("=" * 70)
    finally:
        cleanup_test_artifacts()
