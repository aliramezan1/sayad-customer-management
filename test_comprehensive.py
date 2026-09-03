import sys
import os
import json
import sqlite3
from fastapi.testclient import TestClient

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from app.main import app
from app.database import get_db, init_db, DB_PATH

client = TestClient(app)

def test_1_html_home():
    res = client.get("/")
    assert res.status_code == 200
    assert "سامانه جامع مدیریت مشتریان" in res.text
    assert "صیاد پرو" in res.text
    print("PASS: test_1_html_home")

def test_2_stats():
    res = client.get("/api/stats")
    assert res.status_code == 200
    data = res.json()
    assert data["total_customers"] == 52
    assert data["total_cheques"] == 147
    assert data["total_amount"] == 483325000000.0
    assert data["credit_colors"]["سفید"] == 36
    assert data["credit_colors"]["قرمز"] == 14
    assert data["credit_colors"]["قهوه ای"] == 2
    assert len(data["recent_inquiries"]) <= 6
    print(f"PASS: test_2_stats -> total_customers={data['total_customers']}, total_cheques={data['total_cheques']}, total_amount={data['total_amount']:,.0f}")

def test_3_customers_list():
    res = client.get("/api/customers?limit=100")
    assert res.status_code == 200
    data = res.json()
    assert data["count"] == 52
    assert len(data["customers"]) == 52
    
    # Check Customer 49
    cust49 = next((c for c in data["customers"] if c["id"] == 49), None)
    assert cust49 is not None
    assert cust49["full_name"] == "معصومه دوامي"
    assert cust49["cheque_count"] == 6
    assert cust49["total_cheque_amount"] == 82500000000.0

    # Check Customer 10
    cust10 = next((c for c in data["customers"] if c["id"] == 10), None)
    assert cust10 is not None
    assert cust10["full_name"] == "عطاری ید اله"
    assert cust10["cheque_count"] == 12
    assert cust10["total_cheque_amount"] == 24000000000.0

    print("PASS: test_3_customers_list")

def test_4_customer_profile():
    res = client.get("/api/customers/49")
    assert res.status_code == 200
    data = res.json()
    assert data["customer"]["full_name"] == "معصومه دوامي"
    assert len(data["cheques"]) == 6
    assert data["summary"]["cheque_count"] == 6
    assert data["summary"]["total_amount"] == 82500000000.0
    print("PASS: test_4_customer_profile")

def test_5_cheques_list():
    res = client.get("/api/cheques?limit=200")
    assert res.status_code == 200
    data = res.json()
    assert data["count"] == 147
    assert len(data["cheques"]) == 147
    print("PASS: test_5_cheques_list")

def test_6_holders_list():
    res = client.get("/api/holders")
    assert res.status_code == 200
    data = res.json()
    assert len(data["holders"]) == 9
    names = [h["full_name"] for h in data["holders"]]
    assert "علی رمضانزاده" in names
    assert "عادل رمضانزاده" in names
    assert "محمد ضیافتی" in names
    print("PASS: test_6_holders_list")

def test_7_inquiries_list():
    res = client.get("/api/inquiries?limit=10")
    assert res.status_code == 200
    data = res.json()
    assert data["count"] == 10
    assert len(data["inquiries"]) == 10
    print("PASS: test_7_inquiries_list")

def test_8_static_dataset_files():
    for url in ["/data/initial_dataset.json", "/static/data/initial_dataset.json"]:
        res = client.get(url)
        assert res.status_code == 200
        data = res.json()
        assert len(data["customers"]) == 52
        assert len(data["cheques"]) == 147
        assert len(data["holders"]) == 9
        assert len(data["inquiries"]) >= 1000
    print("PASS: test_8_static_dataset_files")

def test_9_excel_export():
    res = client.get("/api/export/excel")
    assert res.status_code == 200
    assert len(res.content) > 5000
    assert res.headers["content-type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    print(f"PASS: test_9_excel_export -> {len(res.content)} bytes")

def test_10_scheduler_status():
    res = client.get("/api/scheduler/status")
    assert res.status_code == 200
    assert "is_running" in res.json()
    print("PASS: test_10_scheduler_status")

def test_11_fresh_db_seeding():
    """Verify that a brand new empty database can initialize and seed 100% cleanly without errors."""
    test_db_path = "test_clean_init.db"
    if os.path.exists(test_db_path):
        os.remove(test_db_path)
    
    import app.database
    orig_path = app.database.DB_PATH
    try:
        app.database.DB_PATH = test_db_path
        app.database.init_db()
        
        conn = sqlite3.connect(test_db_path)
        cur = conn.cursor()
        c_cnt = cur.execute("SELECT count(*) FROM customers").fetchone()[0]
        ch_cnt = cur.execute("SELECT count(*) FROM cheques").fetchone()[0]
        h_cnt = cur.execute("SELECT count(*) FROM holders").fetchone()[0]
        inq_cnt = cur.execute("SELECT count(*) FROM pasargad_inquiries").fetchone()[0]
        conn.close()

        assert c_cnt == 52
        assert ch_cnt == 147
        assert h_cnt == 9
        assert inq_cnt >= 1000
        print(f"PASS: test_11_fresh_db_seeding -> Brand new DB initialized with {c_cnt} customers, {ch_cnt} cheques, {h_cnt} holders, {inq_cnt} inquiries.")
    finally:
        app.database.DB_PATH = orig_path
        if os.path.exists(test_db_path):
            os.remove(test_db_path)

if __name__ == "__main__":
    print("=" * 60)
    print("RUNNING COMPREHENSIVE AUTOMATED TEST SUITE")
    print("=" * 60)
    test_1_html_home()
    test_2_stats()
    test_3_customers_list()
    test_4_customer_profile()
    test_5_cheques_list()
    test_6_holders_list()
    test_7_inquiries_list()
    test_8_static_dataset_files()
    test_9_excel_export()
    test_10_scheduler_status()
    test_11_fresh_db_seeding()
    print("=" * 60)
    print("ALL 11 TEST CASES PASSED PERFECTLY!")
    print("=" * 60)
