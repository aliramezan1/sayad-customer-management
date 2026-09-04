"""
Test Suite for Phase 4: Fintech Intelligence, Risk Matrix & PWA UX
Sayad Pro 3.0
"""
import sys
import os
import json
import sqlite3
from fastapi.testclient import TestClient

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from app.main import app
from app.database import get_db, DB_PATH
from app.services.risk_engine import (
    calculate_customer_fhs,
    get_cash_flow_forecast,
    get_risk_matrix,
    get_near_maturity_alerts,
    get_all_customers_fhs
)

client = TestClient(app)

def test_1_fhs_calculation():
    """Test Financial Health Score engine for various customer credit profiles."""
    with get_db() as db:
        # Test customer 49 (معصومه دوامی) - Clean record, white credit color, high volume
        fhs_49 = calculate_customer_fhs(49, db)
        assert fhs_49 is not None
        assert 0 <= fhs_49["fhs_score"] <= 100
        assert fhs_49["level"] in ["عالی", "خوب"]
        assert fhs_49["cbi_rating"] == "سفید"
        assert fhs_49["factors"]["cbi_score"] == 100.0

        # Test customer 3 (قرمز credit color)
        fhs_3 = calculate_customer_fhs(3, db)
        assert fhs_3 is not None
        assert fhs_3["fhs_score"] < 50
        assert fhs_3["level"] == "پرخطر"
        assert fhs_3["color"] == "#ef4444"
        assert fhs_3["cbi_rating"] == "قرمز"
        assert fhs_3["factors"]["cbi_score"] == 10.0

        # Test non-existent customer raises ValueError
        try:
            calculate_customer_fhs(999999, db)
            assert False, "Expected ValueError for non-existent customer"
        except ValueError:
            pass

        # Test batch all customers
        all_fhs = get_all_customers_fhs(db)
        assert len(all_fhs) == 52
        for data in all_fhs:
            assert 0 <= data["fhs_score"] <= 100
            assert data["level"] in ["عالی", "خوب", "متوسط", "پرخطر"]
    print("PASS: test_1_fhs_calculation -> Individual and bulk FHS calculation verified.")

def test_2_predictive_cash_flow():
    """Test risk-weighted cash flow forecasting across 30, 60, 90 day horizons."""
    with get_db() as db:
        cf = get_cash_flow_forecast(days=90, conn=db)
        assert "horizons" in cf
        assert "summary" in cf
        assert "daily_timeline" in cf

        h = cf["horizons"]
        assert "30_days" in h
        assert "60_days" in h
        assert "90_days" in h
        assert "overdue" in h
        assert "beyond_90" in h

        for key in ["30_days", "60_days", "90_days"]:
            bucket = h[key]
            assert "nominal" in bucket
            assert "realizable" in bucket
            assert "shortfall" in bucket
            assert "realization_rate" in bucket
            assert "count" in bucket
            assert bucket["nominal"] >= bucket["realizable"]
            assert 0 <= bucket["realization_rate"] <= 100

        assert h["90_days"]["nominal"] >= h["30_days"]["nominal"]
        assert h["90_days"]["count"] >= h["30_days"]["count"]

        s = cf["summary"]
        assert "nominal_total_90d" in s
        assert "realizable_total_90d" in s
        assert "shortfall_total_90d" in s
        assert "realization_rate_90d" in s
    print(f"PASS: test_2_predictive_cash_flow -> 90d nominal={s['nominal_total_90d']:,.0f}, realizable={s['realizable_total_90d']:,.0f}, shortfall={s['shortfall_total_90d']:,.0f}, rate={s['realization_rate_90d']}%.")

def test_3_risk_matrix():
    """Test 2D Risk Matrix segmentation (FHS x Exposure)."""
    with get_db() as db:
        matrix = get_risk_matrix(conn=db)
        assert "quadrants" in matrix
        assert "summary" in matrix
        assert "thresholds" in matrix
        q = matrix["quadrants"]
        assert "stars" in q
        assert "opportunities" in q
        assert "watchlist" in q
        assert "critical" in q

        total_quadrant_customers = (
            q["stars"]["count"] +
            q["opportunities"]["count"] +
            q["watchlist"]["count"] +
            q["critical"]["count"]
        )
        assert total_quadrant_customers == 52
        assert matrix["summary"]["total_customers"] == 52

        # Verify stars customer structure
        if q["stars"]["count"] > 0:
            first_star = q["stars"]["customers"][0]
            assert "customer_id" in first_star
            assert "full_name" in first_star
            assert "fhs_score" in first_star
            assert "total_amount" in first_star
            assert first_star["fhs_score"] >= 60.0
    print(f"PASS: test_3_risk_matrix -> Stars:{q['stars']['count']}, Opportunities:{q['opportunities']['count']}, Watchlist:{q['watchlist']['count']}, Critical:{q['critical']['count']}.")

def test_4_near_maturity_alerts():
    """Test near-maturity proactive alerts (cheques due within 7 days)."""
    with get_db() as db:
        alerts = get_near_maturity_alerts(days_threshold=7, conn=db)
        assert isinstance(alerts, list)
        for alert in alerts:
            assert alert["days_remaining"] <= 7
            assert alert["priority"] in ["critical", "warning", "normal"]
            assert "sayadi_id" in alert
            assert "customer_name" in alert
            assert "amount" in alert
            assert "credit_color" in alert
    print(f"PASS: test_4_near_maturity_alerts -> Detected {len(alerts)} cheques maturing within 7 days.")

def test_5_fastapi_analytics_endpoints():
    """Test FastAPI REST endpoints for analytics and risk metrics."""
    # Cash Flow
    res = client.get("/api/analytics/cash-flow?days=60")
    assert res.status_code == 200
    data = res.json()
    assert "horizons" in data
    assert "summary" in data

    # Risk Matrix
    res = client.get("/api/analytics/risk-matrix")
    assert res.status_code == 200
    data = res.json()
    assert "quadrants" in data
    assert "summary" in data

    # Customer FHS
    res = client.get("/api/analytics/customer-fhs/49")
    assert res.status_code == 200
    data = res.json()
    assert data["customer_id"] == 49
    assert "fhs_score" in data
    assert data["fhs_score"] >= 70

    # Non-existent customer
    res = client.get("/api/analytics/customer-fhs/999999")
    assert res.status_code == 404

    # Near maturity alerts
    res = client.get("/api/analytics/alerts/near-maturity")
    assert res.status_code == 200
    data = res.json()
    assert "alerts" in data
    assert "count" in data
    assert data["count"] == len(data["alerts"])
    print("PASS: test_5_fastapi_analytics_endpoints -> All analytical endpoints returned 200 OK.")

def test_6_rbac_authorization():
    """Test RBAC enforcement across analytics endpoints."""
    # Auditor role has read permission -> 200 OK
    res = client.get("/api/analytics/risk-matrix", headers={"X-Role": "auditor"})
    assert res.status_code == 200

    # Operator role has read permission -> 200 OK
    res = client.get("/api/analytics/cash-flow", headers={"X-Role": "operator"})
    assert res.status_code == 200

    # Invalid / unauthorized role -> 403 Forbidden
    res = client.get("/api/analytics/risk-matrix", headers={"X-Role": "guest"})
    assert res.status_code == 403
    assert "دسترسی غیرمجاز" in res.json()["detail"]

    # Customer FHS with invalid role -> 403 Forbidden
    res = client.get("/api/analytics/customer-fhs/49", headers={"X-Role": "unknown_role"})
    assert res.status_code == 403
    assert "دسترسی غیرمجاز" in res.json()["detail"]
    print("PASS: test_6_rbac_authorization -> RBAC access verified (auditor/operator allowed, unauthorized roles rejected with 403).")

def test_7_pwa_manifest_and_sw():
    """Test PWA manifest and service worker delivery and content."""
    # Manifest
    res_m = client.get("/manifest.json")
    assert res_m.status_code == 200
    manifest = res_m.json()
    assert "صیاد پرو" in manifest["name"]
    assert manifest["short_name"] == "صیاد پرو"
    assert manifest["display"] == "standalone"
    assert manifest["start_url"] in ["/", "/index.html", "./"]
    assert len(manifest["icons"]) >= 3

    # Service Worker
    res_sw = client.get("/sw.js")
    assert res_sw.status_code == 200
    assert "javascript" in res_sw.headers.get("content-type", "").lower()
    assert res_sw.headers.get("Service-Worker-Allowed") == "/"
    assert "CACHE_NAME" in res_sw.text
    assert "sayad-pro-v3.0.0" in res_sw.text
    print("PASS: test_7_pwa_manifest_and_sw -> Manifest and Service Worker properly served with correct headers.")

def test_8_pwa_icons_existence():
    """Verify that all generated PWA icon assets exist in both static and docs folders."""
    icon_files = [
        "icons/icon-192.png",
        "icons/icon-512.png",
        "icons/icon-maskable.png",
        "icons/icon.svg"
    ]
    for rel_path in icon_files:
        static_p = os.path.join("app", "static", rel_path)
        docs_p = os.path.join("docs", rel_path)
        assert os.path.exists(static_p), f"Missing {static_p}"
        assert os.path.exists(docs_p), f"Missing {docs_p}"
        assert os.path.getsize(static_p) > 100
        assert os.path.getsize(docs_p) > 100
    print("PASS: test_8_pwa_icons_existence -> All PWA icons present and valid in app/static/icons and docs/icons.")

def test_9_frontend_docs_synchronization():
    """Verify 100% synchronization between app/static/templates and docs."""
    files_to_compare = [
        ("templates/index.html", "docs/index.html"),
        ("app/static/js/app.js", "docs/js/app.js"),
        ("app/static/manifest.json", "docs/manifest.json"),
        ("app/static/sw.js", "docs/sw.js")
    ]
    for src, dst in files_to_compare:
        assert os.path.exists(src), f"Missing {src}"
        assert os.path.exists(dst), f"Missing {dst}"
        with open(src, "rb") as f1, open(dst, "rb") as f2:
            content1 = f1.read()
            content2 = f2.read()
            assert content1 == content2, f"Mismatch between {src} and {dst}!"
    print("PASS: test_9_frontend_docs_synchronization -> templates and docs are 100% in sync.")

def test_10_customer_list_and_profile_fhs_integration():
    """Verify that existing customer endpoints include the newly integrated FHS data."""
    # List customers
    res = client.get("/api/customers?limit=10")
    assert res.status_code == 200
    data = res.json()
    first_cust = data["customers"][0]
    assert "fhs_score" in first_cust
    assert "fhs_level" in first_cust
    assert "fhs_color" in first_cust

    # Customer profile
    res_prof = client.get("/api/customers/49")
    assert res_prof.status_code == 200
    p_data = res_prof.json()
    assert "fhs" in p_data
    assert p_data["fhs"]["fhs_score"] >= 70
    assert "factors" in p_data["fhs"]
    print("PASS: test_10_customer_list_and_profile_fhs_integration -> /api/customers and /api/customers/{id} successfully include FHS.")

if __name__ == "__main__":
    print("=" * 65)
    print("RUNNING PHASE 4: FINTECH INTELLIGENCE & PWA UX TEST SUITE")
    print("=" * 65)
    test_1_fhs_calculation()
    test_2_predictive_cash_flow()
    test_3_risk_matrix()
    test_4_near_maturity_alerts()
    test_5_fastapi_analytics_endpoints()
    test_6_rbac_authorization()
    test_7_pwa_manifest_and_sw()
    test_8_pwa_icons_existence()
    test_9_frontend_docs_synchronization()
    test_10_customer_list_and_profile_fhs_integration()
    print("=" * 65)
    print("ALL 10 PHASE 4 TESTS PASSED FLAWLESSLY!")
    print("=" * 65)
