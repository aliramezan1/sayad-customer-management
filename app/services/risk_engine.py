# -*- coding: utf-8 -*-
"""
Fintech Intelligence, Financial Health Score (FHS), Risk Matrix & Predictive Cash Flow Engine.
Part of Sayad Pro 3.0 Fintech Architecture.
"""
import sqlite3
from typing import Dict, Any, List, Optional
from datetime import datetime, date
import statistics
import logging

from app.database import get_db
from app.services.pasargad import calculate_days_until_due, jalali_to_gregorian

logger = logging.getLogger("app.services.risk_engine")

# Central Bank Credit Color to Score mapping (0-100)
CBI_COLOR_SCORES: Dict[str, float] = {
    "سفید": 100.0,
    "سبز": 90.0,
    "زرد": 70.0,
    "نارنجی": 40.0,
    "قهوه ای": 20.0,
    "قهوه‌ای": 20.0,
    "قرمز": 10.0,
    "نامشخص": 60.0,
}

# Realization / Collection probability per credit rating
COLLECTION_PROBABILITIES: Dict[str, float] = {
    "سفید": 1.00,   # 100%
    "سبز": 0.95,    # 95%
    "زرد": 0.85,    # 85%
    "نارنجی": 0.60,  # 60%
    "قهوه ای": 0.20, # 20%
    "قهوه‌ای": 0.20, # 20%
    "قرمز": 0.20,    # 20%
    "نامشخص": 0.20,  # 20%
}


def _normalize_credit_color(color: Optional[str]) -> str:
    """Normalize credit color string."""
    if not color:
        return "نامشخص"
    c = str(color).strip()
    if c in CBI_COLOR_SCORES:
        return c
    if "سفید" in c:
        return "سفید"
    if "سبز" in c:
        return "سبز"
    if "زرد" in c:
        return "زرد"
    if "نارنجی" in c:
        return "نارنجی"
    if "قرمز" in c:
        return "قرمز"
    if "قهوه" in c:
        return "قهوه ای"
    return "نامشخص"


def get_portfolio_benchmarks(conn: Optional[sqlite3.Connection] = None) -> Dict[str, float]:
    """
    Computes system-wide portfolio benchmark values (mean, median amount, total cheques).
    """
    should_close = False
    if conn is None:
        conn = get_db()
        should_close = True

    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COALESCE(SUM(amount), 0)
            FROM cheques
            GROUP BY customer_id
        """)
        amounts = [r[0] for r in cursor.fetchall() if r[0] > 0]
        if amounts:
            med_amt = float(statistics.median(amounts))
            mean_amt = float(statistics.mean(amounts))
            max_amt = float(max(amounts))
        else:
            med_amt = 4_000_000_000.0
            mean_amt = 9_000_000_000.0
            max_amt = 50_000_000_000.0

        return {
            "median_customer_amount": med_amt,
            "mean_customer_amount": mean_amt,
            "max_customer_amount": max_amt
        }
    finally:
        if should_close:
            conn.close()


def calculate_customer_fhs(customer_id: int, conn: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
    """
    Calculates Financial Health Score (FHS: 0 to 100) for a specific customer.
    Formula:
      - CBI Central Bank credit rating score (Weight: 60%)
      - Ratio of cleared cheques reward (+25 points)
      - Debt burden & on-time history vs portfolio balance (+15 points)
      - Bounced cheques penalty (-40 points)
    Categorizes into 4 tiers:
      - عالی: 85 - 100 (Excellent)
      - خوب: 70 - 84 (Good)
      - متوسط: 50 - 69 (Fair)
      - پرخطر: زیر 50 (High Risk)
    """
    should_close = False
    if conn is None:
        conn = get_db()
        should_close = True

    try:
        cursor = conn.cursor()

        # 1. Fetch customer details
        cursor.execute("SELECT id, full_name, national_id, phone, credit_color FROM customers WHERE id = ?", (customer_id,))
        cust_row = cursor.fetchone()
        if not cust_row:
            raise ValueError(f"Customer with ID {customer_id} not found.")

        cust = dict(cust_row)
        norm_color = _normalize_credit_color(cust.get("credit_color"))
        cbi_base_score = CBI_COLOR_SCORES.get(norm_color, 60.0)

        # 2. Fetch cheques summary
        cursor.execute("""
            SELECT 
                COUNT(*) as count,
                COALESCE(SUM(amount), 0) as total_amt,
                COALESCE(MIN(cheque_date), '') as earliest_date,
                COALESCE(MAX(cheque_date), '') as latest_date
            FROM cheques 
            WHERE customer_id = ?
        """, (customer_id,))
        ch_row = cursor.fetchone()
        cheque_count = ch_row[0]
        total_amount = float(ch_row[1])

        # 3. Fetch latest pasargad inquiry aggregates for this customer's cheques
        cursor.execute("""
            SELECT 
                COALESCE(SUM(pi.in_transit_amount), 0) as in_transit_amt,
                COALESCE(SUM(pi.cleared_amount), 0) as cleared_amt,
                COALESCE(SUM(pi.cleared_count), 0) as cleared_cnt,
                COALESCE(SUM(pi.bounced_amount), 0) as bounced_amt,
                COALESCE(SUM(pi.bounced_count), 0) as bounced_cnt
            FROM cheques ch
            LEFT JOIN pasargad_inquiries pi ON pi.id = (
                SELECT id FROM pasargad_inquiries 
                WHERE sayadi_id = ch.sayadi_id 
                ORDER BY id DESC LIMIT 1
            )
            WHERE ch.customer_id = ?
        """, (customer_id,))
        pi_row = cursor.fetchone()
        in_transit_amt = float(pi_row[0])
        cleared_amt = float(pi_row[1])
        cleared_cnt = int(pi_row[2])
        bounced_amt = float(pi_row[3])
        bounced_cnt = int(pi_row[4])

        # Overdue cheques check
        cursor.execute("SELECT cheque_date, amount FROM cheques WHERE customer_id = ?", (customer_id,))
        cheque_dates = cursor.fetchall()
        overdue_cnt = 0
        overdue_amt = 0.0
        for cd in cheque_dates:
            days = calculate_days_until_due(cd[0])
            if days is not None and days < 0:
                overdue_cnt += 1
                overdue_amt += float(cd[1] or 0)

        # ── Weighted Fintech Formula Components ──
        # Component 1: Central Bank Credit Rating (Weight: 60%)
        # Base: (cbi_base_score / 100.0) * 60.0  => max 60.0
        cbi_component = (cbi_base_score / 100.0) * 60.0

        # Component 2: Cleared Cheques Reward (+25 points)
        # Ratio of cleared volume & count
        if cleared_cnt > 0 or cleared_amt > 0:
            count_ratio = min(1.0, cleared_cnt / max(cheque_count, 1))
            amt_ratio = min(1.0, cleared_amt / max(total_amount, 1)) if total_amount > 0 else 1.0
            cleared_ratio = max(count_ratio, amt_ratio)
            cleared_component = cleared_ratio * 25.0
        else:
            # Customer has no cleared records yet
            if norm_color in ("سفید", "سبز") and bounced_cnt == 0:
                cleared_ratio = 0.60
                cleared_component = 15.0  # Fair initial baseline for clean new customers
            else:
                cleared_ratio = 0.0
                cleared_component = 0.0

        # Component 3: Debt Burden & On-Time Performance (+15 points)
        # Evaluates customer leverage relative to portfolio median
        benchmarks = get_portfolio_benchmarks(conn)
        median_vol = benchmarks.get("median_customer_amount", 4_200_000_000.0)
        
        if overdue_cnt > 0 or bounced_cnt > 0:
            # Has past due or bounced commitments
            penalty_ratio = min(1.0, (bounced_amt + overdue_amt) / max(total_amount, 1.0))
            commitment_component = max(0.0, 15.0 * (1.0 - penalty_ratio * 1.5))
        else:
            # Clean payment history
            if total_amount <= median_vol * 3.0:
                commitment_component = 15.0
            else:
                # Higher leverage, slightly moderate
                commitment_component = 12.0

        # Component 4: Bounced Cheques Penalty (-40 points)
        if bounced_cnt > 0 or bounced_amt > 0:
            b_cnt_ratio = min(1.0, bounced_cnt / max(cheque_count, bounced_cnt, 1))
            b_amt_ratio = min(1.0, bounced_amt / max(total_amount, bounced_amt, 1.0))
            bounced_ratio = max(b_cnt_ratio, b_amt_ratio)
            # Minimum penalty of 15 points if any bounced cheque exists
            bounced_penalty = min(40.0, max(15.0, bounced_ratio * 40.0))
        else:
            bounced_ratio = 0.0
            bounced_penalty = 0.0

        # Raw Score Calculation & Clamping (0 - 100)
        raw_score = cbi_component + cleared_component + commitment_component - bounced_penalty
        fhs_score = max(0.0, min(100.0, round(raw_score, 1)))

        # Categorization into 4 Tiers
        if fhs_score >= 85.0:
            level = "عالی"
            level_en = "excellent"
            color = "#10b981"  # Emerald
            bg_class = "bg-emerald-500/10 text-emerald-400 border-emerald-500/30"
            recommendation = "مشتری ممتاز با سلامت مالی درخشان. واجد شرایط دریافت بالاترین سقف اعتبار و تسهیلات تجاری."
        elif fhs_score >= 70.0:
            level = "خوب"
            level_en = "good"
            color = "#3b82f6"  # Blue
            bg_class = "bg-blue-500/10 text-blue-400 border-blue-500/30"
            recommendation = "سلامت مالی مطلوب و کم‌ریسک. تداوم همکاری با رعایت دوره‌های معمول تسویه حساب توصیه می‌شود."
        elif fhs_score >= 50.0:
            level = "متوسط"
            level_en = "fair"
            color = "#f59e0b"  # Amber
            bg_class = "bg-amber-500/10 text-amber-400 border-amber-500/30"
            recommendation = "ریسک متوسط و نیازمند پایش. پذیرش چک جدید صرفاً با اخذ تضامین تکمیلی یا سررسیدهای کوتاه‌مدت."
        else:
            level = "پرخطر"
            level_en = "high_risk"
            color = "#ef4444"  # Red
            bg_class = "bg-rose-500/10 text-rose-400 border-rose-500/30"
            recommendation = "هشدار بحرانی: سلامت مالی بسیار ضعیف و احتمال بالای نکول. از پذیرش هرگونه چک جدید اکیداً خودداری شود."

        return {
            "customer_id": cust["id"],
            "full_name": cust["full_name"],
            "national_id": cust.get("national_id"),
            "fhs_score": fhs_score,
            "level": level,
            "level_en": level_en,
            "color": color,
            "bg_class": bg_class,
            "cbi_rating": norm_color,
            "factors": {
                "cbi_score": cbi_base_score,
                "cbi_component": round(cbi_component, 1),
                "cleared_ratio": round(cleared_ratio * 100, 1),
                "cleared_component": round(cleared_component, 1),
                "commitment_component": round(commitment_component, 1),
                "bounced_ratio": round(bounced_ratio * 100, 1),
                "bounced_penalty": round(bounced_penalty, 1),
                "total_cheques": cheque_count,
                "total_amount": total_amount,
                "in_transit_amount": in_transit_amt,
                "cleared_count": cleared_cnt,
                "cleared_amount": cleared_amt,
                "bounced_count": bounced_cnt,
                "bounced_amount": bounced_amt,
                "overdue_count": overdue_cnt,
                "overdue_amount": overdue_amt
            },
            "recommendation": recommendation
        }
    finally:
        if should_close:
            conn.close()


def get_all_customers_fhs(conn: Optional[sqlite3.Connection] = None) -> List[Dict[str, Any]]:
    """
    Computes FHS for all registered customers in the database.
    """
    should_close = False
    if conn is None:
        conn = get_db()
        should_close = True

    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM customers ORDER BY id ASC")
        cust_ids = [r[0] for r in cursor.fetchall()]
        results = []
        for cid in cust_ids:
            fhs = calculate_customer_fhs(cid, conn)
            results.append(fhs)
        return results
    finally:
        if should_close:
            conn.close()


def get_cash_flow_forecast(days: int = 90, conn: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
    """
    Risk-Weighted Predictive Cash Flow Forecasting Engine.
    Categorizes incoming cheques across time horizons (30, 60, 90 days and daily timeline).
    Applies collection probabilities by CBI credit rating:
      - سفید (White): 100%
      - سبز (Green): 95%
      - زرد (Yellow): 85%
      - نارنجی (Orange): 60%
      - قرمز / قهوه ای / نامشخص (Red/Brown/Unknown): 20%
    Computes Nominal Cash Flow vs Realizable Cash Flow, plus Potential Shortfall and Variance.
    """
    should_close = False
    if conn is None:
        conn = get_db()
        should_close = True

    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                ch.id, ch.customer_id, ch.sayadi_id, ch.cheque_number, ch.amount,
                ch.cheque_date, ch.bank_name, ch.status,
                c.full_name as customer_name,
                c.credit_color as credit_color
            FROM cheques ch
            LEFT JOIN customers c ON ch.customer_id = c.id
            ORDER BY ch.cheque_date ASC
        """)
        rows = [dict(r) for r in cursor.fetchall()]

        # Buckets initialization
        buckets = {
            "30": {"nominal": 0.0, "realizable": 0.0, "shortfall": 0.0, "count": 0, "cheques": []},
            "60": {"nominal": 0.0, "realizable": 0.0, "shortfall": 0.0, "count": 0, "cheques": []},
            "90": {"nominal": 0.0, "realizable": 0.0, "shortfall": 0.0, "count": 0, "cheques": []},
            "overdue": {"nominal": 0.0, "realizable": 0.0, "shortfall": 0.0, "count": 0, "cheques": []},
            "beyond_90": {"nominal": 0.0, "realizable": 0.0, "shortfall": 0.0, "count": 0, "cheques": []},
        }

        daily_map: Dict[str, Dict[str, Any]] = {}

        for ch in rows:
            amt = float(ch.get("amount") or 0.0)
            ch_date = str(ch.get("cheque_date") or "").strip()
            color = _normalize_credit_color(ch.get("credit_color"))
            prob = COLLECTION_PROBABILITIES.get(color, 0.20)
            realizable = round(amt * prob, 2)
            shortfall = round(amt - realizable, 2)

            days_remaining = calculate_days_until_due(ch_date)

            item = {
                "cheque_id": ch["id"],
                "customer_id": ch["customer_id"],
                "customer_name": ch["customer_name"],
                "sayadi_id": ch["sayadi_id"],
                "cheque_number": ch["cheque_number"],
                "amount": amt,
                "cheque_date": ch_date,
                "days_remaining": days_remaining,
                "credit_color": color,
                "collection_probability": prob,
                "realizable_amount": realizable,
                "shortfall_amount": shortfall,
                "bank_name": ch.get("bank_name")
            }

            # If overdue
            if days_remaining is not None and days_remaining < 0:
                buckets["overdue"]["nominal"] += amt
                buckets["overdue"]["realizable"] += realizable
                buckets["overdue"]["shortfall"] += shortfall
                buckets["overdue"]["count"] += 1
                buckets["overdue"]["cheques"].append(item)
                continue

            # Within horizon
            if days_remaining is not None:
                if 0 <= days_remaining <= 30:
                    buckets["30"]["nominal"] += amt
                    buckets["30"]["realizable"] += realizable
                    buckets["30"]["shortfall"] += shortfall
                    buckets["30"]["count"] += 1
                    buckets["30"]["cheques"].append(item)

                if 0 <= days_remaining <= 60:
                    buckets["60"]["nominal"] += amt
                    buckets["60"]["realizable"] += realizable
                    buckets["60"]["shortfall"] += shortfall
                    buckets["60"]["count"] += 1
                    buckets["60"]["cheques"].append(item)

                if 0 <= days_remaining <= 90:
                    buckets["90"]["nominal"] += amt
                    buckets["90"]["realizable"] += realizable
                    buckets["90"]["shortfall"] += shortfall
                    buckets["90"]["count"] += 1
                    buckets["90"]["cheques"].append(item)

                    # Accumulate daily timeline
                    if ch_date not in daily_map:
                        daily_map[ch_date] = {
                            "date": ch_date,
                            "days_remaining": days_remaining,
                            "nominal": 0.0,
                            "realizable": 0.0,
                            "shortfall": 0.0,
                            "cheque_count": 0,
                            "cheques": []
                        }
                    daily_map[ch_date]["nominal"] += amt
                    daily_map[ch_date]["realizable"] += realizable
                    daily_map[ch_date]["shortfall"] += shortfall
                    daily_map[ch_date]["cheque_count"] += 1
                    daily_map[ch_date]["cheques"].append(item)
                elif days_remaining > 90:
                    buckets["beyond_90"]["nominal"] += amt
                    buckets["beyond_90"]["realizable"] += realizable
                    buckets["beyond_90"]["shortfall"] += shortfall
                    buckets["beyond_90"]["count"] += 1
                    buckets["beyond_90"]["cheques"].append(item)

        # Sort daily timeline
        daily_timeline = sorted(daily_map.values(), key=lambda d: d["date"])

        # Compute summary rates
        def _calc_rate(realizable: float, nominal: float) -> float:
            return round((realizable / nominal) * 100.0, 1) if nominal > 0 else 100.0

        for key in ["30", "60", "90", "overdue", "beyond_90"]:
            buckets[key]["realization_rate"] = _calc_rate(buckets[key]["realizable"], buckets[key]["nominal"])

        return {
            "forecast_days": days,
            "horizons": {
                "30_days": buckets["30"],
                "60_days": buckets["60"],
                "90_days": buckets["90"],
                "overdue": buckets["overdue"],
                "beyond_90": buckets["beyond_90"]
            },
            "summary": {
                "nominal_total_90d": buckets["90"]["nominal"],
                "realizable_total_90d": buckets["90"]["realizable"],
                "shortfall_total_90d": buckets["90"]["shortfall"],
                "realization_rate_90d": buckets["90"]["realization_rate"],
                "cheques_count_90d": buckets["90"]["count"],
                "overdue_nominal": buckets["overdue"]["nominal"],
                "overdue_count": buckets["overdue"]["count"]
            },
            "daily_timeline": daily_timeline
        }
    finally:
        if should_close:
            conn.close()


def get_risk_matrix(conn: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
    """
    2D Fintech Risk Matrix Engine.
    Segments customers across two dimensions:
      - Risk Dimension: Low Risk (FHS >= 70 / CBI White & Green) vs High Risk (FHS < 70)
      - Commitment / Volume Dimension: High Volume (>= Portfolio Median) vs Low Volume
    4 Quadrants:
      1. Stars & Golden (کم‌ریسک و پرتراکنش - ستاره‌ها و مشتریان طلایی)
      2. Opportunities & Standard (کم‌ریسک و کم‌تراکنش - عادی و فرصت‌ها)
      3. Watchlist (پرریسک با مبالغ خرد - تحت نظر)
      4. Critical Red Alert (پرریسک با تعهدات سنگین - هشدار قرمز و بحرانی)
    """
    should_close = False
    if conn is None:
        conn = get_db()
        should_close = True

    try:
        customers_fhs = get_all_customers_fhs(conn)
        benchmarks = get_portfolio_benchmarks(conn)
        median_vol = benchmarks.get("median_customer_amount", 4_200_000_000.0)

        stars = []        # Q1: Low Risk, High Volume
        opportunities = [] # Q2: Low Risk, Low Volume
        watchlist = []     # Q3: High Risk, Low Volume
        critical = []      # Q4: High Risk, High Volume

        for c in customers_fhs:
            fhs_score = c["fhs_score"]
            total_amt = c["factors"]["total_amount"]
            color = c["cbi_rating"]

            is_low_risk = (fhs_score >= 70.0) or (color in ("سفید", "سبز") and fhs_score >= 60.0)
            is_high_volume = (total_amt >= median_vol)

            item = {
                "customer_id": c["customer_id"],
                "full_name": c["full_name"],
                "national_id": c.get("national_id"),
                "fhs_score": fhs_score,
                "level": c["level"],
                "cbi_rating": color,
                "total_amount": total_amt,
                "cheque_count": c["factors"]["total_cheques"],
                "bounced_count": c["factors"]["bounced_count"],
                "bounced_amount": c["factors"]["bounced_amount"],
                "in_transit_amount": c["factors"]["in_transit_amount"],
                "cleared_amount": c["factors"]["cleared_amount"],
                "overdue_count": c["factors"]["overdue_count"],
                "recommendation": c["recommendation"]
            }

            if is_low_risk and is_high_volume:
                stars.append(item)
            elif is_low_risk and not is_high_volume:
                opportunities.append(item)
            elif not is_low_risk and not is_high_volume:
                watchlist.append(item)
            else:
                critical.append(item)

        # Sort each quadrant descending by total amount
        stars.sort(key=lambda x: x["total_amount"], reverse=True)
        opportunities.sort(key=lambda x: x["total_amount"], reverse=True)
        watchlist.sort(key=lambda x: x["total_amount"], reverse=True)
        critical.sort(key=lambda x: x["total_amount"], reverse=True)

        def _quadrant_stats(q_list: List[Dict[str, Any]]) -> Dict[str, Any]:
            cnt = len(q_list)
            tot_amt = sum(x["total_amount"] for x in q_list)
            avg_fhs = round(sum(x["fhs_score"] for x in q_list) / cnt, 1) if cnt > 0 else 0.0
            return {
                "count": cnt,
                "total_amount": tot_amt,
                "average_fhs": avg_fhs,
                "customers": q_list
            }

        total_customers = len(customers_fhs)

        return {
            "thresholds": {
                "volume_median": median_vol,
                "fhs_low_risk_min": 70.0
            },
            "quadrants": {
                "stars": {
                    "id": "q1_stars",
                    "title": "کم‌ریسک و پرتراکنش (ستاره‌ها و مشتریان طلایی)",
                    "title_en": "Stars & Golden Portfolio",
                    "badge_color": "emerald",
                    "description": "ستون‌های سودآوری و خوش‌حسابی صندوق با گردش مالی بالا و ضریب سلامت مالی عالی.",
                    **_quadrant_stats(stars)
                },
                "opportunities": {
                    "id": "q2_opportunities",
                    "title": "کم‌ریسک و کم‌تراکنش (عادی و فرصت‌ها)",
                    "title_en": "Opportunities & Standard",
                    "badge_color": "blue",
                    "description": "مشتریان با اعتبار پاک و سابقه سلامت، دارای پتانسیل توسعه حجم مبادلات تجاری.",
                    **_quadrant_stats(opportunities)
                },
                "watchlist": {
                    "id": "q3_watchlist",
                    "title": "پرریسک با مبالغ خرد (تحت نظر)",
                    "title_en": "Watchlist & Monitored",
                    "badge_color": "amber",
                    "description": "مشتریان با نمره اعتباری ضعیف اما با مبالغ تعهدات محدود، نیازمند کنترل و وصول سر موعد.",
                    **_quadrant_stats(watchlist)
                },
                "critical": {
                    "id": "q4_critical",
                    "title": "پرریسک با تعهدات سنگین (هشدار قرمز و بحرانی)",
                    "title_en": "Critical Red Alert",
                    "badge_color": "rose",
                    "description": "بزرگترین ریسک اعتباری صندوق با بدهی و تعهدات سنگین همراه با سوابق برگشتی و رتبه نامساعد.",
                    **_quadrant_stats(critical)
                }
            },
            "summary": {
                "total_customers": total_customers,
                "stars_percentage": round((len(stars) / total_customers) * 100, 1) if total_customers > 0 else 0.0,
                "critical_percentage": round((len(critical) / total_customers) * 100, 1) if total_customers > 0 else 0.0,
                "watchlist_percentage": round((len(watchlist) / total_customers) * 100, 1) if total_customers > 0 else 0.0,
                "opportunities_percentage": round((len(opportunities) / total_customers) * 100, 1) if total_customers > 0 else 0.0
            }
        }
    finally:
        if should_close:
            conn.close()


def get_near_maturity_alerts(days_threshold: int = 7, conn: Optional[sqlite3.Connection] = None) -> List[Dict[str, Any]]:
    """
    Returns cheques maturing within the upcoming `days_threshold` days (default 7 days).
    Highlights high-risk cheques (Yellow, Orange, Red) requiring urgent collection intervention.
    """
    should_close = False
    if conn is None:
        conn = get_db()
        should_close = True

    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                ch.id, ch.customer_id, ch.sayadi_id, ch.cheque_number, ch.amount,
                ch.cheque_date, ch.bank_name, ch.status,
                c.full_name as customer_name,
                c.national_id as customer_national_id,
                c.phone as customer_phone,
                c.credit_color as credit_color
            FROM cheques ch
            LEFT JOIN customers c ON ch.customer_id = c.id
            ORDER BY ch.cheque_date ASC
        """)
        rows = [dict(r) for r in cursor.fetchall()]

        alerts = []
        for ch in rows:
            days = calculate_days_until_due(ch.get("cheque_date"))
            if days is not None and 0 <= days <= days_threshold:
                color = _normalize_credit_color(ch.get("credit_color"))
                amt = float(ch.get("amount") or 0.0)

                # Determine urgency priority
                if color in ("قرمز", "قهوه ای", "قهوه‌ای") or days <= 2:
                    priority = "critical"
                    priority_fa = "بحرانی"
                elif color in ("زرد", "نارنجی") or days <= 4:
                    priority = "warning"
                    priority_fa = "هشدار"
                else:
                    priority = "normal"
                    priority_fa = "عادی"

                alerts.append({
                    "cheque_id": ch["id"],
                    "customer_id": ch["customer_id"],
                    "customer_name": ch["customer_name"],
                    "customer_phone": ch.get("customer_phone"),
                    "sayadi_id": ch["sayadi_id"],
                    "cheque_number": ch["cheque_number"],
                    "amount": amt,
                    "cheque_date": ch["cheque_date"],
                    "days_remaining": days,
                    "credit_color": color,
                    "bank_name": ch.get("bank_name"),
                    "priority": priority,
                    "priority_fa": priority_fa
                })

        # Sort: priority first (critical, warning, normal), then days remaining
        priority_order = {"critical": 0, "warning": 1, "normal": 2}
        alerts.sort(key=lambda a: (priority_order.get(a["priority"], 3), a["days_remaining"]))
        return alerts
    finally:
        if should_close:
            conn.close()
