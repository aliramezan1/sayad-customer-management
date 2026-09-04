# -*- coding: utf-8 -*-
"""
Pasargad Bank Inquiry Service with Resilient Cascade Engine, Thread-Safe Rate Limiter, and Smart Logging
"""
import requests
import urllib3
import logging
import json
import time
import threading
from datetime import datetime
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

def _acquire_bank_turn():
    """Enforce minimum spacing between calls and handle global 429 cooldown."""
    global _LAST_REQUEST_TIMESTAMP, _GLOBAL_COOLDOWN_UNTIL
    with _BANK_GATE_LOCK:
        now = time.time()
        if now < _GLOBAL_COOLDOWN_UNTIL:
            wait_sec = round(_GLOBAL_COOLDOWN_UNTIL - now, 2)
            smart_logger.log(
                "WARN", "PASARGAD",
                f"خنک‌سازی ترافیک درگاه بانک: توقف موقت به مدت {wait_sec} ثانیه...",
                details={"cooldown_seconds": wait_sec}
            )
            time.sleep(wait_sec)

        now = time.time()
        elapsed = now - _LAST_REQUEST_TIMESTAMP
        if elapsed < _MIN_REQUEST_INTERVAL:
            time.sleep(_MIN_REQUEST_INTERVAL - elapsed)

        _LAST_REQUEST_TIMESTAMP = time.time()

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
    retry_count: int = 3
) -> dict:
    """
    Direct query with rate limiter, exponential retry, and detailed status breakdown.
    """
    clean_sayadi = str(sayadi_id).strip()
    clean_id_code = str(holder_national_id).strip()

    params = {
        "IdCode": clean_id_code,
        "IdType": id_type,
        "SayadId": clean_sayadi
    }

    for attempt in range(1, retry_count + 1):
        _acquire_bank_turn()
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
                _trigger_global_cooldown(2.5 * attempt)
                smart_logger.log(
                    "WARN", "PASARGAD",
                    f"ترافیک درگاه بانک (۴۲۹) - استراحت و تلاش مجدد مرحله ({attempt}/{retry_count}) برای {clean_id_code}",
                    sayadi_id=clean_sayadi,
                    details={"holder": clean_id_code, "status": 429, "attempt": attempt},
                    duration_ms=duration_ms
                )
                time.sleep(2.0 * attempt)
                continue

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
                time.sleep(1.0 * attempt)
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


def cascade_pasargad_inquiry(sayadi_id: str, preferred_holder_id: int = None, customer_id: int = None, customer_name: str = None) -> dict:
    """
    Intelligent Multi-Holder Cascade Engine:
    1. Prioritizes known holder from database or previous successful inquiries.
    2. Enforces safe interval between queries to prevent 429 rate-limiting.
    3. Handles 429 with backoff and avoids false 'not in cartable' classification.
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
        f"شروع استعلام آبشاری بانک پاسارگاد برای شناسه {clean_sayadi}",
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

    # 1. Fetch cheque info
    cursor.execute("SELECT customer_id, cheque_date, holder_id FROM cheques WHERE sayadi_id = ?", (clean_sayadi,))
    ch = cursor.fetchone()
    cheque_date = ""
    if ch:
        if not customer_id and ch["customer_id"]:
            customer_id = ch["customer_id"]
        if not preferred_holder_id and ch["holder_id"]:
            preferred_holder_id = ch["holder_id"]
        cheque_date = str(ch["cheque_date"] or "")

    # 2. Check previous successful inquiry for this sayadi_id to reuse holder
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

    # Reorder holders so the most likely holder is checked first
    if preferred_holder_id:
        holders.sort(key=lambda h: 0 if h["id"] == preferred_holder_id else 1)

    successful_res = None
    matched_holder = None
    last_error_msg = ""
    had_rate_limit = False

    for idx, h in enumerate(holders):
        res = query_single_holder(clean_sayadi, h["national_id"])
        
        if res["status"] == "success":
            successful_res = res
            matched_holder = h
            break
        elif res["status"] == "rate_limited":
            had_rate_limit = True
            last_error_msg = res.get("message", "")
            # Stop cascading to avoid bombarding other holders while rate-limited
            break
        else:
            last_error_msg = res.get("message", "")
            # Small pacing between holders
            if idx < len(holders) - 1:
                time.sleep(0.35)
            continue

    if successful_res and matched_holder:
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
        conn.close()

        smart_logger.log(
            "SUCCESS", "PASARGAD",
            f"دارنده مطابقت یافت: {matched_holder['full_name']} برای شناسه {clean_sayadi}",
            sayadi_id=clean_sayadi,
            customer_name=customer_name,
            details=successful_res
        )

        return successful_res

    conn.close()

    # If the process was interrupted by rate limit, report rate_limited (NOT not_in_cartable)
    if had_rate_limit:
        return {
            "status": "rate_limited",
            "sayadi_id": clean_sayadi,
            "message": "ترافیک بالای درگاه بانک پاسارگاد – لطفاً کمی بعد مجدداً استعلام بگیرید",
            "raw_response": last_error_msg
        }

    is_passed = False
    if cheque_date and len(cheque_date) == 8 and cheque_date.isdigit():
        if int(cheque_date) <= 14030607:
            is_passed = True

    if is_passed:
        human_status = "چک در کارتابل هیچ‌یک از ۹ دارنده نیست (احتمالاً پاس شده است - سررسید گذشته)"
    else:
        human_status = "چک در کارتابل هیچ‌یک از ۹ دارنده صندوق یافت نشد"
    
    smart_logger.log(
        "WARN", "PASARGAD",
        f"{clean_sayadi}: {human_status}",
        sayadi_id=clean_sayadi,
        customer_name=customer_name or "",
        details={"is_passed": is_passed, "last_error": last_error_msg}
    )

    return {
        "status": "not_in_cartable",
        "sayadi_id": clean_sayadi,
        "is_passed_due": is_passed,
        "in_transit_amount": 0,
        "in_transit_count": 0,
        "cleared_amount": 0,
        "cleared_count": 0,
        "bounced_amount": 0,
        "bounced_count": 0,
        "message": human_status,
        "raw_response": last_error_msg
    }


def record_pasargad_inquiry(sayadi_id: str, holder_id: int = None, customer_id: int = None, customer_name: str = None) -> dict:
    """Wrapper that invokes cascade inquiry."""
    return cascade_pasargad_inquiry(sayadi_id, preferred_holder_id=holder_id, customer_id=customer_id, customer_name=customer_name)


def query_pasargad_bounced_cheques(sayadi_id: str, holder_national_id: str, id_type: str = "1", timeout: int = 8) -> dict:
    """Backward compatibility wrapper."""
    return query_single_holder(sayadi_id, holder_national_id, id_type=id_type, timeout=timeout)
