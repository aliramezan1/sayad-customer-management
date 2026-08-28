"""
Pasargad Bank Inquiry Service with Multi-Holder Cascade Engine & Human-Readable Bank Responses
Endpoint: https://sec.bpi.ir/prls/api/v1/inquiry/chequeStatus
Query Params: IdCode, IdType (1 = حقیقی), SayadId
"""
import requests
import urllib3
import logging
import json
import time
from datetime import datetime
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from app.database import get_db

urllib3.disable_warnings()
logger = logging.getLogger("app.services.pasargad")

PASARGAD_API_URL = "https://sec.bpi.ir/prls/api/v1/inquiry/chequeStatus"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Referer": "https://vbank.bpi.ir/",
    "Origin": "https://vbank.bpi.ir",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "fa,en;q=0.9",
    "Connection": "keep-alive"
}

def create_pasargad_session():
    session = requests.Session()
    retry_strategy = Retry(
        total=2,
        backoff_factor=0.3,
        status_forcelist=[429, 500, 502, 503, 504],
        raise_on_status=False
    )
    adapter = HTTPAdapter(
        max_retries=retry_strategy,
        pool_connections=30,
        pool_maxsize=30
    )
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

GLOBAL_SESSION = create_pasargad_session()

def translate_bank_error(status_code: int, raw_text: str) -> str:
    """Translate raw bank responses into human-readable Persian explanations."""
    if not raw_text:
        if status_code == 429:
            return "ترافیک لحظه‌ای بالای درگاه بانک پاسارگاد (لطفاً کمی بعد مجدداً تلاش کنید)"
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
            return "اطلاعات این شناسه صیادی در سامانه بانک یافت نشد"
        if "idcode" in msg_str or "کد ملی" in msg:
            return "کد ملی دارنده با اطلاعات ثبت‌شده چک در بانک مطابقت ندارد"
        if msg:
            return f"پیام بانک: {msg}"
    except Exception:
        pass

    if "404" in str(status_code):
        return "شناسه صیادی در سامانه استعلام بانک یافت نشد"
    return f"پیام درگاه بانک: {raw_text[:120]}"

def query_single_holder(sayadi_id: str, holder_national_id: str, id_type: str = "1", timeout: int = 8) -> dict:
    """Direct query for a single holder national ID."""
    clean_sayadi = str(sayadi_id).strip()
    clean_id_code = str(holder_national_id).strip()

    params = {
        "IdCode": clean_id_code,
        "IdType": id_type,
        "SayadId": clean_sayadi
    }

    try:
        response = GLOBAL_SESSION.get(
            PASARGAD_API_URL,
            params=params,
            headers=HEADERS,
            verify=False,
            timeout=timeout
        )

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
        else:
            human_msg = translate_bank_error(response.status_code, response.text)
            return {
                "status": "not_in_cartable" if response.status_code == 400 else "error",
                "sayadi_id": clean_sayadi,
                "holder_national_id": clean_id_code,
                "message": human_msg,
                "raw_response": response.text
            }

    except Exception as e:
        return {
            "status": "error",
            "sayadi_id": clean_sayadi,
            "holder_national_id": clean_id_code,
            "message": f"خطای ارتباط با سرور بانک: {str(e)}",
            "raw_response": ""
        }

def cascade_pasargad_inquiry(sayadi_id: str, preferred_holder_id: int = None, customer_id: int = None) -> dict:
    """
    ⚡ Multi-Holder Cascade Inquiry Engine across all 9 predefined holders.
    Iterates through holders until the true holder is found, or marks as passed/not in cartable.
    """
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT id, national_id, full_name FROM holders WHERE is_active = 1 ORDER BY id ASC")
    holders = [dict(r) for r in cursor.fetchall()]

    # Fetch cheque info if available
    cursor.execute("SELECT customer_id, cheque_date, holder_id FROM cheques WHERE sayadi_id = ?", (sayadi_id,))
    ch = cursor.fetchone()
    if ch:
        if not customer_id and ch["customer_id"]:
            customer_id = ch["customer_id"]
        if not preferred_holder_id and ch["holder_id"]:
            preferred_holder_id = ch["holder_id"]
        cheque_date = str(ch["cheque_date"] or "")
    else:
        cheque_date = ""

    # Put preferred holder first
    if preferred_holder_id:
        holders.sort(key=lambda h: 0 if h["id"] == preferred_holder_id else 1)

    successful_res = None
    matched_holder = None
    last_error_msg = ""

    for h in holders:
        res = query_single_holder(sayadi_id, h["national_id"])
        
        # If successfully found data
        if res["status"] == "success":
            # If onGoingAmount > 0 or owners info with data, we definitely found the holder!
            successful_res = res
            matched_holder = h
            break
        elif res["status"] == "not_in_cartable":
            last_error_msg = res["message"]
            continue
        else:
            last_error_msg = res["message"]
            continue

    # If found matching holder
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
            sayadi_id, matched_holder["id"], customer_id,
            successful_res["in_transit_count"], successful_res["in_transit_amount"],
            successful_res["cleared_count"], successful_res["cleared_amount"],
            successful_res["bounced_count"], successful_res["bounced_amount"],
            successful_res["raw_response"], "success"
        ))

        # Update holder in cheques table
        cursor.execute("UPDATE cheques SET holder_id = ?, updated_at = datetime('now', 'localtime') WHERE sayadi_id = ?", (matched_holder["id"], sayadi_id))
        conn.commit()

        successful_res["holder_id"] = matched_holder["id"]
        successful_res["holder_name"] = matched_holder["full_name"]
        successful_res["inquiry_id"] = cursor.lastrowid
        conn.close()
        return successful_res

    # Check if due date is passed
    is_passed = False
    today_num = 14030607 # Approximate current year/date comparison
    if cheque_date and len(cheque_date) == 8 and cheque_date.isdigit():
        if int(cheque_date) <= 14030607:
            is_passed = True

    conn.close()

    if is_passed:
        human_status = "چک در کارتابل هیچ‌یک از ۹ دارنده نیست (احتمالاً پاس شده است - سررسید گذشته)"
    else:
        human_status = "چک در کارتابل هیچ‌یک از ۹ دارنده صندوق یافت نشد"

    return {
        "status": "not_in_cartable",
        "sayadi_id": sayadi_id,
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

def record_pasargad_inquiry(sayadi_id: str, holder_id: int = None, customer_id: int = None) -> dict:
    """Wrapper that invokes cascade inquiry."""
    return cascade_pasargad_inquiry(sayadi_id, preferred_holder_id=holder_id, customer_id=customer_id)
