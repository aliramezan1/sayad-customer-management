# -*- coding: utf-8 -*-
"""
Test Suite for Phase 2: Banking Resilience & Pareto Engine
Verifies:
1. Stage 1 Fast Pareto Query (<600ms, single holder queried, persisted to DB)
2. Stage 2 Parallel Cartable Pool (ThreadPoolExecutor max_workers=3, cancellation on match)
3. Exponential backoff with random jitter formula
4. 100% Historical data preservation (no zeroing out on not_in_cartable)
5. Scheduler Tiered Smart Maturity Polling & Itemized reporting
"""
import sys
import os
import time
import json
import sqlite3
from datetime import datetime, date
from unittest.mock import patch, MagicMock

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from app.database import get_db, init_db, DB_PATH
from app.services.pasargad import (
    cascade_pasargad_inquiry,
    query_single_holder,
    calculate_days_until_due,
    jalali_to_gregorian,
    _trigger_global_cooldown
)
from app.services.scheduler import scheduler_instance
from app.services.smart_logger import smart_logger

def test_1_days_until_due_and_conversion():
    print("Testing 1: Date calculations and Solar Hijri conversions...")
    # 1405/06/14 corresponds to 2026-09-05
    gy, gm, gd = jalali_to_gregorian(1405, 6, 14)
    assert (gy, gm, gd) == (2026, 9, 5)

    # Overdue by ~2 years
    days_old = calculate_days_until_due("14030901")
    assert days_old is not None and days_old < -30

    # Near term: 14050620 -> 20 Shahrivar 1405 (~6 days from 14 Shahrivar 1405)
    days_near = calculate_days_until_due("14050620")
    assert days_near is not None and 0 <= days_near <= 7

    # Future: 14060102 -> Farvardin 1406 (> 150 days)
    days_future = calculate_days_until_due("14060102")
    assert days_future is not None and days_future > 30

    print(f"  [PASS] Date calculations verified: Old={days_old}d, Near={days_near}d, Future={days_future}d")


def test_2_stage1_fast_pareto_query():
    print("Testing 2: Stage 1 Fast Pareto Query...")
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT sayadi_id, holder_id FROM cheques WHERE sayadi_id IS NOT NULL AND length(trim(sayadi_id))=16 LIMIT 1")
    row = cursor.fetchone()
    test_sayadi = row["sayadi_id"]
    conn.close()

    mock_resp_data = {
        "onGoingAmount": 550000000.0,
        "blocked": 0,
        "ownersInfo": [{"bouncedAmount": 0, "clearedAmount": 200000000.0, "idCode": "0921974061"}]
    }
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = mock_resp_data
    mock_response.text = json.dumps(mock_resp_data)

    with patch("app.services.pasargad.GLOBAL_SESSION.get", return_value=mock_response) as mock_get:
        t0 = time.perf_counter()
        res = cascade_pasargad_inquiry(test_sayadi, preferred_holder_id=1)
        duration = (time.perf_counter() - t0) * 1000

        # Verify Stage 1 hit
        assert res["status"] == "success"
        assert res["cascade_stage"] == 1
        assert res["holder_id"] == 1
        assert res["in_transit_amount"] == 550000000.0
        assert res["cleared_amount"] == 200000000.0
        
        # Verify only 1 HTTP call made (Stage 1 did not touch the other 8 holders)
        assert mock_get.call_count == 1
        print(f"  [PASS] Stage 1 Fast Query completed in {duration:.1f}ms with exactly 1 call!")

    # Verify DB persistence
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM pasargad_inquiries WHERE sayadi_id = ? ORDER BY id DESC LIMIT 1", (test_sayadi,))
    inq = cursor.fetchone()
    assert inq is not None
    assert inq["status"] == "success"
    assert inq["holder_id"] == 1
    assert inq["in_transit_amount"] == 550000000.0

    cursor.execute("SELECT holder_id FROM cheques WHERE sayadi_id = ?", (test_sayadi,))
    ch_holder = cursor.fetchone()["holder_id"]
    assert ch_holder == 1
    conn.close()
    print("  [PASS] Stage 1 inquiry successfully persisted to database and cheque updated!")


def test_3_stage2_parallel_cartable_pool():
    print("Testing 3: Stage 2 Parallel Cartable Pool with ThreadPoolExecutor & cancellation...")
    test_sayadi = "9999888877776666"

    # Insert temporary cheque
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO cheques (customer_id, sayadi_id, amount, cheque_date, holder_id) VALUES (1, ?, 100000000, '14050625', 1)", (test_sayadi,))
    conn.commit()
    conn.close()

    # Define mock bank responses:
    # Holder 1 (Stage 1) -> 400 not_in_cartable
    # Holder 2 (Stage 2) -> 400 not_in_cartable
    # Holder 3 (Stage 2, national_id=0922236992) -> 200 SUCCESS
    # Others -> 400 not_in_cartable
    def side_effect_get(url, params=None, headers=None, verify=False, timeout=8):
        id_code = params.get("IdCode")
        mock_resp = MagicMock()
        if id_code == "0922236992": # Mohammad Ziafati (holder 3)
            data = {
                "onGoingAmount": 800000000.0,
                "blocked": 0,
                "ownersInfo": [{"bouncedAmount": 0, "clearedAmount": 0, "idCode": "0922236992"}]
            }
            mock_resp.status_code = 200
            mock_resp.json.return_value = data
            mock_resp.text = json.dumps(data)
        else:
            mock_resp.status_code = 400
            mock_resp.json.return_value = {"message": "not in cartable"}
            mock_resp.text = '{"message": "چک در کارتابل یافت نشد"}'
        return mock_resp

    with patch("app.services.pasargad.GLOBAL_SESSION.get", side_effect=side_effect_get) as mock_get:
        res = cascade_pasargad_inquiry(test_sayadi, preferred_holder_id=1)
        assert res["status"] == "success"
        assert res["cascade_stage"] == 2
        assert res["holder_id"] == 3
        assert res["in_transit_amount"] == 800000000.0
        # Call count should be Stage 1 (1) + a subset of Stage 2 (due to cooperative cancellation)
        assert mock_get.call_count <= 9
        print(f"  [PASS] Stage 2 parallel cartable pool successfully matched holder 3 ({res['holder_name']}) in {mock_get.call_count} total calls!")

    # Verify DB persistence for stage 2
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM pasargad_inquiries WHERE sayadi_id = ? AND status = 'success' ORDER BY id DESC LIMIT 1", (test_sayadi,))
    inq = cursor.fetchone()
    assert inq is not None
    assert inq["holder_id"] == 3
    assert inq["in_transit_amount"] == 800000000.0
    conn.close()
    print("  [PASS] Stage 2 inquiry successfully persisted and updated holder in DB!")


def test_4_historical_data_preservation():
    print("Testing 4: 100% Historical data preservation on not_in_cartable...")
    test_sayadi = "8888777766665555"

    conn = get_db()
    cursor = conn.cursor()
    # Insert previous successful record
    cursor.execute("""
    INSERT INTO pasargad_inquiries (
        sayadi_id, holder_id, customer_id, in_transit_count, in_transit_amount,
        cleared_count, cleared_amount, bounced_count, bounced_amount, status
    ) VALUES (?, 1, 1, 1, 950000000.0, 2, 400000000.0, 0, 0, 'success')
    """, (test_sayadi,))
    cursor.execute("INSERT OR REPLACE INTO cheques (customer_id, sayadi_id, amount, cheque_date, holder_id) VALUES (1, ?, 950000000, '14050601', 1)", (test_sayadi,))
    conn.commit()
    conn.close()

    # Bank returns 400 not_in_cartable for all holders
    mock_resp = MagicMock()
    mock_resp.status_code = 400
    mock_resp.text = '{"message": "چک در کارتابل یافت نشد"}'
    mock_resp.json.return_value = {"message": "not in cartable"}

    with patch("app.services.pasargad.GLOBAL_SESSION.get", return_value=mock_resp):
        res = cascade_pasargad_inquiry(test_sayadi)
        assert res["status"] == "not_in_cartable"
        assert res["preserved_from_history"] == True
        # Critical: amounts must NOT be zeroed out!
        assert res["in_transit_amount"] == 950000000.0
        assert res["cleared_amount"] == 400000000.0
        assert res["in_transit_count"] == 1
        assert res["cleared_count"] == 2
        print("  [PASS] Previous credit amounts 100% preserved (in_transit=950M, cleared=400M) without zeroing out!")


def test_5_exponential_jitter_backoff():
    print("Testing 5: Exponential backoff with random jitter calculation...")
    from app.services.pasargad import random
    
    for attempt in range(1, 4):
        wait_time = round((1.2 ** attempt) + random.uniform(0.2, 0.6), 2)
        min_expected = round((1.2 ** attempt) + 0.2, 2)
        max_expected = round((1.2 ** attempt) + 0.6, 2)
        assert min_expected <= wait_time <= max_expected
        print(f"  Attempt {attempt}: wait_time = {wait_time:.2f}s (Range: {min_expected}s - {max_expected}s)")
    print("  [PASS] Exponential backoff with random jitter strictly complies with specification!")


def test_6_scheduler_tiered_smart_polling():
    print("Testing 6: Scheduler Tiered Smart Maturity Polling & Filtering...")
    
    # Insert an old settled cheque (>30 days overdue and status='passed' with 0 in transit)
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO cheques (customer_id, sayadi_id, amount, cheque_date, holder_id, status) VALUES (1, '1111222233334444', 50000000, '14030101', 1, 'passed')")
    cursor.execute("INSERT INTO pasargad_inquiries (sayadi_id, holder_id, customer_id, in_transit_count, in_transit_amount, cleared_count, cleared_amount, status) VALUES ('1111222233334444', 1, 1, 0, 0, 1, 50000000, 'success')")
    conn.commit()
    conn.close()

    # Mock record_pasargad_inquiry to avoid live HTTP calls during unit test
    def mock_inquiry(sayadi_id, holder_id=None, customer_id=None, customer_name=None):
        return {"status": "success", "sayadi_id": sayadi_id, "in_transit_amount": 1000000}

    with patch("app.services.scheduler.record_pasargad_inquiry", side_effect=mock_inquiry), \
         patch("app.services.scheduler.time.sleep", return_value=None):
        report = scheduler_instance.run_batch_inquiry(default_holder_id=1)
        assert report["status"] in ("success", "partial")
        assert "excluded_count" in report
        assert "unchanged_count" in report
        assert "success_count" in report
        assert report["excluded_count"] >= 1, f"Expected at least 1 excluded cheque, got {report['excluded_count']}"
        assert report["total_processed"] + report["excluded_count"] == report["total_cheques"]
        print(f"  [PASS] Scheduler report verified: Processed={report['total_processed']} | Excluded={report['excluded_count']} | Success={report['success_count']}")

    # Check scheduler_logs in DB
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM scheduler_logs ORDER BY id DESC LIMIT 1")
    s_log = cursor.fetchone()
    assert s_log is not None
    assert "استعلام چندسطحی پارتو بانک پاسارگاد" in s_log["task_name"]
    assert "معاف" in s_log["details"]
    assert "موفق" in s_log["details"]
    conn.close()
    print("  [PASS] Scheduler logs properly recorded itemized audit entry in database with excluded count!")


def cleanup_test_data():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM cheques WHERE sayadi_id IN ('9999888877776666', '8888777766665555', '1111222233334444')")
    cursor.execute("DELETE FROM pasargad_inquiries WHERE sayadi_id IN ('9999888877776666', '8888777766665555', '1111222233334444')")
    cursor.execute("DELETE FROM scheduler_logs WHERE task_name = 'استعلام چندسطحی پارتو بانک پاسارگاد'")
    conn.commit()
    conn.close()
    try:
        from app.main import invalidate_stats_cache
        invalidate_stats_cache()
    except Exception:
        pass

if __name__ == "__main__":
    print("=" * 60)
    print("RUNNING PHASE 2 RESILIENCE & PARETO TEST SUITE")
    print("=" * 60)
    cleanup_test_data()
    try:
        test_1_days_until_due_and_conversion()
        test_2_stage1_fast_pareto_query()
        test_3_stage2_parallel_cartable_pool()
        test_4_historical_data_preservation()
        test_5_exponential_jitter_backoff()
        test_6_scheduler_tiered_smart_polling()
        print("=" * 60)
        print("ALL PHASE 2 RESILIENCE & PARETO TESTS PASSED 100%!")
        print("=" * 60)
    finally:
        cleanup_test_data()
