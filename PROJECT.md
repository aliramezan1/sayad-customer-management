# Project: Sayad Customer Management (سیستم مدیریت و گزارش اعتباری مشتریان صیادی)

## Architecture
- **Architecture Style**: Clean modular service-oriented architecture with SQLite backend and OpenPyXL Excel reporting.
- **Data Flow**:
  1. Raw Data (`چک_ها صندوق ١۴٠۵٠۵٢٩.xlsx`, `customers.db`, `نتایج_استعلام.xlsx`)
  2. `IdentityResolver`: Deduplicates to 48 unique customers, formats 10-digit National IDs, separates 0933387075 (Heshmati vs Alipour), flags UNRESOLVED_IDENTITY & EXEMPT. [DONE]
  3. `FinancialAggregator`: Enforces the Golden Rule of No-Double-Count (banking inquiry status aggregated strictly once per unique customer); audits fund checks (exactly 147 checks = 483,325,000,000 Rials). [DONE]
  4. `TrendDetector`: Computes data freshness tags, detects transitions ('in-flight -> bounced', e.g. Zahra Bahrami Pouya -3.5B / +3.5B), clearances, and bounce persistence (chronic, intermittent, new, clean). [DONE]
  5. `RiskEngine`: Computes 0-100 risk score using 7 weighted components, applies all 6 mandatory floors, calculates HHI concentration index and top 10 risk issuers. [DONE]
  6. `ExcelExporter` & `DualAuditService`: Builds the 10-sheet RTL Excel report with Vazirmatn/Tahoma styling, Rial formatting, 14 formulaic dual-audit checks (PASS), saving to project root and Desktop. [IN_PROGRESS]

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | F1 | 10-digit text national ID primary key with leading zeros preserved & hierarchical validation | M1 | ORIGINAL_REQUEST §R1 |
| 2 | F2 | Disambiguation of national code 0933387075 (Hossein Heshmati check 2380030072556088 vs Amirhossein Alipour promissory note 1113333) | M1 | ORIGINAL_REQUEST §R1 |
| 3 | F3 | Flagging UNRESOLVED_IDENTITY (missing national IDs) and EXEMPT (promissory notes) | M1 | ORIGINAL_REQUEST §R1 |
| 4 | F4 | Strict financial separation: physical fund commitments vs banking inquiry status | M2 | ORIGINAL_REQUEST §R2 |
| 5 | F5 | Golden Rule of No-Double-Count: Unique customer banking status aggregated strictly ONCE | M2 | ORIGINAL_REQUEST §R2 |
| 6 | F6 | Fund checks audit: Exactly 147 checks totaling 483,325,000,000 Rials | M2 | ORIGINAL_REQUEST §R2 |
| 7 | F7 | Data freshness status labeling (FRESH_SUCCESS, REUSED_VALID_SUCCESS, etc.) | M2 | ORIGINAL_REQUEST §R3 |
| 8 | F8 | Transition detection 'in-flight -> bounced' (Zahra Bahrami Pouya -3.5B / +3.5B, Toroghi, etc.) | M2 | ORIGINAL_REQUEST §R3 |
| 9 | F9 | Real clearance detection (کاهش برگشتی ≈ افزایش رفع سوءاثر, e.g. Javad Ghafourian) | M2 | ORIGINAL_REQUEST §R3 |
| 10 | F10 | Bounce persistence classification (chronic >=6, intermittent 3-5, new 1-2, clean 0) | M2 | ORIGINAL_REQUEST §R3 |
| 11 | F11 | Exact 7-component risk scoring formula (30%, 20%, 15%, 15%, 10%, 5%, 5%) | M3 | ORIGINAL_REQUEST §R4 |
| 12 | F12 | Mandatory risk score floors (>50B->85, >20B->78, >10B->72, >5B->65, pos->45, new->35) | M3 | ORIGINAL_REQUEST §R4 |
| 13 | F13 | 5 Risk tiers and HHI concentration calculation for top 10 issuers | M3 | ORIGINAL_REQUEST §R4 |
| 14 | F14 | 10-Sheet professional RTL Excel generator with Vazirmatn/Tahoma & Rial formatting | M4 | ORIGINAL_REQUEST §R5 |
| 15 | F15 | Dual-Audit sheet (`09_ممیزی`) with 14 automated PASS/FAIL validation formulas | M4 | ORIGINAL_REQUEST §R5 |
| 16 | F16 | Test isolation and alignment to 48 canonical customers | M1 | code_analysis.md |
| 17 | F17 | Mandatory closing statement insertion and verification | M4 | ORIGINAL_REQUEST §R5 |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Identity Resolution & Customer Deduplication | R1 (F1, F2, F3, F16): `identity_resolver.py` & canonical customer deduplication | none | DONE |
| M2 | Financial Separation & Trend/Event Engine | R2, R3 (F4, F5, F6, F7, F8, F9, F10): `financial_aggregator.py` & `trend_detector.py` | M1 | DONE |
| M3 | Risk Scoring & Concentration Engine | R4 (F11, F12, F13): `risk_engine.py` with 7 components, 6 floors, HHI | M2 | DONE |
| M4 | 10-Sheet Excel Workbook & Dual-Audit Generator | R5 (F14, F15, F17): `excel_exporter.py`, `dual_audit_service.py`, report outputs | M3 | DONE (27 tests passed) |
| M5 | E2E Verification & Forensic Integrity Audit | Acceptance Criteria 1-4 validation, Challenger testing, Forensic Integrity Audit | M4 | PLANNED |

## Interface Contracts

### `IdentityResolver` (`app/services/identity_resolver.py`) - STATUS: DONE (72 tests passed)
```python
class IdentityResolver:
    def get_canonical_customers(self) -> list[dict]: ...
```

### `FinancialAggregator` (`app/services/financial_aggregator.py`) - STATUS: DONE (28 tests passed)
```python
class FinancialAggregator:
    def get_fund_cheques_audit(self) -> dict: ...
    def get_portfolio_banking_summary(self) -> dict: ...
```

### `TrendDetector` (`app/services/trend_detector.py`) - STATUS: DONE (28 tests passed)
```python
class TrendDetector:
    def detect_events(self) -> list[dict]: ...
```

### `RiskEngine` (`app/services/risk_engine.py`) - STATUS: DONE (25 tests passed)
```python
class RiskEngine:
    def calculate_customer_risk(self, customer_data: dict) -> dict: ...
    def compute_hhi_concentration(self, high_risk_customers: list[dict]) -> dict: ...
```

### `ExcelExporter` (`app/services/excel_exporter.py`)
```python
class ExcelExporter:
    def generate_10_sheet_workbook(self, output_path: str) -> str:
        """Generates the full 10-sheet RTL Excel workbook with Vazirmatn/Tahoma font,
        Rial formatting, and sheet 09_ممیزی with 14 automated PASS/FAIL formulas."""
        ...
```
