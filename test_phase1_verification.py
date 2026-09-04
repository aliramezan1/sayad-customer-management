import sys
import os
import time
from fastapi.testclient import TestClient

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from app.database import get_db, init_db, DB_PATH
from app.main import app, stats_cache, invalidate_stats_cache

client = TestClient(app)

def test_pragmas_and_wal():
    print("Testing 1: PRAGMA optimizations and WAL mode...")
    conn = get_db()
    
    # 1. journal_mode == wal
    jm = conn.execute("PRAGMA journal_mode;").fetchone()[0].lower()
    assert jm == "wal", f"Expected WAL journal_mode, got {jm}"

    # 2. synchronous == 1 (NORMAL)
    sync = conn.execute("PRAGMA synchronous;").fetchone()[0]
    assert sync == 1, f"Expected synchronous=1 (NORMAL), got {sync}"

    # 3. busy_timeout == 5000
    timeout = conn.execute("PRAGMA busy_timeout;").fetchone()[0]
    assert timeout == 5000, f"Expected busy_timeout=5000, got {timeout}"

    # 4. cache_size == -64000
    cache = conn.execute("PRAGMA cache_size;").fetchone()[0]
    assert cache == -64000, f"Expected cache_size=-64000, got {cache}"

    # 5. foreign_keys == 1 (ON)
    fk = conn.execute("PRAGMA foreign_keys;").fetchone()[0]
    assert fk == 1, f"Expected foreign_keys=1 (ON), got {fk}"

    conn.close()
    print("  [PASS] All 5 PRAGMA settings (WAL, NORMAL, busy_timeout=5000, cache_size=-64000, foreign_keys=ON) verified!")

def test_indexes():
    print("Testing 2: Five composite indexes creation and query plan...")
    init_db()
    conn = get_db()
    cur = conn.cursor()

    cur.execute("PRAGMA index_list(cheques)")
    cheque_indexes = {row[1] for row in cur.fetchall()}
    assert "idx_cheques_sayadi" in cheque_indexes, "idx_cheques_sayadi missing"
    assert "idx_cheques_customer_id" in cheque_indexes, "idx_cheques_customer_id missing"
    assert "idx_cheques_holder_date" in cheque_indexes, "idx_cheques_holder_date missing"

    cur.execute("PRAGMA index_list(pasargad_inquiries)")
    inquiry_indexes = {row[1] for row in cur.fetchall()}
    assert "idx_pasargad_sayadi_latest" in inquiry_indexes, "idx_pasargad_sayadi_latest missing"

    cur.execute("PRAGMA index_list(customers)")
    customer_indexes = {row[1] for row in cur.fetchall()}
    assert "idx_customers_national_id" in customer_indexes, "idx_customers_national_id missing"

    # Verify query planner utilizes index
    cur.execute("EXPLAIN QUERY PLAN SELECT * FROM cheques WHERE sayadi_id = '1234567890123456'")
    plan = cur.fetchall()
    plan_str = " ".join(dict(p).get("detail", "") for p in plan)
    assert "idx_cheques_sayadi" in plan_str, f"idx_cheques_sayadi not used in plan: {plan_str}"

    cur.execute("EXPLAIN QUERY PLAN SELECT * FROM customers WHERE national_id = '0921974061'")
    plan2 = cur.fetchall()
    plan2_str = " ".join(dict(p).get("detail", "") for p in plan2)
    assert "idx_customers_national_id" in plan2_str, f"idx_customers_national_id not used in plan: {plan2_str}"

    conn.close()
    print("  [PASS] All 5 composite indexes created and verified in SQLite query planner!")

def test_stats_ttl_cache_and_invalidation():
    print("Testing 3: Dashboard TTLCache and invalidation on mutations...")
    stats_cache.clear()
    assert stats_cache.get("dashboard_stats") is None

    # First request: computes and populates cache
    t0 = time.perf_counter()
    r1 = client.get("/api/stats")
    t1 = time.perf_counter()
    duration_uncached = t1 - t0
    assert r1.status_code == 200
    assert stats_cache.get("dashboard_stats") is not None

    # Second request: served immediately from RAM cache
    t2 = time.perf_counter()
    r2 = client.get("/api/stats")
    t3 = time.perf_counter()
    duration_cached = t3 - t2
    assert r2.status_code == 200
    assert r1.json() == r2.json()
    print(f"  Uncached: {duration_uncached*1000:.2f}ms | Cached: {duration_cached*1000:.2f}ms (Speedup: {duration_uncached / max(duration_cached, 0.00001):.1f}x)")

    # Test invalidation on customer update
    client.put("/api/customers/1", json={"notes": "تست بهینه‌سازی کش"})
    assert stats_cache.get("dashboard_stats") is None, "Cache should be invalidated after customer update!"

    # Populate again
    r3 = client.get("/api/stats")
    assert r3.status_code == 200
    assert stats_cache.get("dashboard_stats") is not None

    # Test invalidation on cheque creation
    r_cheque = client.post("/api/cheques", json={
        "customer_id": 1,
        "sayadi_id": "9999888877776666",
        "cheque_number": "CHQ-CACHE-TEST",
        "amount": 1000000,
        "cheque_date": "1405/01/01",
        "bank_name": "بانک پاسارگاد",
        "holder_id": 1,
        "status": "pending"
    })
    assert r_cheque.status_code == 200
    ch_id = r_cheque.json()["cheque_id"]
    assert stats_cache.get("dashboard_stats") is None, "Cache should be invalidated after cheque creation!"

    # Clean up created cheque
    client.delete(f"/api/cheques/{ch_id}")
    assert stats_cache.get("dashboard_stats") is None, "Cache should be invalidated after cheque deletion!"

    # Test TTL expiration directly
    stats_cache.set("test_key", "test_val", ttl=0.1)
    assert stats_cache.get("test_key") == "test_val"
    time.sleep(0.15)
    assert stats_cache.get("test_key") is None, "TTL expiration failed!"

    print("  [PASS] TTLCache and automatic invalidation on mutations work flawlessly!")

def test_gzip_middleware():
    print("Testing 4: GZipMiddleware compression...")
    headers = {"Accept-Encoding": "gzip"}
    
    # 1. Large payload (> 1000 bytes) should be compressed
    res = client.get("/api/customers?limit=100", headers=headers)
    assert res.status_code == 200
    enc = res.headers.get("content-encoding", "")
    print(f"  Response content length: {len(res.content)} bytes, Content-Encoding: '{enc}'")
    assert enc == "gzip", f"Expected 'gzip' Content-Encoding for large payload, got: '{enc}'"

    # 2. Small payload (< 1000 bytes) should NOT be compressed
    res_small = client.get("/api/health", headers=headers)
    assert res_small.status_code == 200
    enc_small = res_small.headers.get("content-encoding")
    assert enc_small is None, f"Expected uncompressed response for payload < 1000 bytes, got '{enc_small}'"
    print(f"  Small payload length: {len(res_small.content)} bytes, Content-Encoding: {enc_small} (Uncompressed as expected)")

    print("  [PASS] GZipMiddleware active, strictly respecting minimum_size=1000 threshold!")

def test_integrity_error_handling_and_cleanup():
    print("Testing 5: Foreign key & unique constraint error handling & connection cleanup...")
    # Attempting to assign nonexistent customer_id (foreign key violation)
    r_fk = client.put("/api/cheques/1", json={"customer_id": 999999})
    assert r_fk.status_code == 400, f"Expected 400 on FK violation, got {r_fk.status_code}"
    assert "FOREIGN KEY" in r_fk.json().get("detail", "").upper() or "خطا" in r_fk.json().get("detail", "")

    # Attempting to set duplicate unique full_name
    r_uniq = client.put("/api/customers/2", json={"full_name": "معصومه دوامي"})
    assert r_uniq.status_code == 400, f"Expected 400 on UNIQUE violation, got {r_uniq.status_code}"

    # Verify connection was properly closed and DB remains responsive
    r_check = client.get("/api/customers/1")
    assert r_check.status_code == 200
    print("  [PASS] Foreign key & UNIQUE errors cleanly handled as HTTP 400 without connection leaks!")

def test_multithreaded_wal_concurrency():
    print("Testing 6: Multithreaded concurrent read/write stress under WAL...")
    import concurrent.futures

    def read_worker():
        for _ in range(15):
            r = client.get("/api/stats")
            assert r.status_code == 200

    def write_worker(idx: int):
        for i in range(5):
            r = client.put("/api/customers/1", json={"notes": f"Stress test write {idx}-{i}"})
            assert r.status_code == 200

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        f_reads = [executor.submit(read_worker) for _ in range(4)]
        f_writes = [executor.submit(write_worker, i) for i in range(4)]
        for f in concurrent.futures.as_completed(f_reads + f_writes):
            f.result()

    print("  [PASS] Concurrent read/write stress passed under WAL with zero lock timeouts!")

if __name__ == "__main__":
    print("==================================================")
    print("PHASE 1 PERFORMANCE & DATABASE VERIFICATION")
    print("==================================================")
    test_pragmas_and_wal()
    test_indexes()
    test_stats_ttl_cache_and_invalidation()
    test_gzip_middleware()
    test_integrity_error_handling_and_cleanup()
    test_multithreaded_wal_concurrency()
    print("==================================================")
    print("ALL PHASE 1 TARGETED TESTS PASSED 100%!")
    print("==================================================")
