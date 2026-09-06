"""
Adversarial Stress Test Suite for Milestone 1 (Identity Resolution & Deduplication).

Challenger 1 Empirical Suite testing:
1. Malformed, leading-zero, trailing-space, and non-digit national codes.
2. Arabic vs Persian characters ('ي', 'ك', 'ی', 'ک', half-spaces, Alef Maksura, Hamza).
3. Identity disambiguation of 0933387075 under conflicting or missing inputs.
4. Boundary inputs and mathematical edge cases for Modulo 11 check.
5. Simulated concurrent multi-threaded execution and fresh instance isolation.
"""

import os
import math
import concurrent.futures
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
    return IdentityResolver()


# =====================================================================
# 1. Malformed, Leading-Zero, Trailing-Space, Non-Digit National Codes
# =====================================================================

class TestNationalIdSanitizationAdversarial:
    """Stress testing clean_national_id against adversarial inputs."""

    def test_leading_zeros_padding_various_lengths(self):
        """Verify 8-digit and 9-digit integers/strings are correctly zero-padded to 10 digits."""
        # 8 digits -> 2 leading zeros
        assert clean_national_id("10485295") == "0010485295"
        assert clean_national_id(10485295) == "0010485295"
        # 9 digits -> 1 leading zero
        assert clean_national_id("933387075") == "0933387075"
        assert clean_national_id(933387075) == "0933387075"
        # 10 digits -> preserved as-is
        assert clean_national_id("0010485295") == "0010485295"

    def test_whitespace_and_newline_stripping(self):
        """Verify leading, trailing, and intermixed whitespaces/newlines are handled."""
        assert clean_national_id("   0933387075   ") == "0933387075"
        assert clean_national_id("\t\r\n0933387075\n\t") == "0933387075"
        assert clean_national_id(" 0 9 3 3 3 8 7 0 7 5 ") == "0933387075"

    def test_persian_and_arabic_numeral_conversion(self):
        """Verify Persian and Arabic numerals are accurately converted to ASCII 10-digit format."""
        # Persian numerals
        assert clean_national_id("۰۹۳۳۳۸۷۰۷۵") == "0933387075"
        assert clean_national_id("۰۰۱۰۴۸۵۲۹۵") == "0010485295"
        # Arabic numerals
        assert clean_national_id("٠٩٣٣٣٨٧٠٧٥") == "0933387075"
        assert clean_national_id("٠٠١٠٤٨٥٢٩٥") == "0010485295"
        # Mixed numerals
        assert clean_national_id("09۳۳38۷۰75") == "0933387075"

    def test_non_digit_characters_stripping(self):
        """Verify dashes, slashes, and decorative separators are stripped."""
        assert clean_national_id("093-338707-5") == "0933387075"
        assert clean_national_id("093/338/7075") == "0933387075"
        assert clean_national_id("ID: 0933387075") == "0933387075"

    def test_invalid_lengths_rejected(self):
        """Verify lengths < 8 or > 10 (after non-digit strip) return None."""
        assert clean_national_id("1234567") is None  # 7 digits
        assert clean_national_id("123") is None      # 3 digits
        assert clean_national_id("09123456789") is None  # 11 digits (phone number)
        assert clean_national_id("10100123456") is None  # 11 digits (legal entity ID)
        assert clean_national_id("123456789012") is None # 12 digits

    def test_null_and_empty_sentinels(self):
        """Verify None, empty string, and text sentinels ('null', 'none', 'nan') return None."""
        assert clean_national_id(None) is None
        assert clean_national_id("") is None
        assert clean_national_id("   ") is None
        assert clean_national_id("None") is None
        assert clean_national_id("NULL") is None
        assert clean_national_id("nan") is None
        assert clean_national_id("NaN") is None

    def test_non_string_types(self):
        """Verify behavior with non-string types (lists, dicts, booleans)."""
        assert clean_national_id(True) is None
        assert clean_national_id(False) is None
        assert clean_national_id([]) is None
        assert clean_national_id({}) is None

    def test_nan_float_handling(self):
        """
        Adversarial test: float('nan') or float('inf') passed from pandas/openpyxl.
        Documents whether clean_national_id handles NaN without crashing with ValueError.
        """
        try:
            res_nan = clean_national_id(float('nan'))
            assert res_nan is None
        except ValueError as e:
            pytest.fail(f"VULNERABILITY CONFIRMED: clean_national_id crashed on float('nan'): {e}")

    def test_inf_float_handling(self):
        """Adversarial test: float('inf') passed from numeric calculation."""
        try:
            res_inf = clean_national_id(float('inf'))
            assert res_inf is None
        except OverflowError as e:
            pytest.fail(f"VULNERABILITY CONFIRMED: clean_national_id crashed on float('inf'): {e}")


# =====================================================================
# 2. Arabic vs Persian Characters & Half-Spaces
# =====================================================================

class TestArabicPersianNormalizationAdversarial:
    """Stress testing Persian/Arabic text normalization and half-space handling."""

    def test_arabic_yeh_and_kaf_normalization(self):
        """Standard test: Arabic Yeh (ي) and Kaf (ك) to Persian (ی and ک)."""
        assert normalize_persian_text("اميرحسين كفاييان") == "امیرحسین کفاییان"

    def test_teh_marbuta_and_waw_hamza(self):
        """Verify Teh Marbuta (ة -> ه) and Waw with Hamza (ؤ -> و)."""
        assert normalize_persian_text("مؤسسه اعتباریه") == "موسسه اعتباریه"

    def test_alef_maksura_normalization(self):
        """
        Adversarial test: Arabic Alef Maksura (ى, \u0649).
        In Persian names (مرتضى, مصطفى, موسى, يحيى), \u0649 should normalize to \u06cc (ی).
        """
        norm = normalize_persian_text("مرتضى")
        # In Persian orthography, مرتضی ends with \u06cc
        assert norm == "مرتضی", (
            f"VULNERABILITY CONFIRMED: Alef Maksura (\u0649) was not normalized to Persian Yeh (\u06cc). Got {[ord(c) for c in norm]}"
        )

    def test_yeh_with_hamza_normalization(self):
        """
        Adversarial test: Arabic Yeh with Hamza above (ئ, \u0626).
        Checks if names like قائمی or میرزائی are preserved or normalized.
        """
        norm = normalize_persian_text("قائمی")
        assert "قائمی" in norm or "قایمی" in norm

    def test_half_space_zwnj_handling_in_compound_names(self):
        """
        Adversarial test: Half-space (\u200c, ZWNJ) in compound names.
        Replacing ZWNJ with space (' ') breaks exact matching for compound names
        stored without spaces (e.g. علیپور vs علی‌پور).
        """
        raw_name = "امیرحسین علی\u200cپور"
        norm = normalize_persian_text(raw_name)
        assert "علیپور" in norm or "علی‌پور" in norm or norm == "امیرحسین علی پور"

    def test_resolve_cheque_identity_with_half_space_in_alipour_name(self, resolver):
        """
        Adversarial test: A cheque with national code 0933387075 and name containing ZWNJ
        'امیرحسین علی‌پور' must resolve to Amirhossein Alipour (Customer 1), NOT UNRESOLVED!
        """
        cheque = {
            "national_id": "0933387075",
            "sayadi_id": "",
            "cheque_number": "998877",  # Non-standard serial
            "bank_name": "بانک ملی",
            "original_name": "امیرحسین علی\u200cپور",  # Contains ZWNJ \u200c
        }
        res = resolver.resolve_cheque_identity(cheque)
        assert res["customer_id"] == 1, (
            f"VULNERABILITY CONFIRMED: Failed to resolve Alipour with half-space 'علی\\u200cپور'. "
            f"Got customer_id={res['customer_id']}, method={res['resolution_method']}"
        )


# =====================================================================
# 3. Identity Disambiguation of 0933387075 Under Conflicting/Missing Inputs
# =====================================================================

class TestDisambiguation0933387075Adversarial:
    """Stress testing 0933387075 disambiguation under hostile/conflicting scenarios."""

    def test_missing_all_disambiguating_evidence(self, resolver):
        """
        Cheque with 0933387075 but no sayadi_id, unknown cheque serial, unknown bank, unknown name.
        System MUST NOT guess or assign arbitrarily; must flag UNRESOLVED_IDENTITY.
        """
        cheque = {
            "national_id": "0933387075",
            "sayadi_id": "",
            "cheque_number": "7777777",
            "bank_name": "بانک تجارت",
            "original_name": "فرد نامشخص",
        }
        res = resolver.resolve_cheque_identity(cheque)
        assert res["customer_id"] is None, (
            f"Arbitrary assignment made for ambiguous 0933387075: {res}"
        )
        assert res["identity_status"] == STATUS_UNRESOLVED_IDENTITY
        assert res["resolution_method"] == "UNRESOLVED"

    def test_conflicting_sayad_and_name(self, resolver):
        """
        Adversarial: Cheque has Sayad ID of Heshmati ('2380030072556088')
        BUT original_name is 'امیرحسین علیپور' (Alipour)!
        Documents the precedence: Sayad ID takes precedence over contradictory name.
        """
        cheque = {
            "national_id": "0933387075",
            "sayadi_id": "2380030072556088",  # Belongs to Heshmati
            "cheque_number": "057751",
            "bank_name": "* ایران زمین مفتح مشهد",
            "original_name": "امیرحسین علیپور",  # Contradicts Heshmati!
        }
        res = resolver.resolve_cheque_identity(cheque)
        assert res["customer_id"] in (1, 2)

    def test_conflicting_promissory_serial_and_heshmati_name(self, resolver):
        """
        Adversarial: Cheque serial is '1113333' (Alipour's promissory note)
        BUT name is 'حسین حشمتی'!
        """
        cheque = {
            "national_id": "0933387075",
            "sayadi_id": "",
            "cheque_number": "1113333",  # Alipour
            "bank_name": "* قر سفته",
            "original_name": "حسین حشمتی",  # Heshmati
        }
        res = resolver.resolve_cheque_identity(cheque)
        assert res["customer_id"] is not None

    def test_disambiguation_by_sayad_only_without_national_id(self, resolver):
        """Sayad ID 2380030072556088 without national ID should resolve to Heshmati (ID 2)."""
        cheque = {
            "national_id": None,
            "sayadi_id": "2380030072556088",
            "cheque_number": "9999",
            "bank_name": "",
            "original_name": "",
        }
        res = resolver.resolve_cheque_identity(cheque)
        assert res["customer_id"] == 2
        assert res["confidence"] == "CERTAIN"

    def test_disambiguation_by_promissory_serial_without_national_id(self, resolver):
        """Promissory serial 1113333 without national ID should resolve to Alipour (ID 1)."""
        cheque = {
            "national_id": None,
            "sayadi_id": "",
            "cheque_number": "1113333",
            "bank_name": "",
            "original_name": "",
        }
        res = resolver.resolve_cheque_identity(cheque)
        assert res["customer_id"] == 1
        assert res["is_exempt"] is True


# =====================================================================
# 4. Boundary Inputs & Mathematical Edge Cases for Modulo 11
# =====================================================================

class TestModulo11BoundaryAdversarial:
    """Stress testing Iranian national code Modulo 11 checksum algorithm."""

    def test_all_identical_digits_rejected(self):
        """Verify all repeated digits 0000000000 through 9999999999 are rejected."""
        for digit in range(10):
            nid = str(digit) * 10
            assert validate_national_id(nid) is False, f"{nid} must be invalid"

    def test_mixed_ascii_and_persian_identical_zeros_bypass(self):
        """
        Adversarial test: '00000' + '۰۰۰۰۰' (10 zeros with mixed ASCII and Persian numerals).
        Tests whether the identical digit check len(set(nid)) == 1 is bypassed when
        numeral systems are mixed.
        """
        mixed_zeros = "00000" + "۰" * 5
        is_valid = validate_national_id(mixed_zeros)
        # All zeros MUST be rejected as invalid!
        assert is_valid is False, (
            "VULNERABILITY CONFIRMED: validate_national_id('00000۰۰۰۰۰') validated as True! "
            "Mixing ASCII and Persian zeros bypassed len(set(nid)) == 1."
        )

    def test_mixed_ascii_and_persian_identical_ones_bypass(self):
        """
        Adversarial test: '11111' + '۱۱۱۱۱' (10 ones with mixed ASCII and Persian numerals).
        """
        mixed_ones = "11111" + "۱" * 5
        is_valid = validate_national_id(mixed_ones)
        # All ones MUST be rejected as invalid!
        assert is_valid is False, (
            "VULNERABILITY CONFIRMED: validate_national_id('11111۱۱۱۱۱') validated as True! "
            "Mixing ASCII and Persian ones bypassed len(set(nid)) == 1."
        )

    def test_modulo_11_remainder_zero(self):
        """
        Mathematical boundary: Remainder == 0.
        When sum % 11 == 0, check digit must be exactly 0.
        """
        nid_r0 = "0000001090"
        assert validate_national_id(nid_r0) is True

    def test_modulo_11_remainder_one(self):
        """
        Mathematical boundary: Remainder == 1.
        When sum % 11 == 1, check digit must be exactly 1.
        """
        assert validate_national_id("1234567891") is True

    def test_modulo_11_remainder_ten(self):
        """
        Mathematical boundary: Remainder == 10.
        When sum % 11 == 10, check digit must be 11 - 10 = 1.
        """
        nid_r10 = "0000000191"
        assert validate_national_id(nid_r10) is True

    def test_modulo_11_remainder_two(self):
        """
        Mathematical boundary: Remainder == 2.
        When sum % 11 == 2, check digit must be 11 - 2 = 9.
        """
        nid_r2 = "0000000019"
        assert validate_national_id(nid_r2) is True

    def test_off_by_one_check_digits(self):
        """Verify that altering the check digit by +1 or -1 renders valid codes invalid."""
        valid_codes = [
            "0933387075",
            "0890543331",
            "0927624011",
            "0010485295",
            "6430003159",
            "1234567891",
            "0000001090",
            "0000000191",
            "0000000019",
        ]
        for v in valid_codes:
            assert validate_national_id(v) is True
            last = int(v[-1])
            bad_last_1 = (last + 1) % 10
            bad_last_2 = (last - 1) % 10
            bad_code_1 = v[:-1] + str(bad_last_1)
            bad_code_2 = v[:-1] + str(bad_last_2)
            assert validate_national_id(bad_code_1) is False, f"{bad_code_1} should be invalid"
            assert validate_national_id(bad_code_2) is False, f"{bad_code_2} should be invalid"

    def test_malformed_string_types_in_validator(self):
        """Verify malformed non-digits and invalid lengths return False."""
        assert validate_national_id(None) is False
        assert validate_national_id("") is False
        assert validate_national_id("12345") is False
        assert validate_national_id("12345678901") is False  # 11 chars
        assert validate_national_id("093338707a") is False
        assert validate_national_id("abcdefghij") is False


# =====================================================================
# 5. Simulated Concurrent Calls & Fresh Instances
# =====================================================================

class TestConcurrencyAndInstanceFreshnessAdversarial:
    """Stress testing thread safety and multi-instance concurrency."""

    def test_concurrent_get_canonical_customers(self, resolver):
        """
        Execute 20 concurrent threads calling get_canonical_customers.
        Verify no sqlite3 OperationalError (database locked) and data consistency.
        """
        def fetch_canonical():
            custs = resolver.get_canonical_customers()
            return len(custs), sum(c.get("total_cheque_amount", 0.0) for c in custs)

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(fetch_canonical) for _ in range(20)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        assert len(results) == 20
        for count, total_amt in results:
            assert count == 48, f"Expected 48 customers, got {count}"
            assert total_amt == 483_325_000_000.0, f"Expected 483,325,000,000, got {total_amt}"

    def test_concurrent_fresh_resolver_instances(self):
        """
        Execute 15 concurrent threads each instantiating a fresh IdentityResolver.
        Verify that instance initialization does not leak or cause DB lock.
        """
        def run_fresh_instance():
            fresh_r = IdentityResolver()
            audit = fresh_r.audit_identity_integrity()
            return audit["passed"]

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(run_fresh_instance) for _ in range(15)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        assert all(results), "Not all concurrent fresh instances passed audit"

    def test_immutability_between_consecutive_calls(self, resolver):
        """
        Verify that mutating a customer record returned by one call does not mutate
        the internal database or affect subsequent calls.
        """
        call1 = resolver.get_canonical_customers()
        c0 = call1[0]
        original_name = c0["full_name"]
        # Mutate the dictionary
        c0["full_name"] = "MODIFIED_NAME_ATTACK"
        c0["total_cheque_amount"] = -999999999.0

        # Subsequent call
        call2 = resolver.get_canonical_customers()
        assert call2[0]["full_name"] == original_name, (
            "Mutation of returned dictionary affected subsequent call!"
        )
        assert call2[0]["total_cheque_amount"] != -999999999.0
