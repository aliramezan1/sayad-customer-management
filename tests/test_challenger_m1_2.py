"""
Empirical Verification & Adversarial Stress Harness for Milestone 1
Challenger 2: Independent verification of portfolio fund cheques, canonical customers,
unresolved identities, exempt documents, and Excel-to-DB reconciliation.
"""

import os
import sqlite3
import openpyxl
import pytest
from app.services.identity_resolver import (
    IdentityResolver,
    clean_national_id,
    validate_national_id,
    normalize_persian_text,
    is_exempt_cheque,
    to_ascii_digits,
    STATUS_VERIFIED,
    STATUS_UNRESOLVED_IDENTITY,
    DOC_STATUS_EXEMPT,
    DOC_STATUS_VALID,
    DISAMBIGUATED_NATIONAL_ID,
    UNRESOLVED_CUSTOMER_IDS,
    EXEMPT_CHEQUE_NUMBERS,
)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "customers.db")
EXCEL_PATH = os.path.join(BASE_DIR, "چک_ها صندوق ١۴٠۵٠۵٢٩.xlsx")
TARGET_FUND_AMOUNT = 483_325_000_000.0
TARGET_CHEQUE_COUNT = 147
TARGET_CUSTOMER_COUNT = 48


@pytest.fixture(scope="module")
def resolver():
    return IdentityResolver(db_path=DB_PATH)


@pytest.fixture(scope="module")
def raw_excel_data():
    wb = openpyxl.load_workbook(EXCEL_PATH, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    header = rows[0]
    data = rows[1:]
    return {"header": header, "rows": data}


@pytest.fixture(scope="module")
def db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


# ==============================================================================
# SECTION 1: RAW EXCEL AUDIT & INTEGRITY
# ==============================================================================

def test_raw_excel_row_count_and_total_amount(raw_excel_data):
    """Raw Excel must contain exactly 147 cheques summing to 483,325,000,000 Rials."""
    rows = raw_excel_data["rows"]
    assert len(rows) == TARGET_CHEQUE_COUNT, f"Raw Excel has {len(rows)} rows, expected {TARGET_CHEQUE_COUNT}"

    # Column index 11 is چک|مبلغ
    amounts = [float(r[11]) for r in rows if r[11] is not None]
    assert len(amounts) == TARGET_CHEQUE_COUNT, f"Expected 147 non-null amounts, found {len(amounts)}"
    total = sum(amounts)
    assert total == TARGET_FUND_AMOUNT, f"Raw Excel total {total} != {TARGET_FUND_AMOUNT}"


def test_raw_excel_cheque_numbers_non_empty(raw_excel_data):
    """Every row in raw Excel must have a non-empty cheque number."""
    rows = raw_excel_data["rows"]
    for idx, r in enumerate(rows):
        cheque_no = str(r[1]).strip() if r[1] is not None else ""
        assert cheque_no != "", f"Row {idx+2} in Excel has empty cheque number"


# ==============================================================================
# SECTION 2: RAW EXCEL TO SQLITE RECONCILIATION
# ==============================================================================

def test_raw_excel_to_db_cheque_count_and_amount_parity(raw_excel_data, db_connection):
    """
    Every single cheque in raw Excel must match a record in customers.db cheques table.
    The total amount in DB must match raw Excel exactly (483,325,000,000 Rials).
    """
    cur = db_connection.cursor()
    cur.execute("SELECT COUNT(*), SUM(amount) FROM cheques")
    db_count, db_sum = cur.fetchone()

    assert db_count == TARGET_CHEQUE_COUNT, f"DB cheques count {db_count} != {TARGET_CHEQUE_COUNT}"
    assert db_sum == TARGET_FUND_AMOUNT, f"DB cheques sum {db_sum} != {TARGET_FUND_AMOUNT}"

    cur.execute("SELECT cheque_number, amount FROM cheques")
    db_cheques = cur.fetchall()

    excel_rows = raw_excel_data["rows"]
    excel_cheques = [(str(r[1]).strip(), float(r[11])) for r in excel_rows]

    # Check total sums match
    excel_sum = sum(x[1] for x in excel_cheques)
    assert db_sum == excel_sum == TARGET_FUND_AMOUNT


def test_raw_excel_to_db_row_by_row_exact_parity(raw_excel_data, db_connection):
    """
    Assert 1-to-1 exact matching between raw Excel and DB for all 147 cheques.
    Cheque numbers and amounts must match in exact sequence.
    """
    cur = db_connection.cursor()
    cur.execute("SELECT cheque_number, amount FROM cheques ORDER BY id")
    db_cheques = cur.fetchall()
    excel_rows = raw_excel_data["rows"]

    for idx, (ex, db) in enumerate(zip(excel_rows, db_cheques)):
        ex_num = str(ex[1]).strip()
        db_num = str(db["cheque_number"]).strip()
        ex_amt = float(ex[11])
        db_amt = float(db["amount"])

        assert ex_num == db_num, f"Cheque number mismatch at index {idx+1}: Excel={ex_num}, DB={db_num}"
        assert ex_amt == db_amt, f"Amount mismatch at index {idx+1}: Excel={ex_amt}, DB={db_amt}"


# ==============================================================================
# SECTION 3: CANONICAL CUSTOMER & CHEQUE ASSIGNMENT UNIQUENESS
# ==============================================================================

def test_canonical_customer_count_is_48(resolver):
    """Database must have exactly 48 canonical unique customers."""
    canonical = resolver.get_canonical_customers()
    assert len(canonical) == TARGET_CUSTOMER_COUNT, f"Expected {TARGET_CUSTOMER_COUNT} customers, got {len(canonical)}"


def test_no_orphaned_cheques_in_db(db_connection):
    """Every cheque in DB must have a valid customer_id pointing to an existing customer in customers table."""
    cur = db_connection.cursor()
    cur.execute("""
        SELECT ch.id, ch.cheque_number, ch.amount, ch.customer_id
        FROM cheques ch
        LEFT JOIN customers c ON ch.customer_id = c.id
        WHERE c.id IS NULL OR ch.customer_id IS NULL
    """)
    orphaned = cur.fetchall()
    assert len(orphaned) == 0, f"Found {len(orphaned)} orphaned cheques: {[dict(x) for x in orphaned]}"


def test_every_cheque_belongs_to_exactly_one_customer(resolver):
    """
    Verify that across all 48 canonical customers:
    1. Every cheque ID appears exactly once.
    2. Sum of cheque counts across customers equals 147.
    3. Sum of amounts across customers equals 483,325,000,000 Rials.
    4. No duplicate cheque IDs across different customers.
    """
    canonical = resolver.get_canonical_customers()
    seen_cheque_ids = set()
    total_assigned_cheques = 0
    total_assigned_amount = 0.0

    for cust in canonical:
        cid = cust["id"]
        cheques = cust.get("cheques", [])
        assert cust["cheque_count"] == len(cheques)
        assert cust["total_cheque_amount"] == sum(ch.get("amount", 0.0) for ch in cheques)

        for ch in cheques:
            chid = ch["id"]
            assert chid not in seen_cheque_ids, (
                f"Cheque ID {chid} (num: {ch.get('cheque_number')}) is duplicated! "
                f"Assigned to customer {cid} but already seen."
            )
            seen_cheque_ids.add(chid)
            total_assigned_cheques += 1
            total_assigned_amount += float(ch.get("amount", 0.0))

    assert total_assigned_cheques == TARGET_CHEQUE_COUNT, (
        f"Total assigned cheques {total_assigned_cheques} != {TARGET_CHEQUE_COUNT}"
    )
    assert len(seen_cheque_ids) == TARGET_CHEQUE_COUNT, (
        f"Unique cheque IDs count {len(seen_cheque_ids)} != {TARGET_CHEQUE_COUNT}"
    )
    assert total_assigned_amount == TARGET_FUND_AMOUNT, (
        f"Total assigned amount {total_assigned_amount} != {TARGET_FUND_AMOUNT}"
    )


def test_every_canonical_customer_has_at_least_one_cheque(resolver):
    """Verify that every one of the 48 canonical customers possesses at least 1 cheque."""
    canonical = resolver.get_canonical_customers()
    zero_cheque_customers = [c for c in canonical if c["cheque_count"] == 0]
    assert len(zero_cheque_customers) == 0, (
        f"Found {len(zero_cheque_customers)} customers with 0 cheques: "
        f"{[c['id'] for c in zero_cheque_customers]}"
    )


# ==============================================================================
# SECTION 4: UNRESOLVED_IDENTITY VERIFICATION
# ==============================================================================

def test_unresolved_identity_customers_strictly_accounted(resolver, db_connection):
    """
    Verify the 4 UNRESOLVED_IDENTITY customers (IDs 7, 13, 26, 29):
    1. National ID is None in DB and None in canonical model.
    2. Flagged with identity_status == 'UNRESOLVED_IDENTITY'.
    3. is_unresolved == True.
    4. Their cheques and amounts are tracked accurately and included in the 483,325,000,000 total.
    """
    unresolved = resolver.get_unresolved_identities()
    assert len(unresolved) == 4, f"Expected 4 unresolved customers, got {len(unresolved)}"

    unresolved_ids = {c["id"] for c in unresolved}
    assert unresolved_ids == UNRESOLVED_CUSTOMER_IDS, (
        f"Expected IDs {UNRESOLVED_CUSTOMER_IDS}, got {unresolved_ids}"
    )

    total_unresolved_cheques = sum(c["cheque_count"] for c in unresolved)
    total_unresolved_amount = sum(c["total_cheque_amount"] for c in unresolved)

    # Verify each customer
    for cust in unresolved:
        assert cust["national_id"] is None
        assert cust["identity_status"] == STATUS_UNRESOLVED_IDENTITY
        assert cust["is_unresolved"] is True
        assert cust["cheque_count"] == 1
        assert cust["total_cheque_amount"] > 0

    assert total_unresolved_cheques == 4
    # Sum: 6B (7) + 895M (13) + 350M (26) + 220M (29) = 7,465,000,000
    assert total_unresolved_amount == 7_465_000_000.0


# ==============================================================================
# SECTION 5: EXEMPT DOCUMENTS VERIFICATION
# ==============================================================================

def test_exempt_documents_strictly_accounted(resolver):
    """
    Verify the 3 EXEMPT documents (serials 1113333, 14444, 66666):
    1. Exactly 3 documents flagged with is_exempt == True and document_status == 'EXEMPT'.
    2. Document 1113333: Amirhossein Alipour (Customer 1), amount 2,000,000,000, Bank * قر سفته.
    3. Document 14444: Alireza Yaghoubi (Customer 8), amount 870,000,000, Bank * کشاورزی دکتر حسابی.
    4. Document 66666: Ahmad Zahmatkesh (Customer 16), amount 1,400,000,000, Bank * بانک ملی کوی المهدی.
    5. Sum of exempt documents equals 4,270,000,000 Rials.
    """
    exempt_docs = resolver.get_exempt_documents()
    assert len(exempt_docs) == 3, f"Expected 3 exempt docs, got {len(exempt_docs)}"

    serials = {ch["cheque_number"] for ch in exempt_docs}
    assert serials == EXEMPT_CHEQUE_NUMBERS, f"Expected {EXEMPT_CHEQUE_NUMBERS}, got {serials}"

    total_exempt_amount = sum(ch["amount"] for ch in exempt_docs)
    assert total_exempt_amount == 4_270_000_000.0, f"Expected 4.27B Rials, got {total_exempt_amount}"

    doc_map = {ch["cheque_number"]: ch for ch in exempt_docs}
    # Check 1113333
    d1 = doc_map["1113333"]
    assert d1["customer_id"] == 1
    assert d1["amount"] == 2_000_000_000.0
    assert "سفته" in d1["bank_name"]

    # Check 14444
    d2 = doc_map["14444"]
    assert d2["customer_id"] == 8
    assert d2["amount"] == 870_000_000.0

    # Check 66666
    d3 = doc_map["66666"]
    assert d3["customer_id"] == 16
    assert d3["amount"] == 1_400_000_000.0


# ==============================================================================
# SECTION 6: DISAMBIGUATION OF 0933387075
# ==============================================================================

def test_disambiguation_0933387075_detailed(resolver):
    """
    National ID 0933387075 must never be merged.
    Returns 2 distinct records:
    - Customer 1: Amirhossein Alipour (Promissory note 1113333, 2,000,000,000 Rials, EXEMPT)
    - Customer 2: Hossein Heshmati (Bank cheque 057751, Sayad 2380030072556088, 1,060,000,000 Rials)
    Total amount across both: 3,060,000,000 Rials.
    """
    records = resolver.get_customers_by_national_id(DISAMBIGUATED_NATIONAL_ID)
    assert len(records) == 2, f"Expected 2 records, got {len(records)}"

    rec_map = {r["id"]: r for r in records}
    assert 1 in rec_map and 2 in rec_map

    c1 = rec_map[1]
    c2 = rec_map[2]

    assert c1["full_name"] == "امیرحسین علیپور"
    assert c1["total_cheque_amount"] == 2_000_000_000.0
    assert c1["has_exempt_documents"] is True

    assert c2["full_name"] == "حسین حشمتی"
    assert c2["total_cheque_amount"] == 1_060_000_000.0
    assert c2["has_exempt_documents"] is False

    assert c1["total_cheque_amount"] + c2["total_cheque_amount"] == 3_060_000_000.0


# ==============================================================================
# SECTION 7: ADVERSARIAL STRESS-TESTING OF IDENTITYRESOLVER
# ==============================================================================

def test_adversarial_national_id_formatting_invariants():
    """Verify clean_national_id formatting invariants and checksum defense."""
    # Preservation of leading zeros
    assert clean_national_id("0933387075") == "0933387075"
    assert clean_national_id("0010485295") == "0010485295"
    assert clean_national_id("0890543331") == "0890543331"

    # Numeric integer / float inputs
    assert clean_national_id(933387075) == "0933387075"
    assert clean_national_id(10485295) == "0010485295"

    # Persian and Arabic numerals
    assert clean_national_id("۰۹۳۳۳۸۷۰۷۵") == "0933387075"
    assert clean_national_id("٠٩٣٣٣٨٧٠٧٥") == "0933387075"

    # Formatting with dashes and spaces
    assert clean_national_id(" 093-338-7075 ") == "0933387075"

    # Empty and null-like inputs
    assert clean_national_id(None) is None
    assert clean_national_id("") is None
    assert clean_national_id("None") is None
    assert clean_national_id("null") is None
    assert clean_national_id("nan") is None

    # Length out of bounds
    assert clean_national_id("1234567") is None       # 7 digits -> None
    assert clean_national_id("123456789012") is None  # 12 digits -> None

    # Defense: Even if non-digits or negative numbers are passed into clean_national_id,
    # the second line of defense (validate_national_id) MUST reject invalid checksums!
    cleaned_neg = clean_national_id(-12345678)
    assert cleaned_neg is not None  # Sanitizer extracts digits
    assert validate_national_id(cleaned_neg) is False  # Validator rejects invalid checksum!

    cleaned_alpha = clean_national_id("093338707A")
    assert validate_national_id(cleaned_alpha) is False


def test_adversarial_arabic_normalization_stress():
    """Adversarial text inputs to normalize_persian_text."""
    # Zero-width spaces, combined diacritics, tatweel
    text = "ي\u200cك\u0640ي"  # with zero-width non-joiner and tatweel
    normalized = normalize_persian_text(text)
    assert "ي" not in normalized
    assert "ك" not in normalized

    # Very large string
    large_str = "ي" * 10000
    res = normalize_persian_text(large_str)
    assert "ی" * 10000 == res

    # Mixed inputs
    assert normalize_persian_text(12345) == "12345"


def test_adversarial_resolve_cheque_identity_edge_cases(resolver):
    """Stress test resolve_cheque_identity with adversarial or corrupt inputs."""
    # Empty dict
    res = resolver.resolve_cheque_identity({})
    assert res["customer"] is None
    assert res["resolution_method"] == "UNRESOLVED"
    assert res["identity_status"] == STATUS_UNRESOLVED_IDENTITY

    # Corrupt data types
    res2 = resolver.resolve_cheque_identity({
        "cheque_number": None,
        "sayadi_id": None,
        "national_id": None,
        "bank_name": None,
        "original_name": None,
    })
    assert res2["customer"] is None

    # SQL injection attempt in national_id
    res3 = resolver.resolve_cheque_identity({
        "national_id": "' OR 1=1 --",
        "sayadi_id": "'; DROP TABLE customers; --",
    })
    assert res3["customer"] is None


def test_adversarial_unresolvable_0933387075_fallback(resolver):
    """An unresolvable cheque with 0933387075 must strictly fall back to UNRESOLVED_IDENTITY."""
    ambiguous = {
        "cheque_number": "99999",
        "sayadi_id": "8888777766665555",
        "national_id": "0933387075",
        "bank_name": "بانک ملی",
        "original_name": "شخص فرضی نامعلوم",
    }
    res = resolver.resolve_cheque_identity(ambiguous)
    assert res["customer"] is None
    assert res["resolution_method"] == "UNRESOLVED"
    assert res["identity_status"] == STATUS_UNRESOLVED_IDENTITY


def test_comprehensive_audit_method(resolver):
    """The built-in audit_identity_integrity must report passed == True."""
    audit = resolver.audit_identity_integrity()
    assert audit["passed"] is True
    assert audit["total_customers"] == 48
    assert audit["unresolved_count"] == 4
    assert audit["exempt_documents_count"] == 3
    assert audit["disambiguated_0933387075_count"] == 2
    assert audit["total_cheques_count"] == 147
    assert audit["total_fund_amount"] == 483_325_000_000.0
