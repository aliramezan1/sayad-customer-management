# -*- coding: utf-8 -*-
"""
Financial Aggregator & Separation Service (Milestone 2).

Enforces:
1. Strict separation between:
   a) Physical fund cheques (must equal exactly 483,325,000,000 Rials across 147 cheques).
   b) Bank inquiry status amounts (in-flight, bounced, cleared).
2. Golden Rule of No-Double-Count:
   - For each of the 48 canonical customers (from IdentityResolver), retrieve their latest bank inquiry status.
   - A customer with N cheques in the fund has their bank status aggregated strictly ONCE in portfolio summaries.
   - Total deduplicated portfolio bank amounts:
     * in-flight (total_in_transit): 4,466,069,469,454 Rials
     * bounced (total_bounced): 231,951,000,000 Rials (NOT 604B/677B!)
     * cleared (total_cleared): 1,024,305,185,797 Rials
3. Audit methods that mathematically verify the zero-discrepancy and no-double-count assertions.
"""

import os
import sqlite3
import logging
from typing import Optional, List, Dict, Any, Tuple

from app.services.identity_resolver import (
    IdentityResolver,
    STATUS_VERIFIED,
    STATUS_UNRESOLVED_IDENTITY,
    DOC_STATUS_EXEMPT,
    DOC_STATUS_VALID,
)

logger = logging.getLogger("app.services.financial_aggregator")

# Expected portfolio constants
EXPECTED_FUND_CHEQUE_COUNT = 147
EXPECTED_FUND_TOTAL_AMOUNT = 483_325_000_000.0

EXPECTED_PORTFOLIO_IN_TRANSIT = 4_466_069_469_454.0
EXPECTED_PORTFOLIO_BOUNCED = 231_951_000_000.0
EXPECTED_PORTFOLIO_CLEARED = 1_024_305_185_797.0

EXPECTED_IN_TRANSIT_COUNT = 42
EXPECTED_BOUNCED_COUNT = 12
EXPECTED_CLEARED_COUNT = 37
EXPECTED_CANONICAL_CUSTOMERS_COUNT = 48
EXPECTED_INQUIRED_CUSTOMERS_COUNT = 42


class FinancialAggregator:
    """
    Financial Aggregator enforcing strict separation of fund commitments
    from bank inquiry statuses, and guaranteeing the Golden Rule of No-Double-Count.
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        identity_resolver: Optional[IdentityResolver] = None,
    ):
        """
        Initialize the FinancialAggregator with database path and IdentityResolver.
        """
        if db_path:
            self.db_path = db_path
        else:
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            self.db_path = os.path.join(base_dir, "customers.db")

        if identity_resolver:
            self.resolver = identity_resolver
        else:
            self.resolver = IdentityResolver(db_path=self.db_path)

    def _get_connection(self) -> sqlite3.Connection:
        """Create a connection with sqlite3.Row row_factory."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    # =========================================================================
    # 1. Fund Cheques Audit & Extraction (Physical Commitments)
    # =========================================================================

    def get_fund_cheques(self) -> List[Dict[str, Any]]:
        """
        Retrieve all physical fund cheques across the 48 canonical customers.
        Returns a flat list of 147 cheque dictionaries with customer metadata.
        """
        canonical_customers = self.resolver.get_canonical_customers()
        all_cheques: List[Dict[str, Any]] = []

        for cust in canonical_customers:
            cust_id = cust["id"]
            cust_name = cust["full_name"]
            cust_nid = cust["national_id"]
            cust_status = cust["identity_status"]

            for ch in cust.get("cheques", []):
                cheque_copy = dict(ch)
                cheque_copy["canonical_customer_id"] = cust_id
                cheque_copy["canonical_customer_name"] = cust_name
                cheque_copy["canonical_national_id"] = cust_nid
                cheque_copy["canonical_identity_status"] = cust_status
                all_cheques.append(cheque_copy)

        return all_cheques

    def get_fund_cheques_audit(self) -> Dict[str, Any]:
        """
        Perform a mathematical audit on the physical fund cheques.
        Verifies:
        - Exactly 147 cheques
        - Exactly 483,325,000,000 Rials
        - Discrepancy is zero
        """
        cheques = self.get_fund_cheques()
        total_count = len(cheques)
        total_amount = sum(float(ch.get("amount", 0.0)) for ch in cheques)
        discrepancy = total_amount - EXPECTED_FUND_TOTAL_AMOUNT
        verified = (
            total_count == EXPECTED_FUND_CHEQUE_COUNT
            and abs(discrepancy) < 0.01
        )

        return {
            "total_count": total_count,
            "total_amount": total_amount,
            "expected_count": EXPECTED_FUND_CHEQUE_COUNT,
            "expected_amount": EXPECTED_FUND_TOTAL_AMOUNT,
            "discrepancy": discrepancy,
            "verified": verified,
            "concept": "PHYSICAL_FUND_COMMITMENTS",
            "notes": "مجموع مبالغ چک‌های فیزیکی موجود در صندوق نزد کارتابل‌ها",
        }

    # =========================================================================
    # 2. Banking Inquiry Status per Unique Customer (Golden Rule)
    # =========================================================================

    def get_customer_latest_banking_status(self, customer_id: int) -> Dict[str, Any]:
        """
        Retrieve the latest successful bank inquiry status for a single canonical customer.
        Returns zeroed amounts if no inquiry exists (e.g. EXEMPT or UNRESOLVED).
        """
        default_status = {
            "customer_id": customer_id,
            "has_inquiry": False,
            "in_transit_amount": 0.0,
            "in_transit_count": 0,
            "bounced_amount": 0.0,
            "bounced_count": 0,
            "cleared_amount": 0.0,
            "cleared_count": 0,
            "inquiry_time": None,
            "status": "NOT_FOUND",
            "raw_response": None,
        }

        if not os.path.exists(self.db_path):
            return default_status

        conn = None
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            cur.execute("""
                SELECT 
                    id, sayadi_id, holder_id, customer_id, 
                    in_transit_count, in_transit_amount, 
                    cleared_count, cleared_amount, 
                    bounced_count, bounced_amount, 
                    raw_response, status, inquiry_time
                FROM pasargad_inquiries
                WHERE customer_id = ? AND status = 'success'
                ORDER BY id DESC
                LIMIT 1
            """, (customer_id,))
            row = cur.fetchone()
            if row:
                return {
                    "customer_id": customer_id,
                    "inquiry_id": row["id"],
                    "sayadi_id": row["sayadi_id"],
                    "holder_id": row["holder_id"],
                    "has_inquiry": True,
                    "in_transit_amount": float(row["in_transit_amount"] or 0.0),
                    "in_transit_count": int(row["in_transit_count"] or 0),
                    "bounced_amount": float(row["bounced_amount"] or 0.0),
                    "bounced_count": int(row["bounced_count"] or 0),
                    "cleared_amount": float(row["cleared_amount"] or 0.0),
                    "cleared_count": int(row["cleared_count"] or 0),
                    "inquiry_time": str(row["inquiry_time"] or ""),
                    "status": str(row["status"] or "success"),
                    "raw_response": row["raw_response"],
                }
        except (sqlite3.OperationalError, sqlite3.DatabaseError) as exc:
            logger.warning("Error reading banking status for customer %s: %s", customer_id, exc)
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

        return default_status

    def get_portfolio_banking_summary(self) -> Dict[str, Any]:
        """
        Enforces the Golden Rule of No-Double-Count.
        
        Algorithm:
        1. Retrieve the 48 canonical unique customers from IdentityResolver.
        2. For each canonical customer, retrieve their latest bank inquiry status strictly ONCE.
        3. Regardless of whether a customer has 1, 2, 5, or 8 cheques in the fund,
           their banking status is added to the portfolio sum exactly ONCE.
        
        Returns:
            {
                'total_in_transit': 4466069469454.0,
                'total_bounced': 231951000000.0,
                'total_cleared': 1024305185797.0,
                'total_in_transit_count': 42,
                'total_bounced_count': 12,
                'total_cleared_count': 37,
                'unique_customers_count': 48,
                'inquired_customers_count': 42,
                'verified_no_double_count': True
            }
        """
        canonical_customers = self.resolver.get_canonical_customers()

        total_in_transit = 0.0
        total_bounced = 0.0
        total_cleared = 0.0

        total_in_transit_cnt = 0
        total_bounced_cnt = 0
        total_cleared_cnt = 0

        inquired_count = 0
        bounced_customers_count = 0

        for cust in canonical_customers:
            cid = cust["id"]
            bank_status = self.get_customer_latest_banking_status(cid)

            if bank_status["has_inquiry"]:
                inquired_count += 1
                total_in_transit += bank_status["in_transit_amount"]
                total_bounced += bank_status["bounced_amount"]
                total_cleared += bank_status["cleared_amount"]

                total_in_transit_cnt += bank_status["in_transit_count"]
                total_bounced_cnt += bank_status["bounced_count"]
                total_cleared_cnt += bank_status["cleared_count"]

                if bank_status["bounced_amount"] > 0:
                    bounced_customers_count += 1

        # Check alignment with expected deduplicated totals
        verified_no_double_count = (
            abs(total_in_transit - EXPECTED_PORTFOLIO_IN_TRANSIT) < 0.01
            and abs(total_bounced - EXPECTED_PORTFOLIO_BOUNCED) < 0.01
            and abs(total_cleared - EXPECTED_PORTFOLIO_CLEARED) < 0.01
            and len(canonical_customers) == EXPECTED_CANONICAL_CUSTOMERS_COUNT
            and inquired_count == EXPECTED_INQUIRED_CUSTOMERS_COUNT
            and bounced_customers_count == EXPECTED_BOUNCED_COUNT
        )

        return {
            "total_in_transit": total_in_transit,
            "total_bounced": total_bounced,
            "total_cleared": total_cleared,
            "total_in_transit_count": total_in_transit_cnt,
            "total_bounced_count": total_bounced_cnt,
            "total_cleared_count": total_cleared_cnt,
            "unique_customers_count": len(canonical_customers),
            "inquired_customers_count": inquired_count,
            "bounced_customers_count": bounced_customers_count,
            "verified_no_double_count": verified_no_double_count,
            "concept": "BANKING_INQUIRY_STATUS_DEDUPLICATED",
            "golden_rule_statement": (
                "محاسبات بانکی بر اساس مشتری یکتا انجام شد و هیچ مبلغ در راه/برگشتی/رفع سوءاثر "
                "به دلیل تعدد چک دوباره‌شماری نشده است."
            ),
        }

    # =========================================================================
    # 3. Customer Financial Profiles (Unified Customer-Centric View)
    # =========================================================================

    def get_customer_financial_profile(self, customer_id: int) -> Optional[Dict[str, Any]]:
        """
        Generate a complete financial profile for a single canonical customer,
        maintaining absolute separation between fund commitments and banking status.
        """
        cust = self.resolver.get_customer_by_id(customer_id)
        if not cust:
            return None

        bank_status = self.get_customer_latest_banking_status(customer_id)
        cheques = cust.get("cheques", [])
        fund_amount = sum(float(ch.get("amount", 0.0)) for ch in cheques)

        return {
            # Identity attributes
            "customer_id": cust["id"],
            "full_name": cust["full_name"],
            "national_id": cust["national_id"],
            "identity_status": cust["identity_status"],
            "is_unresolved": cust["is_unresolved"],
            "has_exempt_documents": cust["has_exempt_documents"],
            "original_name_alias": cust.get("original_name_alias"),
            "credit_color": cust.get("credit_color"),
            # Fund physical commitments
            "fund_cheque_count": len(cheques),
            "fund_total_amount": fund_amount,
            "fund_cheques": cheques,
            # Banking network status (deduplicated)
            "bank_has_inquiry": bank_status["has_inquiry"],
            "bank_in_transit_amount": bank_status["in_transit_amount"],
            "bank_in_transit_count": bank_status["in_transit_count"],
            "bank_bounced_amount": bank_status["bounced_amount"],
            "bank_bounced_count": bank_status["bounced_count"],
            "bank_cleared_amount": bank_status["cleared_amount"],
            "bank_cleared_count": bank_status["cleared_count"],
            "bank_inquiry_time": bank_status["inquiry_time"],
            "bank_inquiry_status": bank_status["status"],
        }

    def get_all_customer_financial_profiles(self) -> List[Dict[str, Any]]:
        """
        Return the unified financial profiles for all 48 canonical customers.
        """
        profiles = []
        for cust in self.resolver.get_canonical_customers():
            prof = self.get_customer_financial_profile(cust["id"])
            if prof:
                profiles.append(prof)
        return profiles

    # =========================================================================
    # 4. Mathematical Audits & Verification
    # =========================================================================

    def audit_no_double_count(self) -> Dict[str, Any]:
        """
        Mathematical proof comparing naive cheque-level multiplication (which caused
        the false 604B/677B Rials reported in legacy spreadsheets) against the
        rigorous single-aggregation Golden Rule (231.951B Rials).
        """
        canonical = self.resolver.get_canonical_customers()

        dedup_bounced = 0.0
        dedup_in_transit = 0.0
        dedup_cleared = 0.0

        naive_bounced = 0.0
        naive_in_transit = 0.0
        naive_cleared = 0.0

        for c in canonical:
            cid = c["id"]
            cheque_cnt = len(c.get("cheques", []))
            bank = self.get_customer_latest_banking_status(cid)

            # Deduplicated: counted ONCE
            dedup_bounced += bank["bounced_amount"]
            dedup_in_transit += bank["in_transit_amount"]
            dedup_cleared += bank["cleared_amount"]

            # Naive: multiplied by number of fund cheques
            naive_bounced += bank["bounced_amount"] * cheque_cnt
            naive_in_transit += bank["in_transit_amount"] * cheque_cnt
            naive_cleared += bank["cleared_amount"] * cheque_cnt

        bounced_inflation = naive_bounced - dedup_bounced
        in_transit_inflation = naive_in_transit - dedup_in_transit
        cleared_inflation = naive_cleared - dedup_cleared

        bounced_inflation_pct = (
            (bounced_inflation / dedup_bounced * 100.0) if dedup_bounced > 0 else 0.0
        )
        in_transit_inflation_pct = (
            (in_transit_inflation / dedup_in_transit * 100.0) if dedup_in_transit > 0 else 0.0
        )

        passed = (
            dedup_bounced == EXPECTED_PORTFOLIO_BOUNCED
            and dedup_in_transit == EXPECTED_PORTFOLIO_IN_TRANSIT
            and dedup_cleared == EXPECTED_PORTFOLIO_CLEARED
        )

        return {
            "passed": passed,
            "deduplicated": {
                "bounced": dedup_bounced,
                "in_transit": dedup_in_transit,
                "cleared": dedup_cleared,
            },
            "naive_multiplied": {
                "bounced": naive_bounced,
                "in_transit": naive_in_transit,
                "cleared": naive_cleared,
            },
            "inflation": {
                "bounced_amount": bounced_inflation,
                "bounced_pct": round(bounced_inflation_pct, 2),
                "in_transit_amount": in_transit_inflation,
                "in_transit_pct": round(in_transit_inflation_pct, 2),
                "cleared_amount": cleared_inflation,
            },
            "explanation": (
                "خطای سیستم قبلی ناشی از ضرب وضعیت بانکی مشتری در تعداد چک‌های فیزیکی وی نزد صندوق بود. "
                f"رقم واقعی بدهی برگشتی سبد {dedup_bounced:,.0f} ریال است نه ارقام تورمی."
            ),
        }

    def verify_financial_integrity(self) -> Dict[str, Any]:
        """
        Comprehensive integrity verification for Milestone 2 financial separation:
        1. Fund cheques audit (147 cheques, 483,325,000,000 Rials).
        2. Golden Rule banking audit (in-flight 4.466T, bounced 231.951B, cleared 1.024T).
        3. Zero discrepancy check.
        """
        fund_audit = self.get_fund_cheques_audit()
        banking_summary = self.get_portfolio_banking_summary()
        double_count_audit = self.audit_no_double_count()

        is_passed = (
            fund_audit["verified"]
            and banking_summary["verified_no_double_count"]
            and double_count_audit["passed"]
        )

        return {
            "passed": is_passed,
            "fund_audit": fund_audit,
            "banking_summary": banking_summary,
            "double_count_audit": double_count_audit,
        }
