"""
Unit tests for IdentityResolver (Milestone 1).

Covers:
- Assert exactly 48 canonical unique customers.
- Assert all national IDs preserve leading zeros as 10-digit text strings.
- Assert 0933387075 resolves to two distinct records:
    - Hossein Heshmati (Customer ID 2, Cheque 057751, Sayad 2380030072556088, Bank Iran Zamin)
    - Amirhossein Alipour (Customer ID 1, Promissory note / Safteh 1113333, Bank * قر سفته, EXEMPT)
- Assert 4 UNRESOLVED_IDENTITY customers are flagged properly (IDs 7, 13, 26, 29).
- Assert 3 EXEMPT documents are flagged properly (serials 1113333, 14444, 66666).
- Arabic character normalization ('ي' and 'ك' to 'ی' and 'ک').
- National ID formatting and modulo 11 checksum verification.
- Hierarchical identity resolution (Levels 1 to 5).
- Test isolation and fund total audit (147 cheques, 483,325,000,000 Rials).
"""

import os
import sqlite3
import pytest
from app.services.identity_resolver import (
    IdentityResolver,
    normalize_persian_text,
    clean_national_id,
    validate_national_id,
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


@pytest.fixture
def resolver():
    """Create an instance of IdentityResolver with default database."""
    return IdentityResolver()


# =====================================================================
# 1. Canonical Customers & Deduplication Tests
# =====================================================================

def test_canonical_customers_count_is_exactly_48(resolver):
    """Verify that exactly 48 canonical unique customers are returned."""
    customers = resolver.get_canonical_customers()
    assert len(customers) == 48, f"Expected 48 canonical customers, got {len(customers)}"


def test_customer_ids_are_unique(resolver):
    """Verify that every canonical customer has a unique ID."""
    customers = resolver.get_canonical_customers()
    ids = [c["id"] for c in customers]
    assert len(ids) == len(set(ids)), "Customer IDs must be strictly unique"


def test_fund_total_and_cheque_count(resolver):
    """Verify that all 147 fund cheques exist and sum to 483,325,000,000 Rials."""
    customers = resolver.get_canonical_customers()
    all_cheques = []
    for c in customers:
        all_cheques.extend(c.get("cheques", []))

    assert len(all_cheques) == 147, f"Expected 147 cheques, got {len(all_cheques)}"
    total_amount = sum(ch.get("amount", 0.0) for ch in all_cheques)
    assert total_amount == 483_325_000_000.0, (
        f"Expected 483,325,000,000 Rials, got {total_amount}"
    )


# =====================================================================
# 2. National ID Text Format & Leading Zeros Preservation Tests
# =====================================================================

def test_all_national_ids_preserve_leading_zeros(resolver):
    """
    Assert all non-null national IDs are strictly 10-digit text strings.
    Verify that leading zeros are never stripped or converted to numbers.
    """
    customers = resolver.get_canonical_customers()
    checked_count = 0
    leading_zero_count = 0

    for c in customers:
        nid = c.get("national_id")
        if nid is not None:
            assert isinstance(nid, str), f"National ID must be str, got {type(nid)}"
            assert len(nid) == 10, f"National ID must be exactly 10 digits: {nid}"
            assert nid.isdigit(), f"National ID must contain only digits: {nid}"
            checked_count += 1
            if nid.startswith("0"):
                leading_zero_count += 1

    # 44 customers have national IDs, 4 are unresolved
    assert checked_count == 44, f"Expected 44 customers with national ID, got {checked_count}"
    # In the dataset, over 30 customers have leading zeros (e.g. 0933387075, 0890543331, 0010485295)
    assert leading_zero_count >= 30, f"Expected >= 30 national IDs with leading zero, got {leading_zero_count}"


def test_specific_leading_zero_customers(resolver):
    """Verify specific customers known to have leading zeros."""
    customers = resolver.get_canonical_customers()
    cust_map = {c["id"]: c for c in customers}

    # Farid Vali (ID 30): Starts with TWO zeros '0010485295'
    vali = cust_map.get(30)
    assert vali is not None
    assert vali["national_id"] == "0010485295", f"Expected '0010485295', got {vali['national_id']}"

    # Mohammad Rafigh Toroghi (ID 40): Starts with '0890543331'
    toroghi = cust_map.get(40)
    assert toroghi is not None
    assert toroghi["national_id"] == "0890543331", f"Expected '0890543331', got {toroghi['national_id']}"

    # Zahra Bahrami Pouya (ID 46): Starts with '0927624011'
    bahrami = cust_map.get(46)
    assert bahrami is not None
    assert bahrami["national_id"] == "0927624011", f"Expected '0927624011', got {bahrami['national_id']}"

    # Hossein Heshmati (ID 2): Starts with '0933387075'
    heshmati = cust_map.get(2)
    assert heshmati is not None
    assert heshmati["national_id"] == "0933387075", f"Expected '0933387075', got {heshmati['national_id']}"


def test_clean_national_id_formatting():
    """Test clean_national_id with various input representations."""
    # String with leading zero
    assert clean_national_id("0933387075") == "0933387075"
    assert clean_national_id("0010485295") == "0010485295"

    # Integer or number-like string without leading zero (pads with zfill)
    assert clean_national_id("933387075") == "0933387075"
    assert clean_national_id(933387075) == "0933387075"
    assert clean_national_id(10485295) == "0010485295"

    # Float representation (safe padding)
    assert clean_national_id(933387075.0) == "0933387075"

    # Persian / Arabic digits
    assert clean_national_id("۰۹۳۳۳۸۷۰۷۵") == "0933387075"
    assert clean_national_id("٠٩٣٣٣٨٧٠٧٥") == "0933387075"

    # Dashes and whitespace
    assert clean_national_id(" 093-3387075 ") == "0933387075"

    # None and empty inputs
    assert clean_national_id(None) is None
    assert clean_national_id("") is None
    assert clean_national_id("None") is None
    assert clean_national_id("NULL") is None
    assert clean_national_id("nan") is None


def test_validate_national_id_checksum():
    """Verify Iranian National ID modulo 11 checksum validator."""
    # Valid IDs from dataset
    assert validate_national_id("0933387075") is True
    assert validate_national_id("0890543331") is True
    assert validate_national_id("0927624011") is True
    assert validate_national_id("0010485295") is True
    assert validate_national_id("6430003159") is True

    # Invalid checksum
    assert validate_national_id("0933387076") is False
    assert validate_national_id("1234567890") is False

    # All-identical digits (invalid)
    assert validate_national_id("0000000000") is False
    assert validate_national_id("1111111111") is False

    # Malformed inputs
    assert validate_national_id("123") is False
    assert validate_national_id(None) is False
    assert validate_national_id("abcdefghij") is False


# =====================================================================
# 3. Disambiguation of National ID 0933387075 Tests
# =====================================================================

def test_disambiguation_of_0933387075_returns_two_distinct_records(resolver):
    """
    Assert 0933387075 resolves to two distinct records:
    - Customer ID 2: Hossein Heshmati (Check 057751, Sayad 2380030072556088, Bank Iran Zamin)
    - Customer ID 1: Amirhossein Alipour (Promissory note 1113333, Bank * قر سفته, EXEMPT)
    They must never be merged into one.
    """
    customers = resolver.get_customers_by_national_id(DISAMBIGUATED_NATIONAL_ID)
    assert len(customers) == 2, f"Expected 2 customers for 0933387075, got {len(customers)}"

    cust_ids = {c["id"] for c in customers}
    assert cust_ids == {1, 2}, f"Expected IDs {1, 2}, got {cust_ids}"

    c1 = next(c for c in customers if c["id"] == 1)
    c2 = next(c for c in customers if c["id"] == 2)

    # Assert Alipour
    assert "علیپور" in c1["full_name"]
    assert c1["cheque_count"] == 1
    assert c1["cheques"][0]["cheque_number"] == "1113333"
    assert c1["cheques"][0]["is_exempt"] is True
    assert c1["cheques"][0]["document_status"] == DOC_STATUS_EXEMPT
    assert c1["cheques"][0]["amount"] == 2_000_000_000.0

    # Assert Heshmati
    assert "حشمتی" in c2["full_name"]
    assert c2["cheque_count"] == 1
    assert c2["cheques"][0]["cheque_number"] == "057751"
    assert c2["cheques"][0]["sayadi_id"] == "2380030072556088"
    assert c2["cheques"][0]["is_exempt"] is False
    assert c2["cheques"][0]["document_status"] == DOC_STATUS_VALID
    assert c2["cheques"][0]["amount"] == 1_060_000_000.0


def test_cheque_resolution_disambiguates_0933387075(resolver):
    """
    Test hierarchical resolution of individual cheques with national ID 0933387075.
    """
    # Cheque 057751 with Sayad 2380030072556088 -> Heshmati (Customer 2)
    cheque_heshmati = {
        "cheque_number": "057751",
        "sayadi_id": "2380030072556088",
        "national_id": "0933387075",
        "bank_name": "* ایران زمین مفتح مشهد",
        "original_name": "حسین حشمتی",
    }
    res_heshmati = resolver.resolve_cheque_identity(cheque_heshmati)
    assert res_heshmati["customer_id"] == 2
    assert res_heshmati["is_exempt"] is False
    assert "HESHMATI" in res_heshmati["resolution_method"]

    # Cheque 1113333 promissory note -> Alipour (Customer 1)
    cheque_alipour = {
        "cheque_number": "1113333",
        "sayadi_id": "",
        "national_id": "0933387075",
        "bank_name": "* قر سفته",
        "original_name": "امیرحسین علیپور چک های برگشتی",
    }
    res_alipour = resolver.resolve_cheque_identity(cheque_alipour)
    assert res_alipour["customer_id"] == 1
    assert res_alipour["is_exempt"] is True
    assert "ALIPOUR" in res_alipour["resolution_method"]


# =====================================================================
# 4. UNRESOLVED_IDENTITY Flagging Tests
# =====================================================================

def test_unresolved_identity_customers_count_and_ids(resolver):
    """
    Assert exactly 4 customers lacking national code are flagged UNRESOLVED_IDENTITY:
    IDs 7, 13, 26, 29.
    """
    unresolved = resolver.get_unresolved_identities()
    assert len(unresolved) == 4, f"Expected 4 unresolved customers, got {len(unresolved)}"

    unresolved_ids = {c["id"] for c in unresolved}
    assert unresolved_ids == UNRESOLVED_CUSTOMER_IDS, (
        f"Expected IDs {UNRESOLVED_CUSTOMER_IDS}, got {unresolved_ids}"
    )

    for c in unresolved:
        assert c["national_id"] is None, f"Unresolved customer {c['id']} must have None national_id"
        assert c["identity_status"] == STATUS_UNRESOLVED_IDENTITY
        assert c["is_unresolved"] is True


def test_verified_customers_are_not_flagged_unresolved(resolver):
    """Assert all 44 customers with valid national codes are flagged VERIFIED."""
    customers = resolver.get_canonical_customers()
    verified = [c for c in customers if c["identity_status"] == STATUS_VERIFIED]
    assert len(verified) == 44, f"Expected 44 verified customers, got {len(verified)}"
    for c in verified:
        assert c["is_unresolved"] is False
        assert c["national_id"] is not None


# =====================================================================
# 5. EXEMPT Documents Flagging Tests
# =====================================================================

def test_exempt_documents_count_and_serials(resolver):
    """
    Assert exactly 3 documents are flagged EXEMPT:
    serials 1113333, 14444, 66666.
    """
    exempt_docs = resolver.get_exempt_documents()
    assert len(exempt_docs) == 3, f"Expected 3 exempt documents, got {len(exempt_docs)}"

    serials = {ch["cheque_number"] for ch in exempt_docs}
    assert serials == EXEMPT_CHEQUE_NUMBERS, (
        f"Expected serials {EXEMPT_CHEQUE_NUMBERS}, got {serials}"
    )

    for doc in exempt_docs:
        assert doc["is_exempt"] is True
        assert doc["document_status"] == DOC_STATUS_EXEMPT


def test_is_exempt_cheque_function():
    """Verify is_exempt_cheque helper function on various scenarios."""
    assert is_exempt_cheque({"cheque_number": "1113333"}) is True
    assert is_exempt_cheque({"cheque_number": "14444"}) is True
    assert is_exempt_cheque({"cheque_number": "66666"}) is True
    assert is_exempt_cheque({"bank_name": "* قر سفته"}) is True
    assert is_exempt_cheque({"bank_name": "سفته ضمانت"}) is True
    assert is_exempt_cheque({"notes": "سفته", "sayadi_id": ""}) is True

    # Regular Sayad cheques are not exempt
    assert is_exempt_cheque({
        "cheque_number": "057751",
        "sayadi_id": "2380030072556088",
        "bank_name": "* ايران زمين مفتح مشهد"
    }) is False


# =====================================================================
# 6. Arabic Character Normalization Tests
# =====================================================================

def test_arabic_character_normalization():
    """
    Assert Arabic 'ي' (\u064a) and 'ك' (\u0643) are properly normalized
    to Persian 'ی' (\u06cc) and 'ک' (\u06a9).
    """
    # Test Arabic Yeh
    raw_name_1 = "اميرحسين عليپور"
    normalized_1 = normalize_persian_text(raw_name_1)
    assert "ي" not in normalized_1
    assert normalized_1 == "امیرحسین علیپور"

    # Test Arabic Kaf
    raw_name_2 = "مرتضي كفاييان"
    normalized_2 = normalize_persian_text(raw_name_2)
    assert "ي" not in normalized_2
    assert "ك" not in normalized_2
    assert normalized_2 == "مرتضی کفاییان"

    # Test Teh Marbuta and zero-width spaces
    raw_name_3 = "ملک هاشميه\u200c"
    normalized_3 = normalize_persian_text(raw_name_3)
    assert normalized_3 == "ملک هاشمیه"

    # None and empty
    assert normalize_persian_text(None) == ""
    assert normalize_persian_text("") == ""


def test_customer_names_in_canonical_are_normalized(resolver):
    """Verify that all names and aliases in canonical customers are normalized."""
    customers = resolver.get_canonical_customers()
    for c in customers:
        name = c["full_name"]
        assert "ي" not in name, f"Arabic 'ي' found in name: {name}"
        assert "ك" not in name, f"Arabic 'ك' found in name: {name}"

        alias = c.get("original_name_alias") or ""
        assert "ي" not in alias, f"Arabic 'ي' found in alias: {alias}"
        assert "ك" not in alias, f"Arabic 'ك' found in alias: {alias}"


# =====================================================================
# 7. Hierarchical Identity Resolution (Levels 1 - 5) Tests
# =====================================================================

def test_hierarchical_resolution_level_1_national_id(resolver):
    """Level 1: Exact National ID resolution."""
    cheque = {
        "national_id": "0927624011",
        "sayadi_id": "4317050049334681",
        "cheque_number": "2999903",
    }
    res = resolver.resolve_cheque_identity(cheque)
    assert res["resolution_level"] == 1
    assert res["customer_id"] == 46  # Zahra Bahrami Pouya
    assert res["confidence"] == "CERTAIN"


def test_hierarchical_resolution_level_2_sayad_id(resolver):
    """Level 2: Sayad ID 16-digit match when National ID is missing."""
    cheque = {
        "national_id": None,
        "sayadi_id": "4317050049334681",  # Bahrami Pouya's Sayad ID
        "cheque_number": "2999903",
    }
    res = resolver.resolve_cheque_identity(cheque)
    assert res["resolution_level"] == 2
    assert res["customer_id"] == 46
    assert res["confidence"] == "CERTAIN"


def test_hierarchical_resolution_level_4_customer_name(resolver):
    """Level 4: Customer name match with Arabic letters normalized."""
    cheque = {
        "national_id": None,
        "sayadi_id": "",
        "cheque_number": "999999",
        "original_name": "وحيد زوار",  # Arabic Yeh
    }
    res = resolver.resolve_cheque_identity(cheque)
    assert res["resolution_level"] == 4
    assert res["customer_id"] == 21  # Vahid Zavvar


def test_hierarchical_resolution_level_5_cheque_serial(resolver):
    """Level 5: Cheque serial match for exempt document."""
    cheque = {
        "national_id": None,
        "sayadi_id": "",
        "cheque_number": "14444",
        "original_name": "",
    }
    res = resolver.resolve_cheque_identity(cheque)
    assert res["resolution_level"] == 5
    assert res["customer_id"] == 8  # Alireza Yaghoubi
    assert res["is_exempt"] is True


# =====================================================================
# 8. Comprehensive Integrity Audit Test
# =====================================================================

def test_audit_identity_integrity(resolver):
    """Assert all integrity audit checks pass without violations."""
    audit = resolver.audit_identity_integrity()
    assert audit["passed"] is True, f"Audit failed: {audit}"
    assert audit["total_customers"] == 48
    assert audit["unresolved_count"] == 4
    assert audit["exempt_documents_count"] == 3
    assert audit["disambiguated_0933387075_count"] == 2
    assert len(audit["invalid_national_ids"]) == 0
    assert audit["total_cheques_count"] == 147
    assert audit["total_fund_amount"] == 483_325_000_000.0


# =====================================================================
# 9. Edge Cases, Helper Queries, & DB Isolation Tests
# =====================================================================

def test_get_customer_by_id(resolver):
    """Test retrieving customer by ID and handling unknown IDs."""
    c2 = resolver.get_customer_by_id(2)
    assert c2 is not None
    assert c2["id"] == 2
    assert "حسین حشمتی" in c2["full_name"]

    assert resolver.get_customer_by_id(99999) is None
    assert resolver.get_customer_by_id(-1) is None


def test_get_customers_by_national_id_edge_cases(resolver):
    """Test national ID lookup with non-existent and empty inputs."""
    assert resolver.get_customers_by_national_id("0000000000") == []
    assert resolver.get_customers_by_national_id("") == []
    assert resolver.get_customers_by_national_id("invalid") == []

    # Single customer lookup
    bahrami = resolver.get_customers_by_national_id("0927624011")
    assert len(bahrami) == 1
    assert bahrami[0]["id"] == 46


def test_resolve_cheque_identity_unresolved_case(resolver):
    """Test resolution fallback when no match is found across all 5 levels."""
    unknown_cheque = {
        "national_id": None,
        "sayadi_id": "",
        "cheque_number": "000999888777",
        "original_name": "ناشناس غیرموجود",
        "bank_name": "بانک فرضی",
    }
    res = resolver.resolve_cheque_identity(unknown_cheque)
    assert res["customer"] is None
    assert res["customer_id"] is None
    assert res["identity_status"] == STATUS_UNRESOLVED_IDENTITY
    assert res["resolution_method"] == "UNRESOLVED"


def test_in_memory_db_isolation(tmp_path):
    """
    Test DB isolation: ensure IdentityResolver can work with an isolated database file
    without touching the production customers.db.
    """
    temp_db = str(tmp_path / "test_isolated.db")
    conn = sqlite3.connect(temp_db)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE customers (
        id INTEGER PRIMARY KEY,
        full_name TEXT,
        national_id TEXT,
        phone TEXT, address TEXT, notes TEXT,
        credit_color TEXT, risk_score INTEGER,
        original_name_alias TEXT, created_at TEXT, updated_at TEXT
    )
    """)
    cur.execute("""
    CREATE TABLE cheques (
        id INTEGER PRIMARY KEY,
        customer_id INTEGER,
        sayadi_id TEXT,
        cheque_number TEXT,
        amount REAL,
        cheque_date TEXT,
        bank_name TEXT,
        original_name TEXT,
        row_number INTEGER,
        holder_id INTEGER,
        status TEXT,
        notes TEXT
    )
    """)
    cur.execute("""
    INSERT INTO customers (id, full_name, national_id)
    VALUES (1, 'علیپور اميرحسين', '0933387075'), (2, 'حسين حشمتي', '0933387075')
    """)
    cur.execute("""
    INSERT INTO cheques (id, customer_id, sayadi_id, cheque_number, amount, bank_name)
    VALUES (1, 1, '', '1113333', 2000000000.0, '* قر سفته'),
           (2, 2, '2380030072556088', '057751', 1060000000.0, '* ايران زمين')
    """)
    conn.commit()
    conn.close()

    iso_resolver = IdentityResolver(db_path=temp_db)
    customers = iso_resolver.get_canonical_customers()
    assert len(customers) == 2
    # Ensure Arabic normalization occurred
    assert "ي" not in customers[0]["full_name"]
    assert "ي" not in customers[1]["full_name"]
    # Ensure disambiguation preserved two distinct records
    nids = iso_resolver.get_customers_by_national_id("0933387075")
    assert len(nids) == 2
    assert {c["id"] for c in nids} == {1, 2}

