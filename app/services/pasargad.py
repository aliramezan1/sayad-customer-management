# -*- coding: utf-8 -*-
"""
Pasargad Bank Inquiry Service with Resilient Cascade Engine, Thread-Safe Rate Limiter, and Smart Logging
"""
import requests
import urllib3
import logging
import json
import time
import random
import threading
import concurrent.futures
from datetime import datetime
from typing import Optional
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from app.database import get_db
from app.services.smart_logger import smart_logger

urllib3.disable_warnings()
logger = logging.getLogger("pasargad_inquiry")

PASARGAD_API_URL = "https://sec.bpi.ir/prls/api/v1/inquiry/chequeStatus"
PASARGAD_HEALTH_URL = "https://vbank.bpi.ir"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Referer": "https://vbank.bpi.ir/",
    "Origin": "https://vbank.bpi.ir",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "fa,en;q=0.9",
    "Connection": "keep-alive"
}

# ─────────────────────────────────────────────────────────────
# 🚦 Thread-Safe Rate Limiter & Anti-Flood Gate for Pasargad API
# ─────────────────────────────────────────────────────────────
_BANK_GATE_LOCK = threading.Lock()
_LAST_REQUEST_TIMESTAMP = 0.0
_MIN_REQUEST_INTERVAL = 0.55  # Minimum 550ms between any 2 requests to bank
_GLOBAL_COOLDOWN_UNTIL = 0.0  # Pause all bank traffic across all threads if 429 occurs

def _acquire_bank_turn(cancel_event: threading.Event = None) -> bool:
    """
    Enforce minimum spacing between calls and handle global 429 cooldown.
    Supports cooperative cancellation via cancel_event. Returns False if cancelled.
    """
    global _LAST_REQUEST_TIMESTAMP, _GLOBAL_COOLDOWN_UNTIL
    while True:
        if cancel_event and cancel_event.is_set():
            return False
        with _BANK_GATE_LOCK:
            now = time.time()
            if now < _GLOBAL_COOLDOWN_UNTIL:
                wait_sec = round(_GLOBAL_COOLDOWN_UNTIL - now, 2)
                smart_logger.log(
                    "WARN", "PASARGAD",
                    f"خنک‌سازی ترافیک درگاه بانک: توقف موقت به مدت {wait_sec} ثانیه...",
                    details={"cooldown_seconds": wait_sec}
                )
                sleep_chunk = min(wait_sec, 0.2)
            else:
                elapsed = now - _LAST_REQUEST_TIMESTAMP
                if elapsed < _MIN_REQUEST_INTERVAL:
                    sleep_chunk = _MIN_REQUEST_INTERVAL - elapsed
                else:
                    _LAST_REQUEST_TIMESTAMP = time.time()
                    return True
        time.sleep(sleep_chunk)

def _trigger_global_cooldown(seconds: float = 3.0):
    """Trigger a global cooldown across all threads when 429 is encountered."""
    global _GLOBAL_COOLDOWN_UNTIL
    with _BANK_GATE_LOCK:
        _GLOBAL_COOLDOWN_UNTIL = max(_GLOBAL_COOLDOWN_UNTIL, time.time() + seconds)


def create_pasargad_session():
    session = requests.Session()
    retry_strategy = Retry(
        total=3,
        backoff_factor=0.6,
        status_forcelist=[500, 502, 503, 504],
        raise_on_status=False
    )
    adapter = HTTPAdapter(
        max_retries=retry_strategy,
        pool_connections=20,
        pool_maxsize=20
    )
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

GLOBAL_SESSION = create_pasargad_session()


def translate_bank_error(status_code: int, raw_text: str) -> str:
    """Translate raw bank responses into human-readable Persian explanations."""
    if not raw_text:
        if status_code == 429:
            return "ترافیک لحظه‌ای بالای درگاه بانک پاسارگاد – سیستم خودکار تلاش مجدد خواهد کرد"
        elif status_code >= 500:
            return "اختلال موقت در سرورهای مرکزی بانک پاسارگاد"
        return f"پاسخ ناموفق از سرور بانک (کد وضعیت: {status_code})"
    
    try:
        data = json.loads(raw_text)
        msg = data.get("message") or data.get("error") or data.get("title") or ""
        msg_str = str(msg).lower()

        if "cartable" in msg_str or "کارتابل" in msg:
            return "چک در کارتابل این دارنده یافت نشد (احتمالاً نزد دارنده دیگر است یا پاس شده است)"
        if "not found" in msg_str or "یافت نشد" in msg:
            return "اطلاعات این شناسه صیادی در سامانه استعلام بانک یافت نشد"
        if "idcode" in msg_str or "کد ملی" in msg:
            return "کد ملی دارنده با اطلاعات ثبت‌شده چک در درگاه بانک مطابقت ندارد"
        if msg:
            return f"پیام بانک: {msg}"
    except Exception:
        pass

    if "404" in str(status_code):
        return "شناسه صیادی در سامانه استعلام بانک یافت نشد"
    return f"پیام درگاه بانک: {raw_text[:140]}"


def check_pasargad_health() -> dict:
    """Live health and latency check for Pasargad vBank portal."""
    t1 = time.time()
    try:
        resp = GLOBAL_SESSION.head(PASARGAD_HEALTH_URL, headers=HEADERS, verify=False, timeout=4)
        duration = round((time.time() - t1) * 1000, 2)
        is_on = resp.status_code < 500
        result = {
            "status": "online" if is_on else "degraded",
            "code": resp.status_code,
            "latency_ms": duration,
            "message": "درگاه بانک پاسارگاد فعال و پاسخگوست"
        }
        smart_logger.log("INFO", "PASARGAD", f"پایش سلامت درگاه بانک پاسارگاد: Online ({duration}ms)", details=result, duration_ms=duration)
        return result
    except Exception as e:
        duration = round((time.time() - t1) * 1000, 2)
        result = {
            "status": "offline",
            "code": 0,
            "latency_ms": duration,
            "message": f"خطای ارتباط با درگاه بانک: {str(e)}"
        }
        smart_logger.log("WARN", "PASARGAD", f"خطا در ارتباط با درگاه بانک پاسارگاد: {str(e)}", details=result, duration_ms=duration)
        return result


def query_single_holder(
    sayadi_id: str,
    holder_national_id: str,
    id_type: str = "1",
    timeout: int = 8,
    retry_count: int = 3,
    cancel_event: threading.Event = None
) -> dict:
    """
    Direct query with rate limiter, exponential retry with random jitter, and detailed status breakdown.
    Supports cooperative cancellation via cancel_event.
    """
    clean_sayadi = str(sayadi_id).strip()
    clean_id_code = str(holder_national_id).strip()

    params = {
        "IdCode": clean_id_code,
        "IdType": id_type,
        "SayadId": clean_sayadi
    }

    for attempt in range(1, retry_count + 1):
        if cancel_event and cancel_event.is_set():
            return {
                "status": "cancelled",
                "sayadi_id": clean_sayadi,
                "holder_national_id": clean_id_code,
                "message": "عملیات استعلام متوقف شد."
            }

        got_turn = _acquire_bank_turn(cancel_event=cancel_event)
        if not got_turn:
            return {
                "status": "cancelled",
                "sayadi_id": clean_sayadi,
                "holder_national_id": clean_id_code,
                "message": "عملیات استعلام متوقف شد."
            }

        t_start = time.time()
        try:
            response = GLOBAL_SESSION.get(
                PASARGAD_API_URL,
                params=params,
                headers=HEADERS,
                verify=False,
                timeout=timeout
            )
            duration_ms = (time.time() - t_start) * 1000

            if response.status_code == 200:
                data = response.json()
                on_going = float(data.get("onGoingAmount", 0) or 0)
                blocked = float(data.get("blocked", 0) or 0)
                owners = data.get("ownersInfo", [])

                total_bounced = 0.0
                total_cleared = 0.0
                bounced_count = 0
                cleared_count = 0

                for owner in owners:
                    b_amt = float(owner.get("bouncedAmount", 0) or 0)
                    c_amt = float(owner.get("clearedAmount", 0) or 0)
                    total_bounced += b_amt
                    total_cleared += c_amt
                    if b_amt > 0:
                        bounced_count += 1
                    if c_amt > 0:
                        cleared_count += 1

                smart_logger.log(
                    "SUCCESS", "PASARGAD",
                    f"استعلام موفق برای کدملی {clean_id_code} (مبلغ در راه: {on_going:,.0f} ریال) | شناسه صیادی: {clean_sayadi}",
                    sayadi_id=clean_sayadi,
                    details={"in_transit_amount": on_going, "bounced_amount": total_bounced, "cleared_amount": total_cleared},
                    duration_ms=duration_ms
                )

                return {
                    "status": "success",
                    "sayadi_id": clean_sayadi,
                    "holder_national_id": clean_id_code,
                    "in_transit_amount": on_going,
                    "in_transit_count": 1 if on_going > 0 else 0,
                    "cleared_amount": total_cleared,
                    "cleared_count": cleared_count,
                    "bounced_amount": total_bounced,
                    "bounced_count": bounced_count,
                    "blocked": blocked,
                    "owners_info": owners,
                    "raw_response": response.text,
                    "message": "استعلام با موفقیت دریافت شد."
                }

            elif response.status_code == 429:
                # Exponential Backoff with Random Jitter
                wait_time = round((1.2 ** attempt) + random.uniform(0.2, 0.6), 2)
                _trigger_global_cooldown(wait_time)
                smart_logger.log(
                    "WARN", "PASARGAD",
                    f"ترافیک درگاه بانک (۴۲۹) - اعمال خنک‌کننده و Jitter تصادفی ({wait_time} ثانیه) - تلاش مجدد ({attempt}/{retry_count}) برای {clean_id_code}",
                    sayadi_id=clean_sayadi,
                    details={"holder": clean_id_code, "status": 429, "attempt": attempt, "wait_time": wait_time},
                    duration_ms=duration_ms
                )
                if attempt < retry_count:
                    sleep_end = time.time() + wait_time
                    while time.time() < sleep_end:
                        if cancel_event and cancel_event.is_set():
                            return {
                                "status": "cancelled",
                                "sayadi_id": clean_sayadi,
                                "holder_national_id": clean_id_code,
                                "message": "عملیات استعلام متوقف شد."
                            }
                        time.sleep(min(0.2, max(0.01, sleep_end - time.time())))
                    continue
                break

            else:
                raw_txt = response.text
                human_msg = translate_bank_error(response.status_code, raw_txt)
                is_not_in_cartable = (
                    response.status_code == 400 or
                    "524" in raw_txt or
                    "cartable" in raw_txt.lower() or
                    "کارتابل" in raw_txt
                )

                smart_logger.log(
                    "DEBUG" if is_not_in_cartable else "WARN",
                    "PASARGAD",
                    f"پاسخ بانک: {human_msg} (کدملی {clean_id_code})",
                    sayadi_id=clean_sayadi,
                    details={"code": response.status_code, "holder": clean_id_code, 'resp': raw_txt[:200]},
                    duration_ms=duration_ms
                )

                return {
                    "status": "not_in_cartable" if is_not_in_cartable else "error",
                    "sayadi_id": clean_sayadi,
                    "holder_national_id": clean_id_code,
                    "message": human_msg,
                    "raw_response": raw_txt
                }

        except Exception as e:
            duration_ms = (time.time() - t_start) * 1000
            if attempt < retry_count:
                retry_pause = round(1.0 * attempt + random.uniform(0.1, 0.4), 2)
                sleep_end = time.time() + retry_pause
                while time.time() < sleep_end:
                    if cancel_event and cancel_event.is_set():
                        return {
                            "status": "cancelled",
                            "sayadi_id": clean_sayadi,
                            "holder_national_id": clean_id_code,
                            "message": "عملیات استعلام متوقف شد."
                        }
                    time.sleep(min(0.2, max(0.01, sleep_end - time.time())))
                continue

            smart_logger.log(
                "ERROR", "PASARGAD",
                f"خطای ارتباط با درگاه بانک {clean_id_code}: {str(e)}",
                sayadi_id=clean_sayadi,
                details={"error": str(e), "holder": clean_id_code},
                duration_ms=duration_ms
            )

            return {
                "status": "error",
                "sayadi_id": clean_sayadi,
                "holder_national_id": clean_id_code,
                "message": f"خطای ارتباط با درگاه بانک: {str(e)}",
                "raw_response": ""
            }

    # If loop exited due to repeated 429
    return {
        "status": "rate_limited",
        "sayadi_id": clean_sayadi,
        "holder_national_id": clean_id_code,
        "message": "ترافیک بالای درگاه بانک پاسارگاد (لطفاً چند ثانیه دیگر مجدداً تلاش فرمایید)",
        "raw_response": ""
    }


def jalali_to_gregorian(jy: int, jm: int, jd: int):
    """Convert Jalali (Solar Hijri) date to Gregorian date tuple (year, month, day)."""
    jy = jy + 1595
    days = -355668 + (365 * jy) + ((jy // 33) * 8) + (((jy % 33) + 3) // 4) + jd + ((jm - 1) * 31 if jm < 7 else ((jm - 7) * 30) + 186)
    gy = 400 * (days // 146097)
    days %= 146097
    if days > 36524:
        days -= 1
        gy += 100 * (days // 36524)
        days %= 36524
        if days >= 365:
            days += 1
    gy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        gy += (days - 1) // 365
        days = (days - 1) % 365
    gd = days + 1
    sal_a = [0, 31, 29 if ((gy % 4 == 0 and gy % 100 != 0) or gy % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    gm = 0
    while gm < 13 and gd > sal_a[gm]:
        gd -= sal_a[gm]
        gm += 1
    return gy, gm, gd

def calculate_days_until_due(cheque_date_str: str) -> Optional[int]:
    """Calculate days until cheque maturity date (negative means past due)."""
    if not cheque_date_str or len(cheque_date_str) != 8 or not cheque_date_str.isdigit():
        return None
    try:
        from datetime import date
        jy = int(cheque_date_str[:4])
        jm = int(cheque_date_str[4:6])
        jd = int(cheque_date_str[6:8])
        gy, gm, gd = jalali_to_gregorian(jy, jm, jd)
        today = datetime.now().date()
        due_date = date(gy, gm, gd)
        return (due_date - today).days
    except Exception:
        return None


def cascade_pasargad_inquiry(sayadi_id: str, preferred_holder_id: int = None, customer_id: int = None, customer_name: str = None) -> dict:
    """
    Pareto 2-Stage Cascade Inquiry Engine:
    Stage 1 (Fast Pareto Query):
        Checks the primary holder (holding 92.5% of checks) or preferred_holder first.
        If successful, returns within ~600ms without touching the remaining 8 holders.
    Stage 2 (Parallel Cartable Pool):
        If Stage 1 returns not_in_cartable, queries the other 8 holders concurrently using
        ThreadPoolExecutor(max_workers=3) governed by _acquire_bank_turn().
        On first match, immediately cancels remaining tasks and persists result.
    Resilience:
        100% preserves previous valid historical data upon not_in_cartable/error to prevent zeroing out.
    """
    clean_sayadi = str(sayadi_id).strip()
    if not clean_sayadi or len(clean_sayadi) != 16:
        return {
            "status": "error",
            "sayadi_id": clean_sayadi,
            "message": f"شناسه صیادی باید ۱۶ رقم باشد (داده شده: {clean_sayadi})"
        }

    smart_logger.log(
        "INFO", "PASARGAD",
        f"شروع استعلام آبشاری پارتو بانک پاسارگاد برای شناسه {clean_sayadi}",
        sayadi_id=clean_sayadi,
        customer_name=customer_name or ""
    )

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT id, national_id, full_name FROM holders WHERE is_active = 1 ORDER BY id ASC")
    holders = [dict(r) for r in cursor.fetchall()]
    if not holders:
        conn.close()
        return {
            "status": "error",
            "sayadi_id": clean_sayadi,
            "message": "هیچ دارنده فعالی در سیستم تعریف نشده است."
        }

    # 1. Fetch cheque info (authoritative data from cheques table)
    cursor.execute("SELECT customer_id, cheque_date, holder_id FROM cheques WHERE sayadi_id = ?", (clean_sayadi,))
    ch = cursor.fetchone()
    cheque_date = ""
    if ch:
        if ch["customer_id"]:
            customer_id = ch["customer_id"]
        if not preferred_holder_id and ch["holder_id"]:
            preferred_holder_id = ch["holder_id"]
        cheque_date = str(ch["cheque_date"] or "")

    # 2. Check previous successful inquiry for this sayadi_id to reuse known holder
    if not preferred_holder_id:
        cursor.execute("SELECT holder_id FROM pasargad_inquiries WHERE sayadi_id = ? AND status = 'success' ORDER BY id DESC LIMIT 1", (clean_sayadi,))
        prev = cursor.fetchone()
        if prev and prev["holder_id"]:
            preferred_holder_id = prev["holder_id"]

    if customer_id and not customer_name:
        cursor.execute("SELECT full_name FROM customers WHERE id = ?", (customer_id,))
        cust = cursor.fetchone()
        if cust:
            customer_name = cust["full_name"]

    # Select Stage 1 Pareto Primary Holder (holder_id=1 holds 92.5% of cheques)
    stage1_holder = None
    if preferred_holder_id:
        stage1_holder = next((h for h in holders if h["id"] == preferred_holder_id), None)
    if not stage1_holder:
        stage1_holder = next((h for h in holders if h["id"] == 1), holders[0])

    remaining_holders = [h for h in holders if h["id"] != stage1_holder["id"]]

    # ── STAGE 1: Fast Pareto Query ────────────────────────────────
    smart_logger.log(
        "INFO", "PASARGAD",
        f"مرحله ۱ پارتو (Fast Pareto Query): استعلام اولویت‌دار شناسه {clean_sayadi} با دارنده «{stage1_holder['full_name']}» (هولدر {stage1_holder['id']})...",
        sayadi_id=clean_sayadi,
        customer_name=customer_name or ""
    )
    t_p1_start = time.time()
    res1 = query_single_holder(clean_sayadi, stage1_holder["national_id"])
    duration_p1 = (time.time() - t_p1_start) * 1000

    if res1["status"] == "success":
        # Stage 1 Pareto Hit! Fast Path: ~600ms
        if not customer_id:
            owners_list = res1.get("owners_info") or []
            if owners_list and isinstance(owners_list, list) and len(owners_list) > 0:
                first_owner = owners_list[0]
                id_code = str(first_owner.get("idCode") or "").strip()
                if id_code:
                    cursor.execute("SELECT id, full_name FROM customers WHERE national_id = ? LIMIT 1", (id_code,))
                    cust_match = cursor.fetchone()
                    if cust_match:
                        customer_id = cust_match["id"]
                        customer_name = cust_match["full_name"]

        cursor.execute("""
        INSERT INTO pasargad_inquiries (
            sayadi_id, holder_id, customer_id,
            in_transit_count, in_transit_amount,
            cleared_count, cleared_amount,
            bounced_count, bounced_amount,
            raw_response, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            clean_sayadi, stage1_holder["id"], customer_id,
            res1["in_transit_count"], res1["in_transit_amount"],
            res1["cleared_count"], res1["cleared_amount"],
            res1["bounced_count"], res1["bounced_amount"],
            res1["raw_response"], "success"
        ))

        cursor.execute("UPDATE cheques SET holder_id = ?, updated_at = datetime('now', 'localtime') WHERE sayadi_id = ?", (stage1_holder["id"], clean_sayadi))
        conn.commit()

        res1["holder_id"] = stage1_holder["id"]
        res1["holder_name"] = stage1_holder["full_name"]
        res1["inquiry_id"] = cursor.lastrowid
        res1["cascade_stage"] = 1
        res1["preserved_from_history"] = False
        conn.close()

        smart_logger.log(
            "SUCCESS", "PASARGAD",
            f"مرحله ۱ پارتو موفق (Fast Pareto Query): دارنده «{stage1_holder['full_name']}» در {duration_p1:.0f} میلی‌ثانیه یافت شد | شناسه {clean_sayadi}",
            sayadi_id=clean_sayadi,
            customer_name=customer_name or "",
            duration_ms=duration_p1,
            details={"stage": 1, "holder_id": stage1_holder["id"], "in_transit_amount": res1["in_transit_amount"]}
        )
        return res1

    # If Stage 1 encountered 429 rate-limiting, avoid cascading to 8 other holders immediately
    successful_res = None
    matched_holder = None
    had_rate_limit = False
    all_errors = False
    last_error_msg = res1.get("message", "")

    if res1["status"] == "rate_limited":
        had_rate_limit = True
    else:
        # ── STAGE 2: Parallel Cartable Pool ───────────────────────────
        smart_logger.log(
            "INFO", "PASARGAD",
            f"مرحله ۲ پارتو (Parallel Cartable Pool): چک در کارتابل «{stage1_holder['full_name']}» نبود ({res1.get('message', '')}). بررسی موازی {len(remaining_holders)} دارنده دیگر با ThreadPoolExecutor(max_workers=3)...",
            sayadi_id=clean_sayadi,
            customer_name=customer_name or ""
        )

        cancel_event = threading.Event()
        all_errors = (res1["status"] == "error")

        def _pool_worker(holder_info):
            if cancel_event.is_set():
                return None
            w_res = query_single_holder(
                clean_sayadi,
                holder_info["national_id"],
                cancel_event=cancel_event
            )
            return (holder_info, w_res)

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            future_to_holder = {executor.submit(_pool_worker, h): h for h in remaining_holders}

            for future in concurrent.futures.as_completed(future_to_holder):
                if cancel_event.is_set():
                    break
                try:
                    result_tuple = future.result()
                    if not result_tuple:
                        continue
                    h, res = result_tuple

                    if res.get("status") == "success":
                        successful_res = res
                        matched_holder = h
                        cancel_event.set()
                        # Cancel remaining queued futures
                        for f in future_to_holder:
                            f.cancel()
                        break
                    elif res.get("status") == "rate_limited":
                        had_rate_limit = True
                        last_error_msg = res.get("message", "")
                        all_errors = False
                    elif res.get("status") == "not_in_cartable":
                        all_errors = False
                        last_error_msg = res.get("message", "")
                    elif res.get("status") != "cancelled":
                        last_error_msg = res.get("message", "")
                except Exception as exc:
                    last_error_msg = str(exc)

    if successful_res and matched_holder:
        # Stage 2 parallel query matched a holder!
        if not customer_id:
            owners_list = successful_res.get("owners_info") or []
            if owners_list and isinstance(owners_list, list) and len(owners_list) > 0:
                first_owner = owners_list[0]
                id_code = str(first_owner.get("idCode") or "").strip()
                if id_code:
                    cursor.execute("SELECT id, full_name FROM customers WHERE national_id = ? LIMIT 1", (id_code,))
                    cust_match = cursor.fetchone()
                    if cust_match:
                        customer_id = cust_match["id"]
                        customer_name = cust_match["full_name"]

        cursor.execute("""
        INSERT INTO pasargad_inquiries (
            sayadi_id, holder_id, customer_id,
            in_transit_count, in_transit_amount,
            cleared_count, cleared_amount,
            bounced_count, bounced_amount,
            raw_response, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            clean_sayadi, matched_holder["id"], customer_id,
            successful_res["in_transit_count"], successful_res["in_transit_amount"],
            successful_res["cleared_count"], successful_res["cleared_amount"],
            successful_res["bounced_count"], successful_res["bounced_amount"],
            successful_res["raw_response"], "success"
        ))

        cursor.execute("UPDATE cheques SET holder_id = ?, updated_at = datetime('now', 'localtime') WHERE sayadi_id = ?", (matched_holder["id"], clean_sayadi))
        conn.commit()

        successful_res["holder_id"] = matched_holder["id"]
        successful_res["holder_name"] = matched_holder["full_name"]
        successful_res["inquiry_id"] = cursor.lastrowid
        successful_res["cascade_stage"] = 2
        successful_res["preserved_from_history"] = False
        conn.close()

        smart_logger.log(
            "SUCCESS", "PASARGAD",
            f"پایان مرحله ۲ پارتو: دارنده مطابقت یافت: «{matched_holder['full_name']}» برای شناسه {clean_sayadi}",
            sayadi_id=clean_sayadi,
            customer_name=customer_name or "",
            details={"stage": 2, "holder_id": matched_holder["id"], "in_transit_amount": successful_res["in_transit_amount"]}
        )
        return successful_res

    # ── 100% Historical Data Preservation Fallback ───────────────────
    cursor.execute("""
        SELECT * FROM pasargad_inquiries 
        WHERE sayadi_id = ? AND (status = 'success' OR in_transit_amount > 0 OR cleared_amount > 0 OR bounced_amount > 0)
        ORDER BY id DESC LIMIT 1
    """, (clean_sayadi,))
    prev_success = cursor.fetchone()
    conn.close()

    prev_in_transit = float(prev_success["in_transit_amount"] or 0) if prev_success else 0.0
    prev_in_transit_cnt = int(prev_success["in_transit_count"] or 0) if prev_success else 0
    prev_cleared = float(prev_success["cleared_amount"] or 0) if prev_success else 0.0
    prev_cleared_cnt = int(prev_success["cleared_count"] or 0) if prev_success else 0
    prev_bounced = float(prev_success["bounced_amount"] or 0) if prev_success else 0.0
    prev_bounced_cnt = int(prev_success["bounced_count"] or 0) if prev_success else 0
    prev_holder_id = prev_success["holder_id"] if prev_success else (stage1_holder["id"] if stage1_holder else 1)
    has_history = bool(prev_success)

    # If rate limited
    if had_rate_limit:
        smart_logger.log(
            "WARN", "PASARGAD",
            f"استعلام شناسه {clean_sayadi} به دلیل ترافیک درگاه بانک (۴۲۹) متوقف شد" + (" (داده‌های پیشین حفظ شد)" if has_history else ""),
            sayadi_id=clean_sayadi,
            customer_name=customer_name or "",
            details={"preserved": has_history, "last_error": last_error_msg}
        )
        return {
            "status": "rate_limited",
            "sayadi_id": clean_sayadi,
            "holder_id": prev_holder_id,
            "customer_id": customer_id,
            "in_transit_amount": prev_in_transit,
            "in_transit_count": prev_in_transit_cnt,
            "cleared_amount": prev_cleared,
            "cleared_count": prev_cleared_cnt,
            "bounced_amount": prev_bounced,
            "bounced_count": prev_bounced_cnt,
            "preserved_from_history": has_history,
            "cascade_stage": 0,
            "message": "ترافیک بالای درگاه بانک پاسارگاد – لطفاً کمی بعد مجدداً استعلام بگیرید" + (" (اطلاعات معتبر قبلی حفظ شد)" if has_history else ""),
            "raw_response": last_error_msg
        }

    # If all queries encountered connection/network error
    if all_errors:
        err_msg = f"خطای ارتباط با درگاه بانک پاسارگاد ({last_error_msg or 'عدم پاسخگویی'})"
        if has_history:
            err_msg += " (اطلاعات آخرین استعلام موفق حفظ شد)"
        smart_logger.log(
            "WARN", "PASARGAD",
            f"{clean_sayadi}: {err_msg}",
            sayadi_id=clean_sayadi,
            customer_name=customer_name or "",
            details={"last_error": last_error_msg, "preserved": has_history}
        )
        return {
            "status": "error",
            "sayadi_id": clean_sayadi,
            "holder_id": prev_holder_id,
            "customer_id": customer_id,
            "in_transit_amount": prev_in_transit,
            "in_transit_count": prev_in_transit_cnt,
            "cleared_amount": prev_cleared,
            "cleared_count": prev_cleared_cnt,
            "bounced_amount": prev_bounced,
            "bounced_count": prev_bounced_cnt,
            "preserved_from_history": has_history,
            "cascade_stage": 0,
            "message": err_msg,
            "raw_response": last_error_msg
        }

    # Check if passed maturity date
    is_passed = False
    if cheque_date:
        days_due = calculate_days_until_due(cheque_date)
        if days_due is not None and days_due < 0:
            is_passed = True

    if is_passed:
        human_status = f"چک در کارتابل هیچ‌یک از {len(holders)} دارنده نیست (احتمالاً پاس شده است - سررسید گذشته)"
    else:
        human_status = f"چک در کارتابل هیچ‌یک از {len(holders)} دارنده صندوق یافت نشد"
    
    if has_history:
        human_status += " (اطلاعات آخرین استعلام موفق حفظ شد)"

    smart_logger.log(
        "WARN", "PASARGAD",
        f"{clean_sayadi}: {human_status}",
        sayadi_id=clean_sayadi,
        customer_name=customer_name or "",
        details={"is_passed": is_passed, "last_error": last_error_msg, "preserved": has_history}
    )

    return {
        "status": "not_in_cartable",
        "sayadi_id": clean_sayadi,
        "is_passed_due": is_passed,
        "holder_id": prev_holder_id,
        "customer_id": customer_id,
        "in_transit_amount": prev_in_transit,
        "in_transit_count": prev_in_transit_cnt,
        "cleared_amount": prev_cleared,
        "cleared_count": prev_cleared_cnt,
        "bounced_amount": prev_bounced,
        "bounced_count": prev_bounced_cnt,
        "preserved_from_history": has_history,
        "cascade_stage": 0,
        "message": human_status,
        "raw_response": last_error_msg
    }


def record_pasargad_inquiry(sayadi_id: str, holder_id: int = None, customer_id: int = None, customer_name: str = None) -> dict:
    """Wrapper that invokes cascade inquiry."""
    return cascade_pasargad_inquiry(sayadi_id, preferred_holder_id=holder_id, customer_id=customer_id, customer_name=customer_name)


def query_pasargad_bounced_cheques(sayadi_id: str, holder_national_id: str, id_type: str = "1", timeout: int = 8) -> dict:
    """Backward compatibility wrapper."""
    return query_single_holder(sayadi_id, holder_national_id, id_type=id_type, timeout=timeout)
