"""
Pasargad Bank Inquiry Service
Endpoint: https://sec.bpi.ir/prls/api/v1/inquiry/chequeStatus
Query Params: IdCode, IdType (1 = حقیقی), SayadId
"""
import requests
import urllib3
import logging
import json
from datetime import datetime
from app.database import get_db

urllib3.disable_warnings()
logger = logging.getLogger("app.services.pasargad")

PASARGAD_API_URL = "https://sec.bpi.ir/prls/api/v1/inquiry/chequeStatus"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Referer": "https://vbank.bpi.ir/",
    "Origin": "https://vbank.bpi.ir",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "fa,en;q=0.9",
}

def query_pasargad_bounced_cheques(sayadi_id: str, holder_national_id: str, id_type: str = "1", timeout: int = 15) -> dict:
    """
    Direct API call to Pasargad Virtual Bank (vBank) for Sayadi Cheque & Bounced status.
    
    Returns parsed dictionary with:
      - onGoingAmount (چک‌های در راه)
      - clearedAmount (چک‌های رفع سوء اثر شده)
      - bouncedAmount (چک‌های برگشتی)
      - owners (لیست صاحبان حساب)
      - raw_response (متن خام پاسخ)
      - status (success / error)
    """
    clean_sayadi = str(sayadi_id).strip()
    clean_id_code = str(holder_national_id).strip()

    params = {
        "IdCode": clean_id_code,
        "IdType": id_type,
        "SayadId": clean_sayadi
    }

    try:
        response = requests.get(
            PASARGAD_API_URL,
            params=params,
            headers=HEADERS,
            verify=False,
            timeout=timeout
        )

        if response.status_code == 200:
            data = response.json()
            
            # Extract key metrics
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
            return {
                "status": "error",
                "sayadi_id": clean_sayadi,
                "holder_national_id": clean_id_code,
                "message": f"خطا از سرور بانک پاسارگاد (کد وضعیت: {response.status_code})",
                "raw_response": response.text
            }

    except Exception as e:
        logger.error(f"Error querying Pasargad API: {e}")
        return {
            "status": "error",
            "sayadi_id": clean_sayadi,
            "holder_national_id": clean_id_code,
            "message": f"خطا در برقراری ارتباط با سامانه پاسارگاد: {str(e)}",
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

    # If customer_id not passed, find from cheques
    if not customer_id:
        cursor.execute("SELECT customer_id FROM cheques WHERE sayadi_id = ?", (sayadi_id,))
        cheque_match = cursor.fetchone()
        if cheque_match and cheque_match["customer_id"]:
            customer_id = cheque_match["customer_id"]

    # Execute inquiry
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

        # Update holder_id on cheque if matching
        cursor.execute("UPDATE cheques SET holder_id = ?, updated_at = datetime('now', 'localtime') WHERE sayadi_id = ?", (holder_id, sayadi_id))

        conn.commit()
        result["inquiry_id"] = cursor.lastrowid
        result["holder_name"] = holder_name

    conn.close()
    return result
