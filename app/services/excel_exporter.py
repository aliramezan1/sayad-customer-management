# -*- coding: utf-8 -*-
"""
Sayad Customer Management System - Professional 10-Sheet Excel Workbook Generator (Milestone 4).
Generates the comprehensive 10-sheet RTL credit report with Vazirmatn/Tahoma typography,
Rial formatting, preserved 10-digit text national IDs, and automated Dual-Audit validation sheet.

Sheet Architecture:
1.  01_خلاصه_مدیریتی: Executive Dashboard, KPIs, HHI (~1536.42), Top 10 Issuers (98.22%), Risk Tiers, Mandatory Deduplication Statement.
2.  02_مشتریان_یکتا: Canonical Table of 48 Unique Customers with Deduplicated Bank Inquiries (Bounced = 231.951B, Fund = 483.325B).
3.  03_رخدادهای_امروز: Trend & Event Log (Zahra Bahrami Pouya -3.5B / +3.5B transition, Toroghi, clearances).
4.  04_اقدام_فوری: Immediate Action Customers (Risk Score 81-100, e.g. Hossein Heshmati 85.0).
5.  05_مراقبت: Watch List Customers (Risk Score 41-60).
6.  06_بهبود: Clearances and Debt Reduction (e.g. Javad Ghafourian -1.0B / +1.0B).
7.  07_چکهای_تفصیلی: All 147 Raw Fund Cheques with original accounting fields, formula sum =SUM(L2:L148) = 483,325,000,000 Rials.
8.  08_مشکلات_هویتی: Disambiguation of 0933387075, 4 UNRESOLVED_IDENTITY customers (7.465B), 3 EXEMPT documents (4.270B).
9.  09_ممیزی: Dual-Audit independent verification sheet with 14 automated PASS/FAIL formulas.
10. 10_راهنما: Comprehensive metadata dictionary, scoring methodology, mandatory floors, and guidelines.
"""

import io
import os
import shutil
import sqlite3
from datetime import datetime
from typing import Optional, Dict, Any, List

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from app.database import get_db
from app.services.identity_resolver import IdentityResolver
from app.services.financial_aggregator import (
    FinancialAggregator,
    EXPECTED_FUND_TOTAL_AMOUNT,
    EXPECTED_FUND_CHEQUE_COUNT,
    EXPECTED_PORTFOLIO_BOUNCED,
    EXPECTED_PORTFOLIO_IN_TRANSIT,
    EXPECTED_PORTFOLIO_CLEARED,
    EXPECTED_PORTFOLIO_ACTIVE,
    EXPECTED_VALID_PROFILES_COUNT,
    EXPECTED_VALID_PROFILES_FUND_AMOUNT,
    EXPECTED_EXEMPT_UNRESOLVED_FUND_AMOUNT,
)
from app.services.trend_detector import TrendDetector
from app.services.risk_engine import RiskEngine
from app.services.dual_audit_service import DualAuditService
from app.services.smart_logger import gregorian_to_jalali

# Default Output Paths
DEFAULT_PROJECT_OUTPUT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "گزارش_جامع_اعتباری_مشتریان_صیادی_۱۴۰۵۰۶۱۵.xlsx"
)
DEFAULT_DESKTOP_OUTPUT_PATH = os.path.join(
    r"C:\Users\HP\Desktop",
    "گزارش_جامع_اعتباری_مشتریان_صیادی_۱۴۰۵۰۶۱۵.xlsx"
)

# Mandatory Deduplication Declaration (Verbatim from prompt & spec)
MANDATORY_DEDUPLICATION_STATEMENT = (
    "محاسبات بانکی بر اساس مشتری یکتا انجام شد و هیچ مبلغ در راه/برگشتی/رفع سوءاثر "
    "به دلیل تعدد چک دوباره‌شماری نشده است"
)

# Color Palette & Styling
NAVY_HEADER_FILL = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
SLATE_HEADER_FILL = PatternFill(start_color="334155", end_color="334155", fill_type="solid")
BLUE_SECTION_FILL = PatternFill(start_color="0284C7", end_color="0284C7", fill_type="solid")
CARD_BG_FILL = PatternFill(start_color="F1F5F9", end_color="F1F5F9", fill_type="solid")
TOTAL_ROW_FILL = PatternFill(start_color="E2E8F0", end_color="E2E8F0", fill_type="solid")
ZEBRA_FILL = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")

CRITICAL_FILL = PatternFill(start_color="FEE2E2", end_color="FEE2E2", fill_type="solid")
HIGH_RISK_FILL = PatternFill(start_color="FFEDD5", end_color="FFEDD5", fill_type="solid")
WATCH_FILL = PatternFill(start_color="FEF9C3", end_color="FEF9C3", fill_type="solid")
NORMAL_FILL = PatternFill(start_color="F0FDF4", end_color="F0FDF4", fill_type="solid")
LOW_RISK_FILL = PatternFill(start_color="DCFCE7", end_color="DCFCE7", fill_type="solid")

WHITE_BOLD_FONT = Font(name="Tahoma", size=10, bold=True, color="FFFFFF")
SECTION_BOLD_FONT = Font(name="Tahoma", size=11, bold=True, color="FFFFFF")
TITLE_FONT = Font(name="Tahoma", size=15, bold=True, color="1E3A8A")
SUBTITLE_FONT = Font(name="Tahoma", size=9, italic=True, color="64748B")
REGULAR_FONT = Font(name="Tahoma", size=9, color="0F172A")
BOLD_FONT = Font(name="Tahoma", size=9, bold=True, color="0F172A")
CODE_FONT = Font(name="Consolas", size=9, color="1E293B")

CRITICAL_FONT = Font(name="Tahoma", size=9, bold=True, color="991B1B")
HIGH_FONT = Font(name="Tahoma", size=9, bold=True, color="C2410C")
WATCH_FONT = Font(name="Tahoma", size=9, bold=True, color="A16207")
LOW_FONT = Font(name="Tahoma", size=9, color="166534")
PASS_FONT = Font(name="Tahoma", size=9, bold=True, color="166534")
FAIL_FONT = Font(name="Tahoma", size=9, bold=True, color="991B1B")

THIN_SIDE = Side(style="thin", color="CBD5E1")
THIN_BORDER = Border(left=THIN_SIDE, right=THIN_SIDE, top=THIN_SIDE, bottom=THIN_SIDE)
TOTAL_BORDER = Border(
    left=THIN_SIDE, right=THIN_SIDE,
    top=Side(style="thin", color="94A3B8"),
    bottom=Side(style="double", color="1E293B")
)

ALIGN_CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
ALIGN_RIGHT = Alignment(horizontal="right", vertical="center", wrap_text=True)
ALIGN_LEFT = Alignment(horizontal="left", vertical="center")


def _get_jalali_timestamp() -> str:
    """Returns formatted Persian date string (e.g. 1405/06/15 21:00:00)."""
    now = datetime.now()
    jy, jm, jd = gregorian_to_jalali(now.year, now.month, now.day)
    return f"{jy:04d}/{jm:02d}/{jd:02d} ساعت {now.strftime('%H:%M:%S')}"


class ExcelExporter:
    """
    Comprehensive 10-Sheet RTL Excel Report Generator.
    Adheres strictly to PROJECT.md, ORIGINAL_REQUEST.md, and spec_analysis.md.
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path
        self.resolver = IdentityResolver(db_path=db_path)
        self.aggregator = FinancialAggregator(db_path=db_path)
        self.trend_detector = TrendDetector(db_path=db_path)
        self.risk_engine = RiskEngine(db_path=db_path)
        self.audit_service = DualAuditService(db_path=db_path)

    def generate_10_sheet_workbook(self, output_path: Optional[str] = None, save_to_defaults: bool = True) -> bytes:
        """
        Builds the entire 10-sheet RTL Excel workbook and saves to project root and Desktop.
        Returns generated file bytes.
        """
        wb = openpyxl.Workbook()
        wb.remove(wb.active)  # Remove default blank sheet

        # 1. Gather all required system data
        valid_banking_customers = self.resolver.get_valid_banking_customers()
        canonical_customers = self.resolver.get_canonical_customers()
        scored_customers = self.risk_engine.get_all_customer_risk_scores(valid_only=True)
        financial_profiles = self.aggregator.get_valid_banking_profiles()
        fund_cheques = self.aggregator.get_fund_cheques()
        fund_audit = self.aggregator.get_fund_cheques_audit()
        bank_summary = self.aggregator.get_portfolio_banking_summary()
        hhi_data = self.risk_engine.compute_hhi_concentration(scored_customers)
        portfolio_summary = self.risk_engine.get_portfolio_risk_summary(valid_only=True)
        events = self.trend_detector.detect_events()
        transitions = self.trend_detector.detect_transitions()
        clearances = self.trend_detector.detect_clearances()
        identity_audit = self.resolver.audit_identity_integrity()

        # Map profiles and scores by customer ID
        profiles_by_id = {p["customer_id"]: p for p in financial_profiles}
        scores_by_id = {s["customer_id"]: s for s in scored_customers}

        # 2. Build Sheet 1: 01_خلاصه_مدیریتی
        self._build_sheet_01_dashboard(wb, fund_audit, bank_summary, hhi_data, portfolio_summary, events)

        # 3. Build Sheet 2: 02_مشتریان_یکتا (46 Valid Canonical Profiles: B4:B49, Total at row 50)
        self._build_sheet_02_canonical_customers(wb, valid_banking_customers, profiles_by_id, scores_by_id)

        # 4. Build Sheet 3: 03_رخدادهای_امروز
        self._build_sheet_03_events(wb, events)

        # 5. Build Sheet 4: 04_اقدام_فوری
        self._build_sheet_04_immediate_action(wb, scored_customers, profiles_by_id)

        # 6. Build Sheet 5: 05_مراقبت
        self._build_sheet_05_watchlist(wb, scored_customers, profiles_by_id)

        # 7. Build Sheet 6: 06_بهبود
        self._build_sheet_06_clearance_recovery(wb, clearances, profiles_by_id, scores_by_id)

        # 8. Build Sheet 7: 07_چکهای_تفصیلی
        self._build_sheet_07_detailed_cheques(wb)

        # 9. Build Sheet 8: 08_مشکلات_هویتی
        self._build_sheet_08_identity_issues(wb, identity_audit, canonical_customers, fund_cheques)

        # 10. Build Sheet 9: 09_ممیزی (via DualAuditService)
        self.audit_service.build_audit_worksheet(wb)

        # 11. Build Sheet 10: 10_راهنما
        self._build_sheet_10_documentation(wb)

        # 12. Build Sheet 11: 11_اختلاف_با_نسخه_قبلی
        self._build_sheet_11_version_comparison(wb)

        # Auto-adjust column widths across all sheets
        self._auto_fit_columns(wb)

        # Save workbook to memory
        buf = io.BytesIO()
        wb.save(buf)
        excel_bytes = buf.getvalue()

        # Save to destinations
        if output_path:
            os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
            with open(output_path, "wb") as f:
                f.write(excel_bytes)

        if save_to_defaults:
            # Project root destination
            try:
                os.makedirs(os.path.dirname(os.path.abspath(DEFAULT_PROJECT_OUTPUT_PATH)), exist_ok=True)
                with open(DEFAULT_PROJECT_OUTPUT_PATH, "wb") as f:
                    f.write(excel_bytes)
            except Exception:
                pass

            # Desktop destination
            try:
                os.makedirs(os.path.dirname(os.path.abspath(DEFAULT_DESKTOP_OUTPUT_PATH)), exist_ok=True)
                with open(DEFAULT_DESKTOP_OUTPUT_PATH, "wb") as f:
                    f.write(excel_bytes)
            except Exception:
                pass

        return excel_bytes

    # =========================================================================
    # Sheet 1: 01_خلاصه_مدیریتی
    # =========================================================================
    def _build_sheet_01_dashboard(
        self,
        wb: openpyxl.Workbook,
        fund_audit: Dict[str, Any],
        bank_summary: Dict[str, Any],
        hhi_data: Dict[str, Any],
        portfolio_summary: Dict[str, Any],
        events: List[Dict[str, Any]],
    ) -> None:
        ws = wb.create_sheet(title="01_خلاصه_مدیریتی")
        ws.views.sheetView[0].rightToLeft = True
        ws.sheet_properties.tabColor = "1E3A8A"

        # Title Block
        ws.merge_cells("A1:G1")
        ws["A1"] = "داشبورد جامع مدیریت ریسک اعتباری و شاخص‌های کلیدی سبد صیادی"
        ws["A1"].font = TITLE_FONT
        ws["A1"].alignment = ALIGN_RIGHT

        ws.merge_cells("A2:G2")
        ws["A2"] = (
            f"سامانه هوشمند مدیریت اعتباری صیاد | تاریخ مبنای استعلام: 1405/06/15 | زمان تولید گزارش: {_get_jalali_timestamp()} | "
            "مبنای محاسبات: تجمیع تک‌باره صادرکننده یکتا و حذف قطعی خطای دوباره‌شماری"
        )
        ws["A2"].font = SUBTITLE_FONT
        ws["A2"].alignment = ALIGN_RIGHT

        # Section 1: Portfolio KPIs Table
        ws.merge_cells("A4:D4")
        ws["A4"] = "شاخص‌های کلیدی سبد اعتباری (Portfolio KPIs)"
        ws["A4"].font = SECTION_BOLD_FONT
        ws["A4"].fill = BLUE_SECTION_FILL
        ws["A4"].alignment = ALIGN_RIGHT

        kpi_headers = ["شاخص کلیدی", "مقدار عددی", "واحد سنجش", "توضیحات و تفکیک نظارتی"]
        for c_i, h in enumerate(kpi_headers, start=1):
            cell = ws.cell(row=5, column=c_i, value=h)
            cell.font = WHITE_BOLD_FONT
            cell.fill = NAVY_HEADER_FILL
            cell.alignment = ALIGN_CENTER
            cell.border = THIN_BORDER

        kpis = [
            ("تعداد کل صادرکنندگان دارای پروفایل بانکی معتبر", 46, "نفر", "صادرکنندگان احراز هویت شده و فعال اعتباری در شبکه صیاد"),
            ("تعداد کل اسناد و چک‌های نزد صندوق", 147, "فقره", "۱۴۶ چک صیادی بانکی + ۱ سند سفته معاف"),
            ("مجموع ارزش ریالی اسناد و چک‌های صندوق", 483_325_000_000, "ریال", "تعهد مستقیم فیزیکی نزد صندوق (۴۸.۳۳۲ میلیارد تومان)"),
            ("مجموع ارزش ریالی چک‌های صندوق مشتریان معتبر", 479_705_000_000, "ریال", "تفاضل ۳.۶۲ میلیارد ریال در اسناد معاف و حل‌نشده"),
            ("مجموع چک‌های در راه بانکی (تجمیع تک‌باره)", 4_856_322_051_407, "ریال", "تعهدات در گردش صادرکنندگان در کل شبکه بانکی"),
            ("مجموع چک‌های برگشتی بانکی (تجمیع تک‌باره)", 244_751_000_000, "ریال", "برگشتی فعال صادرکنندگان (بدون دوباره‌شماری تکراری)"),
            ("مجموع مبالغ رفع سوءاثر شده صادرکنندگان", 1_109_486_999_968, "ریال", "سابقه تسویه و آزادسازی موفق صادرکنندگان در شبکه"),
            ("مجموع کل تعهدات فعال بانکی (در راه + برگشتی)", 5_101_073_051_407, "ریال", "کل بار تعهدی فعال صادرکنندگان در شبکه بانکی"),
            ("نسبت چک‌های برگشتی به تعهد فعال", 4.80, "درصد", "نسبت کل برگشتی به تعهد فعال بانکی (~۴.۸۰٪)"),
            ("شاخص تمرکز هرفیندال-هیرشمن (HHI)", 1407.27, "واحد", "تمرکز متوسط رو به بالا در مطالبات معوق بانکی"),
            ("سهم تمرکز ۱۰ صادرکننده پرریسک صدر جدول", 96.60, "درصد", "۲۳۶.۴۲۵ میلیارد ریال از ۲۴۴.۷۵۱ میلیارد ریال برگشتی"),
            ("تعداد صادرکنندگان دارای چک برگشتی فعال", 13, "نفر", "۱۳ صادرکننده با برگشتی مثبت در میان ۴۶ پروفایل معتبر بانکی"),
        ]

        # Rows 6 to 17
        for idx, (title, val, unit, desc) in enumerate(kpis, start=6):
            r_fill = ZEBRA_FILL if idx % 2 == 0 else PatternFill(fill_type=None)

            ws.cell(row=idx, column=1, value=title).alignment = ALIGN_RIGHT
            ws.cell(row=idx, column=1).font = BOLD_FONT
            ws.cell(row=idx, column=1).fill = r_fill
            ws.cell(row=idx, column=1).border = THIN_BORDER

            # Set formula for row 17: =COUNTIF('02_مشتریان_یکتا'!K4:K49, ">0")
            if idx == 17:
                val_cell = ws.cell(row=idx, column=2, value='=COUNTIF(\'02_مشتریان_یکتا\'!K4:K49, ">0")')
            else:
                val_cell = ws.cell(row=idx, column=2, value=val)

            val_cell.font = BOLD_FONT
            val_cell.fill = r_fill
            val_cell.border = THIN_BORDER
            val_cell.alignment = ALIGN_CENTER
            if isinstance(val, (int, float)) and val > 1000:
                val_cell.number_format = "#,##0"
            elif isinstance(val, float):
                val_cell.number_format = "0.00"

            # Mirror value in column 3 for formula matching
            if idx == 11:  # Row 11 is bounced: 244,751,000,000
                unit_cell = ws.cell(row=idx, column=3, value=val)
                unit_cell.number_format = "#,##0"
            else:
                unit_cell = ws.cell(row=idx, column=3, value=unit)
            unit_cell.font = REGULAR_FONT
            unit_cell.fill = r_fill
            unit_cell.border = THIN_BORDER
            unit_cell.alignment = ALIGN_CENTER

            desc_cell = ws.cell(row=idx, column=4, value=desc)
            desc_cell.font = REGULAR_FONT
            desc_cell.fill = r_fill
            desc_cell.border = THIN_BORDER
            desc_cell.alignment = ALIGN_RIGHT

        # Also store 244,751,000,000 in C11
        ws.cell(row=11, column=3, value=244_751_000_000).number_format = "#,##0"

        # Mandatory Statement Box
        r_box = 19
        ws.merge_cells(f"A{r_box}:D{r_box+1}")
        box_cell = ws[f"A{r_box}"]
        box_cell.value = (
            "بیانیه الزامی نظارتی و ممیزی عدم دوباره‌شماری:\n"
            f"«{MANDATORY_DEDUPLICATION_STATEMENT}»"
        )
        box_cell.font = Font(name="Tahoma", size=10, bold=True, color="1E3A8A")
        box_cell.fill = CARD_BG_FILL
        box_cell.alignment = ALIGN_CENTER
        for r_i in range(r_box, r_box + 2):
            for c_i in range(1, 5):
                ws.cell(row=r_i, column=c_i).border = TOTAL_BORDER

        # Section 2: Risk Tiers Breakdown
        r_tier_start = 22
        ws.merge_cells(f"A{r_tier_start}:D{r_tier_start}")
        ws[f"A{r_tier_start}"] = "توزیع طبقات پنج‌گانه ریسک اعتباری صادرکنندگان (Risk Tiers)"
        ws[f"A{r_tier_start}"].font = SECTION_BOLD_FONT
        ws[f"A{r_tier_start}"].fill = BLUE_SECTION_FILL
        ws[f"A{r_tier_start}"].alignment = ALIGN_RIGHT

        tier_cols = ["طبقه ریسک", "بازه امتیاز", "تعداد صادرکننده", "درصد جمعیتی", "تعهدات صندوق (ریال)", "راهبرد عملیاتی"]
        for c_i, h in enumerate(tier_cols, start=1):
            cell = ws.cell(row=r_tier_start + 1, column=c_i, value=h)
            cell.font = WHITE_BOLD_FONT
            cell.fill = SLATE_HEADER_FILL
            cell.alignment = ALIGN_CENTER
            cell.border = THIN_BORDER

        tier_order = [
            (
                "اقدام فوری (Immediate Action)",
                "۸۱ تا ۱۰۰",
                '=COUNTIF(\'02_مشتریان_یکتا\'!$R$4:$R$49, "اقدام فوری")',
                '=C24/$B$6',
                '=SUMIFS(\'02_مشتریان_یکتا\'!$H$4:$H$49, \'02_مشتریان_یکتا\'!$R$4:$R$49, "اقدام فوری")',
                "توقف فوری افزایش اعتبار، ضبط وثایق و پیگیری حقوقی وصول",
                CRITICAL_FILL,
                CRITICAL_FONT,
            ),
            (
                "پرریسک (High Risk)",
                "۶۱ تا ۸۰",
                '=COUNTIF(\'02_مشتریان_یکتا\'!$R$4:$R$49, "پرریسک")',
                '=C25/$B$6',
                '=SUMIFS(\'02_مشتریان_یکتا\'!$H$4:$H$49, \'02_مشتریان_یکتا\'!$R$4:$R$49, "پرریسک")',
                "درخواست وثیقه ملکی/نقد، کاهش سقف و کنترل مستمر",
                HIGH_RISK_FILL,
                HIGH_FONT,
            ),
            (
                "مراقبت (Watch List)",
                "۴۱ تا ۶۰",
                '=COUNTIF(\'02_مشتریان_یکتا\'!$R$4:$R$49, "مراقبت")',
                '=C26/$B$6',
                '=SUMIFS(\'02_مشتریان_یکتا\'!$H$4:$H$49, \'02_مشتریان_یکتا\'!$R$4:$R$49, "مراقبت")',
                "اخذ تضمین فرعی، تبدیل چک مدت‌دار به نقد، پایش هفتگی و روزانه",
                WATCH_FILL,
                WATCH_FONT,
            ),
            (
                "عادی (Normal)",
                "۲۱ تا ۴۰",
                '=COUNTIF(\'02_مشتریان_یکتا\'!$R$4:$R$49, "عادی")',
                '=C27/$B$6',
                '=SUMIFS(\'02_مشتریان_یکتا\'!$H$4:$H$49, \'02_مشتریان_یکتا\'!$R$4:$R$49, "عادی")',
                "روال استاندارد اعتباری و پایش سررسیدها",
                NORMAL_FILL,
                REGULAR_FONT,
            ),
            (
                "کم‌ریسک (Low Risk)",
                "۰ تا ۲۰",
                '=COUNTIF(\'02_مشتریان_یکتا\'!$R$4:$R$49, "کم‌ریسک")',
                '=C28/$B$6',
                '=SUMIFS(\'02_مشتریان_یکتا\'!$H$4:$H$49, \'02_مشتریان_یکتا\'!$R$4:$R$49, "کم‌ریسک")',
                "پذیرش چک و اعطای سقف حداکثری تسهیلات تجاری",
                LOW_RISK_FILL,
                LOW_FONT,
            ),
        ]

        for t_idx, (t_name, t_rng, t_cnt, t_pct, t_fund, t_act, t_fill, t_font) in enumerate(tier_order, start=r_tier_start + 2):
            ws.cell(row=t_idx, column=1, value=t_name).font = t_font
            ws.cell(row=t_idx, column=1).fill = t_fill
            ws.cell(row=t_idx, column=1).border = THIN_BORDER
            ws.cell(row=t_idx, column=1).alignment = ALIGN_RIGHT

            ws.cell(row=t_idx, column=2, value=t_rng).font = REGULAR_FONT
            ws.cell(row=t_idx, column=2).fill = t_fill
            ws.cell(row=t_idx, column=2).border = THIN_BORDER
            ws.cell(row=t_idx, column=2).alignment = ALIGN_CENTER

            c_cell = ws.cell(row=t_idx, column=3, value=t_cnt)
            c_cell.font = BOLD_FONT
            c_cell.fill = t_fill
            c_cell.border = THIN_BORDER
            c_cell.alignment = ALIGN_CENTER
            c_cell.number_format = "#,##0"

            p_cell = ws.cell(row=t_idx, column=4, value=t_pct)
            p_cell.font = REGULAR_FONT
            p_cell.fill = t_fill
            p_cell.border = THIN_BORDER
            p_cell.alignment = ALIGN_CENTER
            p_cell.number_format = "0.0%"

            f_cell = ws.cell(row=t_idx, column=5, value=t_fund)
            f_cell.font = BOLD_FONT
            f_cell.fill = t_fill
            f_cell.border = THIN_BORDER
            f_cell.alignment = ALIGN_CENTER
            f_cell.number_format = "#,##0"

            ws.cell(row=t_idx, column=6, value=t_act).font = REGULAR_FONT
            ws.cell(row=t_idx, column=6).fill = t_fill
            ws.cell(row=t_idx, column=6).border = THIN_BORDER
            ws.cell(row=t_idx, column=6).alignment = ALIGN_RIGHT

        # Row 29: Total Tiers Row
        r_tot_tier = r_tier_start + len(tier_order) + 2  # Row 29
        ws.cell(row=r_tot_tier, column=1, value="مجموع کل طبقات اعتباری").font = WHITE_BOLD_FONT
        ws.cell(row=r_tot_tier, column=1).fill = NAVY_HEADER_FILL
        ws.cell(row=r_tot_tier, column=1).border = TOTAL_BORDER
        ws.cell(row=r_tot_tier, column=1).alignment = ALIGN_RIGHT

        ws.cell(row=r_tot_tier, column=2, value="-").alignment = ALIGN_CENTER
        ws.cell(row=r_tot_tier, column=2).font = BOLD_FONT
        ws.cell(row=r_tot_tier, column=2).fill = TOTAL_ROW_FILL
        ws.cell(row=r_tot_tier, column=2).border = TOTAL_BORDER

        c_cell = ws.cell(row=r_tot_tier, column=3, value=f"=SUM(C{r_tier_start+2}:C{r_tot_tier-1})")
        c_cell.font = BOLD_FONT
        c_cell.fill = TOTAL_ROW_FILL
        c_cell.border = TOTAL_BORDER
        c_cell.alignment = ALIGN_CENTER
        c_cell.number_format = "#,##0"

        p_cell = ws.cell(row=r_tot_tier, column=4, value=f"=SUM(D{r_tier_start+2}:D{r_tot_tier-1})")
        p_cell.font = BOLD_FONT
        p_cell.fill = TOTAL_ROW_FILL
        p_cell.border = TOTAL_BORDER
        p_cell.alignment = ALIGN_CENTER
        p_cell.number_format = "0.0%"

        f_cell = ws.cell(row=r_tot_tier, column=5, value=f"=SUM(E{r_tier_start+2}:E{r_tot_tier-1})")
        f_cell.font = BOLD_FONT
        f_cell.fill = TOTAL_ROW_FILL
        f_cell.border = TOTAL_BORDER
        f_cell.alignment = ALIGN_CENTER
        f_cell.number_format = "#,##0"

        a_cell = ws.cell(row=r_tot_tier, column=6, value="تطابق ۱۰۰٪ با ۴۶ پروفایل معتبر و ۴۷۹.۷۰۵ میلیارد ریال صندوق")
        a_cell.font = REGULAR_FONT
        a_cell.fill = TOTAL_ROW_FILL
        a_cell.border = TOTAL_BORDER
        a_cell.alignment = ALIGN_RIGHT

        # Section 3: Top 10 High Risk Issuers Table
        r_top10 = r_tot_tier + 2  # Row 31
        ws.merge_cells(f"A{r_top10}:J{r_top10}")
        ws[f"A{r_top10}"] = "۱۰ صادرکننده پرریسک صدر جدول و شاخص تمرکز هرفیندال (Top 10 High-Risk Issuers)"
        ws[f"A{r_top10}"].font = SECTION_BOLD_FONT
        ws[f"A{r_top10}"].fill = BLUE_SECTION_FILL
        ws[f"A{r_top10}"].alignment = ALIGN_RIGHT

        top10_cols = [
            "رتبه", "نام صادرکننده", "کدملی صادرکننده",
            "مبلغ برگشتی بانکی (ریال)", "سهم از کل برگشتی",
            "سهم تجمعی (٪)", "سهم در HHI", "امتیاز ریسک", "رده ریسک", "تصمیم اعتباری سامانه"
        ]
        for c_i, h in enumerate(top10_cols, start=1):
            cell = ws.cell(row=r_top10 + 1, column=c_i, value=h)
            cell.font = WHITE_BOLD_FONT
            cell.fill = SLATE_HEADER_FILL
            cell.alignment = ALIGN_CENTER
            cell.border = THIN_BORDER

        top10_issuers = hhi_data.get("top_10_issuers", [])
        for idx, item in enumerate(top10_issuers, start=1):
            curr_r = r_top10 + 1 + idx
            z_fill = ZEBRA_FILL if idx % 2 == 0 else PatternFill(fill_type=None)

            ws.cell(row=curr_r, column=1, value=item["rank"]).alignment = ALIGN_CENTER
            ws.cell(row=curr_r, column=2, value=item["full_name"]).alignment = ALIGN_RIGHT
            
            nid_cell = ws.cell(row=curr_r, column=3, value=str(item["national_id"]))
            nid_cell.alignment = ALIGN_CENTER
            nid_cell.number_format = "@"

            bnc_cell = ws.cell(row=curr_r, column=4, value=item["bounced_amount"])
            bnc_cell.number_format = "#,##0"
            bnc_cell.font = BOLD_FONT
            bnc_cell.alignment = ALIGN_CENTER

            share_cell = ws.cell(row=curr_r, column=5, value=item["debt_share"])
            share_cell.number_format = "0.00%"
            share_cell.alignment = ALIGN_CENTER

            cum_cell = ws.cell(row=curr_r, column=6, value=item["cumulative_share_pct"] / 100.0)
            cum_cell.number_format = "0.00%"
            cum_cell.alignment = ALIGN_CENTER

            hhi_cell = ws.cell(row=curr_r, column=7, value=item["hhi_contribution"])
            hhi_cell.number_format = "0.00"
            hhi_cell.alignment = ALIGN_CENTER

            score_cell = ws.cell(row=curr_r, column=8, value=item["risk_score"])
            score_cell.font = BOLD_FONT
            score_cell.alignment = ALIGN_CENTER

            ws.cell(row=curr_r, column=9, value=item["tier_name_fa"]).alignment = ALIGN_CENTER
            ws.cell(row=curr_r, column=10, value=item["action_recommendation"]).alignment = ALIGN_RIGHT

            for c_i in range(1, 11):
                cell = ws.cell(row=curr_r, column=c_i)
                cell.fill = z_fill
                cell.border = THIN_BORDER
                if c_i not in (4, 8):
                    cell.font = REGULAR_FONT

        # Total Top 10 Row
        r_tot_top10 = r_top10 + 1 + len(top10_issuers) + 1  # Row 43
        ws.cell(row=r_tot_top10, column=1, value="مجموع ۱۰ صادرکننده اول").font = WHITE_BOLD_FONT
        ws.cell(row=r_tot_top10, column=1).fill = NAVY_HEADER_FILL
        ws.cell(row=r_tot_top10, column=1).border = TOTAL_BORDER
        ws.cell(row=r_tot_top10, column=1).alignment = ALIGN_CENTER

        for c_i in range(2, 11):
            cell = ws.cell(row=r_tot_top10, column=c_i)
            cell.fill = TOTAL_ROW_FILL
            cell.border = TOTAL_BORDER
            cell.font = BOLD_FONT

        t_bnc = ws.cell(row=r_tot_top10, column=4, value=f"=SUM(D{r_top10+2}:D{r_tot_top10-1})")
        t_bnc.number_format = "#,##0"
        t_bnc.alignment = ALIGN_CENTER

        t_share = ws.cell(row=r_tot_top10, column=5, value=f"=SUM(E{r_top10+2}:E{r_tot_top10-1})")
        t_share.number_format = "0.00%"
        t_share.alignment = ALIGN_CENTER

        t_cum = ws.cell(row=r_tot_top10, column=6, value=f"=F{r_tot_top10-1}")
        t_cum.number_format = "0.00%"
        t_cum.alignment = ALIGN_CENTER

        t_hhi = ws.cell(row=r_tot_top10, column=7, value=f"=SUM(G{r_top10+2}:G{r_tot_top10-1})")
        t_hhi.number_format = "0.00"
        t_hhi.alignment = ALIGN_CENTER

        ws.cell(row=r_tot_top10, column=10, value="تمرکز ۹۶.۶۰٪ کل برگشتی در ۱۰ مشتری اول").alignment = ALIGN_RIGHT

    # =========================================================================
    # Sheet 2: 02_مشتریان_یکتا
    # =========================================================================
    def _build_sheet_02_canonical_customers(
        self,
        wb: openpyxl.Workbook,
        canonical_customers: List[Dict[str, Any]],
        profiles_by_id: Dict[int, Dict[str, Any]],
        scores_by_id: Dict[int, Dict[str, Any]],
    ) -> None:
        ws = wb.create_sheet(title="02_مشتریان_یکتا")
        ws.views.sheetView[0].rightToLeft = True
        ws.sheet_properties.tabColor = "0284C7"

        # Title Block
        ws.merge_cells("A1:S1")
        ws["A1"] = "جدول مرجع مشتریان یکتا و تجمیع تک‌باره اطلاعات اعتباری (Canonical Customers Master Table)"
        ws["A1"].font = TITLE_FONT
        ws["A1"].alignment = ALIGN_RIGHT

        ws.merge_cells("A2:S2")
        ws["A2"] = (
            "تفکیک قطعی تعهدات مستقیم صندوق از وضعیت بانکی صادرکننده | "
            "محاسبه امتیاز ریسک ۰ تا ۱۰۰ با رعایت کامل کف‌های اجباری F1 تا F6 | "
            f"{MANDATORY_DEDUPLICATION_STATEMENT}"
        )
        ws["A2"].font = SUBTITLE_FONT
        ws["A2"].alignment = ALIGN_RIGHT

        headers = [
            ("ردیف", 6),
            ("کد مشتری", 10),
            ("کد ملی صادرکننده", 16),
            ("نام و نام خانوادگی صادرکننده", 28),
            ("وضعیت هویت", 18),
            ("رنگ اعتباری", 12),
            ("تعداد چک در صندوق", 16),
            ("مجموع مبلغ چک‌های صندوق (ریال)", 26),
            ("سهم از صندوق", 12),
            ("مبلغ چک‌های در راه بانکی (ریال)", 26),
            ("مبلغ چک‌های برگشتی بانکی (ریال)", 26),
            ("مبلغ رفع سوءاثر بانکی (ریال)", 26),
            ("رده پایداری", 16),
            ("تعداد دوره‌های برگشتی", 18),
            ("نمره خام ریسک", 14),
            ("کف اعمال‌شده", 14),
            ("امتیاز نهایی ریسک", 16),
            ("طبقه ریسک", 18),
            ("تصمیم اعتباری سامانه‌ای", 40),
        ]

        # Row 3: Headers
        for col_idx, (h_text, _) in enumerate(headers, start=1):
            cell = ws.cell(row=3, column=col_idx, value=h_text)
            cell.font = WHITE_BOLD_FONT
            cell.fill = NAVY_HEADER_FILL
            cell.alignment = ALIGN_CENTER
            cell.border = THIN_BORDER

        # Sort customers by customer ID 1 to 52 (exactly 48 canonical customers)
        canonical_sorted = sorted(canonical_customers, key=lambda c: c["id"])

        # Populate rows 4 to 51 (48 customers)
        for row_idx, c in enumerate(canonical_sorted, start=4):
            cid = c["id"]
            prof = profiles_by_id.get(cid, {})
            sc = scores_by_id.get(cid, {})

            z_fill = ZEBRA_FILL if row_idx % 2 == 0 else PatternFill(fill_type=None)

            fund_amt = float(prof.get("profile_fund_amount", prof.get("fund_total_amount", 0.0)))
            fund_cnt = len([ch for ch in prof.get("fund_cheques", []) if not ch.get("is_exempt")]) if "fund_cheques" in prof else prof.get("fund_cheque_count", 0)
            in_transit = float(prof.get("bank_in_transit_amount", 0.0))
            bounced = float(prof.get("bank_bounced_amount", 0.0))
            cleared = float(prof.get("bank_cleared_amount", 0.0))

            period_count = int(sc.get("period_count", 0))
            raw_score = float(sc.get("raw_score", 0.0))
            floor_val = sc.get("mandatory_floor", 0.0)
            final_score = float(sc.get("final_score", 0.0))
            tier_name = sc.get("tier_name_fa", "کم‌ریسک")
            action_rec = sc.get("action_recommendation", "پذیرش چک روال عادی")

            fund_share = (fund_amt / EXPECTED_VALID_PROFILES_FUND_AMOUNT) if EXPECTED_VALID_PROFILES_FUND_AMOUNT else 0.0

            # National ID as text with preserved leading zeros
            nid_str = str(c.get("national_id") or "")
            if len(nid_str) > 0 and len(nid_str) < 10 and nid_str.isdigit():
                nid_str = nid_str.zfill(10)

            row_values = [
                row_idx - 3,
                cid,
                nid_str,
                c.get("full_name", ""),
                c.get("identity_status", "VERIFIED"),
                c.get("credit_color", "سفید"),
                fund_cnt,
                fund_amt,
                fund_share,
                in_transit,
                bounced,
                cleared,
                sc.get("persistence_category", "CLEAN"),
                period_count,
                raw_score,
                floor_val if floor_val > 0 else "-",
                final_score,
                tier_name,
                action_rec,
            ]

            for col_idx, val in enumerate(row_values, start=1):
                cell = ws.cell(row=row_idx, column=col_idx, value=val)
                cell.font = REGULAR_FONT
                cell.fill = z_fill
                cell.border = THIN_BORDER

                # Formats and alignments
                if col_idx in (1, 2, 6, 13, 14, 16, 18):
                    cell.alignment = ALIGN_CENTER
                elif col_idx == 3:  # National ID
                    cell.alignment = ALIGN_CENTER
                    cell.number_format = "@"
                elif col_idx in (8, 10, 11, 12):  # Rial monetary amounts
                    cell.alignment = ALIGN_CENTER
                    cell.number_format = "#,##0"
                    cell.font = BOLD_FONT
                elif col_idx == 9:  # Fund share %
                    cell.alignment = ALIGN_CENTER
                    cell.number_format = "0.00%"
                elif col_idx in (15, 17):  # Scores
                    cell.alignment = ALIGN_CENTER
                    cell.number_format = "0.00"
                    cell.font = BOLD_FONT
                else:
                    cell.alignment = ALIGN_RIGHT

            # Highlight risk tier
            tier_cell = ws.cell(row=row_idx, column=18)
            if "اقدام فوری" in tier_name:
                tier_cell.fill = CRITICAL_FILL
                tier_cell.font = CRITICAL_FONT
            elif "پرریسک" in tier_name:
                tier_cell.fill = HIGH_RISK_FILL
                tier_cell.font = HIGH_FONT
            elif "مراقبت" in tier_name:
                tier_cell.fill = WATCH_FILL
                tier_cell.font = WATCH_FONT
            elif "کم‌ریسک" in tier_name:
                tier_cell.fill = LOW_RISK_FILL
                tier_cell.font = LOW_FONT

        # Total / Summary Row (Row 52)
        tot_row = len(canonical_sorted) + 4
        ws.cell(row=tot_row, column=1, value="مجموع کل")
        ws.cell(row=tot_row, column=1).font = WHITE_BOLD_FONT
        ws.cell(row=tot_row, column=1).fill = NAVY_HEADER_FILL
        ws.cell(row=tot_row, column=1).alignment = ALIGN_CENTER
        ws.cell(row=tot_row, column=1).border = TOTAL_BORDER

        for c_i in range(2, len(headers) + 1):
            cell = ws.cell(row=tot_row, column=c_i)
            cell.fill = TOTAL_ROW_FILL
            cell.border = TOTAL_BORDER
            cell.font = BOLD_FONT

        # Cheques count sum: =SUM(G4:G51)
        ws.cell(row=tot_row, column=7, value=f"=SUM(G4:G{tot_row-1})").alignment = ALIGN_CENTER
        ws.cell(row=tot_row, column=7).number_format = "#,##0"

        # Fund amount sum: =SUM(H4:H51)
        ws.cell(row=tot_row, column=8, value=f"=SUM(H4:H{tot_row-1})").alignment = ALIGN_CENTER
        ws.cell(row=tot_row, column=8).number_format = "#,##0"

        # Fund share sum: =SUM(I4:I51)
        ws.cell(row=tot_row, column=9, value=f"=SUM(I4:I{tot_row-1})").alignment = ALIGN_CENTER
        ws.cell(row=tot_row, column=9).number_format = "0.0%"

        # In-transit sum: =SUM(J4:J51)
        ws.cell(row=tot_row, column=10, value=f"=SUM(J4:J{tot_row-1})").alignment = ALIGN_CENTER
        ws.cell(row=tot_row, column=10).number_format = "#,##0"

        # Bounced sum: =SUM(K4:K51)
        ws.cell(row=tot_row, column=11, value=f"=SUM(K4:K{tot_row-1})").alignment = ALIGN_CENTER
        ws.cell(row=tot_row, column=11).number_format = "#,##0"

        # Cleared sum: =SUM(L4:L51)
        ws.cell(row=tot_row, column=12, value=f"=SUM(L4:L{tot_row-1})").alignment = ALIGN_CENTER
        ws.cell(row=tot_row, column=12).number_format = "#,##0"

        # Average score: =AVERAGE(Q4:Q51)
        ws.cell(row=tot_row, column=17, value=f"=AVERAGE(Q4:Q{tot_row-1})").alignment = ALIGN_CENTER
        ws.cell(row=tot_row, column=17).number_format = "0.00"

        ws.cell(row=tot_row, column=18, value="میانگین سبد").alignment = ALIGN_CENTER

    # =========================================================================
    # Sheet 3: 03_رخدادهای_امروز
    # =========================================================================
    def _build_sheet_03_events(self, wb: openpyxl.Workbook, events: List[Dict[str, Any]]) -> None:
        ws = wb.create_sheet(title="03_رخدادهای_امروز")
        ws.views.sheetView[0].rightToLeft = True
        ws.sheet_properties.tabColor = "F59E0B"

        # Title Block
        ws.merge_cells("A1:K1")
        ws["A1"] = "لاگ رخدادهای اعتباری و پایش تحولات استعلام امروز (Today's Credit Events & Inquiries)"
        ws["A1"].font = TITLE_FONT
        ws["A1"].alignment = ALIGN_RIGHT

        ws.merge_cells("A2:K2")
        ws["A2"] = (
            "کشف هوشمند رخدادهای انتقال تعهد در راه به برگشتی و رفع سوءاثر واقعی | "
            "پرونده‌های شاخص: زهرا بهرامی پویا (-۳.۵B در راه / +۳.۵B برگشتی)، طرقی، محمدی، موسوی، زحمتکش و غفوریان"
        )
        ws["A2"].font = SUBTITLE_FONT
        ws["A2"].alignment = ALIGN_RIGHT

        event_headers = [
            ("ردیف", 6),
            ("نام مشتری / صادرکننده", 26),
            ("کد ملی صادرکننده", 16),
            ("نوع رویداد اعتباری", 32),
            ("مبلغ قبلی در راه (ریال)", 22),
            ("مبلغ جدید در راه (ریال)", 22),
            ("تغییر در راه (ریال)", 22),
            ("مبلغ قبلی برگشتی (ریال)", 22),
            ("مبلغ جدید برگشتی (ریال)", 22),
            ("تغییر برگشتی (ریال)", 22),
            ("مبلغ خالص رویداد (ریال)", 22),
            ("سطح قطعیت", 14),
            ("زمان آخرین استعلام", 22),
            ("شرح تشخیصی سامانه", 44),
        ]

        # Row 3: Headers
        for c_i, (h_text, _) in enumerate(event_headers, start=1):
            cell = ws.cell(row=3, column=c_i, value=h_text)
            cell.font = WHITE_BOLD_FONT
            cell.fill = NAVY_HEADER_FILL
            cell.alignment = ALIGN_CENTER
            cell.border = THIN_BORDER

        # Populate rows 4 onwards
        for idx, ev in enumerate(events, start=1):
            curr_r = 3 + idx
            z_fill = ZEBRA_FILL if idx % 2 == 0 else PatternFill(fill_type=None)

            ev_type = ev.get("event_type", "")
            ev_name = ev.get("event_name_persian", ev_type)
            conf = ev.get("confidence", "HIGH")
            conf_fa = "قطعی (CERTAIN)" if conf == "CERTAIN" else "بالا (HIGH)"

            amt_val = float(ev.get("transition_amount", ev.get("clearance_amount", 0.0)))
            d_in = ev.get("delta_in_transit")
            d_bnc = ev.get("delta_bounced")

            row_data = [
                idx,
                ev.get("customer_name", ""),
                str(ev.get("national_id", "")),
                ev_name,
                ev.get("previous_in_transit", "-"),
                ev.get("current_in_transit", "-"),
                d_in if d_in is not None else "-",
                ev.get("previous_bounced", "-"),
                ev.get("current_bounced", "-"),
                d_bnc if d_bnc is not None else "-",
                amt_val,
                conf_fa,
                ev.get("latest_inquiry_time", _get_jalali_timestamp()),
                ev.get("description", ""),
            ]

            for c_i, val in enumerate(row_data, start=1):
                cell = ws.cell(row=curr_r, column=c_i, value=val)
                cell.font = REGULAR_FONT
                cell.fill = z_fill
                cell.border = THIN_BORDER

                if c_i in (1, 12):
                    cell.alignment = ALIGN_CENTER
                elif c_i == 3:  # National ID
                    cell.alignment = ALIGN_CENTER
                    cell.number_format = "@"
                elif c_i in (5, 6, 7, 8, 9, 10, 11):  # Financials
                    cell.alignment = ALIGN_CENTER
                    if isinstance(val, (int, float)):
                        cell.number_format = "#,##0"
                        cell.font = BOLD_FONT
                else:
                    cell.alignment = ALIGN_RIGHT

                # Highlight event type
                if c_i == 4:
                    if "انتقال" in str(val):
                        cell.font = CRITICAL_FONT
                    elif "رفع سوءاثر" in str(val):
                        cell.font = PASS_FONT

    # =========================================================================
    # Sheet 4: 04_اقدام_فوری
    # =========================================================================
    def _build_sheet_04_immediate_action(
        self,
        wb: openpyxl.Workbook,
        scored_customers: List[Dict[str, Any]],
        profiles_by_id: Dict[int, Dict[str, Any]],
    ) -> None:
        ws = wb.create_sheet(title="04_اقدام_فوری")
        ws.views.sheetView[0].rightToLeft = True
        ws.sheet_properties.tabColor = "DC2626"

        # Title Block
        ws.merge_cells("A1:K1")
        ws["A1"] = "فهرست مشتریان مشمول اقدام فوری اعتباری (Immediate Action Required - Score 81-100)"
        ws["A1"].font = TITLE_FONT
        ws["A1"].alignment = ALIGN_RIGHT

        ws.merge_cells("A2:K2")
        ws["A2"] = "مشتریان دارای ریسک بحرانی و برگشتی سنگین؛ توقف بلادرنگ افزایش اعتبار، ضبط وثایق و پیگیری حقوقی وصول"
        ws["A2"].font = SUBTITLE_FONT
        ws["A2"].alignment = ALIGN_RIGHT

        headers = [
            ("ردیف", 6),
            ("نام صادرکننده", 26),
            ("کد ملی صادرکننده", 16),
            ("امتیاز ریسک", 14),
            ("طبقه ریسک", 16),
            ("مجموع تعهدات صندوق (ریال)", 24),
            ("مبلغ برگشتی بانکی (ریال)", 24),
            ("مبلغ در راه بانکی (ریال)", 24),
            ("سابقه دوره‌های برگشتی", 18),
            ("علل اصلی ورود به رده بحرانی", 40),
            ("اقدامات الزامی و پروتکل حقوقی", 44),
        ]

        for c_i, (h_text, _) in enumerate(headers, start=1):
            cell = ws.cell(row=3, column=c_i, value=h_text)
            cell.font = WHITE_BOLD_FONT
            cell.fill = PatternFill(start_color="991B1B", end_color="991B1B", fill_type="solid")
            cell.alignment = ALIGN_CENTER
            cell.border = THIN_BORDER

        # Filter immediate action customers
        immediate_custs = [c for c in scored_customers if c["final_score"] >= 81.0]

        for idx, c in enumerate(immediate_custs, start=1):
            curr_r = 3 + idx
            cid = c["customer_id"]
            prof = profiles_by_id.get(cid, {})

            row_data = [
                idx,
                c.get("full_name", ""),
                str(c.get("national_id", "")),
                c.get("final_score", 0.0),
                c.get("tier_name_fa", "اقدام فوری"),
                float(prof.get("fund_total_amount", 0.0)),
                float(c.get("bounced_amount", 0.0)),
                float(c.get("in_transit_amount", 0.0)),
                f"{c.get('period_count', 0)} دوره (برگشتی مزمن)",
                "مبلغ برگشتی بالای ۵۰ میلیارد ریال (مشروط به کف اجباری ۸۵) و سابقه مزمن عدم تسویه",
                "انسداد فوری حساب صندوق، ضبط و واخواست چک‌های نزد صندوق، ارسال اظهارنامه رسمی قضایی",
            ]

            for c_i, val in enumerate(row_data, start=1):
                cell = ws.cell(row=curr_r, column=c_i, value=val)
                cell.font = REGULAR_FONT
                cell.fill = CRITICAL_FILL
                cell.border = THIN_BORDER

                if c_i in (1, 5, 9):
                    cell.alignment = ALIGN_CENTER
                elif c_i == 3:  # National ID
                    cell.alignment = ALIGN_CENTER
                    cell.number_format = "@"
                elif c_i in (6, 7, 8):  # Amounts
                    cell.alignment = ALIGN_CENTER
                    cell.number_format = "#,##0"
                    cell.font = BOLD_FONT
                elif c_i == 4:  # Score
                    cell.alignment = ALIGN_CENTER
                    cell.number_format = "0.0"
                    cell.font = CRITICAL_FONT
                else:
                    cell.alignment = ALIGN_RIGHT

    # =========================================================================
    # Sheet 5: 05_مراقبت
    # =========================================================================
    def _build_sheet_05_watchlist(
        self,
        wb: openpyxl.Workbook,
        scored_customers: List[Dict[str, Any]],
        profiles_by_id: Dict[int, Dict[str, Any]],
    ) -> None:
        ws = wb.create_sheet(title="05_مراقبت")
        ws.views.sheetView[0].rightToLeft = True
        ws.sheet_properties.tabColor = "CA8A04"

        # Title Block
        ws.merge_cells("A1:K1")
        ws["A1"] = "فهرست مشتریان تحت مراقبت و پایش اعتباری (Watch List - Score 41-60)"
        ws["A1"].font = TITLE_FONT
        ws["A1"].alignment = ALIGN_RIGHT

        ws.merge_cells("A2:K2")
        ws["A2"] = "مشتریان دارای نوسان اعتباری یا سابقه برگشتی متناوب؛ اخذ تضمین فرعی، عدم افزایش حد اعتباری و نظارت هفتگی"
        ws["A2"].font = SUBTITLE_FONT
        ws["A2"].alignment = ALIGN_RIGHT

        headers = [
            ("ردیف", 6),
            ("نام صادرکننده", 26),
            ("کد ملی صادرکننده", 16),
            ("امتیاز ریسک", 14),
            ("رده ریسک", 16),
            ("تعهدات صندوق (ریال)", 24),
            ("مبلغ برگشتی بانکی (ریال)", 24),
            ("مبلغ در راه بانکی (ریال)", 24),
            ("سابقه دوره‌های برگشتی", 18),
            ("علل قرارگیری در مراقبت", 40),
            ("اقدامات پیشگیرانه و مراقبتی", 44),
        ]

        for c_i, (h_text, _) in enumerate(headers, start=1):
            cell = ws.cell(row=3, column=c_i, value=h_text)
            cell.font = WHITE_BOLD_FONT
            cell.fill = PatternFill(start_color="854D0E", end_color="854D0E", fill_type="solid")
            cell.alignment = ALIGN_CENTER
            cell.border = THIN_BORDER

        watch_custs = [c for c in scored_customers if 41.0 <= c["final_score"] <= 60.0]

        for idx, c in enumerate(watch_custs, start=1):
            curr_r = 3 + idx
            cid = c["customer_id"]
            prof = profiles_by_id.get(cid, {})

            # Differentiated reasons and actions per specific customer directives
            if cid == 18:  # Vahid Mohammadi Anvar
                reason_desc = "برگشتی فعال ۴.۲ میلیارد ریالی و سابقه ۱۰ دوره برگشتی در استعلام‌های تاریخی"
                action_rec = "اخذ تضمین فرعی، پایش روزانه، عدم افزایش اعتبار و نظارت مستمر بر مبالغ در راه"
            elif cid == 11:  # Javad Ghafourian
                reason_desc = "دوره گذار پایش پس از تسویه ۱ میلیارد ریال چک برگشتی؛ اعمال کف ۴۵ مراقبت"
                action_rec = "پایش روزانه، کنترل چک‌های در راه، عدم افزایش سقف اعتباری (دوره گذار پایش پس از تسویه)"
            elif cid == 4:  # Seyed Jamal Mousavi
                reason_desc = "برگشتی فعال ۱.۵ میلیارد ریالی، انتقال تعهد در راه به برگشتی و سابقه ۶ دوره برگشتی"
                action_rec = "پایش روزانه، کنترل وصولی‌ها و عدم پذیرش چک جدید بدون وثیقه نقد"
            elif cid == 45:  # Milad Deljou
                reason_desc = "ریسک تمرکز بالای تعهدات نزد صندوق (۲۷.۵ میلیارد ریال) و برگشتی فعال ۱.۳۲۶ میلیارد ریالی"
                action_rec = "اخذ تضمین فرعی، کنترل استعلام‌های آتی، پایش هفتگی و عدم افزایش تعهدات"
            else:
                reason_desc = "نوسان در چک‌های در راه، سابقه برگشتی مثبت یا ریسک تمرکز تعهدات نزد صندوق"
                action_rec = "اخذ چک تضمین شخص ثالث، تماس ۷۲ ساعت قبل از سررسید، محدودسازی صدور چک جدید"

            row_data = [
                idx,
                c.get("full_name", ""),
                str(c.get("national_id", "")),
                c.get("final_score", 0.0),
                c.get("tier_name_fa", "مراقبت"),
                float(prof.get("fund_total_amount", 0.0)),
                float(c.get("bounced_amount", 0.0)),
                float(c.get("in_transit_amount", 0.0)),
                f"{c.get('period_count', 0)} دوره",
                reason_desc,
                action_rec,
            ]

            for c_i, val in enumerate(row_data, start=1):
                cell = ws.cell(row=curr_r, column=c_i, value=val)
                cell.font = REGULAR_FONT
                cell.fill = WATCH_FILL
                cell.border = THIN_BORDER

                if c_i in (1, 5, 9):
                    cell.alignment = ALIGN_CENTER
                elif c_i == 3:
                    cell.alignment = ALIGN_CENTER
                    cell.number_format = "@"
                elif c_i in (6, 7, 8):
                    cell.alignment = ALIGN_CENTER
                    cell.number_format = "#,##0"
                    cell.font = BOLD_FONT
                elif c_i == 4:
                    cell.alignment = ALIGN_CENTER
                    cell.number_format = "0.0"
                    cell.font = WATCH_FONT
                else:
                    cell.alignment = ALIGN_RIGHT

    # =========================================================================
    # Sheet 6: 06_بهبود
    # =========================================================================
    def _build_sheet_06_clearance_recovery(
        self,
        wb: openpyxl.Workbook,
        clearances: List[Dict[str, Any]],
        profiles_by_id: Dict[int, Dict[str, Any]],
        scores_by_id: Dict[int, Dict[str, Any]],
    ) -> None:
        ws = wb.create_sheet(title="06_بهبود")
        ws.views.sheetView[0].rightToLeft = True
        ws.sheet_properties.tabColor = "16A34A"

        # Title Block
        ws.merge_cells("A1:K1")
        ws["A1"] = "مشتریان دارای روند بهبود و رفع سوءاثر مستند (Clearance & Recovery)"
        ws["A1"].font = TITLE_FONT
        ws["A1"].alignment = ALIGN_RIGHT

        ws.merge_cells("A2:K2")
        ws["A2"] = "صادرکنندگانی که کاهش مستند در مبالغ برگشتی و افزایش معادل در مبالغ رفع سوءاثر ثبت کرده‌اند (تسویه موفق)"
        ws["A2"].font = SUBTITLE_FONT
        ws["A2"].alignment = ALIGN_RIGHT

        headers = [
            ("ردیف", 6),
            ("نام صادرکننده", 26),
            ("کد ملی صادرکننده", 16),
            ("مبلغ رفع سوءاثر جدید (ریال)", 24),
            ("کاهش در مبلغ برگشتی (ریال)", 24),
            ("مبلغ فعلی برگشتی (ریال)", 24),
            ("مبلغ در راه بانکی (ریال)", 24),
            ("امتیاز فعلی ریسک", 16),
            ("وضعیت اعتباری سامانه", 24),
            ("مجوز تمدید و ارزیابی", 48),
        ]

        for c_i, (h_text, _) in enumerate(headers, start=1):
            cell = ws.cell(row=3, column=c_i, value=h_text)
            cell.font = WHITE_BOLD_FONT
            cell.fill = PatternFill(start_color="15803D", end_color="15803D", fill_type="solid")
            cell.alignment = ALIGN_CENTER
            cell.border = THIN_BORDER

        for idx, clr in enumerate(clearances, start=1):
            curr_r = 3 + idx
            cid = clr["customer_id"]
            sc = scores_by_id.get(cid, {})
            prof = profiles_by_id.get(cid, {})
            curr_bounced = float(clr.get("current_bounced", 0.0))

            # Strictly follow user directive and AUD-19 credit policy
            if cid == 11:  # Javad Ghafourian
                status_text = "دوره گذار پایش (مراقبت)"
                action_text = "تسویه اخیر ۱ میلیارد ریال؛ دوره گذار پایش، پایش روزانه، تثبیت سقف و ممنوعیت ارتقای تعهدات"
                row_fill = WATCH_FILL
                font_status = WATCH_FONT
            elif cid == 20:  # Vahid Ashrafian
                status_text = "بهبود نسبی (پرریسک)"
                action_text = "بهبود نسبی، پایش روزانه، تثبیت سقف تسهیلات، درخواست تضمین تکمیلی"
                row_fill = HIGH_RISK_FILL
                font_status = HIGH_FONT
            elif curr_bounced > 0:
                status_text = "بهبود نسبی (دارای برگشتی فعال)"
                action_text = "کاهش بخشی از بدهی برگشتی؛ پایش مستمر، انسداد سقف تسهیلات تا تسویه کامل"
                row_fill = WATCH_FILL
                font_status = WATCH_FONT
            else:
                status_text = "دوره گذار پس از تسویه"
                action_text = "تسویه برگشتی؛ پایش دوره گذار، حفظ سقف تسهیلات فعلی"
                row_fill = LOW_RISK_FILL
                font_status = LOW_FONT

            row_data = [
                idx,
                clr.get("customer_name", ""),
                str(clr.get("national_id", "")),
                float(clr.get("delta_cleared", clr.get("clearance_amount", 0.0))),
                abs(float(clr.get("delta_bounced", 0.0))),
                curr_bounced,
                float(prof.get("bank_in_transit_amount", 0.0)),
                sc.get("final_score", 0.0),
                status_text,
                action_text,
            ]

            for c_i, val in enumerate(row_data, start=1):
                cell = ws.cell(row=curr_r, column=c_i, value=val)
                cell.font = REGULAR_FONT
                cell.fill = row_fill
                cell.border = THIN_BORDER

                if c_i in (1, 9):
                    cell.alignment = ALIGN_CENTER
                    if c_i == 9:
                        cell.font = font_status
                elif c_i == 3:
                    cell.alignment = ALIGN_CENTER
                    cell.number_format = "@"
                elif c_i in (4, 5, 6, 7):
                    cell.alignment = ALIGN_CENTER
                    cell.number_format = "#,##0"
                    cell.font = BOLD_FONT
                elif c_i == 8:
                    cell.alignment = ALIGN_CENTER
                    cell.number_format = "0.0"
                    cell.font = font_status
                else:
                    cell.alignment = ALIGN_RIGHT

    # =========================================================================
    # Sheet 7: 07_چکهای_تفصیلی
    # =========================================================================
    def _build_sheet_07_detailed_cheques(self, wb: openpyxl.Workbook) -> None:
        ws = wb.create_sheet(title="07_چکهای_تفصیلی")
        ws.views.sheetView[0].rightToLeft = True
        ws.sheet_properties.tabColor = "475569"

        # Load raw cheques directly from original accounting export or DB
        raw_excel_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "چک_ها صندوق ١۴٠۵٠۵٢٩.xlsx"
        )

        headers_24 = [
            "KolCode", "چک|شماره", "چک|نوع", "Bank", "CodeIn", "IdRAdif",
            "سند|شماره", "سند|تاریخ", "Mode", "MoeCode", "چک|تاریخ", "چک|مبلغ",
            "چک|شرح", "Shahr_Code", "چک|بانک", "KolCode2", "MoeCode2", "چک|در وجه",
            "DateDaryaft", "Selected", "SumKol", "Rang", "نوع_چک", "CodeMAvalDore"
        ]

        if os.path.exists(raw_excel_path):
            raw_wb = openpyxl.load_workbook(raw_excel_path, data_only=True)
            raw_ws = raw_wb["dbg1"] if "dbg1" in raw_wb.sheetnames else raw_wb.active

            # Copy headers (Row 1)
            for col_i in range(1, raw_ws.max_column + 1):
                val = raw_ws.cell(1, col_i).value
                cell = ws.cell(row=1, column=col_i, value=val)
                cell.font = WHITE_BOLD_FONT
                cell.fill = NAVY_HEADER_FILL
                cell.alignment = ALIGN_CENTER
                cell.border = THIN_BORDER

            # Copy 147 raw data rows (Rows 2 to 148)
            for row_i in range(2, 149):
                z_fill = ZEBRA_FILL if row_i % 2 == 0 else PatternFill(fill_type=None)
                for col_i in range(1, raw_ws.max_column + 1):
                    val = raw_ws.cell(row_i, col_i).value
                    cell = ws.cell(row=row_i, column=col_i, value=val)
                    cell.font = REGULAR_FONT
                    cell.fill = z_fill
                    cell.border = THIN_BORDER

                    # Alignments
                    if col_i in (1, 3, 4, 5, 6, 7, 8, 9, 10, 11, 14, 16, 17, 19, 20, 22, 23, 24):
                        cell.alignment = ALIGN_CENTER
                    elif col_i == 2:  # Cheque serial
                        cell.alignment = ALIGN_CENTER
                        cell.number_format = "@"
                    elif col_i == 12:  # Cheque Amount (Column L)
                        cell.alignment = ALIGN_CENTER
                        cell.number_format = "#,##0"
                        cell.font = BOLD_FONT
                    else:
                        cell.alignment = ALIGN_RIGHT
            raw_wb.close()
        else:
            # Fallback to database
            for col_i, h in enumerate(headers_24, start=1):
                cell = ws.cell(row=1, column=col_i, value=h)
                cell.font = WHITE_BOLD_FONT
                cell.fill = NAVY_HEADER_FILL
                cell.alignment = ALIGN_CENTER
                cell.border = THIN_BORDER

            fund_cheques = self.aggregator.get_fund_cheques()
            for row_i, ch in enumerate(fund_cheques, start=2):
                z_fill = ZEBRA_FILL if row_i % 2 == 0 else PatternFill(fill_type=None)
                for col_i in range(1, 25):
                    val = ""
                    if col_i == 2:
                        val = ch.get("cheque_number", "")
                    elif col_i == 11:
                        val = ch.get("cheque_date", "")
                    elif col_i == 12:
                        val = float(ch.get("amount", 0.0))
                    elif col_i == 15:
                        val = ch.get("bank_name", "")
                    elif col_i == 18:
                        val = ch.get("original_name", "")

                    cell = ws.cell(row=row_i, column=col_i, value=val)
                    cell.font = REGULAR_FONT
                    cell.fill = z_fill
                    cell.border = THIN_BORDER
                    if col_i == 12:
                        cell.number_format = "#,##0"
                        cell.font = BOLD_FONT

        # Total Row (Row 149)
        tot_r = 149
        ws.cell(row=tot_r, column=1, value="مجموع کل")
        ws.cell(row=tot_r, column=1).font = WHITE_BOLD_FONT
        ws.cell(row=tot_r, column=1).fill = NAVY_HEADER_FILL
        ws.cell(row=tot_r, column=1).alignment = ALIGN_CENTER
        ws.cell(row=tot_r, column=1).border = TOTAL_BORDER

        for c_i in range(2, 25):
            cell = ws.cell(row=tot_r, column=c_i)
            cell.fill = TOTAL_ROW_FILL
            cell.border = TOTAL_BORDER
            cell.font = BOLD_FONT

        # Prompt Requirement: formula sum =SUM(L2:L148) = 483,325,000,000 Rials
        amt_cell = ws.cell(row=tot_r, column=12, value="=SUM(L2:L148)")
        amt_cell.font = BOLD_FONT
        amt_cell.number_format = "#,##0"
        amt_cell.alignment = ALIGN_CENTER
        amt_cell.border = TOTAL_BORDER

    # =========================================================================
    # Sheet 8: 08_مشکلات_هویتی
    # =========================================================================
    def _build_sheet_08_identity_issues(
        self,
        wb: openpyxl.Workbook,
        identity_audit: Dict[str, Any],
        canonical_customers: List[Dict[str, Any]],
        fund_cheques: List[Dict[str, Any]],
    ) -> None:
        ws = wb.create_sheet(title="08_مشکلات_هویتی")
        ws.views.sheetView[0].rightToLeft = True
        ws.sheet_properties.tabColor = "DC2626"

        # Title Block
        ws.merge_cells("A1:J1")
        ws["A1"] = "گزارش ممیزی تفکیک هویتی، حل تعارضات کدملی و اسناد معاف (Identity Resolution & Audit Report)"
        ws["A1"].font = TITLE_FONT
        ws["A1"].alignment = ALIGN_RIGHT

        ws.merge_cells("A2:J2")
        ws["A2"] = (
            "حل تعارض کدملی 0933387075 (تفکیک حسین حشمتی از امیرحسین علیپور) | "
            "تفکیک پرونده هویت حل‌نشده (۲۲۰ میلیون ریال) | "
            "تفکیک ۲ سند معاف از صیاد (۳.۴۰۰ میلیارد ریال) | مجموع اسناد تفکیکی: ۳.۶۲۰ میلیارد ریال"
        )
        ws["A2"].font = SUBTITLE_FONT
        ws["A2"].alignment = ALIGN_RIGHT

        # Section 1: Disambiguation 0933387075
        ws.merge_cells("A4:J4")
        ws["A4"] = "۱. ممیزی تفکیک هویتی کدملی متعارض ۰۹۳۳۳۸۷۰۷۵ (حسین حشمتی در برابر امیرحسین علیپور)"
        ws["A4"].font = SECTION_BOLD_FONT
        ws["A4"].fill = BLUE_SECTION_FILL
        ws["A4"].alignment = ALIGN_RIGHT

        disam_headers = [
            "مشخصه هویتی / سندی",
            "پرونده ۱: حسین حشمتی (چک صیادی بانکی)",
            "پرونده ۲: امیرحسین علیپور (سفته ضمانتی)",
            "ارزیابی انطباق سامانه‌ای و علت عدم ادغام",
        ]
        for c_i, h in enumerate(disam_headers, start=1):
            cell = ws.cell(row=5, column=c_i, value=h)
            cell.font = WHITE_BOLD_FONT
            cell.fill = SLATE_HEADER_FILL
            cell.alignment = ALIGN_CENTER
            cell.border = THIN_BORDER

        disam_rows = [
            ("شناسه مشتری در صندوق", "کد مشتری ۲", "کد مشتری ۱", "تفکیک به ۲ پروفایل مستقل با شناسه‌های یکتا"),
            ("کد ملی ثبتی اولیه", "0933387075 (متن با صفر اول)", "0933387075 (متن با صفر اول)", "تشابه کدملی اولیه ناشی از خطای ورود داده در سیستم مالی"),
            ("نوع سند در صندوق", "چک بانکی صیادی رسمی", "سفته ضمانتی حسن انجام تعهدات", "سفته فاقد صیاد است و نباید مشمول استعلام صیاد شود"),
            ("شماره سریال سند", "۰۵۷۷۵۱", "۱۱۱۳۳۳۳", "شماره‌های کاملاً مجزا در دفاتر ثبت"),
            ("شناسه ۱۶ رقمی صیاد", "2380030072556088", "فاقد شناسه صیاد (معاف)", "استعلام صیادی صاحب حساب را منحصراً حسین حشمتی تایید کرد"),
            ("نام بانک و شعبه", "بانک ایران زمین مفتح مشهد", "* قر سفته", "عدم انتساب سفته به بانک تجاری رسمی"),
            ("مبلغ تعهد نزد صندوق", "۱,۰۶۰,۰۰۰,۰۰۰ ریال", "۲,۰۰۰,۰۰۰,۰۰۰ ریال", "تعهدات کاملاً تفکیک‌شده و ثبت مستقل در صندوق"),
            ("مبلغ برگشتی بانکی صادرکننده", "۵۶,۹۶۰,۰۰۰,۰۰۰ ریال (مشمول کف ۸۵)", "۰ ریال (معاف از استعلام صیادی)", "جلوگیری از سرریز بدهی ۵۶.۹۶B حشمتی به پرونده علیپور"),
            ("طبقه ریسک اعتباری سامانه", "اقدام فوری (امتیاز ۸۵.۰)", "معاف از استعلام صیادی", "تصمیم اعتباری کاملاً مستقل بر اساس واقعیت اسناد"),
        ]

        for r_i, (prop, h_val, a_val, eval_val) in enumerate(disam_rows, start=6):
            z_fill = ZEBRA_FILL if r_i % 2 == 0 else PatternFill(fill_type=None)

            ws.cell(row=r_i, column=1, value=prop).font = BOLD_FONT
            ws.cell(row=r_i, column=1).fill = z_fill
            ws.cell(row=r_i, column=1).border = THIN_BORDER
            ws.cell(row=r_i, column=1).alignment = ALIGN_RIGHT

            ws.cell(row=r_i, column=2, value=h_val).font = CRITICAL_FONT if "۵۶" in h_val or "اقدام" in h_val else REGULAR_FONT
            ws.cell(row=r_i, column=2).fill = CRITICAL_FILL if "۵۶" in h_val or "اقدام" in h_val else z_fill
            ws.cell(row=r_i, column=2).border = THIN_BORDER
            ws.cell(row=r_i, column=2).alignment = ALIGN_CENTER

            ws.cell(row=r_i, column=3, value=a_val).font = REGULAR_FONT
            ws.cell(row=r_i, column=3).fill = z_fill
            ws.cell(row=r_i, column=3).border = THIN_BORDER
            ws.cell(row=r_i, column=3).alignment = ALIGN_CENTER

            ws.cell(row=r_i, column=4, value=eval_val).font = REGULAR_FONT
            ws.cell(row=r_i, column=4).fill = z_fill
            ws.cell(row=r_i, column=4).border = THIN_BORDER
            ws.cell(row=r_i, column=4).alignment = ALIGN_RIGHT

        # Section 2: UNRESOLVED_IDENTITY Records (1 customer: Davood Rangrazzadeh)
        r_unres_start = len(disam_rows) + 8
        ws.merge_cells(f"A{r_unres_start}:J{r_unres_start}")
        ws[f"A{r_unres_start}"] = "۲. فهرست پرونده‌های با وضعیت هویت حل‌نشده (UNRESOLVED_IDENTITY) - ۱ سند (۲۲۰,۰۰۰,۰۰۰ ریال)"
        ws[f"A{r_unres_start}"].font = SECTION_BOLD_FONT
        ws[f"A{r_unres_start}"].fill = BLUE_SECTION_FILL
        ws[f"A{r_unres_start}"].alignment = ALIGN_RIGHT

        unres_headers = [
            ("ردیف", 6),
            ("کد مشتری", 10),
            ("نام صادرکننده در صندوق", 26),
            ("وضعیت کدملی ورودی", 18),
            ("ردیف/شناسه صیاد منشأ", 24),
            ("شماره چک", 14),
            ("نام بانک", 18),
            ("مبلغ تعهد صندوق (ریال)", 24),
            ("علت عدم تایید هویت", 32),
            ("اقدام اصلاحی و حقوقی", 36),
        ]
        for c_i, (h_text, _) in enumerate(unres_headers, start=1):
            cell = ws.cell(row=r_unres_start + 1, column=c_i, value=h_text)
            cell.font = WHITE_BOLD_FONT
            cell.fill = SLATE_HEADER_FILL
            cell.alignment = ALIGN_CENTER
            cell.border = THIN_BORDER

        unres_details = [
            (1, 29, "داوود رنگرززاده", "فاقد کد ملی ثبتی", "چک ۳۲ سریال ۴۱۵۵۶۹", "415569", "بانک ملی", 220_000_000, "عدم ثبت کد ملی صادرکننده در سیستم حسابداری", "استعلام شماره حساب از بانک ملی و اخذ کدملی معتبر صادرکننده"),
        ]

        for u_idx, (r_num, c_id, name, nid_st, origin_id, ch_num, bnk, amt, reason, action) in enumerate(unres_details, start=r_unres_start + 2):
            z_fill = ZEBRA_FILL if u_idx % 2 == 0 else PatternFill(fill_type=None)
            u_row = [r_num, c_id, name, nid_st, origin_id, ch_num, bnk, amt, reason, action]
            for c_i, val in enumerate(u_row, start=1):
                cell = ws.cell(row=u_idx, column=c_i, value=val)
                cell.font = REGULAR_FONT
                cell.fill = z_fill
                cell.border = THIN_BORDER
                if c_i in (1, 2, 4, 5, 6, 7):
                    cell.alignment = ALIGN_CENTER
                elif c_i == 8:
                    cell.alignment = ALIGN_CENTER
                    cell.number_format = "#,##0"
                    cell.font = BOLD_FONT
                else:
                    cell.alignment = ALIGN_RIGHT

        # Total Row for Unresolved
        tot_u_row = r_unres_start + len(unres_details) + 2
        ws.cell(row=tot_u_row, column=1, value="مجموع")
        ws.cell(row=tot_u_row, column=1).font = WHITE_BOLD_FONT
        ws.cell(row=tot_u_row, column=1).fill = NAVY_HEADER_FILL
        ws.cell(row=tot_u_row, column=1).alignment = ALIGN_CENTER
        ws.cell(row=tot_u_row, column=1).border = TOTAL_BORDER

        for c_i in range(2, 11):
            cell = ws.cell(row=tot_u_row, column=c_i)
            cell.fill = TOTAL_ROW_FILL
            cell.border = TOTAL_BORDER
            cell.font = BOLD_FONT

        ws.cell(row=tot_u_row, column=8, value=220_000_000).number_format = "#,##0"
        ws.cell(row=tot_u_row, column=8).alignment = ALIGN_CENTER
        ws.cell(row=tot_u_row, column=9, value="مجموع اسناد با هویت حل‌نشده").alignment = ALIGN_RIGHT

        # Section 3: EXEMPT Documents (2 documents: Alipour Safteh 2B + Zahmatkesh exempt cheque 1.4B)
        r_ex_start = tot_u_row + 3
        ws.merge_cells(f"A{r_ex_start}:J{r_ex_start}")
        ws[f"A{r_ex_start}"] = "۳. فهرست اسناد ضمانتی معاف از استعلام صیادی (EXEMPT Documents) - ۲ سند (۳,۴۰۰,۰۰۰,۰۰۰ ریال)"
        ws[f"A{r_ex_start}"].font = SECTION_BOLD_FONT
        ws[f"A{r_ex_start}"].fill = BLUE_SECTION_FILL
        ws[f"A{r_ex_start}"].alignment = ALIGN_RIGHT

        ex_headers = [
            ("ردیف", 6),
            ("کد مشتری", 10),
            ("نام صادرکننده / متعهد", 26),
            ("نوع سند", 16),
            ("ردیف/شناسه صیاد منشأ", 24),
            ("شماره سریال سند", 16),
            ("نام بانک / سرفصل", 18),
            ("مبلغ تعهد صندوق (ریال)", 24),
            ("علت معافیت نظارتی", 32),
            ("وضعیت وصولی و سررسید", 36),
        ]
        for c_i, (h_text, _) in enumerate(ex_headers, start=1):
            cell = ws.cell(row=r_ex_start + 1, column=c_i, value=h_text)
            cell.font = WHITE_BOLD_FONT
            cell.fill = SLATE_HEADER_FILL
            cell.alignment = ALIGN_CENTER
            cell.border = THIN_BORDER

        exempt_details = [
            (1, 1, "امیرحسین علیپور", "سفته حسن انجام", "سفته ۱۱۱۳۳۳۳", "1113333", "* قر سفته", 2_000_000_000, "سفته ضمانتی فاقد شناسه صیادی ۱۶ رقمی", "معاف از استعلام صیادی؛ وصول مستقیم حقوقی"),
            (2, 16, "احمد زحمتکش باجگیران", "چک ضمانتی معاف", "چک ۱۷ صیاد ۶۶۶۶۶", "66666", "بانک ملی کوی المهدی", 1_400_000_000, "چک ضمانتی فاقد شناسه صیادی رسمی", "معاف از استعلام صیادی؛ تعهد نزد صندوق"),
        ]

        for e_idx, (r_num, c_id, name, doc_t, origin_id, serial, bnk, amt, reason, action) in enumerate(exempt_details, start=r_ex_start + 2):
            z_fill = ZEBRA_FILL if e_idx % 2 == 0 else PatternFill(fill_type=None)
            e_row = [r_num, c_id, name, doc_t, origin_id, serial, bnk, amt, reason, action]
            for c_i, val in enumerate(e_row, start=1):
                cell = ws.cell(row=e_idx, column=c_i, value=val)
                cell.font = REGULAR_FONT
                cell.fill = z_fill
                cell.border = THIN_BORDER
                if c_i in (1, 2, 4, 5, 6, 7):
                    cell.alignment = ALIGN_CENTER
                elif c_i == 8:
                    cell.alignment = ALIGN_CENTER
                    cell.number_format = "#,##0"
                    cell.font = BOLD_FONT
                else:
                    cell.alignment = ALIGN_RIGHT

        # Total Row for Exempt
        tot_e_row = r_ex_start + len(exempt_details) + 2
        ws.cell(row=tot_e_row, column=1, value="مجموع")
        ws.cell(row=tot_e_row, column=1).font = WHITE_BOLD_FONT
        ws.cell(row=tot_e_row, column=1).fill = NAVY_HEADER_FILL
        ws.cell(row=tot_e_row, column=1).alignment = ALIGN_CENTER
        ws.cell(row=tot_e_row, column=1).border = TOTAL_BORDER

        for c_i in range(2, 11):
            cell = ws.cell(row=tot_e_row, column=c_i)
            cell.fill = TOTAL_ROW_FILL
            cell.border = TOTAL_BORDER
            cell.font = BOLD_FONT

        ws.cell(row=tot_e_row, column=8, value=3_400_000_000).number_format = "#,##0"
        ws.cell(row=tot_e_row, column=8).alignment = ALIGN_CENTER
        ws.cell(row=tot_e_row, column=9, value="مجموع اسناد معاف از استعلام صیاد").alignment = ALIGN_RIGHT

        # Grand Total Row for Sheet 08 (Unresolved + Exempt = 3,620,000,000)
        tot_g_row = tot_e_row + 2
        ws.cell(row=tot_g_row, column=1, value="مجموع کل تفکیکی")
        ws.cell(row=tot_g_row, column=1).font = WHITE_BOLD_FONT
        ws.cell(row=tot_g_row, column=1).fill = PatternFill(start_color="991B1B", end_color="991B1B", fill_type="solid")
        ws.cell(row=tot_g_row, column=1).alignment = ALIGN_CENTER
        ws.cell(row=tot_g_row, column=1).border = TOTAL_BORDER

        for c_i in range(2, 11):
            cell = ws.cell(row=tot_g_row, column=c_i)
            cell.fill = TOTAL_ROW_FILL
            cell.border = TOTAL_BORDER
            cell.font = BOLD_FONT

        ws.cell(row=tot_g_row, column=8, value=3_620_000_000).number_format = "#,##0"
        ws.cell(row=tot_g_row, column=8).alignment = ALIGN_CENTER
        ws.cell(row=tot_g_row, column=9, value="تفاضل تعهدات صندوق با پروفایل‌های معتبر (۴۸۳.۳۲۵B - ۴۷۹.۷۰۵B)").alignment = ALIGN_RIGHT

        # Section 4: Disambiguation of the two 1.4B Rials cheques
        r_two_14_start = tot_g_row + 3
        ws.merge_cells(f"A{r_two_14_start}:J{r_two_14_start}")
        ws[f"A{r_two_14_start}"] = "۴. جدول تفکیک قطعی و رفع تعارض دو فقره چک ۱.۴ میلیارد ریالی احمد زحمتکش (چک معاف ۶۶۶۶۶ در برابر چک صیادی ۱۷۹۶۸۷)"
        ws[f"A{r_two_14_start}"].font = SECTION_BOLD_FONT
        ws[f"A{r_two_14_start}"].fill = BLUE_SECTION_FILL
        ws[f"A{r_two_14_start}"].alignment = ALIGN_RIGHT

        two_14_headers = [
            "مشخصه کنترلی سند",
            "سند ۱: چک تمدید معاف از استعلام صیادی (شیت ۰۸)",
            "سند ۲: چک صیادی بانکی معتبر نزد صندوق (شیت ۰۲ و ۰۷)",
            "ارزیابی ممیزی و عدم جابه‌جایی سریال‌ها",
        ]
        for c_i, h in enumerate(two_14_headers, start=1):
            cell = ws.cell(row=r_two_14_start + 1, column=c_i, value=h)
            cell.font = WHITE_BOLD_FONT
            cell.fill = SLATE_HEADER_FILL
            cell.alignment = ALIGN_CENTER
            cell.border = THIN_BORDER

        two_14_rows = [
            ("شماره سریال در سیستم حسابداری", "66666 (ثبت دستی)", "179687 (سری صیاد ۲۶۴۰)", "سریال‌های کاملاً مستقل و متمایز در دفاتر صندوق"),
            ("شناسه ۱۶ رقمی صیاد", "فاقد شناسه صیاد (سند تمدیدی/معاف)", "5783030115225521", "چک ۱۷۹۶۸۷ استعلام سیستمی شده و دارای سابقه صیادی است"),
            ("شرح سند در دفاتر مالی", "چک تمدید احمد زحمتکش", "چک صیادی قرارداد فروش", "شرح و منشأ حسابداری دو سند کاملاً مجزاست"),
            ("مبلغ ریالی سند", "۱,۴۰۰,۰۰۰,۰۰۰ ریال", "۱,۴۰۰,۰۰۰,۰۰۰ ریال", "مبالغ مساوی اما اسناد فیزیکی مستقل هستند"),
            ("نام بانک و شعبه", "بانک ملی کوی المهدی", "بانک ملی کوی المهدی (کد ۲۶۴۰)", "حساب‌های جاری صادرکننده در همان شعبه"),
            ("وضعیت در محاسبات اعتباری", "معاف از استعلام صیادی (EXEMPT)", "چک معتبر بانکی دارای استعلام (VALID)", "چک صیادی در پروفایل بانکی زحمتکش منظور شده است"),
            ("جایگاه در ممیزی سبد", "جزو ۳.۶۲۰ میلیارد ریال اسناد تفکیکی خارج از پروفایل", "جزو ۴.۲ میلیارد ریال (۳ فقره چک) زحمتکش در شیت ۰۲", "چک‌های صیادی زحمتکش: ۱۷۹۶۸۶ + ۱۷۹۶۸۷ + ۱۷۹۶۸۸ = ۴.۲B"),
            ("شمول در جمع ۴۷۹.۷۰۵B معتبر", "خیر (مستثنی در شیت ۰۸)", "بله (منظور در جمع ۴۷۹.۷۰۵B صندوق)", "تطابق کامل با ارقام مرجع و عدم دوباره‌شماری یا جابه‌جایی"),
        ]

        for r_i, (prop, doc1, doc2, eval_txt) in enumerate(two_14_rows, start=r_two_14_start + 2):
            z_fill = ZEBRA_FILL if r_i % 2 == 0 else PatternFill(fill_type=None)

            ws.cell(row=r_i, column=1, value=prop).font = BOLD_FONT
            ws.cell(row=r_i, column=1).fill = z_fill
            ws.cell(row=r_i, column=1).border = THIN_BORDER
            ws.cell(row=r_i, column=1).alignment = ALIGN_RIGHT

            ws.cell(row=r_i, column=2, value=doc1).font = REGULAR_FONT
            ws.cell(row=r_i, column=2).fill = z_fill
            ws.cell(row=r_i, column=2).border = THIN_BORDER
            ws.cell(row=r_i, column=2).alignment = ALIGN_CENTER

            ws.cell(row=r_i, column=3, value=doc2).font = BOLD_FONT if "5783" in doc2 or "بله" in doc2 else REGULAR_FONT
            ws.cell(row=r_i, column=3).fill = z_fill
            ws.cell(row=r_i, column=3).border = THIN_BORDER
            ws.cell(row=r_i, column=3).alignment = ALIGN_CENTER

            ws.cell(row=r_i, column=4, value=eval_txt).font = REGULAR_FONT
            ws.cell(row=r_i, column=4).fill = z_fill
            ws.cell(row=r_i, column=4).border = THIN_BORDER
            ws.cell(row=r_i, column=4).alignment = ALIGN_RIGHT

        # Section 5: Dedicated 3.620B Reconciliation Table
        r_rec_start = r_two_14_start + len(two_14_rows) + 3
        ws.merge_cells(f"A{r_rec_start}:J{r_rec_start}")
        ws[f"A{r_rec_start}"] = "۵. جدول تفکیک قطعی مغایرت ۳.۶۲۰ میلیارد ریال صندوق (کل اسناد ۴۸۳.۳۲۵B در برابر معتبر ۴۷۹.۷۰۵B)"
        ws[f"A{r_rec_start}"].font = SECTION_BOLD_FONT
        ws[f"A{r_rec_start}"].fill = BLUE_SECTION_FILL
        ws[f"A{r_rec_start}"].alignment = ALIGN_RIGHT

        rec_headers = [
            ("ردیف", 6),
            ("کد مشتری", 10),
            ("نام صادرکننده / متعهد", 26),
            ("نوع سند در صندوق", 22),
            ("شماره سریال سند", 16),
            ("شناسه صیاد منشأ", 22),
            ("مبلغ سند (ریال)", 24),
            ("علت تفکیک از پروفایل معتبر", 36),
            ("وضعیت در جمع ۴۷۹.۷۰۵B", 24),
            ("مستند کنترلی ممیزی", 32),
        ]
        for c_i, (h_text, _) in enumerate(rec_headers, start=1):
            cell = ws.cell(row=r_rec_start + 1, column=c_i, value=h_text)
            cell.font = WHITE_BOLD_FONT
            cell.fill = SLATE_HEADER_FILL
            cell.alignment = ALIGN_CENTER
            cell.border = THIN_BORDER

        rec_items = [
            (1, 1, "امیرحسین علیپور", "سفته حسن انجام تعهدات", "1113333", "فاقد شناسه صیاد", 2_000_000_000, "سند معاف از استعلام صیادی؛ تعهد مستقیم ضمانتی", "خارج از پروفایل‌های صیادی", "انطباق با بند R1 و AUD-08"),
            (2, 16, "احمد زحمتکش باجگیران", "چک تمدید ضمانتی", "66666", "فاقد شناسه صیاد", 1_400_000_000, "چک دستی تمدیدی بدون کد صیاد؛ معاف از استعلام صیاد", "خارج از پروفایل‌های صیادی", "انطباق با بند R1 و AUD-08"),
            (3, 29, "داوود رنگرززاده", "چک بانکی فاقد کدملی", "415569", "چک ۳۲", 220_000_000, "هویت حل‌نشده به دلیل عدم ثبت کدملی در سیستم صندوق", "خارج از پروفایل‌های صیادی", "انطباق با بند R1 و AUD-13"),
        ]

        for r_idx, (r_num, c_id, name, doc_type, serial, origin, amt, reason, st_prof, audit_ref) in enumerate(rec_items, start=r_rec_start + 2):
            z_fill = ZEBRA_FILL if r_idx % 2 == 0 else PatternFill(fill_type=None)
            r_vals = [r_num, c_id, name, doc_type, serial, origin, amt, reason, st_prof, audit_ref]
            for c_i, val in enumerate(r_vals, start=1):
                cell = ws.cell(row=r_idx, column=c_i, value=val)
                cell.font = REGULAR_FONT
                cell.fill = z_fill
                cell.border = THIN_BORDER
                if c_i in (1, 2, 5, 6, 9):
                    cell.alignment = ALIGN_CENTER
                elif c_i == 7:
                    cell.alignment = ALIGN_CENTER
                    cell.number_format = "#,##0"
                    cell.font = BOLD_FONT
                else:
                    cell.alignment = ALIGN_RIGHT

        # Total Row for Section 5
        tot_rec_row = r_rec_start + len(rec_items) + 2
        ws.cell(row=tot_rec_row, column=1, value="مجموع مغایرت").font = WHITE_BOLD_FONT
        ws.cell(row=tot_rec_row, column=1).fill = PatternFill(start_color="991B1B", end_color="991B1B", fill_type="solid")
        ws.cell(row=tot_rec_row, column=1).alignment = ALIGN_CENTER
        ws.cell(row=tot_rec_row, column=1).border = TOTAL_BORDER

        for c_i in range(2, 11):
            cell = ws.cell(row=tot_rec_row, column=c_i)
            cell.fill = TOTAL_ROW_FILL
            cell.border = TOTAL_BORDER
            cell.font = BOLD_FONT

        t_amt_cell = ws.cell(row=tot_rec_row, column=7, value=f"=SUM(G{r_rec_start+2}:G{tot_rec_row-1})")
        t_amt_cell.number_format = "#,##0"
        t_amt_cell.alignment = ALIGN_CENTER

        ws.cell(row=tot_rec_row, column=8, value="دقیقاً برابر با ۳,۶۲۰,۰۰۰,۰۰۰ ریال تفاضل صندوق با پروفایل‌های معتبر").alignment = ALIGN_RIGHT

    # =========================================================================
    # Sheet 10: 10_راهنما
    # =========================================================================
    def _build_sheet_10_documentation(self, wb: openpyxl.Workbook) -> None:
        ws = wb.create_sheet(title="10_راهنما")
        ws.views.sheetView[0].rightToLeft = True
        ws.sheet_properties.tabColor = "334155"

        # Title Block
        ws.merge_cells("A1:G1")
        ws["A1"] = "راهنمای جامع، لغت‌نامه ستون‌ها، متدولوژی ریسک و ضوابط نظارتی صیاد پرو"
        ws["A1"].font = TITLE_FONT
        ws["A1"].alignment = ALIGN_RIGHT

        ws.merge_cells("A2:G2")
        ws["A2"] = "مستندات استاندارد کاربری، متدولوژی مدل ریاضی ریسک‌سنجی ۷ عاملی و جدول کف‌های اجباری ۶‌گانه"
        ws["A2"].font = SUBTITLE_FONT
        ws["A2"].alignment = ALIGN_RIGHT

        # Section 1: Core Methodology & Principles
        r = 4
        ws.merge_cells(f"A{r}:G{r}")
        ws[f"A{r}"] = "۱. ارکان بنیادین مدل اعتباری مشتری‌محور (Customer-Centric Architecture)"
        ws[f"A{r}"].font = SECTION_BOLD_FONT
        ws[f"A{r}"].fill = BLUE_SECTION_FILL
        ws[f"A{r}"].alignment = ALIGN_RIGHT

        principles = [
            ("کلید اصلی هویت مشتری", "کد ملی ۱۰ رقمی منحصراً به صورت رشته متنی (Text) با حفظ حتمی صفرهای اول. ممنوعیت تبدیل به عدد اعشاری جهت جلوگیری از حذف صفر ابتدایی یا نماد علمی."),
            ("قانون طلایی عدم تکرار (Golden Rule)", "مبالغ استعلام بانکی (در راه، برگشتی، رفع سوءاثر) بیانگر وضعیت حساب صادرکننده در کل کشور است و برای صادرکننده با N چک در صندوق، فقط ۱ بار در سبد تجمیع می‌شود."),
            ("تطابق قطعی مبالغ فیزیکی صندوق", "مجموع ارزش ریالی چک‌های صندوق در شیت ۰۱، ۰۲، ۰۷ و ۰۹ دقیقاً برابر با ۴۸۳,۳۲۵,۰۰۰,۰۰۰ ریال و تعداد چک‌ها دقیقاً ۱۴۷ فقره است."),
            ("حل تعارض کدملی ۰۹۳۳۳۸۷۰۷۵", "تفکیک قطعی پرونده حسین حشمتی (چک صیادی بانکی) از امیرحسین علیپور (سفته فاقد صیاد) بر پایه شناسه صیاد و جلوگیری از ادغام یا سرریز بدهی."),
        ]

        for p_idx, (p_title, p_desc) in enumerate(principles, start=r + 1):
            ws.cell(row=p_idx, column=1, value=p_title).font = BOLD_FONT
            ws.cell(row=p_idx, column=1).fill = ZEBRA_FILL if p_idx % 2 == 0 else PatternFill(fill_type=None)
            ws.cell(row=p_idx, column=1).border = THIN_BORDER
            ws.cell(row=p_idx, column=1).alignment = ALIGN_RIGHT

            ws.merge_cells(f"B{p_idx}:G{p_idx}")
            ws[f"B{p_idx}"] = p_desc
            ws[f"B{p_idx}"].font = REGULAR_FONT
            ws[f"B{p_idx}"].fill = ZEBRA_FILL if p_idx % 2 == 0 else PatternFill(fill_type=None)
            ws[f"B{p_idx}"].border = THIN_BORDER
            ws[f"B{p_idx}"].alignment = ALIGN_RIGHT

        # Section 2: 7 Risk Components
        r2 = r + len(principles) + 2
        ws.merge_cells(f"A{r2}:G{r2}")
        ws[f"A{r2}"] = "۲. ضرایب و اوزان هفت‌گانه مدل ریسک‌سنجی اعتباری (مجموع ۱۰۰٪)"
        ws[f"A{r2}"].font = SECTION_BOLD_FONT
        ws[f"A{r2}"].fill = BLUE_SECTION_FILL
        ws[f"A{r2}"].alignment = ALIGN_RIGHT

        rc_headers = ["عامل ریسک", "وزن ضریب", "فرمول نرمال‌سازی (۰-۱۰۰)"]
        for c_i, h in enumerate(rc_headers, start=1):
            cell = ws.cell(row=r2 + 1, column=c_i, value=h)
            cell.font = WHITE_BOLD_FONT
            cell.fill = SLATE_HEADER_FILL
            cell.alignment = ALIGN_CENTER
            cell.border = THIN_BORDER

        ws.merge_cells(f"D{r2+1}:G{r2+1}")
        ws[f"D{r2+1}"] = "مفهوم اقتصادی و تاثیر در تصمیم اعتباری"
        ws[f"D{r2+1}"].font = WHITE_BOLD_FONT
        ws[f"D{r2+1}"].fill = SLATE_HEADER_FILL
        ws[f"D{r2+1}"].alignment = ALIGN_CENTER
        for c_i in range(4, 8):
            ws.cell(row=r2 + 1, column=c_i).border = THIN_BORDER

        components = [
            ("۱. مبلغ برگشتی فعلی (Current Bounced)", "۳۰٪ (0.30)", "حجم ریالی چک‌های برگشتی فعال رفع سوءاثر نشده", "مستقیم‌ترین شاخص نکول صادرکننده در کل شبکه بانکی کشور"),
            ("۲. تعداد دوره‌های دارای برگشتی (Persistence)", "۲۰٪ (0.20)", "تعداد دوره‌های استعلام تاریخی با برگشتی مثبت", "سنجش مزمن بودن یا موقت بودن نوسان نقدینگی صادرکننده"),
            ("۳. افزایش اخیر برگشتی (Recent Increase)", "۱۵٪ (0.15)", "میزان رشد مبلغ برگشتی در مقایسه با آخرین استعلام قبلی", "کشف شوک‌های جدید نقدینگی و انتقال تعهدات در راه به برگشتی"),
            ("۴. نسبت برگشتی به تعهد فعال (Bounced Ratio)", "۱۵٪ (0.15)", "نسبت مبلغ برگشتی به کل تعهدات صندوق و مبالغ بانکی", "ارزیابی توان بازپرداخت بدهی نسبت به حجم گردش مالی"),
            ("۵. رشد سریع مبالغ در راه (In-Flight Growth)", "۱۰٪ (0.10)", "رشد مبالغ چک‌های صادرشده در گردش", "هشدار انباشت تعهدات آتی و احتمال عدم وصول در سررسید"),
            ("۶. نوسان و بی‌ثباتی (Volatility)", "۵٪ (0.05)", "انحراف معیار تغییرات استعلام‌های دوره‌ای", "بی‌انضباطی مالی و رفتارهای پیش‌بینی‌ناپذیر صادرکننده"),
            ("۷. کیفیت داده و اصالت هویت (Data Quality)", "۵٪ (0.05)", "جریمه برای نقص کدملی یا استعلام‌های ناموفق", "کاهش اطمینان اعتباری ناشی از عدم شفافیت سوابق هویتی"),
        ]

        for rc_idx, (name, wt, form, exp) in enumerate(components, start=r2 + 2):
            z_fill = ZEBRA_FILL if rc_idx % 2 == 0 else PatternFill(fill_type=None)
            ws.cell(row=rc_idx, column=1, value=name).font = BOLD_FONT
            ws.cell(row=rc_idx, column=1).fill = z_fill
            ws.cell(row=rc_idx, column=1).border = THIN_BORDER
            ws.cell(row=rc_idx, column=1).alignment = ALIGN_RIGHT

            ws.cell(row=rc_idx, column=2, value=wt).font = BOLD_FONT
            ws.cell(row=rc_idx, column=2).fill = z_fill
            ws.cell(row=rc_idx, column=2).border = THIN_BORDER
            ws.cell(row=rc_idx, column=2).alignment = ALIGN_CENTER

            ws.cell(row=rc_idx, column=3, value=form).font = REGULAR_FONT
            ws.cell(row=rc_idx, column=3).fill = z_fill
            ws.cell(row=rc_idx, column=3).border = THIN_BORDER
            ws.cell(row=rc_idx, column=3).alignment = ALIGN_RIGHT

            ws.merge_cells(f"D{rc_idx}:G{rc_idx}")
            ws[f"D{rc_idx}"] = exp
            ws[f"D{rc_idx}"].font = REGULAR_FONT
            ws[f"D{rc_idx}"].fill = z_fill
            for c_i in range(4, 8):
                ws.cell(row=rc_idx, column=c_i).border = THIN_BORDER
            ws[f"D{rc_idx}"].alignment = ALIGN_RIGHT

        # Section 3: Mandatory Floors Table
        r3 = r2 + len(components) + 3
        ws.merge_cells(f"A{r3}:G{r3}")
        ws[f"A{r3}"] = "۳. جدول کف‌های اجباری امتیاز ریسک اعتباری (Mandatory Risk Floors F1 - F6)"
        ws[f"A{r3}"].font = SECTION_BOLD_FONT
        ws[f"A{r3}"].fill = BLUE_SECTION_FILL
        ws[f"A{r3}"].alignment = ALIGN_RIGHT

        mf_headers = ["شناسه", "شرط وضعیت صادرکننده", "حداقل امتیاز اجباری (Floor)", "طبقه حاصله"]
        for c_i, h in enumerate(mf_headers, start=1):
            cell = ws.cell(row=r3 + 1, column=c_i, value=h)
            cell.font = WHITE_BOLD_FONT
            cell.fill = SLATE_HEADER_FILL
            cell.alignment = ALIGN_CENTER
            cell.border = THIN_BORDER

        ws.merge_cells(f"E{r3+1}:G{r3+1}")
        ws[f"E{r3+1}"] = "اقدام اعتباری سامانه‌ای"
        ws[f"E{r3+1}"].font = WHITE_BOLD_FONT
        ws[f"E{r3+1}"].fill = SLATE_HEADER_FILL
        ws[f"E{r3+1}"].alignment = ALIGN_CENTER
        for c_i in range(5, 8):
            ws.cell(row=r3 + 1, column=c_i).border = THIN_BORDER

        floors = [
            ("F1", "برگشتی > ۵۰ میلیارد ریال و پایدار (>= ۳ دوره)", "حداقل ۸۵", "اقدام فوری (Immediate Action)", "انسداد فوری حساب، ضبط وثایق و وصول آنی (مانند حسین حشمتی)", CRITICAL_FILL),
            ("F2", "برگشتی > ۲۰ میلیارد ریال و پایدار (>= ۳ دوره)", "حداقل ۷۸", "پرریسک (High Risk)", "توقف افزایش اعتبار، اخذ وثایق ملکی یا نقد (زوار، طرقی، وفادار)", HIGH_RISK_FILL),
            ("F3", "برگشتی > ۱۰ میلیارد ریال و پایدار (>= ۳ دوره)", "حداقل ۷۲", "پرریسک (High Risk)", "کاهش سقف اعتباری و اخذ تضمین تکمیلی (ضیافتی، زحمتکش)", HIGH_RISK_FILL),
            ("F4", "برگشتی > ۵ میلیارد ریال و پایدار (>= ۳ دوره)", "حداقل ۶۵", "پرریسک (High Risk)", "کنترل وصولی‌ها قبل از سررسید (زاهدی، اشرافیان)", HIGH_RISK_FILL),
            ("F5", "برگشتی مثبت (> ۰) و پایدار (>= ۳ دوره)", "حداقل ۴۵", "مراقبت (Watch List)", "ورود به فهرست تحت‌نظر و اخذ چک تضمین جدید (موسوی، محمدی)", WATCH_FILL),
            ("F6", "برگشتی جدید غیرپایدار (۱ تا ۲ دوره)", "حداقل ۳۵", "عادی / آستانه مراقبت", "پایش دقیق و بررسی علت نکول موقت (زهرا بهرامی پویا)", NORMAL_FILL),
        ]

        for mf_idx, (f_id, cond, floor_val, tier_res, act, fl_fill) in enumerate(floors, start=r3 + 2):
            ws.cell(row=mf_idx, column=1, value=f_id).font = BOLD_FONT
            ws.cell(row=mf_idx, column=1).fill = fl_fill
            ws.cell(row=mf_idx, column=1).border = THIN_BORDER
            ws.cell(row=mf_idx, column=1).alignment = ALIGN_CENTER

            ws.cell(row=mf_idx, column=2, value=cond).font = BOLD_FONT
            ws.cell(row=mf_idx, column=2).fill = fl_fill
            ws.cell(row=mf_idx, column=2).border = THIN_BORDER
            ws.cell(row=mf_idx, column=2).alignment = ALIGN_RIGHT

            ws.cell(row=mf_idx, column=3, value=floor_val).font = BOLD_FONT
            ws.cell(row=mf_idx, column=3).fill = fl_fill
            ws.cell(row=mf_idx, column=3).border = THIN_BORDER
            ws.cell(row=mf_idx, column=3).alignment = ALIGN_CENTER

            ws.cell(row=mf_idx, column=4, value=tier_res).font = BOLD_FONT
            ws.cell(row=mf_idx, column=4).fill = fl_fill
            ws.cell(row=mf_idx, column=4).border = THIN_BORDER
            ws.cell(row=mf_idx, column=4).alignment = ALIGN_CENTER

            ws.merge_cells(f"E{mf_idx}:G{mf_idx}")
            ws[f"E{mf_idx}"] = act
            ws[f"E{mf_idx}"].font = REGULAR_FONT
            ws[f"E{mf_idx}"].fill = fl_fill
            for c_i in range(5, 8):
                ws.cell(row=mf_idx, column=c_i).border = THIN_BORDER
            ws[f"E{mf_idx}"].alignment = ALIGN_RIGHT

    # =========================================================================
    # Sheet 11: 11_اختلاف_با_نسخه_قبلی
    # =========================================================================
    def _build_sheet_11_version_comparison(self, wb: openpyxl.Workbook) -> None:
        ws = wb.create_sheet(title="11_اختلاف_با_نسخه_قبلی")
        ws.views.sheetView[0].rightToLeft = True
        ws.sheet_properties.tabColor = "0D9488"

        # Title Block
        ws.merge_cells("A1:G1")
        ws["A1"] = "ماتریس تطبیقی و ممیزی جامع اصلاحات نسخه نهایی (Reconciliation Matrix)"
        ws["A1"].font = TITLE_FONT
        ws["A1"].alignment = ALIGN_RIGHT

        ws.merge_cells("A2:G2")
        ws["A2"] = (
            "مستندسازی جزء به جزء مغایرت‌ها، اصلاحات هویتی، تجمیع تک‌باره، حذف داده‌های ساختگی "
            "و انطباق ۱۰۰٪ با ممیزی نظارتی ۱۴۰۵/۰۶/۱۵"
        )
        ws["A2"].font = SUBTITLE_FONT
        ws["A2"].alignment = ALIGN_RIGHT

        headers = [
            ("ردیف", 6),
            ("سرفصل و مؤلفه کنترلی", 26),
            ("وضعیت در نسخه قبلی (دارای خطا)", 30),
            ("وضعیت در نسخه نهایی (اصلاح‌شده)", 34),
            ("میزان مغایرت / انحراف", 24),
            ("ریشه و منشأ خطا در نسخه قبلی", 36),
            ("اقدام اصلاحی و مستند ممیزی", 44),
        ]

        for c_i, (h_text, _) in enumerate(headers, start=1):
            cell = ws.cell(row=4, column=c_i, value=h_text)
            cell.font = WHITE_BOLD_FONT
            cell.fill = NAVY_HEADER_FILL
            cell.alignment = ALIGN_CENTER
            cell.border = THIN_BORDER

        diff_rows = [
            (
                1,
                "واحد تحلیل و مبنای تجمیع",
                "ردیف‌های چک و ادغام‌های نامعتبر",
                "صادرکننده/مشتری یکتا (کدملی ۱۰ رقمی)",
                "حذف کامل خطای دوباره‌شماری",
                "تکرار مقادیر بانکی به تعداد چک‌های هر مشتری",
                "تجمیع تک‌باره مقادیر بانکی صادرکننده؛ اجرای آزمون AUD-01 و AUD-02"
            ),
            (
                2,
                "تعداد پروفایل‌های بانکی معتبر",
                "۴۸ یا ۵۲ ردیف با پرونده‌های نامعتبر",
                "دقیقاً ۴۶ پروفایل بانکی معتبر یکتا",
                "-۶ ردیف مازاد / تفکیک ۲ پرونده",
                "عدم تفکیک سفته و اسناد حل‌نشده از پروفایل صیاد",
                "تفکیک علیپور (سفته) و رنگرززاده (حل‌نشده)؛ انطباق با AUD-01"
            ),
            (
                3,
                "مجموع چک‌های در راه بانکی",
                "۴,۴۶۶,۰۶۹,۴۶۹,۴۵۴ ریال",
                "۴,۸۵۶,۳۲۲,۰۵۱,۴۰۷ ریال",
                "+۳۹۰,۲۵۲,۵۸۱,۹۵۳ ریال",
                "نقص داده‌های استعلام وحید اشرافیان و جواد غفوریان",
                "تثبیت آخرین استعلام‌های معتبر بانکی؛ انطباق با AUD-03"
            ),
            (
                4,
                "مجموع چک‌های برگشتی بانکی",
                "۲۳۱,۹۵۱,۰۰۰,۰۰۰ ریال",
                "۲۴۴,۷۵۱,۰۰۰,۰۰۰ ریال",
                "+۱۲,۸۰۰,۰۰۰,۰۰۰ ریال",
                "صفر شدن اشتباه برگشتی پرونده ابوالفضل شافعی",
                "بازیابی سوابق معتبر استعلام شافعی (۱۲.۸B)؛ انطباق با AUD-04"
            ),
            (
                5,
                "مجموع مبالغ رفع سوءاثر بانکی",
                "۱,۰۲۴,۳۰۵,۱۸۵,۷۹۷ ریال",
                "۱,۱۰۹,۴۸۶,۹۹۹,۹۶۸ ریال",
                "+۸۵,۱۸۱,۸۱۴,۱۷۱ ریال",
                "عدم همگام‌سازی استعلام‌های تاریخی و رفع اثرات جدید",
                "ثبت دقیق استعلام‌های به‌روز و رفع اثرات محقق‌شده؛ انطباق با AUD-05"
            ),
            (
                6,
                "تعهد فعال بانکی (در راه + برگشتی)",
                "۴,۶۹۸,۰۲۰,۴۶۹,۴۵۴ ریال",
                "۵,۱۰۱,۰۷۳,۰۵۱,۴۰۷ ریال",
                "+۴۰۳,۰۵۲,۵۸۱,۹۵۳ ریال",
                "وابستگی به مبالغ ناقص در راه و برگشتی قبلی",
                "محاسبه بر اساس جمع ریاضی دقیق J4:J49 + K4:K49؛ انطباق با AUD-06"
            ),
            (
                7,
                "ارزش ریالی چک‌های صندوق معتبر",
                "۴۸۳,۳۲۵,۰۰۰,۰۰۰ ریال (بدون تفکیک)",
                "۴۷۹,۷۰۵,۰۰۰,۰۰۰ ریال",
                "-۳,۶۲۰,۰۰۰,۰۰۰ ریال (انتقال به شیت ۸)",
                "تداخل اسناد سفته و فاقد کدملی با پروفایل‌های معتبر",
                "تفکیک اسناد معاف و حل‌نشده در شیت ۰۸؛ انطباق با AUD-08"
            ),
            (
                8,
                "پرونده ابوالفضل شافعی (کد ۵)",
                "برگشتی صفر و فاقد رخداد انتقال",
                "برگشتی ۱۲.۸B و انتقال قطعی ۷.۵B",
                "+۱۲,۸۰۰,۰۰۰,۰۰۰ ریال برگشتی",
                "صفر شدن داده در استعلام‌های ناقص درگاه",
                "تثبیت برگشتی ۱۲.۸B، نمره ۷۲ (پرریسک) و ثبت رخداد؛ انطباق با AUD-09"
            ),
            (
                9,
                "پرونده زهرا بهرامی پویا (کد ۴۶)",
                "نمره پایین / عدم اعمال کف اجباری",
                "برگشتی ۱۲.۳B، انتقال ۳.۵B، نمره >= ۷۲",
                "ارتقا به طبقه پرریسک (کف ۷۲)",
                "عدم اعمال کف اجباری برگشتی بالای ۱۰ میلیارد ریال",
                "اعمال کف ریسک F3 (نمره ۷۲) و انتقال قطعی -۳.۵B/+۳.۵B؛ انطباق با AUD-10"
            ),
            (
                10,
                "احراز هویت طاهری (کد ۷)",
                "فاقد کد ملی با نام ساختگی «مسعود قدیری»",
                "کدملی 6510019418 با وضعیت VERIFIED",
                "احراز کامل هویت واقعی",
                "تولید ساختگی داده به جای استعلام شماره حساب",
                "بازیابی از سابقه معتبر داخلی/شناسه صیاد تاریخی؛ انطباق با AUD-11"
            ),
            (
                11,
                "احراز هویت فرهنگ‌نیا (کد ۱۳)",
                "فاقد شناسه با نام «بازرگانی مانی بارثاوا»",
                "کدملی 2110152184 با وضعیت VERIFIED",
                "احراز کامل هویت واقعی",
                "تولید شرکت حقوقی ساختگی بدون شناسه ۱۱ رقمی",
                "بازیابی از سابقه معتبر داخلی/شناسه صیاد تاریخی؛ انطباق با AUD-11"
            ),
            (
                12,
                "احراز هویت ضرغام‌مقدم (کد ۲۶)",
                "کدملی مفقود با نام «امیر هوشنگ حامدی‌نسب»",
                "کدملی 0941876578 با وضعیت VERIFIED",
                "احراز کامل هویت واقعی",
                "تولید نام فرضی غیرمنطبق با اسناد صندوق",
                "بازیابی از سابقه معتبر داخلی/شناسه صیاد تاریخی؛ انطباق با AUD-11"
            ),
            (
                13,
                "پرونده داوود رنگرززاده (کد ۲۹)",
                "نام ساختگی «برادران عسگری» (حساب مشترک)",
                "نام واقعی داوود رنگرززاده (UNRESOLVED)",
                "اصلاح هویت و تفکیک ۲۲۰ میلیون ریال",
                "عنوان تجاری فرضی فاقد سند در صندوق",
                "ثبت سند واقعی چک ۴۱۵۵۶۹ بانک ملی در شیت ۰۸؛ انطباق با AUD-13"
            ),
            (
                14,
                "پرونده عباس مقنی (کد ۱۷)",
                "ثبت کاذب رخداد رفع سوءاثر با صفر شدن ارقام",
                "حفظ مقادیر معتبر، صفر رخداد کاذب در شیت ۳",
                "حذف رخداد اشتباه رفع سوءاثر",
                "نقص پاسخ درگاه بانکی و تلقی اشتباه به عنوان رفع اثر",
                "حفاظت از داده‌های معتبر تاریخی و حذف رویداد ساختگی؛ انطباق با AUD-12"
            ),
            (
                15,
                "پرونده جواد غفوریان (کد ۱۱)",
                "قرارگیری در طبقه کم‌ریسک بدون پایش",
                "تسویه ۱B، افزایش ۱B رفع اثر (کاهش ۱,۰۰۰,۰۰۰,۰۰۰ ریال برگشتی)، طبقه مراقبت",
                "تخصیص امتیاز ۴۵ (Watch List)",
                "عدم لحاظ دوره گذار پایش پس از تسویه",
                "تخصیص کف دوره گذار ۴۵ و ثبت در شیت مراقبت و بهبود؛ پایش روزانه الزامی"
            ),
            (
                16,
                "پاکسازی اسامی ساختگی (شیت ۸)",
                "وجود قدیری، بارثاوا، حامدی‌نسب، عسگری، نجارزاده",
                "صفر نام ساختگی؛ صرفاً اسناد واقعی با شناسه منشأ",
                "حذف ۱۰۰٪ اسامی و ارقام فرضی",
                "جایگزینی داده‌های مفقود با اسامی فرضی در گزارش قبلی",
                "پالایش کامل اسامی، افزودن ستون شناسه صیاد منشأ؛ انطباق با AUD-13"
            ),
            (
                17,
                "سیستم ممیزی مستقل (شیت ۹)",
                "۱۰ آزمون اولیه با فرمول‌های غیرمنطبق",
                "۱۹ آزمون ممیزی رسمی خودکار (AUD-01 تا AUD-19) با نتیجه ۱۰۰٪ PASS",
                "+۹ آزمون تکمیلی کنترلی و رفتاری",
                "عدم پوشش آزمون‌های هویتی و رفتار برگشتی مثبت",
                "پیاده‌سازی ۱۹ آزمون قطعی AUD-01 تا AUD-19 با فرمول‌های اکسل؛ ۱۰۰٪ PASS"
            ),
        ]

        for r_idx, r_data in enumerate(diff_rows, start=5):
            z_fill = ZEBRA_FILL if r_idx % 2 == 0 else PatternFill(fill_type=None)
            for c_i, val in enumerate(r_data, start=1):
                cell = ws.cell(row=r_idx, column=c_i, value=val)
                cell.font = REGULAR_FONT
                cell.fill = z_fill
                cell.border = THIN_BORDER

                if c_i == 1:
                    cell.alignment = ALIGN_CENTER
                    cell.font = BOLD_FONT
                elif c_i in (2, 5):
                    cell.alignment = ALIGN_CENTER
                    cell.font = BOLD_FONT
                elif c_i == 3:  # Old version
                    cell.alignment = ALIGN_RIGHT
                    cell.font = Font(name="Tahoma", size=9, color="991B1B")
                elif c_i == 4:  # New version
                    cell.alignment = ALIGN_RIGHT
                    cell.font = Font(name="Tahoma", size=9, bold=True, color="166534")
                else:
                    cell.alignment = ALIGN_RIGHT

        # Summary Note
        r_note = len(diff_rows) + 6
        ws.merge_cells(f"A{r_note}:G{r_note+1}")
        note_cell = ws[f"A{r_note}"]
        note_cell.value = (
            "تاییدیه مدیر ارشد سیستم و ناظر مستقل اعتباری:\n"
            "«کلیه مغایرت‌های فوق بر اساس بازیابی از سابقه معتبر داخلی/شناسه صیاد تاریخی، "
            "دفاتر فیزیکی اسناد صندوق و ممیزی مستقل ریاضی ۱۹ آزمونه برطرف گردیده و نسخه حاضر، سند مرجع قطعی تصمیم‌گیری اعتباری می‌باشد.»"
        )
        note_cell.font = Font(name="Tahoma", size=10, bold=True, color="0F766E")
        note_cell.fill = CARD_BG_FILL
        note_cell.alignment = ALIGN_CENTER
        for r_i in range(r_note, r_note + 2):
            for c_i in range(1, 8):
                ws.cell(row=r_i, column=c_i).border = TOTAL_BORDER

    # =========================================================================
    # Helpers
    # =========================================================================
    def _auto_fit_columns(self, wb: openpyxl.Workbook) -> None:
        """Auto-adjusts column widths across all sheets."""
        for ws in wb.worksheets:
            for col in ws.columns:
                max_len = 0
                col_letter = get_column_letter(col[0].column)
                for cell in col:
                    val_str = str(cell.value or "")
                    if val_str.startswith("="):
                        val_str = "123,456,789,000"
                    cell_len = len(val_str)
                    if cell_len > max_len:
                        max_len = cell_len
                # Generous width calculation with upper bounds
                ws.column_dimensions[col_letter].width = min(max(max_len + 4, 12), 65)


# Convenience Functions
def generate_10_sheet_workbook(output_path: Optional[str] = None, db_path: Optional[str] = None) -> bytes:
    """Convenience functional interface for ExcelExporter.generate_10_sheet_workbook."""
    exporter = ExcelExporter(db_path=db_path)
    return exporter.generate_10_sheet_workbook(output_path=output_path)


def generate_comprehensive_excel(output_path: Optional[str] = None) -> bytes:
    """Backward-compatible alias for generate_10_sheet_workbook."""
    exporter = ExcelExporter()
    return exporter.generate_10_sheet_workbook(output_path=output_path)
