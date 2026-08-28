"""
Pasargad Bank Inquiry Service with High-Resilience Connection Pooling & Retry Strategy
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

# Create a robust session with connection pooling and retry adapter
def create_pasargad_session():
    session = requests.Session()
    retry_strategy = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
        raise_on_status=False
    )
    adapter = HTTPAdapter(
        max_retries=retry_strategy,
        pool_connections=25,
        pool_maxsize=25
    )
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

GLOBAL_SESSION = create_pasargad_session()

def query_pasargad_bounced_cheques(sayadi_id: str, holder_national_id: str, id_type: str = "1", timeout: int = 10) -> dict:
    """
    Direct API call to Pasargad Virtual Bank (vBank) for Sayadi Cheque & Bounced status.
    With intelligent retry and connection pooling.
    """
    clean_sayadi = str(sayadi_id).strip()
    clean_id_code = str(holder_national_id).strip()

    params = {
        "IdCode": clean_id_code,
        "IdType": id_type,
        "SayadId": clean_sayadi
    }

    # Attempt with global session, fallback to fresh session if needed
    for attempt in range(1, 3):
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
            elif response.status_code in [429, 503]:
                # Bank rate limit hit, backoff and retry
                time.sleep(0.8 * attempt)
                continue
            else:
                return {
                    "status": "error",
                    "sayadi_id": clean_sayadi,
                    "holder_national_id": clean_id_code,
                    "message": f"پاسخ سرور بانک پاسارگاد (کد وضعیت: {response.status_code})",
                    "raw_response": response.text
                }

        except Exception as e:
            logger.warning(f"Attempt {attempt} failed for Sayadi {clean_sayadi}: {e}")
            if attempt < 2:
                time.sleep(0.5)
                continue
            return {
                "status": "error",
                "sayadi_id": clean_sayadi,
                "holder_national_id": clean_id_code,
                "message": f"ترافیک بالای سرور بانک یا تایم‌اوت ارتباط: {str(e)}",
                "raw_response": ""
            }

    return {
        "status": "error",
        "sayadi_id": clean_sayadi,
        "holder_national_id": clean_id_code,
        "message": "عدم پاسخگویی سرور بانک پس از تلاش‌های مکرر.",
        "raw_response": ""
    }

def record_pasargad_inquiry(sayadi_id: str, holder_id: int, customer_id: int = None) -> dict:
    """
    Perform Pasargad inquiry and record the result into database.
    """
    conn = get_db()
    cursor = conn.cursor()

    # Get holder national ID
    cursor.execute("SELECT national_id, full_name FROM holders WHERE id = ?", (holder_id,))
    holder = cursor.fetchone()
    if not holder:
        conn.close()
        return {"status": "error", "message": "هولدر دارنده چک نامعتبر است."}

    holder_national_id = holder["national_id"]
    holder_name = holder["full_name"]

    if not customer_id:
        cursor.execute("SELECT customer_id FROM cheques WHERE sayadi_id = ?", (sayadi_id,))
        cheque_match = cursor.fetchone()
        if cheque_match and cheque_match["customer_id"]:
            customer_id = cheque_match["customer_id"]

    result = query_pasargad_bounced_cheques(sayadi_id, holder_national_id)

    if result["status"] == "success":
        cursor.execute("""
        INSERT INTO pasargad_inquiries (
            sayadi_id, holder_id, customer_id,
            in_transit_count, in_transit_amount,
            cleared_count, cleared_amount,
            bounced_count, bounced_amount,
            raw_response, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            sayadi_id, holder_id, customer_id,
            result["in_transit_count"], result["in_transit_amount"],
            result["cleared_count"], result["cleared_amount"],
            result["bounced_count"], result["bounced_amount"],
            result["raw_response"], "success"
        ))

        cursor.execute("UPDATE cheques SET holder_id = ?, updated_at = datetime('now', 'localtime') WHERE sayadi_id = ?", (holder_id, sayadi_id))
        conn.commit()
        result["inquiry_id"] = cursor.lastrowid
        result["holder_name"] = holder_name

    conn.close()
    return result
