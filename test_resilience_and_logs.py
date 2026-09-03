# -*- coding: utf-8 -*-
"""
Automated Test Suite for Resilient Pasargad Inquiry Engine & Smart Logging System
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import requests
import json
import time

BASE_URL = "http://127.0.0.1:8000"

def test_all():
    print("==================================================")
    print("🚀 Running Full Test Suite for Resilience & Logging")
    print("==================================================")

    passed = 0
    total = 0

    # Test 1: Health Endpoint
    total += 1
    try:
        r = requests.get(f"{BASE_URL}/api/health", timeout=5)
        assert r.status_code == 200, f"Expected 200, got {r.status_code}"
        data = r.json()
        assert data.get("status") == "healthy"
        assert "pasargad_gateway" in data
        print(f"✅ Test 1 Passed: /api/health -> Gateway Status: {data['pasargad_gateway'].get('status')} ({data['pasargad_gateway'].get('latency_ms')}ms)")
        passed += 1
    except Exception as e:
        print(f"❌ Test 1 Failed: {e}")

    # Test 2: Client Log Creation
    total += 1
    try:
        payload = {
            "level": "INFO",
            "tag": "TEST",
            "message": "لاگ آزمایشی برای بررسی سلامت سیستم لاگینگ",
            "sayadi_id": "1234567890123456",
            "customer_name": "مشتری آزمایشی"
        }
        r = requests.post(f"{BASE_URL}/api/logs/client", json=payload, timeout=5)
        assert r.status_code == 200, f"Expected 200, got {r.status_code}"
        data = r.json()
        assert data.get("status") == "success"
        print("✅ Test 2 Passed: POST /api/logs/client -> Log created and forwarded")
        passed += 1
    except Exception as e:
        print(f"❌ Test 2 Failed: {e}")

    # Test 3: Query Logs Endpoint
    total += 1
    try:
        r = requests.get(f"{BASE_URL}/api/logs?limit=50", timeout=5)
        assert r.status_code == 200, f"Expected 200, got {r.status_code}"
        data = r.json()
        assert "logs" in data
        assert "stats" in data
        print(f"✅ Test 3 Passed: GET /api/logs -> Retrieved {len(data['logs'])} logs | Total recorded: {data['stats'].get('total')}")
        passed += 1
    except Exception as e:
        print(f"❌ Test 3 Failed: {e}")

    # Test 4: Export Logs as JSON and Text
    total += 1
    try:
        r_json = requests.get(f"{BASE_URL}/api/logs/export?format=json", timeout=5)
        r_txt = requests.get(f"{BASE_URL}/api/logs/export?format=text", timeout=5)
        assert r_json.status_code == 200 and r_txt.status_code == 200
        print(f"✅ Test 4 Passed: GET /api/logs/export (JSON: {len(r_json.content)} bytes, TXT: {len(r_txt.content)} bytes)")
        passed += 1
    except Exception as e:
        print(f"❌ Test 4 Failed: {e}")

    # Test 5: Pasargad Inquiry API (Graceful status & No 400 on not in cartable)
    total += 1
    try:
        inq_payload = {
            "sayadi_id": "2359050004531111",
            "holder_id": 1,
            "customer_id": 1
        }
        r = requests.post(f"{BASE_URL}/api/inquiries/pasargad", json=inq_payload, timeout=12)
        assert r.status_code == 200, f"Expected 200, got {r.status_code}"
        data = r.json()
        assert "status" in data
        assert "message" in data
        print(f"✅ Test 5 Passed: POST /api/inquiries/pasargad -> Status: {data.get('status')} | Message: {data.get('message')}")
        passed += 1
    except Exception as e:
        print(f"❌ Test 5 Failed: {e}")

    # Test 6: Inquiries History List
    total += 1
    try:
        r = requests.get(f"{BASE_URL}/api/inquiries?limit=10", timeout=5)
        assert r.status_code == 200
        data = r.json()
        assert "inquiries" in data
        print(f"✅ Test 6 Passed: GET /api/inquiries -> {data.get('count')} total inquiries accessible")
        passed += 1
    except Exception as e:
        print(f"❌ Test 6 Failed: {e}")

    # Test 7: Stats Verification
    total += 1
    try:
        r = requests.get(f"{BASE_URL}/api/stats", timeout=5)
        assert r.status_code == 200
        data = r.json()
        assert data.get("total_customers") == 52
        assert data.get("total_cheques") == 147
        print(f"✅ Test 7 Passed: GET /api/stats -> 52 Customers, 147 Cheques, Total: {data.get('total_amount'):,}")
        passed += 1
    except Exception as e:
        print(f"❌ Test 7 Failed: {e}")

    print("==================================================")
    print(f"🎯 Results: {passed}/{total} Tests Passed ({passed/total*100:.0f}%)")
    print("==================================================")

if __name__ == "__main__":
    test_all()
