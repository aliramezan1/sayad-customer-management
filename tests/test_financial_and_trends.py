# -*- coding: utf-8 -*-
"""
Unit tests for Milestone 2: Financial Separation & Trend/Event Engine.

Covers:
1. Physical Fund Cheques Audit:
   - Exactly 147 cheques.
   - Exactly 483,325,000,000 Rials total.
   - Mathematical zero-discrepancy.
2. Golden Rule of No-Double-Count:
   - Dedup portfolio in-flight: 4,466,069,469,454 Rials.
   - Dedup portfolio bounced: 231,951,000,000 Rials (NOT 604B/677B!).
   - Dedup portfolio cleared: 1,024,305,185,797 Rials.
   - Customer with multiple cheques counted strictly ONCE in portfolio bank aggregation.
   - 12 unique customers with active bounced cheques.
   - 42 customers with valid inquiries.
3. Transition Detection ('in-flight -> bounced'):
   - Zahra Bahrami Pouya (Customer 46, 0927624011): -3.5B in-flight / +3.5B bounced (CERTAIN).
   - Mohammad Rafigh Toroghi (Customer 40): -5.3B in-flight / +5.3B bounced.
   - Vahid Mohammadi Anvar (Customer 18): -3.7B in-flight / +3.7B bounced.
   - Seyed Jamal Mousavi (Customer 4): -1.5B in-flight / +1.5B bounced.
   - Ahmad Zahmatkesh (Customer 16): -1.4B in-flight / +1.4B bounced.
4. Real Clearance Detection ('کاهش برگشتی ≈ افزایش رفع سوءاثر'):
   - Javad Ghafourian Ghalibaf (Customer 11): -1.0B bounced / +1.0B cleared (CERTAIN).
5. Bounce Persistence Classification:
   - Chronic (مزمن): >= 6 periods (Heshmati, Zavar, etc.).
   - Intermittent/Persistent (متناوب/پایدار): 3 to 5 periods (Mousavi).
   - New (رخداد جدید): 1 to 2 periods (Zahra Bahrami Pouya).
   - Clean (بدون برگشتی): 0 periods.
6. Data Freshness Labeling:
   - 6 statuses: FRESH_SUCCESS, REUSED_VALID_SUCCESS, NOT_FOUND, FAILED, EXEMPT, UNRESOLVED_IDENTITY.
   - Values for historical/reused data are NEVER zeroed out.
"""

import pytest
from app.services.financial_aggregator import (
    FinancialAggregator,
    EXPECTED_FUND_CHEQUE_COUNT,
    EXPECTED_FUND_TOTAL_AMOUNT,
    EXPECTED_PORTFOLIO_IN_TRANSIT,
    EXPECTED_PORTFOLIO_BOUNCED,
    EXPECTED_PORTFOLIO_CLEARED,
    EXPECTED_BOUNCED_COUNT,
    EXPECTED_INQUIRED_CUSTOMERS_COUNT,
    EXPECTED_CANONICAL_CUSTOMERS_COUNT,
)
from app.services.trend_detector import (
    TrendDetector,
    classify_bounce_persistence_periods,
    FRESH_SUCCESS,
    REUSED_VALID_SUCCESS,
    NOT_FOUND,
    FAILED,
    EXEMPT,
    UNRESOLVED_IDENTITY,
    PERSISTENCE_CHRONIC,
    PERSISTENCE_INTERMITTENT,
    PERSISTENCE_NEW,
    PERSISTENCE_CLEAN,
)
from app.services.identity_resolver import IdentityResolver


@pytest.fixture
def aggregator():
    """Create a FinancialAggregator instance."""
    return FinancialAggregator()


@pytest.fixture
def trend_detector():
    """Create a TrendDetector instance."""
    return TrendDetector()


# =============================================================================
# 1. Physical Fund Cheques Audit Tests (R2, F6)
# =============================================================================

def test_fund_cheques_exact_count_147(aggregator):
    """Verify that physical fund cheques total exactly 147 documents."""
    cheques = aggregator.get_fund_cheques()
    assert len(cheques) == EXPECTED_FUND_CHEQUE_COUNT, (
        f"Expected {EXPECTED_FUND_CHEQUE_COUNT} cheques, got {len(cheques)}"
    )


def test_fund_cheques_exact_sum_483b(aggregator):
    """Verify that physical fund cheques sum to exactly 483,325,000,000 Rials."""
    cheques = aggregator.get_fund_cheques()
    total_amount = sum(float(ch.get("amount", 0.0)) for ch in cheques)
    assert total_amount == EXPECTED_FUND_TOTAL_AMOUNT, (
        f"Expected {EXPECTED_FUND_TOTAL_AMOUNT} Rials, got {total_amount}"
    )


def test_fund_cheques_audit_method(aggregator):
    """Verify that get_fund_cheques_audit returns zero discrepancy and verified=True."""
    audit = aggregator.get_fund_cheques_audit()
    assert audit["verified"] is True
    assert audit["total_count"] == 147
    assert audit["total_amount"] == 483_325_000_000.0
    assert audit["discrepancy"] == 0.0
    assert audit["concept"] == "PHYSICAL_FUND_COMMITMENTS"


def test_all_fund_cheques_belong_to_canonical_customers(aggregator):
    """Verify that every cheque is properly mapped to a canonical customer ID (1-52)."""
    cheques = aggregator.get_fund_cheques()
    canonical_ids = {c["id"] for c in aggregator.resolver.get_canonical_customers()}
    for ch in cheques:
        assert ch["canonical_customer_id"] in canonical_ids
        assert ch["canonical_customer_name"] is not None
        assert ch["amount"] > 0


# =============================================================================
# 2. Golden Rule of No-Double-Count Tests (R2, F4, F5)
# =============================================================================

def test_portfolio_banking_deduplicated_sums(aggregator):
    """
    Verify Golden Rule of No-Double-Count portfolio banking sums:
    - in-flight: 4,466,069,469,454 Rials
    - bounced: 231,951,000,000 Rials (NOT 604B or 677B!)
    - cleared: 1,024,305,185,797 Rials
    """
    summary = aggregator.get_portfolio_banking_summary()
    assert summary["verified_no_double_count"] is True
    assert summary["total_in_transit"] == EXPECTED_PORTFOLIO_IN_TRANSIT
    assert summary["total_bounced"] == EXPECTED_PORTFOLIO_BOUNCED
    assert summary["total_cleared"] == EXPECTED_PORTFOLIO_CLEARED
    assert summary["unique_customers_count"] == EXPECTED_CANONICAL_CUSTOMERS_COUNT
    assert summary["inquired_customers_count"] == EXPECTED_INQUIRED_CUSTOMERS_COUNT
    assert summary["bounced_customers_count"] == EXPECTED_BOUNCED_COUNT


def test_golden_rule_customer_with_multiple_cheques_counted_once(aggregator):
    """
    Verify that customers with multiple cheques in the fund are NOT multiplied:
    - Mohammad Ziafati (ID 3): 8 cheques in fund, but bounced is 19.16B (counted ONCE, not 8x).
    - Vahid Zavar (ID 21): 5 cheques in fund, but bounced is 46.08B (counted ONCE, not 5x).
    """
    # Mohammad Ziafati
    prof_ziafati = aggregator.get_customer_financial_profile(3)
    assert prof_ziafati is not None
    assert prof_ziafati["fund_cheque_count"] == 8
    assert prof_ziafati["bank_bounced_amount"] == 19_160_000_000.0

    # Vahid Zavar
    prof_zavar = aggregator.get_customer_financial_profile(21)
    assert prof_zavar is not None
    assert prof_zavar["fund_cheque_count"] == 5
    assert prof_zavar["bank_bounced_amount"] == 46_080_000_000.0


def test_audit_no_double_count_mathematical_inflation_proof(aggregator):
    """
    Verify audit_no_double_count demonstrates the artificial inflation caused
    by naive cheque-multiplication and confirms deduplicated portfolio sum.
    """
    audit = aggregator.audit_no_double_count()
    assert audit["passed"] is True
    assert audit["deduplicated"]["bounced"] == 231_951_000_000.0
    assert audit["deduplicated"]["in_transit"] == 4_466_069_469_454.0
    # Naive multiplication produces massive artificial inflation (> 100%)
    assert audit["naive_multiplied"]["bounced"] > 600_000_000_000.0
    assert audit["inflation"]["bounced_pct"] > 100.0


def test_bounced_customers_count_is_exactly_12(aggregator):
    """Verify that exactly 12 unique customers have active bounced cheques."""
    summary = aggregator.get_portfolio_banking_summary()
    assert summary["bounced_customers_count"] == 12

    # Check the 12 customers explicitly
    profiles = aggregator.get_all_customer_financial_profiles()
    bounced_custs = [p for p in profiles if p["bank_bounced_amount"] > 0]
    assert len(bounced_custs) == 12
    total_bounced = sum(p["bank_bounced_amount"] for p in bounced_custs)
    assert total_bounced == 231_951_000_000.0


def test_complete_financial_profiles_separation(aggregator):
    """
    Verify strict separation between physical fund commitments and bank inquiry status.
    Fund commitments (483.325B) are completely separate from banking network status.
    """
    profiles = aggregator.get_all_customer_financial_profiles()
    assert len(profiles) == 48

    total_fund = sum(p["fund_total_amount"] for p in profiles)
    assert total_fund == 483_325_000_000.0

    total_bounced = sum(p["bank_bounced_amount"] for p in profiles)
    assert total_bounced == 231_951_000_000.0


# =============================================================================
# 3. Transition Detection Tests (R3, F8)
# =============================================================================

def test_zahra_bahrami_pouya_transition_detected(trend_detector):
    """
    Verify detection of Zahra Bahrami Pouya (Customer 46, 0927624011):
    - in-flight decreased from 342.33B to 338.83B (-3.5B)
    - bounced increased from 8.8B to 12.3B (+3.5B)
    - balance error == 0 (CERTAIN)
    """
    transitions = trend_detector.detect_transitions()
    zahra_events = [t for t in transitions if t["customer_id"] == 46]
    assert len(zahra_events) == 1, "Zahra Bahrami Pouya transition event must be detected"

    event = zahra_events[0]
    assert event["national_id"] == "0927624011"
    assert event["delta_in_transit"] == -3_500_000_000.0
    assert event["delta_bounced"] == 3_500_000_000.0
    assert event["previous_in_transit"] == 342_330_000_000.0
    assert event["current_in_transit"] == 338_830_000_000.0
    assert event["previous_bounced"] == 8_800_000_000.0
    assert event["current_bounced"] == 12_300_000_000.0
    assert event["balance_error"] == 0.0
    assert event["confidence"] == "CERTAIN"


def test_mohammad_rafigh_toroghi_transition(trend_detector):
    """
    Verify detection of Mohammad Rafigh Toroghi (Customer 40):
    - delta in-transit == -5,300,000,000 Rials (-5.3B)
    - delta bounced == +5,300,000,000 Rials (+5.3B)
    """
    transitions = trend_detector.detect_transitions()
    t_events = [t for t in transitions if t["customer_id"] == 40]
    assert len(t_events) == 1
    event = t_events[0]
    assert event["delta_in_transit"] == -5_300_000_000.0
    assert event["delta_bounced"] == 5_300_000_000.0
    assert event["balance_error"] == 0.0
    assert event["confidence"] == "CERTAIN"


def test_vahid_mohammadi_anvar_transition(trend_detector):
    """
    Verify detection of Vahid Mohammadi Anvar (Customer 18):
    - delta in-transit == -3,700,000,000 Rials (-3.7B)
    - delta bounced == +3,700,000,000 Rials (+3.7B)
    """
    transitions = trend_detector.detect_transitions()
    t_events = [t for t in transitions if t["customer_id"] == 18]
    assert len(t_events) == 1
    event = t_events[0]
    assert event["delta_in_transit"] == -3_700_000_000.0
    assert event["delta_bounced"] == 3_700_000_000.0
    assert event["balance_error"] == 0.0
    assert event["confidence"] == "CERTAIN"


def test_seyed_jamal_mousavi_transition(trend_detector):
    """
    Verify detection of Seyed Jamal Mousavi (Customer 4):
    - delta in-transit == -1,500,000,000 Rials (-1.5B)
    - delta bounced == +1,500,000,000 Rials (+1.5B)
    """
    transitions = trend_detector.detect_transitions()
    t_events = [t for t in transitions if t["customer_id"] == 4]
    assert len(t_events) == 1
    event = t_events[0]
    assert event["delta_in_transit"] == -1_500_000_000.0
    assert event["delta_bounced"] == 1_500_000_000.0
    assert event["balance_error"] == 0.0
    assert event["confidence"] == "CERTAIN"


def test_ahmad_zahmatkesh_transition(trend_detector):
    """
    Verify detection of Ahmad Zahmatkesh (Customer 16):
    - delta in-transit == -1,400,000,000 Rials (-1.4B)
    - delta bounced == +1,400,000,000 Rials (+1.4B)
    """
    transitions = trend_detector.detect_transitions()
    t_events = [t for t in transitions if t["customer_id"] == 16]
    assert len(t_events) == 1
    event = t_events[0]
    assert event["delta_in_transit"] == -1_400_000_000.0
    assert event["delta_bounced"] == 1_400_000_000.0
    assert event["balance_error"] == 0.0
    assert event["confidence"] == "CERTAIN"


def test_transitions_count_and_sorting(trend_detector):
    """Verify that all 5 key transitions are detected and sorted by amount descending."""
    transitions = trend_detector.detect_transitions()
    assert len(transitions) == 5
    # Order: Toroghi (5.3B) > Mohammadi (3.7B) > Bahrami (3.5B) > Mousavi (1.5B) > Zahmatkesh (1.4B)
    amounts = [t["transition_amount"] for t in transitions]
    assert amounts == sorted(amounts, reverse=True)
    assert amounts[0] == 5_300_000_000.0
    assert amounts[-1] == 1_400_000_000.0


# =============================================================================
# 4. Real Clearance Detection Tests (R3, F9)
# =============================================================================

def test_javad_ghafourian_clearance_event(trend_detector):
    """
    Verify detection of real clearance for Javad Ghafourian Ghalibaf (Customer 11):
    - delta bounced == -1,000,000,000 Rials (-1.0B)
    - delta cleared == +1,000,000,000 Rials (+1.0B)
    - balance error == 0 (CERTAIN)
    """
    clearances = trend_detector.detect_clearances()
    c_events = [c for c in clearances if c["customer_id"] == 11]
    assert len(c_events) == 1, "Javad Ghafourian clearance event must be detected"

    event = c_events[0]
    assert event["delta_bounced"] == -1_000_000_000.0
    assert event["delta_cleared"] == 1_000_000_000.0
    assert event["previous_bounced"] == 1_000_000_000.0
    assert event["current_bounced"] == 0.0
    assert event["previous_cleared"] == 13_295_000_000.0
    assert event["current_cleared"] == 14_295_000_000.0
    assert event["balance_error"] == 0.0
    assert event["confidence"] == "CERTAIN"


def test_detect_events_master_method(trend_detector):
    """Verify master detect_events method returns both transitions and clearances."""
    events = trend_detector.detect_events()
    event_types = {e["event_type"] for e in events}
    assert "IN_FLIGHT_TO_BOUNCED" in event_types
    assert "REAL_CLEARANCE" in event_types
    assert len(events) >= 6


# =============================================================================
# 5. Bounce Persistence Classification Tests (R3, F10)
# =============================================================================

def test_classify_bounce_persistence_all_four_categories():
    """Verify classify_bounce_persistence_periods covers all 4 required categories."""
    # 1. Chronic (>= 6)
    c6 = classify_bounce_persistence_periods(6)
    assert c6["category"] == PERSISTENCE_CHRONIC
    assert c6["code"] == "CHRONIC"
    assert "مزمن" in c6["persian_label"]

    c10 = classify_bounce_persistence_periods(10)
    assert c10["category"] == PERSISTENCE_CHRONIC

    # 2. Intermittent/Persistent (3 to 5)
    c3 = classify_bounce_persistence_periods(3)
    assert c3["category"] == PERSISTENCE_INTERMITTENT
    assert c3["code"] == "INTERMITTENT"
    assert "متناوب" in c3["persian_label"]

    c5 = classify_bounce_persistence_periods(5)
    assert c5["category"] == PERSISTENCE_INTERMITTENT

    # 3. New (1 to 2)
    c1 = classify_bounce_persistence_periods(1)
    assert c1["category"] == PERSISTENCE_NEW
    assert c1["code"] == "NEW"
    assert "جدید" in c1["persian_label"]

    c2 = classify_bounce_persistence_periods(2)
    assert c2["category"] == PERSISTENCE_NEW

    # 4. Clean (0)
    c0 = classify_bounce_persistence_periods(0)
    assert c0["category"] == PERSISTENCE_CLEAN
    assert c0["code"] == "CLEAN"
    assert "بدون برگشتی" in c0["persian_label"]


def test_zahra_bahrami_pouya_is_new_bounce(trend_detector):
    """Verify Zahra Bahrami Pouya (Customer 46) is classified as NEW bounce (1 period)."""
    p = trend_detector.classify_bounce_persistence(46)
    assert p["category"] == PERSISTENCE_NEW
    assert p["period_count"] == 1


def test_seyed_jamal_mousavi_is_intermittent(trend_detector):
    """Verify Seyed Jamal Mousavi (Customer 4) is classified as INTERMITTENT (5 periods)."""
    p = trend_detector.classify_bounce_persistence(4)
    assert p["category"] == PERSISTENCE_INTERMITTENT
    assert p["period_count"] == 5


def test_chronic_customers(trend_detector):
    """Verify major chronic bounce customers (Heshmati, Zavar, Ziafati, Toroghi)."""
    for cid in (2, 21, 3, 40):
        p = trend_detector.classify_bounce_persistence(cid)
        assert p["category"] == PERSISTENCE_CHRONIC, (
            f"Customer {cid} expected CHRONIC, got {p['category']} (periods: {p['period_count']})"
        )
        assert p["period_count"] >= 6


def test_clean_customers(trend_detector):
    """Verify clean customers have 0 periods and CLEAN category."""
    # Javad Hemmati (6), Ali Yaghoubi (8)
    for cid in (6, 8):
        p = trend_detector.classify_bounce_persistence(cid)
        assert p["category"] == PERSISTENCE_CLEAN
        assert p["period_count"] == 0


# =============================================================================
# 6. Data Freshness Labeling Tests (R3, F7)
# =============================================================================

def test_freshness_statuses_defined():
    """Verify all 6 required freshness statuses are exported."""
    statuses = {FRESH_SUCCESS, REUSED_VALID_SUCCESS, NOT_FOUND, FAILED, EXEMPT, UNRESOLVED_IDENTITY}
    assert len(statuses) == 6


def test_unresolved_identities_freshness_tag(trend_detector):
    """Verify that customers lacking national ID are labeled UNRESOLVED_IDENTITY (IDs 7, 13, 26, 29)."""
    for cid in (7, 13, 26, 29):
        f = trend_detector.get_customer_freshness(cid)
        assert f["status"] == UNRESOLVED_IDENTITY, (
            f"Customer {cid} expected UNRESOLVED_IDENTITY, got {f['status']}"
        )


def test_exempt_customer_freshness_tag(trend_detector):
    """Verify Amirhossein Alipour (Customer 1, promissory note 1113333) is labeled EXEMPT."""
    f = trend_detector.get_customer_freshness(1)
    assert f["status"] == EXEMPT, f"Customer 1 expected EXEMPT, got {f['status']}"


def test_reused_valid_success_preserves_values_not_zeroed(trend_detector):
    """
    Verify historical data values are strictly NOT ZEROED OUT:
    Customer 4 (Seyed Jamal Mousavi) has latest inquiry on 2026-09-05.
    Must be labeled REUSED_VALID_SUCCESS with positive amounts preserved.
    """
    f = trend_detector.get_customer_freshness(4)
    assert f["status"] == REUSED_VALID_SUCCESS
    assert f["is_historical"] is True
    assert f["inquiry_time"] is not None
    # CRITICAL: historical values must NOT be zero
    assert f["amounts"]["in_transit"] > 0
    assert f["amounts"]["bounced"] > 0
    assert f["amounts"]["cleared"] > 0
    assert f["amounts"]["bounced"] == 2_800_000_000.0


def test_fresh_success_tag(trend_detector):
    """Verify customers inquired on reference date are labeled FRESH_SUCCESS."""
    # Hossein Heshmati (Customer 2) was inquired on 2026-09-06
    f = trend_detector.get_customer_freshness(2)
    assert f["status"] == FRESH_SUCCESS
    assert f["is_historical"] is False
    assert f["amounts"]["bounced"] == 56_960_000_000.0


def test_all_canonical_customers_have_valid_freshness(trend_detector):
    """Verify all 48 canonical customers have one of the 6 defined freshness statuses."""
    freshness_map = trend_detector.get_all_customer_freshness()
    assert len(freshness_map) == 48

    valid_statuses = {FRESH_SUCCESS, REUSED_VALID_SUCCESS, NOT_FOUND, FAILED, EXEMPT, UNRESOLVED_IDENTITY}
    for cid, f in freshness_map.items():
        assert f["status"] in valid_statuses, f"Customer {cid} has invalid status {f['status']}"
