# -*- coding: utf-8 -*-
"""
Unit and Integration Tests for Milestone 3: Risk Scoring & Concentration Engine (R4, F11, F12, F13).

Tests:
1. Exact 7-component formula weighting and scaling (F11):
   - Current bounced amount (30%)
   - Number of periods with bounced debt (20%)
   - Recent bounced increase (15%)
   - Ratio of bounced to active commitment (15%)
   - Rapid in-flight growth (10%)
   - Volatility / instability (5%)
   - Data quality / freshness penalty (5%)
2. All 6 mandatory floors individually with boundary cases (F12):
   - Floor 1: Bounced > 50B and persistent (>= 3 periods) -> min 85 (e.g. Hossein Heshmati)
   - Floor 2: Bounced > 20B and persistent (>= 3 periods) -> min 78 (e.g. Vahid Zavar, Toroghi, Vafadar)
   - Floor 3: Bounced > 10B and persistent (>= 3 periods) -> min 72 (e.g. Ziafati, Zahmatkesh)
   - Floor 4: Bounced > 5B and persistent (>= 3 periods) -> min 65 (e.g. Zahedi, Ashrafian)
   - Floor 5: Bounced > 0 and persistent (>= 3 periods) -> min 45 (e.g. Mohammadi Anvar, Mousavi, Deljou)
   - Floor 6: New non-persistent bounced (> 0 and 1-2 periods) -> min 35 (e.g. Zahra Bahrami Pouya)
3. 5 risk tiers mapping and action recommendations (F13):
   - Low (0 to 20): کم‌ریسک
   - Normal (21 to 40): عادی
   - Watch (41 to 60): مراقبت
   - High (61 to 80): پرریسک
   - Immediate Action (81 to 100): اقدام فوری
4. HHI concentration calculation and Top 10 issuers list (F13):
   - Total deduplicated bounced: 231,951,000,000 Rials
   - Top 10 bounced total: 227,825,000,000 Rials
   - Top 10 concentration: ~98.22%
   - HHI index: ~1536.4
5. Full customer scoring across all 48 canonical customers.
"""

import pytest
from typing import Dict, Any

from app.services.risk_engine import (
    RiskEngine,
    calculate_customer_risk,
    compute_hhi_concentration,
    get_top_10_issuers,
    evaluate_mandatory_floor,
    classify_risk_tier,
    compute_component_bounced_amount,
    compute_component_persistence_periods,
    compute_component_recent_bounced_increase,
    compute_component_bounced_ratio,
    compute_component_in_flight_growth,
    compute_component_volatility,
    compute_component_data_quality,
    WEIGHT_CURRENT_BOUNCED,
    WEIGHT_PERSISTENCE_PERIODS,
    WEIGHT_RECENT_BOUNCED_INCREASE,
    WEIGHT_BOUNCED_TO_ACTIVE_RATIO,
    WEIGHT_RAPID_IN_FLIGHT_GROWTH,
    WEIGHT_VOLATILITY,
    WEIGHT_DATA_QUALITY,
    FLOOR_50B_PERSISTENT,
    FLOOR_20B_PERSISTENT,
    FLOOR_10B_PERSISTENT,
    FLOOR_5B_PERSISTENT,
    FLOOR_POS_PERSISTENT,
    FLOOR_NEW_NON_PERSISTENT,
    TIER_LOW,
    TIER_NORMAL,
    TIER_WATCH,
    TIER_HIGH,
    TIER_IMMEDIATE_ACTION,
    RECOMMENDATION_IMMEDIATE_ACTION,
    RECOMMENDATION_HIGH,
    RECOMMENDATION_WATCH,
    RECOMMENDATION_NORMAL,
    RECOMMENDATION_LOW,
)


@pytest.fixture
def risk_engine():
    """Provides an initialized RiskEngine instance."""
    return RiskEngine()


# =============================================================================
# 1. Formula Weighting & Component Normalization Tests (F11)
# =============================================================================

def test_weights_sum_to_exact_unity():
    """Verify that the 7 component weights sum exactly to 1.00 (100%)."""
    total_weight = (
        WEIGHT_CURRENT_BOUNCED
        + WEIGHT_PERSISTENCE_PERIODS
        + WEIGHT_RECENT_BOUNCED_INCREASE
        + WEIGHT_BOUNCED_TO_ACTIVE_RATIO
        + WEIGHT_RAPID_IN_FLIGHT_GROWTH
        + WEIGHT_VOLATILITY
        + WEIGHT_DATA_QUALITY
    )
    assert abs(total_weight - 1.00) < 1e-9
    assert WEIGHT_CURRENT_BOUNCED == 0.30
    assert WEIGHT_PERSISTENCE_PERIODS == 0.20
    assert WEIGHT_RECENT_BOUNCED_INCREASE == 0.15
    assert WEIGHT_BOUNCED_TO_ACTIVE_RATIO == 0.15
    assert WEIGHT_RAPID_IN_FLIGHT_GROWTH == 0.10
    assert WEIGHT_VOLATILITY == 0.05
    assert WEIGHT_DATA_QUALITY == 0.05


def test_component_1_bounced_amount_scale():
    """Verify Component 1 (30% weight) scales linearly up to 50B Rials and caps at 100."""
    assert compute_component_bounced_amount(0.0) == 0.0
    assert compute_component_bounced_amount(-1000.0) == 0.0
    assert compute_component_bounced_amount(25_000_000_000.0) == 50.0
    assert compute_component_bounced_amount(50_000_000_000.0) == 100.0
    # Over 50B caps at 100
    assert compute_component_bounced_amount(60_000_000_000.0) == 100.0
    assert compute_component_bounced_amount(100_000_000_000.0) == 100.0


def test_component_2_persistence_periods_scale():
    """Verify Component 2 (20% weight) scales linearly up to 10 periods and caps at 100."""
    assert compute_component_persistence_periods(0) == 0.0
    assert compute_component_persistence_periods(-1) == 0.0
    assert compute_component_persistence_periods(1) == 10.0
    assert compute_component_persistence_periods(5) == 50.0
    assert compute_component_persistence_periods(10) == 100.0
    assert compute_component_persistence_periods(15) == 100.0
    # If customer explicitly has 0 bounced debt, active persistence is 0
    assert compute_component_persistence_periods(8, bounced_amount=0.0) == 0.0
    assert compute_component_persistence_periods(8, bounced_amount=1_000_000.0) == 80.0


def test_component_3_recent_bounced_increase_scale():
    """Verify Component 3 (15% weight) scales linearly up to 5B Rials and caps at 100."""
    assert compute_component_recent_bounced_increase(0.0) == 0.0
    assert compute_component_recent_bounced_increase(-500_000_000.0) == 0.0
    assert compute_component_recent_bounced_increase(2_500_000_000.0) == 50.0
    assert compute_component_recent_bounced_increase(5_000_000_000.0) == 100.0
    # Real transition values: +5.3B (Toroghi) and +3.5B (Bahrami Pouya)
    assert compute_component_recent_bounced_increase(5_300_000_000.0) == 100.0
    assert compute_component_recent_bounced_increase(3_500_000_000.0) == 70.0


def test_component_4_bounced_to_active_ratio_scale():
    """
    Verify Component 4 (15% weight) computes ratio = bounced / (fund + in_transit).
    Ratio >= 1.0 gives 100.0.
    """
    # 0 bounced -> 0
    assert compute_component_bounced_ratio(0.0, 100_000_000_000.0) == 0.0
    # 20B bounced / 100B active -> 20% -> 20.0
    assert compute_component_bounced_ratio(20_000_000_000.0, 100_000_000_000.0) == 20.0
    # 50B bounced / 100B active -> 50% -> 50.0
    assert compute_component_bounced_ratio(50_000_000_000.0, 100_000_000_000.0) == 50.0
    # 100B bounced / 100B active -> 100% -> 100.0
    assert compute_component_bounced_ratio(100_000_000_000.0, 100_000_000_000.0) == 100.0
    # 150B bounced / 100B active -> 100.0 (capped)
    assert compute_component_bounced_ratio(150_000_000_000.0, 100_000_000_000.0) == 100.0
    # Denominator == 0 with bounced > 0 -> 100.0
    assert compute_component_bounced_ratio(10_000_000_000.0, 0.0) == 100.0
    # Denominator == 0 with bounced == 0 -> 0.0
    assert compute_component_bounced_ratio(0.0, 0.0) == 0.0


def test_component_5_in_flight_growth_scale():
    """Verify Component 5 (10% weight) scales linearly up to 10B Rials."""
    assert compute_component_in_flight_growth(0.0) == 0.0
    assert compute_component_in_flight_growth(-1_000_000.0) == 0.0
    assert compute_component_in_flight_growth(2_000_000_000.0) == 20.0
    assert compute_component_in_flight_growth(5_000_000_000.0) == 50.0
    assert compute_component_in_flight_growth(10_000_000_000.0) == 100.0
    assert compute_component_in_flight_growth(15_000_000_000.0) == 100.0


def test_component_6_volatility_scale():
    """Verify Component 6 (5% weight) properly normalizes volatility metrics."""
    assert compute_component_volatility(0.0) == 0.0
    assert compute_component_volatility(-0.5) == 0.0
    # CV as ratio in [0, 1]
    assert compute_component_volatility(0.25) == 25.0
    assert compute_component_volatility(0.50) == 50.0
    assert compute_component_volatility(1.00) == 100.0
    # Direct scale > 1
    assert compute_component_volatility(42.5) == 42.5
    assert compute_component_volatility(150.0) == 100.0


def test_component_7_data_quality_penalties():
    """Verify Component 7 (5% weight) correctly assesses data quality penalties."""
    # UNRESOLVED_IDENTITY -> 100
    assert compute_component_data_quality(identity_status="UNRESOLVED_IDENTITY") == 100.0
    # FAILED inquiry -> 100
    assert compute_component_data_quality(freshness_status="FAILED") == 100.0
    # NOT_FOUND inquiry -> 80
    assert compute_component_data_quality(freshness_status="NOT_FOUND") == 80.0
    # REUSED_VALID_SUCCESS -> 30
    assert compute_component_data_quality(freshness_status="REUSED_VALID_SUCCESS") == 30.0
    # EXEMPT document -> 10
    assert compute_component_data_quality(freshness_status="EXEMPT") == 10.0
    # FRESH_SUCCESS -> 0
    assert compute_component_data_quality(identity_status="VERIFIED", freshness_status="FRESH_SUCCESS") == 0.0


# =============================================================================
# 2. Mandatory Score Floors Individual & Boundary Tests (F12)
# =============================================================================

def test_floor_1_over_50b_persistent():
    """
    Floor 1: Bounced > 50B Rials and persistent (>= 3 periods) -> min score 85.
    Boundary tests at 50B threshold and persistence thresholds.
    """
    # 1. Just above threshold: 50,000,000,001 with 3 periods -> Floor 85
    f, rule = evaluate_mandatory_floor(50_000_000_001.0, 3)
    assert f == FLOOR_50B_PERSISTENT
    assert rule == "BOUNCED_OVER_50B_PERSISTENT"

    # 2. High persistence: 56.96B with 8 periods (Hossein Heshmati) -> Floor 85
    f, rule = evaluate_mandatory_floor(56_960_000_000.0, 8)
    assert f == FLOOR_50B_PERSISTENT
    assert rule == "BOUNCED_OVER_50B_PERSISTENT"

    # 3. Exact boundary: 50,000,000,000 is NOT > 50B -> Falls to Floor 2 (78)
    f, rule = evaluate_mandatory_floor(50_000_000_000.0, 3)
    assert f == FLOOR_20B_PERSISTENT

    # 4. Over 50B but NOT persistent (periods = 2) -> Floor 1 does NOT apply, Floor 6 applies (35)
    f, rule = evaluate_mandatory_floor(60_000_000_000.0, 2)
    assert f == FLOOR_NEW_NON_PERSISTENT
    assert rule == "BOUNCED_NEW_NON_PERSISTENT"

    # 5. Over 50B with 1 period (new shock) -> Floor 6 applies (35)
    f, rule = evaluate_mandatory_floor(55_000_000_000.0, 1)
    assert f == FLOOR_NEW_NON_PERSISTENT


def test_floor_2_over_20b_persistent():
    """
    Floor 2: Bounced > 20B Rials and persistent (>= 3 periods) -> min score 78.
    Boundary tests at 20B threshold and portfolio exemplars.
    """
    # 1. Just above 20B: 20,000,000,001 with 3 periods -> Floor 78
    f, rule = evaluate_mandatory_floor(20_000_000_001.0, 3)
    assert f == FLOOR_20B_PERSISTENT
    assert rule == "BOUNCED_OVER_20B_PERSISTENT"

    # 2. Vahid Zavar: 46.08B with 11 periods -> Floor 78
    f, rule = evaluate_mandatory_floor(46_080_000_000.0, 11)
    assert f == FLOOR_20B_PERSISTENT

    # 3. Mohammad Rafigh Toroghi: 40.30B with 7 periods -> Floor 78
    f, rule = evaluate_mandatory_floor(40_300_000_000.0, 7)
    assert f == FLOOR_20B_PERSISTENT

    # 4. Mohammad Javad Vafadar: 21.63B with 8 periods -> Floor 78
    f, rule = evaluate_mandatory_floor(21_630_000_000.0, 8)
    assert f == FLOOR_20B_PERSISTENT

    # 5. Exact boundary: 20,000,000,000 is NOT > 20B -> Falls to Floor 3 (72)
    f, rule = evaluate_mandatory_floor(20_000_000_000.0, 3)
    assert f == FLOOR_10B_PERSISTENT

    # 6. Over 20B but non-persistent (2 periods) -> Floor 6 (35)
    f, rule = evaluate_mandatory_floor(25_000_000_000.0, 2)
    assert f == FLOOR_NEW_NON_PERSISTENT


def test_floor_3_over_10b_persistent():
    """
    Floor 3: Bounced > 10B Rials and persistent (>= 3 periods) -> min score 72.
    Boundary tests at 10B threshold and portfolio exemplars.
    """
    # 1. Just above 10B: 10,000,000,001 with 3 periods -> Floor 72
    f, rule = evaluate_mandatory_floor(10_000_000_001.0, 3)
    assert f == FLOOR_10B_PERSISTENT
    assert rule == "BOUNCED_OVER_10B_PERSISTENT"

    # 2. Mohammad Ziafati Maldar: 19.16B with 10 periods -> Floor 72
    f, rule = evaluate_mandatory_floor(19_160_000_000.0, 10)
    assert f == FLOOR_10B_PERSISTENT

    # 3. Ahmad Zahmatkesh: 11.55B with 9 periods -> Floor 72
    f, rule = evaluate_mandatory_floor(11_550_000_000.0, 9)
    assert f == FLOOR_10B_PERSISTENT

    # 4. Exact boundary: 10,000,000,000 is NOT > 10B -> Falls to Floor 4 (65)
    f, rule = evaluate_mandatory_floor(10_000_000_000.0, 3)
    assert f == FLOOR_5B_PERSISTENT

    # 5. Over 10B but 1 period -> Floor 6 (35)
    f, rule = evaluate_mandatory_floor(15_000_000_000.0, 1)
    assert f == FLOOR_NEW_NON_PERSISTENT


def test_floor_4_over_5b_persistent():
    """
    Floor 4: Bounced > 5B Rials and persistent (>= 3 periods) -> min score 65.
    Boundary tests at 5B threshold and portfolio exemplars.
    """
    # 1. Just above 5B: 5,000,000,001 with 3 periods -> Floor 65
    f, rule = evaluate_mandatory_floor(5_000_000_001.0, 3)
    assert f == FLOOR_5B_PERSISTENT
    assert rule == "BOUNCED_OVER_5B_PERSISTENT"

    # 2. Mohammad Zahedi (Ali Asghar Zahedi): 9.398B with 8 periods -> Floor 65
    f, rule = evaluate_mandatory_floor(9_398_000_000.0, 8)
    assert f == FLOOR_5B_PERSISTENT

    # 3. Vahid Ashrafian (Saeed Ashrafian): 6.247B with 6 periods -> Floor 65
    f, rule = evaluate_mandatory_floor(6_247_000_000.0, 6)
    assert f == FLOOR_5B_PERSISTENT

    # 4. Exact boundary: 5,000,000,000 is NOT > 5B -> Falls to Floor 5 (45)
    f, rule = evaluate_mandatory_floor(5_000_000_000.0, 3)
    assert f == FLOOR_POS_PERSISTENT

    # 5. Over 5B but 2 periods -> Floor 6 (35)
    f, rule = evaluate_mandatory_floor(7_000_000_000.0, 2)
    assert f == FLOOR_NEW_NON_PERSISTENT


def test_floor_5_positive_persistent():
    """
    Floor 5: Bounced > 0 and persistent (>= 3 periods) -> min score 45.
    Applies to all persistent debts up to 5B Rials.
    """
    # 1. Smallest positive amount: 1 Rial with 3 periods -> Floor 45
    f, rule = evaluate_mandatory_floor(1.0, 3)
    assert f == FLOOR_POS_PERSISTENT
    assert rule == "BOUNCED_POSITIVE_PERSISTENT"

    # 2. Vahid Mohammadi Anvar: 4.20B with 8 periods -> Floor 45
    f, rule = evaluate_mandatory_floor(4_200_000_000.0, 8)
    assert f == FLOOR_POS_PERSISTENT

    # 3. Seyed Jamal Mousavi: 2.80B with 5 periods -> Floor 45
    f, rule = evaluate_mandatory_floor(2_800_000_000.0, 5)
    assert f == FLOOR_POS_PERSISTENT

    # 4. Milad Deljou: 1.326B with 10 periods -> Floor 45
    f, rule = evaluate_mandatory_floor(1_326_000_000.0, 10)
    assert f == FLOOR_POS_PERSISTENT


def test_floor_6_new_non_persistent():
    """
    Floor 6: New non-persistent bounced (> 0 and 1-2 periods) -> min score 35.
    Applies to fresh transitions and temporary shocks (e.g. Zahra Bahrami Pouya).
    """
    # 1. Zahra Bahrami Pouya: 12.30B with 1 period -> Floor 35
    f, rule = evaluate_mandatory_floor(12_300_000_000.0, 1)
    assert f == FLOOR_NEW_NON_PERSISTENT
    assert rule == "BOUNCED_NEW_NON_PERSISTENT"

    # 2. Small bounced with 2 periods -> Floor 35
    f, rule = evaluate_mandatory_floor(500_000_000.0, 2)
    assert f == FLOOR_NEW_NON_PERSISTENT

    # 3. Zero bounced with 1 period -> No floor applies (0.0)
    f, rule = evaluate_mandatory_floor(0.0, 1)
    assert f == 0.0
    assert rule is None


def test_floor_does_not_lower_higher_raw_score(risk_engine):
    """
    Verify that if the calculated raw score is higher than the mandatory floor,
    the final score remains the higher raw score (floor is a minimum, not a cap).
    """
    # Customer with high bounced, persistent, high ratio, high volatility:
    # Floor is 78.0, but raw score evaluates to ~82.0
    high_input = {
        "bounced_amount": 45_000_000_000.0,
        "period_count": 8,
        "delta_bounced": 5_000_000_000.0,
        "fund_total_amount": 1_000_000_000.0,
        "in_transit_amount": 2_000_000_000.0, # ratio = 45 / 3 = 15.0 -> 100% C4
        "delta_in_transit": 5_000_000_000.0,
        "volatility": 0.8,
        "freshness_status": "FRESH_SUCCESS",
    }
    res = risk_engine.calculate_customer_risk(high_input)
    assert res["mandatory_floor"] == 78.0
    assert res["raw_score"] > 78.0
    assert res["final_score"] == pytest.approx(res["raw_score"], abs=0.1)
    assert res["is_floor_triggered"] is False


# =============================================================================
# 3. Risk Tiers & Action Recommendations Tests (F13)
# =============================================================================

def test_risk_tier_boundary_mappings():
    """
    Verify exact 5 risk tier mappings:
    - کم‌ریسک (Low): 0 to 20
    - عادی (Normal): 21 to 40
    - مراقبت (Watch): 41 to 60
    - پرریسک (High): 61 to 80
    - اقدام فوری (Immediate Action): 81 to 100
    """
    # Low: 0 to 20
    assert classify_risk_tier(0.0)["tier_code"] == TIER_LOW
    assert classify_risk_tier(10.5)["tier_code"] == TIER_LOW
    assert classify_risk_tier(20.0)["tier_code"] == TIER_LOW
    assert classify_risk_tier(20.0)["tier_name_fa"] == "کم‌ریسک"

    # Normal: 21 to 40
    assert classify_risk_tier(20.01)["tier_code"] == TIER_NORMAL
    assert classify_risk_tier(30.0)["tier_code"] == TIER_NORMAL
    assert classify_risk_tier(40.0)["tier_code"] == TIER_NORMAL
    assert classify_risk_tier(40.0)["tier_name_fa"] == "عادی"

    # Watch: 41 to 60
    assert classify_risk_tier(40.01)["tier_code"] == TIER_WATCH
    assert classify_risk_tier(50.0)["tier_code"] == TIER_WATCH
    assert classify_risk_tier(60.0)["tier_code"] == TIER_WATCH
    assert classify_risk_tier(60.0)["tier_name_fa"] == "مراقبت"

    # High: 61 to 80
    assert classify_risk_tier(60.01)["tier_code"] == TIER_HIGH
    assert classify_risk_tier(72.0)["tier_code"] == TIER_HIGH
    assert classify_risk_tier(78.0)["tier_code"] == TIER_HIGH
    assert classify_risk_tier(80.0)["tier_code"] == TIER_HIGH
    assert classify_risk_tier(80.0)["tier_name_fa"] == "پرریسک"

    # Immediate Action: 81 to 100
    assert classify_risk_tier(80.01)["tier_code"] == TIER_IMMEDIATE_ACTION
    assert classify_risk_tier(85.0)["tier_code"] == TIER_IMMEDIATE_ACTION
    assert classify_risk_tier(100.0)["tier_code"] == TIER_IMMEDIATE_ACTION
    assert classify_risk_tier(85.0)["tier_name_fa"] == "اقدام فوری"


def test_action_recommendations_verbatim_compliance():
    """Verify action recommendations match verbatim requirements from prompt and R4."""
    act_imm = classify_risk_tier(85.0)["action_recommendation"]
    assert "توقف فوری تخصیص اعتبار" in act_imm
    assert "مطالبه وثیقه ملکی/نقدی" in act_imm
    assert "اقدام حقوقی و وصول آنی" in act_imm

    act_watch = classify_risk_tier(45.0)["action_recommendation"]
    assert "پایش هفتگی" in act_watch
    assert "اخذ تضمین مضاعف" in act_watch
    assert "عدم پذیرش چک جدید با سررسید بالای ۳۰ روز" in act_watch

    act_norm = classify_risk_tier(30.0)["action_recommendation"]
    assert "ادامه تعامل در سقف مصوب" in act_norm

    act_low = classify_risk_tier(10.0)["action_recommendation"]
    assert "ادامه تعامل در سقف مصوب" in act_low


# =============================================================================
# 4. HHI Concentration & Top 10 Issuers Tests (F13)
# =============================================================================

def test_hhi_empty_and_single_monopoly_cases(risk_engine):
    """Verify mathematical boundary cases of HHI calculation."""
    # 1. Empty list
    res_empty = risk_engine.compute_hhi_concentration([])
    assert res_empty["hhi"] == 0.0
    assert res_empty["top_10_concentration_pct"] == 0.0

    # 2. Single monopoly issuer (100% debt share) -> HHI must equal 10,000.0
    monopoly = [{"customer_id": 1, "bounced_amount": 50_000_000_000.0}]
    res_mono = risk_engine.compute_hhi_concentration(monopoly)
    assert res_mono["total_bounced"] == 50_000_000_000.0
    assert res_mono["hhi"] == 10000.0
    assert res_mono["top_10_concentration_pct"] == 100.0

    # 3. 10 equal issuers (10% each) -> HHI = 10 * (10^2) = 1,000.0
    ten_equal = [{"customer_id": i, "bounced_amount": 10_000_000_000.0} for i in range(1, 11)]
    res_ten = risk_engine.compute_hhi_concentration(ten_equal)
    assert res_ten["total_bounced"] == 100_000_000_000.0
    assert res_ten["hhi"] == pytest.approx(1000.0, abs=0.01)
    assert res_ten["top_10_concentration_pct"] == 100.0


def test_portfolio_hhi_concentration_exact_values(risk_engine):
    """
    Verify portfolio HHI concentration and top 10 values on actual database:
    - total_bounced: 231,951,000,000 Rials
    - top 10 total: 227,825,000,000 Rials
    - cumulative concentration: 98.22%
    - HHI all: ~1536.4 (verbatim from prompt: ~1536.4)
    - HHI top 10: ~1534.6
    """
    hhi_data = risk_engine.compute_hhi_concentration()
    assert hhi_data["total_bounced"] == 231_951_000_000.0
    assert hhi_data["bounced_issuers_count"] == 12
    assert hhi_data["top_10_issuers_count"] == 10
    assert hhi_data["top_10_bounced_amount"] == 227_825_000_000.0
    assert hhi_data["top_10_concentration_pct"] == 98.22
    assert hhi_data["hhi"] == pytest.approx(1536.42, abs=0.1)
    assert hhi_data["hhi_top10"] == pytest.approx(1534.64, abs=0.1)


def test_top_10_issuers_ranking_order(risk_engine):
    """
    Verify the ranked top 10 issuers list:
    1. Hossein Heshmati (56.96B)
    2. Vahid Zavar (46.08B)
    3. Mohammad Rafigh Toroghi (40.30B)
    4. Mohammad Javad Vafadar (21.63B)
    5. Mohammad Ziafati Maldar (19.16B)
    6. Zahra Bahrami Pouya (12.30B)
    7. Ahmad Zahmatkesh (11.55B)
    8. Mohammad Zahedi (9.398B)
    9. Vahid Ashrafian (6.247B)
    10. Vahid Mohammadi Anvar (4.20B)
    """
    top10 = risk_engine.get_top_10_issuers()
    assert len(top10) == 10

    # Ensure strictly descending by bounced_amount
    bounced_amounts = [t["bounced_amount"] for t in top10]
    assert bounced_amounts == sorted(bounced_amounts, reverse=True)

    # Spot-check key issuers
    assert top10[0]["customer_id"] == 2
    assert top10[0]["national_id"] == "0933387075"
    assert top10[0]["bounced_amount"] == 56_960_000_000.0
    assert top10[0]["debt_share_pct"] == pytest.approx(24.56, abs=0.05)

    assert top10[1]["customer_id"] == 21
    assert top10[1]["bounced_amount"] == 46_080_000_000.0
    assert top10[1]["debt_share_pct"] == pytest.approx(19.87, abs=0.05)

    assert top10[2]["customer_id"] == 40
    assert top10[2]["bounced_amount"] == 40_300_000_000.0
    assert top10[2]["debt_share_pct"] == pytest.approx(17.37, abs=0.05)

    assert top10[3]["customer_id"] == 36
    assert top10[3]["bounced_amount"] == 21_630_000_000.0

    assert top10[4]["customer_id"] == 3
    assert top10[4]["bounced_amount"] == 19_160_000_000.0

    assert top10[5]["customer_id"] == 46
    assert top10[5]["national_id"] == "0927624011"
    assert top10[5]["bounced_amount"] == 12_300_000_000.0

    # Cumulative share of top 10 is 98.22%
    assert top10[-1]["cumulative_share_pct"] == 98.22


# =============================================================================
# 5. Full Portfolio Scoring & Canonical Customers Integration Tests
# =============================================================================

def test_full_scoring_across_all_48_canonical_customers(risk_engine):
    """
    Verify all 48 canonical customers are scored without error:
    - Exactly 48 records returned
    - Every score is within [0.0, 100.0]
    - No NaN, Inf, or None values in scores
    - Every customer has an assigned tier and recommendation
    """
    scores = risk_engine.get_all_customer_risk_scores()
    assert len(scores) == 48

    canonical_ids = set()
    for s in scores:
        cid = s["customer_id"]
        assert cid not in canonical_ids, f"Duplicate customer_id {cid} found in scoring!"
        canonical_ids.add(cid)

        score = s["final_score"]
        assert 0.0 <= score <= 100.0, f"Invalid score {score} for customer {cid}"
        assert s["tier_code"] in (TIER_LOW, TIER_NORMAL, TIER_WATCH, TIER_HIGH, TIER_IMMEDIATE_ACTION)
        assert len(s["action_recommendation"]) > 0


def test_hossein_heshmati_reaches_immediate_action(risk_engine):
    """
    Verify Hossein Heshmati (Customer 2, NID 0933387075):
    - Bounced = 56.96B Rials (> 50B)
    - Persistent (8 periods)
    - Final score >= 85 (Floor 85 applied)
    - Tier == IMMEDIATE_ACTION (اقدام فوری)
    """
    res = risk_engine.calculate_customer_risk(2)
    assert res["national_id"] == "0933387075"
    assert res["bounced_amount"] == 56_960_000_000.0
    assert res["mandatory_floor"] == 85.0
    assert res["final_score"] >= 85.0
    assert res["tier_code"] == TIER_IMMEDIATE_ACTION
    assert res["tier_name_fa"] == "اقدام فوری"


def test_zahra_bahrami_pouya_new_bounce_scoring(risk_engine):
    """
    Verify Zahra Bahrami Pouya (Customer 46, NID 0927624011):
    - Bounced = 12.30B Rials
    - New non-persistent bounce (1 period)
    - Floor 35 applied
    - Final score >= 35.0
    """
    res = risk_engine.calculate_customer_risk(46)
    assert res["national_id"] == "0927624011"
    assert res["bounced_amount"] == 12_300_000_000.0
    assert res["period_count"] == 1
    assert res["mandatory_floor"] == 35.0
    assert res["final_score"] >= 35.0
    assert res["persistence_category"] == "NEW"


def test_unresolved_identity_customers_quality_penalty(risk_engine):
    """
    Verify customers with UNRESOLVED_IDENTITY (Taheri, Farhangnia, Zargham, Rangrazzadeh)
    receive the 100-point data quality penalty (C7 = 100), contributing 5 points to raw score.
    """
    for cid in (7, 13, 26, 29):
        res = risk_engine.calculate_customer_risk(cid)
        assert res["identity_status"] == "UNRESOLVED_IDENTITY"
        assert res["components"]["c7_data_quality"] == 100.0
        assert res["weighted_components"]["w7_data_quality"] == 5.0
        assert res["final_score"] >= 5.0


def test_portfolio_risk_summary(risk_engine):
    """Verify get_portfolio_risk_summary returns complete dashboard statistics."""
    summary = risk_engine.get_portfolio_risk_summary()
    assert summary["total_canonical_customers"] == 48
    assert summary["total_fund_amount"] == 483_325_000_000.0
    assert summary["total_bounced_amount"] == 231_951_000_000.0
    assert summary["bounced_customers_count"] == 12
    assert summary["top_10_concentration_pct"] == 98.22
    assert summary["hhi"] == pytest.approx(1536.42, abs=0.1)
    assert len(summary["top_10_issuers"]) == 10
    assert len(summary["tier_distribution"]) == 5
