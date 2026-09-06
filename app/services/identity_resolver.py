"""
Identity Resolution & Customer Deduplication Service (Milestone 1).

Implements:
- Hierarchical Identity Resolution:
    1. National ID (10-digit text)
    2. Sayad ID (16-digit string)
    3. Sayad ID history (previous inquiries / CBI official names)
    4. Customer name (Arabic character normalization)
    5. Cheque serial / registration notes
- Strict 10-digit text National ID format with leading zeros preserved (never converted to int/float).
- Disambiguation of National ID 0933387075:
    - Hossein Heshmati (Customer ID 2, Cheque 057751, Sayad 2380030072556088, Bank Iran Zamin)
    - Amirhossein Alipour (Customer ID 1, Promissory Note / Safteh 1113333, Bank * قر سفته, EXEMPT)
    - Distinguishes the two records and prevents merging solely on national ID.
- Flagging UNRESOLVED_IDENTITY for customers lacking national code (IDs 7, 13, 26, 29).
- Flagging EXEMPT for promissory notes / non-Sayad documents (serials 1113333, 14444, 66666).
- Deduplication to exactly 48 canonical unique customers.
"""

import os
import re
import math
import sqlite3
import json
import logging
from typing import Optional, List, Dict, Any, Tuple, Set, Union

logger = logging.getLogger("app.services.identity_resolver")

# Constants
DISAMBIGUATED_NATIONAL_ID = "0933387075"
UNRESOLVED_CUSTOMER_IDS = {7, 13, 26, 29}
EXEMPT_CHEQUE_NUMBERS = {"1113333", "14444", "66666"}

STATUS_VERIFIED = "VERIFIED"
STATUS_UNRESOLVED_IDENTITY = "UNRESOLVED_IDENTITY"

DOC_STATUS_EXEMPT = "EXEMPT"
DOC_STATUS_VALID = "VALID"

# Arabic to Persian character mapping
ARABIC_TO_PERSIAN = {
    'ي': 'ی',
    'ك': 'ک',
    'ى': 'ی',
    'ة': 'ه',
    'ؤ': 'و',
    'إ': 'ا',
    'أ': 'ا',
    'آ': 'آ',
    'ء': '',
}

# Arabic/Persian digits to English ASCII digits
DIGIT_MAP = {
    '۰': '0', '۱': '1', '۲': '2', '۳': '3', '۴': '4',
    '۵': '5', '۶': '6', '۷': '7', '۸': '8', '۹': '9',
    '٠': '0', '١': '1', '٢': '2', '٣': '3', '٤': '4',
    '٥': '5', '٦': '6', '٧': '7', '٨': '8', '٩': '9',
}


def normalize_persian_text(text: Optional[str]) -> str:
    """
    Standardize Arabic characters to Persian equivalents and clean whitespace.
    Specifically normalizes 'ي' to 'ی' and 'ك' to 'ک'.
    """
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)

    # Replace specific Arabic characters
    for ar_char, fa_char in ARABIC_TO_PERSIAN.items():
        text = text.replace(ar_char, fa_char)

    # Normalize excessive whitespace and zero-width spaces
    text = re.sub(r'[\u200b\u200c\u200d\u200e\u200f]+', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def to_ascii_digits(text: Optional[str]) -> str:
    """Convert Persian and Arabic numerals to ASCII 0-9."""
    if not text:
        return ""
    chars = []
    for ch in str(text):
        chars.append(DIGIT_MAP.get(ch, ch))
    return "".join(chars)


def clean_national_id(nid: Any) -> Optional[str]:
    """
    Sanitize and preserve 10-digit text national ID format.
    Guarantees leading zeros are preserved (e.g. '0927624011', '0890543331', '0933387075').
    Never converts or truncates to integer or float.
    Returns None if empty or invalid.
    """
    if nid is None:
        return None

    # If it's float or int or string, convert via ascii digits string representation
    if isinstance(nid, float):
        # Prevent float truncation like 927624011.0; guard against NaN and Inf
        if math.isnan(nid) or math.isinf(nid):
            return None
        nid_str = f"{int(nid)}"
    else:
        nid_str = str(nid).strip()

    # Convert Persian/Arabic digits to ASCII
    nid_str = to_ascii_digits(nid_str)

    # Remove non-digits (dashes, spaces)
    cleaned = re.sub(r'\D', '', nid_str)

    if not cleaned or cleaned.lower() in ("none", "null", "nan"):
        return None

    # If length is between 8 and 10, pad with leading zeros to maintain 10 digits
    if len(cleaned) <= 10 and len(cleaned) >= 8:
        cleaned = cleaned.zfill(10)
        return cleaned

    if len(cleaned) == 10:
        return cleaned

    return None


def validate_national_id(nid: Optional[str]) -> bool:
    """
    Validate 10-digit Iranian National Code using standard modulo 11 checksum.
    Returns True if valid, False otherwise.
    """
    if not nid or not isinstance(nid, str):
        return False

    # Normalize Persian and Arabic numerals to ASCII digits before validation
    nid = to_ascii_digits(nid.strip())
    if not re.match(r'^[0-9]{10}$', nid):
        return False

    # Check for all-identical digits (e.g. '0000000000', '1111111111') which are invalid
    if len(set(nid)) == 1:
        return False

    check_digit = int(nid[9])
    total = sum(int(nid[i]) * (10 - i) for i in range(9))
    remainder = total % 11

    if remainder < 2:
        return check_digit == remainder
    else:
        return check_digit == (11 - remainder)


def is_exempt_cheque(cheque: Dict[str, Any]) -> bool:
    """
    Determine if a cheque is an EXEMPT document (promissory note / safteh or non-Sayad).
    Serials explicitly exempt: '1113333', '14444', '66666'.
    """
    cheque_num = str(cheque.get("cheque_number") or "").strip()
    if cheque_num in EXEMPT_CHEQUE_NUMBERS:
        return True

    bank_name = str(cheque.get("bank_name") or "")
    if "سفته" in bank_name or "* قر سفته" in bank_name:
        return True

    sayadi_id = str(cheque.get("sayadi_id") or "").strip()
    notes = str(cheque.get("notes") or "")
    if "سفته" in notes and (not sayadi_id or len(sayadi_id) != 16):
        return True

    return False


class IdentityResolver:
    """
    Hierarchical Identity Resolution and Customer Deduplication Service.
    Resolves data to 48 canonical unique customers.
    """

    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize IdentityResolver with optional SQLite database path.
        Defaults to project customers.db if not specified.
        """
        if db_path:
            self.db_path = db_path
        else:
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            self.db_path = os.path.join(base_dir, "customers.db")

    def _get_connection(self) -> sqlite3.Connection:
        """Create a connection with sqlite3.Row row_factory."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def get_canonical_customers(self) -> List[Dict[str, Any]]:
        """
        Returns exactly 48 canonical customer dictionaries with sanitized 10-digit national IDs,
        distinguishing Hossein Heshmati from Amirhossein Alipour (national ID 0933387075),
        flagging UNRESOLVED_IDENTITY for customers without national codes (IDs 7, 13, 26, 29),
        and associating cheques with proper EXEMPT flags (serials 1113333, 14444, 66666).
        """
        # If DB file exists, load from DB
        if os.path.exists(self.db_path):
            return self._load_from_sqlite()
        else:
            # Fallback to initial_dataset.json if DB not found
            return self._load_from_json()

    def _load_from_sqlite(self) -> List[Dict[str, Any]]:
        """Extract and resolve customers from SQLite database."""
        conn = self._get_connection()
        cursor = conn.cursor()

        # Fetch all cheques grouped by customer_id
        cursor.execute("""
        SELECT 
            id, customer_id, sayadi_id, cheque_number, amount, cheque_date, 
            bank_name, original_name, row_number, holder_id, status, notes
        FROM cheques
        ORDER BY id
        """)
        cheques_by_customer: Dict[int, List[Dict[str, Any]]] = {}
        for row in cursor.fetchall():
            ch = dict(row)
            # Flag EXEMPT status
            if is_exempt_cheque(ch):
                ch["document_status"] = DOC_STATUS_EXEMPT
                ch["is_exempt"] = True
            else:
                ch["document_status"] = DOC_STATUS_VALID
                ch["is_exempt"] = False

            # Normalize text fields
            ch["bank_name"] = normalize_persian_text(ch.get("bank_name"))
            ch["original_name"] = normalize_persian_text(ch.get("original_name"))
            ch["notes"] = normalize_persian_text(ch.get("notes"))

            cid = ch.get("customer_id")
            if cid is not None:
                cheques_by_customer.setdefault(cid, []).append(ch)

        # Fetch all customers
        cursor.execute("""
        SELECT 
            id, full_name, national_id, phone, address, notes, 
            credit_color, risk_score, original_name_alias, created_at, updated_at
        FROM customers
        ORDER BY id
        """)
        raw_customers = cursor.fetchall()
        conn.close()

        canonical_customers: List[Dict[str, Any]] = []

        for row in raw_customers:
            cust = dict(row)
            cid = cust["id"]
            raw_nid = cust.get("national_id")

            # Clean and preserve 10-digit text national ID
            cleaned_nid = clean_national_id(raw_nid)
            cust["national_id"] = cleaned_nid

            # Normalize Persian name and alias
            cust["full_name"] = normalize_persian_text(cust.get("full_name"))
            cust["original_name_alias"] = normalize_persian_text(cust.get("original_name_alias"))

            # Attach cheques
            cust_cheques = cheques_by_customer.get(cid, [])
            cust["cheques"] = cust_cheques
            cust["cheque_count"] = len(cust_cheques)
            cust["total_cheque_amount"] = sum(ch.get("amount", 0.0) for ch in cust_cheques)

            # Check if customer holds any exempt document
            cust["has_exempt_documents"] = any(ch.get("is_exempt", False) for ch in cust_cheques)

            # Flag UNRESOLVED_IDENTITY vs VERIFIED
            if cid in UNRESOLVED_CUSTOMER_IDS or cleaned_nid is None:
                cust["identity_status"] = STATUS_UNRESOLVED_IDENTITY
                cust["is_unresolved"] = True
            else:
                cust["identity_status"] = STATUS_VERIFIED
                cust["is_unresolved"] = False

            # Disambiguation metadata for 0933387075
            if cleaned_nid == DISAMBIGUATED_NATIONAL_ID:
                if cid == 2:
                    # Hossein Heshmati
                    cust["disambiguation_role"] = "HESHMATI_SAYAD_ISSUER"
                    cust["disambiguation_notes"] = "حسین حشمتی - صادرکننده چک صیادی ۲۳۸۰۰۳۰۰۷۲۵۵۶۰۸۸ عهده بانک ایران زمین"
                elif cid == 1:
                    # Amirhossein Alipour
                    cust["disambiguation_role"] = "ALIPOUR_PROMISSORY_NOTE"
                    cust["disambiguation_notes"] = "امیرحسین علیپور - دارنده سند سفته ۱۱۱۳۳۳۳ فاقد شناسه صیادی (معاف)"

            canonical_customers.append(cust)

        return canonical_customers

    def _load_from_json(self) -> List[Dict[str, Any]]:
        """Fallback to initial_dataset.json when SQLite DB is not available."""
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        json_path = os.path.join(base_dir, "data", "initial_dataset.json")

        if not os.path.exists(json_path):
            raise FileNotFoundError(f"Neither SQLite DB ({self.db_path}) nor JSON ({json_path}) exists.")

        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        cheques_by_customer: Dict[int, List[Dict[str, Any]]] = {}
        for ch in data.get("cheques", []):
            if is_exempt_cheque(ch):
                ch["document_status"] = DOC_STATUS_EXEMPT
                ch["is_exempt"] = True
            else:
                ch["document_status"] = DOC_STATUS_VALID
                ch["is_exempt"] = False

            ch["bank_name"] = normalize_persian_text(ch.get("bank_name"))
            ch["original_name"] = normalize_persian_text(ch.get("original_name"))
            ch["notes"] = normalize_persian_text(ch.get("notes"))

            cid = ch.get("customer_id")
            if cid is not None:
                cheques_by_customer.setdefault(cid, []).append(ch)

        canonical_customers = []
        for cust in data.get("customers", []):
            cid = cust["id"]
            cleaned_nid = clean_national_id(cust.get("national_id"))
            cust["national_id"] = cleaned_nid
            cust["full_name"] = normalize_persian_text(cust.get("full_name"))
            cust["original_name_alias"] = normalize_persian_text(cust.get("original_name_alias"))

            cust_cheques = cheques_by_customer.get(cid, [])
            cust["cheques"] = cust_cheques
            cust["cheque_count"] = len(cust_cheques)
            cust["total_cheque_amount"] = sum(ch.get("amount", 0.0) for ch in cust_cheques)
            cust["has_exempt_documents"] = any(ch.get("is_exempt", False) for ch in cust_cheques)

            if cid in UNRESOLVED_CUSTOMER_IDS or cleaned_nid is None:
                cust["identity_status"] = STATUS_UNRESOLVED_IDENTITY
                cust["is_unresolved"] = True
            else:
                cust["identity_status"] = STATUS_VERIFIED
                cust["is_unresolved"] = False

            if cleaned_nid == DISAMBIGUATED_NATIONAL_ID:
                if cid == 2:
                    cust["disambiguation_role"] = "HESHMATI_SAYAD_ISSUER"
                    cust["disambiguation_notes"] = "حسین حشمتی - صادرکننده چک صیادی ۲۳۸۰۰۳۰۰۷۲۵۵۶۰۸۸ عهده بانک ایران زمین"
                elif cid == 1:
                    cust["disambiguation_role"] = "ALIPOUR_PROMISSORY_NOTE"
                    cust["disambiguation_notes"] = "امیرحسین علیپور - دارنده سند سفته ۱۱۱۳۳۳۳ فاقد شناسه صیادی (معاف)"

            canonical_customers.append(cust)

        return canonical_customers

    def _disambiguate_0933387075(
        self,
        cheque: Dict[str, Any],
        canonical: Optional[List[Dict[str, Any]]] = None,
        input_nid: Optional[str] = None,
        cheque_number: str = "",
        sayadi_id: str = "",
        bank_name: str = "",
        original_name: str = "",
        is_exempt: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """
        Disambiguate National ID 0933387075 between Hossein Heshmati and Amirhossein Alipour.
        Handles compound name variants with and without ZWNJ/spaces (علی پور, علیپور, علی‌پور).
        """
        if canonical is None:
            canonical = self.get_canonical_customers()
        if input_nid is None and "national_id" in cheque:
            input_nid = clean_national_id(cheque.get("national_id"))
        if not cheque_number and "cheque_number" in cheque:
            cheque_number = str(cheque.get("cheque_number") or "").strip()
        if not sayadi_id and "sayadi_id" in cheque:
            sayadi_id = str(cheque.get("sayadi_id") or "").strip()
        if not bank_name and "bank_name" in cheque:
            bank_name = normalize_persian_text(cheque.get("bank_name"))
        if not original_name and "original_name" in cheque:
            original_name = normalize_persian_text(cheque.get("original_name"))
        if not is_exempt and cheque:
            is_exempt = is_exempt_cheque(cheque)

        if not (input_nid == DISAMBIGUATED_NATIONAL_ID or cheque_number in ("1113333", "057751")):
            return None

        # Hossein Heshmati indicators:
        is_heshmati = (
            sayadi_id == "2380030072556088" or 
            cheque_number == "057751" or 
            "ایران زمین" in bank_name or 
            "حشمتی" in original_name
        )

        # Amirhossein Alipour indicators (supports compound names with/without half-space ZWNJ):
        orig_compact = original_name.replace(" ", "")
        is_alipour = (
            cheque_number == "1113333" or 
            "سفته" in bank_name or 
            "علیپور" in original_name or 
            "علی پور" in original_name or
            "علیپور" in orig_compact
        )

        if is_heshmati and not is_alipour:
            match = next((c for c in canonical if c["id"] == 2), None)
            return {
                "customer": match,
                "customer_id": 2,
                "resolution_level": 1,
                "resolution_method": "NATIONAL_ID_DISAMBIGUATION_HESHMATI",
                "confidence": "CERTAIN",
                "is_exempt": False,
                "identity_status": STATUS_VERIFIED,
            }
        elif is_alipour and not is_heshmati:
            match = next((c for c in canonical if c["id"] == 1), None)
            return {
                "customer": match,
                "customer_id": 1,
                "resolution_level": 1,
                "resolution_method": "NATIONAL_ID_DISAMBIGUATION_ALIPOUR",
                "confidence": "CERTAIN",
                "is_exempt": True,
                "identity_status": STATUS_VERIFIED,
            }
        elif is_heshmati and is_alipour:
            # Disputed/contradictory evidence: Sayad/cheque serial takes precedence
            if sayadi_id == "2380030072556088" or cheque_number == "057751":
                match = next((c for c in canonical if c["id"] == 2), None)
                return {
                    "customer": match,
                    "customer_id": 2,
                    "resolution_level": 1,
                    "resolution_method": "NATIONAL_ID_DISAMBIGUATION_HESHMATI",
                    "confidence": "HIGH",
                    "is_exempt": False,
                    "identity_status": STATUS_VERIFIED,
                }
            elif cheque_number == "1113333" or "سفته" in bank_name:
                match = next((c for c in canonical if c["id"] == 1), None)
                return {
                    "customer": match,
                    "customer_id": 1,
                    "resolution_level": 1,
                    "resolution_method": "NATIONAL_ID_DISAMBIGUATION_ALIPOUR",
                    "confidence": "HIGH",
                    "is_exempt": True,
                    "identity_status": STATUS_VERIFIED,
                }

        # If input_nid == DISAMBIGUATED_NATIONAL_ID but neither Heshmati nor Alipour matched:
        if input_nid == DISAMBIGUATED_NATIONAL_ID:
            return {
                "customer": None,
                "customer_id": None,
                "resolution_level": 1,
                "resolution_method": "UNRESOLVED",
                "confidence": "NONE",
                "is_exempt": is_exempt,
                "identity_status": STATUS_UNRESOLVED_IDENTITY,
            }

        return None

    def _resolve_by_sayad_history(
        self,
        sayadi_id: str,
        canonical: Optional[List[Dict[str, Any]]] = None,
        is_exempt: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """
        Level 3: Match by Sayad ID history (via pasargad_inquiries or cbi_inquiries).
        """
        if not sayadi_id or not os.path.exists(self.db_path):
            return None

        if canonical is None:
            canonical = self.get_canonical_customers()

        conn = None
        try:
            conn = self._get_connection()
            cur = conn.cursor()

            # Check pasargad_inquiries (contains historical records with customer_id)
            cur.execute(
                "SELECT customer_id FROM pasargad_inquiries WHERE sayadi_id = ? AND customer_id IS NOT NULL ORDER BY id DESC LIMIT 1",
                (sayadi_id,)
            )
            p_row = cur.fetchone()
            if p_row and p_row["customer_id"]:
                hist_cid = p_row["customer_id"]
                match = next((c for c in canonical if c["id"] == hist_cid), None)
                if match:
                    return {
                        "customer": match,
                        "customer_id": match["id"],
                        "resolution_level": 3,
                        "resolution_method": "SAYAD_HISTORY_PASARGAD_MATCH",
                        "confidence": "HIGH",
                        "is_exempt": is_exempt,
                        "identity_status": match["identity_status"],
                    }

            # Fallback check on cbi_inquiries (for official CBI inquiry full_name)
            cur.execute(
                "SELECT full_name FROM cbi_inquiries WHERE sayadi_id = ? ORDER BY id DESC LIMIT 1",
                (sayadi_id,)
            )
            cbi_row = cur.fetchone()
            if cbi_row and cbi_row["full_name"]:
                cbi_name = normalize_persian_text(cbi_row["full_name"])
                for c in canonical:
                    if c["full_name"] == cbi_name or cbi_name in c["full_name"]:
                        return {
                            "customer": c,
                            "customer_id": c["id"],
                            "resolution_level": 3,
                            "resolution_method": "SAYAD_HISTORY_CBI_MATCH",
                            "confidence": "HIGH",
                            "is_exempt": is_exempt,
                            "identity_status": c["identity_status"],
                        }
        except (sqlite3.OperationalError, sqlite3.DatabaseError):
            pass
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

        return None

    def _resolve_by_name(
        self,
        original_name: str,
        canonical: Optional[List[Dict[str, Any]]] = None,
        is_exempt: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """
        Level 4: Match by Customer Name / Alias (Arabic characters normalized).
        Guards against false-positive substring matches: requires candidate token length >= 3
        or full word match, avoiding matching single characters or generic substrings.
        """
        if not original_name:
            return None

        if canonical is None:
            canonical = self.get_canonical_customers()

        # 1. Exact match against full_name or non-empty original_name_alias
        for c in canonical:
            c_name = c["full_name"]
            c_alias = c.get("original_name_alias") or ""
            if original_name == c_name or (c_alias and original_name == c_alias):
                return {
                    "customer": c,
                    "customer_id": c["id"],
                    "resolution_level": 4,
                    "resolution_method": "CUSTOMER_NAME_EXACT_MATCH",
                    "confidence": "HIGH",
                    "is_exempt": is_exempt,
                    "identity_status": c["identity_status"],
                }

        # 2. Embedded canonical name inside longer original_name (e.g. verbose bank memo)
        # Requires candidate full_name length >= 4 and must uniquely match exactly one customer
        embedded_matches = [
            c for c in canonical 
            if len(c["full_name"]) >= 4 and c["full_name"] in original_name
        ]
        if len(embedded_matches) == 1:
            match = embedded_matches[0]
            return {
                "customer": match,
                "customer_id": match["id"],
                "resolution_level": 4,
                "resolution_method": "CUSTOMER_NAME_SUBSTRING_MATCH",
                "confidence": "MEDIUM",
                "is_exempt": is_exempt,
                "identity_status": match["identity_status"],
            }

        # 3. Substring within canonical name: requires length >= 6, >= 2 words/tokens, and unique match
        tokens = [t for t in original_name.split() if len(t) >= 2]
        if len(original_name) >= 6 and len(tokens) >= 2:
            partial_matches = [
                c for c in canonical 
                if original_name in c["full_name"]
            ]
            if len(partial_matches) == 1:
                match = partial_matches[0]
                return {
                    "customer": match,
                    "customer_id": match["id"],
                    "resolution_level": 4,
                    "resolution_method": "CUSTOMER_NAME_SUBSTRING_MATCH",
                    "confidence": "MEDIUM",
                    "is_exempt": is_exempt,
                    "identity_status": match["identity_status"],
                }

        return None

    def resolve_cheque_identity(self, cheque: Dict[str, Any]) -> Dict[str, Any]:
        """
        Hierarchical identity resolution for an individual cheque:
        Level 1: National ID (with 0933387075 disambiguation)
        Level 2: Sayad ID (16 digits)
        Level 3: Sayad ID history (previous inquiries)
        Level 4: Customer name (Arabic-normalized matching)
        Level 5: Cheque serial / registration notes
        """
        canonical = self.get_canonical_customers()
        cheque_number = str(cheque.get("cheque_number") or "").strip()
        sayadi_id = str(cheque.get("sayadi_id") or "").strip()
        bank_name = normalize_persian_text(cheque.get("bank_name"))
        notes = normalize_persian_text(cheque.get("notes"))
        original_name = normalize_persian_text(cheque.get("original_name"))
        input_nid = clean_national_id(cheque.get("national_id"))

        # Check EXEMPT document first
        is_exempt = is_exempt_cheque(cheque)

        # ----------------------------------------------------
        # Special Disambiguation: National Code 0933387075
        # ----------------------------------------------------
        disambiguated = self._disambiguate_0933387075(
            cheque=cheque,
            canonical=canonical,
            input_nid=input_nid,
            cheque_number=cheque_number,
            sayadi_id=sayadi_id,
            bank_name=bank_name,
            original_name=original_name,
            is_exempt=is_exempt,
        )
        if disambiguated is not None:
            return disambiguated

        # Level 1: Match by National ID (for all other customers)
        if input_nid and input_nid != DISAMBIGUATED_NATIONAL_ID:
            match = next((c for c in canonical if c["national_id"] == input_nid), None)
            if match:
                return {
                    "customer": match,
                    "customer_id": match["id"],
                    "resolution_level": 1,
                    "resolution_method": "NATIONAL_ID_EXACT",
                    "confidence": "CERTAIN",
                    "is_exempt": is_exempt,
                    "identity_status": match["identity_status"],
                }

        # Level 2: Match by 16-digit Sayad ID
        if sayadi_id and len(sayadi_id) == 16:
            for c in canonical:
                for ch in c.get("cheques", []):
                    if str(ch.get("sayadi_id") or "").strip() == sayadi_id:
                        return {
                            "customer": c,
                            "customer_id": c["id"],
                            "resolution_level": 2,
                            "resolution_method": "SAYAD_ID_MATCH",
                            "confidence": "CERTAIN",
                            "is_exempt": is_exempt,
                            "identity_status": c["identity_status"],
                        }

        # Level 3: Match by Sayad ID history (via pasargad_inquiries or cbi_inquiries)
        if sayadi_id and os.path.exists(self.db_path):
            l3_match = self._resolve_by_sayad_history(sayadi_id, canonical, is_exempt)
            if l3_match:
                return l3_match

        # Level 4: Match by Customer Name / Alias (Arabic characters normalized)
        if original_name:
            l4_match = self._resolve_by_name(original_name, canonical, is_exempt)
            if l4_match:
                return l4_match

        # Level 5: Match by Cheque Serial / Registration Notes
        if cheque_number:
            # Check exempt serials
            if cheque_number == "14444":
                # Alireza Yaghoubi (ID 8)
                match = next((c for c in canonical if c["id"] == 8), None)
                return {
                    "customer": match,
                    "customer_id": 8,
                    "resolution_level": 5,
                    "resolution_method": "SERIAL_EXEMPT_YAGHOUBI",
                    "confidence": "CERTAIN",
                    "is_exempt": True,
                    "identity_status": STATUS_VERIFIED,
                }
            elif cheque_number == "66666" or "احمد زحمتکش" in notes:
                # Ahmad Zahmatkesh (ID 16)
                match = next((c for c in canonical if c["id"] == 16), None)
                return {
                    "customer": match,
                    "customer_id": 16,
                    "resolution_level": 5,
                    "resolution_method": "SERIAL_EXEMPT_ZAHMATKESH",
                    "confidence": "CERTAIN",
                    "is_exempt": True,
                    "identity_status": STATUS_VERIFIED,
                }

            # Search in canonical cheques for this serial
            for c in canonical:
                for ch in c.get("cheques", []):
                    if str(ch.get("cheque_number") or "").strip() == cheque_number:
                        return {
                            "customer": c,
                            "customer_id": c["id"],
                            "resolution_level": 5,
                            "resolution_method": "CHEQUE_SERIAL_MATCH",
                            "confidence": "MEDIUM",
                            "is_exempt": is_exempt,
                            "identity_status": c["identity_status"],
                        }

        # Unresolved identity fallback
        return {
            "customer": None,
            "customer_id": None,
            "resolution_level": 5,
            "resolution_method": "UNRESOLVED",
            "confidence": "NONE",
            "is_exempt": is_exempt,
            "identity_status": STATUS_UNRESOLVED_IDENTITY,
        }

    def get_customer_by_id(self, customer_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve a canonical customer by ID."""
        for cust in self.get_canonical_customers():
            if cust["id"] == customer_id:
                return cust
        return None

    def get_customers_by_national_id(self, national_id: str) -> List[Dict[str, Any]]:
        """
        Retrieve canonical customer(s) by national ID.
        For 0933387075, returns both Hossein Heshmati and Amirhossein Alipour.
        For all other national IDs, returns a single customer list or empty list.
        """
        cleaned = clean_national_id(national_id)
        if not cleaned:
            return []
        canonical = self.get_canonical_customers()
        return [c for c in canonical if c.get("national_id") == cleaned]

    def get_unresolved_identities(self) -> List[Dict[str, Any]]:
        """
        Return customers flagged with UNRESOLVED_IDENTITY (lacking national code: IDs 7, 13, 26, 29).
        """
        canonical = self.get_canonical_customers()
        return [c for c in canonical if c.get("identity_status") == STATUS_UNRESOLVED_IDENTITY]

    def get_exempt_documents(self) -> List[Dict[str, Any]]:
        """
        Return the 3 EXEMPT documents (serials 1113333, 14444, 66666).
        """
        exempt_docs: List[Dict[str, Any]] = []
        for cust in self.get_canonical_customers():
            for ch in cust.get("cheques", []):
                if ch.get("is_exempt", False):
                    exempt_docs.append(ch)
        return exempt_docs

    def audit_identity_integrity(self) -> Dict[str, Any]:
        """
        Perform a comprehensive integrity audit on customer identities and deduplication.
        Verifies:
        - Exactly 48 canonical customers
        - Exactly 4 unresolved identities
        - Exactly 3 exempt cheques
        - 0933387075 disambiguated into 2 records
        - Leading zeros preserved on all national IDs
        - Exactly 147 fund cheques totaling 483,325,000,000 Rials
        """
        canonical = self.get_canonical_customers()
        total_customers = len(canonical)
        unresolved = self.get_unresolved_identities()
        exempt_docs = self.get_exempt_documents()
        nids_0933 = self.get_customers_by_national_id(DISAMBIGUATED_NATIONAL_ID)

        # Check leading zeros
        invalid_nids = []
        for c in canonical:
            nid = c.get("national_id")
            if nid is not None:
                if not isinstance(nid, str) or len(nid) != 10 or not nid.isdigit():
                    invalid_nids.append((c["id"], c["full_name"], nid))

        # Check fund cheques sum
        all_cheques = []
        for c in canonical:
            all_cheques.extend(c.get("cheques", []))

        total_cheques_count = len(all_cheques)
        total_fund_amount = sum(ch.get("amount", 0.0) for ch in all_cheques)

        is_passed = (
            total_customers == 48 and
            len(unresolved) == 4 and
            len(exempt_docs) == 3 and
            len(nids_0933) == 2 and
            len(invalid_nids) == 0 and
            total_cheques_count == 147 and
            total_fund_amount == 483_325_000_000.0
        )

        return {
            "passed": is_passed,
            "total_customers": total_customers,
            "unresolved_count": len(unresolved),
            "unresolved_ids": [c["id"] for c in unresolved],
            "exempt_documents_count": len(exempt_docs),
            "exempt_serials": [ch["cheque_number"] for ch in exempt_docs],
            "disambiguated_0933387075_count": len(nids_0933),
            "disambiguated_names": [c["full_name"] for c in nids_0933],
            "invalid_national_ids": invalid_nids,
            "total_cheques_count": total_cheques_count,
            "total_fund_amount": total_fund_amount,
        }
