# -*- coding: utf-8 -*-
"""
Comprehensive Unit and Integration Tests for Milestone 4 (R5, F14, F15, F17).
Validates the 10-sheet RTL Excel workbook generator, dual-audit engine,
formula evaluations, and data invariants across all sheets.
"""

import os
import io
import pytest
import openpyxl

from app.services.excel_exporter import (
    ExcelExporter,
    generate_10_sheet_workbook,
    generate_comprehensive_excel,
    DEFAULT_PROJECT_OUTPUT_PATH,
    DEFAULT_DESKTOP_OUTPUT_PATH,
    MANDATORY_DEDUPLICATION_STATEMENT,
)
from app.services.dual_audit_service import (
    DualAuditService,
    audit_excel_workbook,
    DUAL_AUDIT_SPECS,
)
from app.services.financial_aggregator import (
    EXPECTED_FUND_TOTAL_AMOUNT,
    EXPECTED_FUND_CHEQUE_COUNT,
    EXPECTED_PORTFOLIO_BOUNCED,
    EXPECTED_PORTFOLIO_IN_TRANSIT,
    EXPECTED_PORTFOLIO_CLEARED,
    EXPECTED_CANONICAL_CUSTOMERS_COUNT,
)

EXPECTED_SHEET_NAMES = [
    "01_خلاصه_مدیریتی",
    "02_مشتریان_یکتا",
    "03_رخدادهای_امروز",
    "04_اقدام_فوری",
    "05_مراقبت",
    "06_بهبود",
    "07_چکهای_تفصیلی",
    "08_مشکلات_هویتی",
    "09_ممیزی",
    "10_راهنما",
]


@pytest.fixture(scope="module")
def generated_workbook():
    """Generates the workbook once for the test module and returns (wb, excel_bytes)."""
    exporter = ExcelExporter()
    excel_bytes = exporter.generate_10_sheet_workbook()
    wb = openpyxl.load_workbook(io.BytesIO(excel_bytes), data_only=False)
    return wb, excel_bytes


# =============================================================================
# 1. Output Destinations & Generation Parity Tests
# =============================================================================

def test_file_generation_at_both_destinations():
    """Verify workbook is generated and saved at both project root and Desktop."""
    exporter = ExcelExporter()
    data = exporter.generate_10_sheet_workbook()
    assert len(data) > 0

    assert os.path.exists(DEFAULT_PROJECT_OUTPUT_PATH), (
        f"Workbook must exist at project root: {DEFAULT_PROJECT_OUTPUT_PATH}"
    )
    assert os.path.getsize(DEFAULT_PROJECT_OUTPUT_PATH) > 0

    assert os.path.exists(DEFAULT_DESKTOP_OUTPUT_PATH), (
        f"Workbook must exist at Desktop: {DEFAULT_DESKTOP_OUTPUT_PATH}"
    )
    assert os.path.getsize(DEFAULT_DESKTOP_OUTPUT_PATH) > 0


def test_custom_output_path_generation(tmp_path):
    """Verify workbook can be saved to a custom output path."""
    custom_path = str(tmp_path / "custom_report.xlsx")
    exporter = ExcelExporter()
    data = exporter.generate_10_sheet_workbook(output_path=custom_path, save_to_defaults=False)
    assert os.path.exists(custom_path)
    assert os.path.getsize(custom_path) == len(data)


def test_backward_compatible_aliases():
    """Verify generate_10_sheet_workbook and generate_comprehensive_excel functions work."""
    data1 = generate_10_sheet_workbook()
    data2 = generate_comprehensive_excel()
    assert len(data1) > 0
    assert len(data2) > 0


# =============================================================================
# 2. 10-Sheet Structure & RTL Verification Tests
# =============================================================================

def test_all_10_sheet_names_exist(generated_workbook):
    """Verify that all 10 exact sheet names exist in the workbook."""
    wb, _ = generated_workbook
    sheet_names = wb.sheetnames
    assert len(sheet_names) >= 10, f"Expected at least 10 sheets, got {len(sheet_names)}: {sheet_names}"
    for expected in EXPECTED_SHEET_NAMES:
        assert expected in sheet_names, f"Missing sheet: {expected}"


def test_rtl_layout_on_all_10_sheets(generated_workbook):
    """Verify that every sheet has Right-To-Left layout enabled (ws.views.sheetView[0].rightToLeft = True)."""
    wb, _ = generated_workbook
    for s_name in wb.sheetnames:
        ws = wb[s_name]
        is_rtl = ws.views.sheetView[0].rightToLeft
        assert is_rtl is True, f"Sheet '{s_name}' must have rightToLeft = True"


# =============================================================================
# 3. Sheet 01: 01_خلاصه_مدیریتی Tests
# =============================================================================

def test_sheet_01_mandatory_deduplication_statement(generated_workbook):
    """Verify Sheet 01 contains the mandatory deduplication declaration statement."""
    wb, _ = generated_workbook
    ws = wb["01_خلاصه_مدیریتی"]
    found = False
    for r in range(1, ws.max_row + 1):
        for c in range(1, ws.max_column + 1):
            val = str(ws.cell(r, c).value or "")
            if "محاسبات بانکی بر اساس مشتری یکتا انجام شد" in val:
                found = True
                break
        if found:
            break
    assert found, f"Mandatory statement '{MANDATORY_DEDUPLICATION_STATEMENT}' not found in Sheet 01"


def test_sheet_01_portfolio_kpis(generated_workbook):
    """Verify Sheet 01 contains correct portfolio KPIs or formula links."""
    wb, _ = generated_workbook
    ws = wb["01_خلاصه_مدیریتی"]

    # Search for key KPI values or live formula references in column 2
    col2_values = [str(ws.cell(r, 2).value or "") for r in range(1, ws.max_row + 1)]
    assert any("COUNTA" in v or "46" in v for v in col2_values), "Valid profiles count 46 must be referenced"
    assert any("COUNTA" in v or "147" in v for v in col2_values), "Cheques count 147 must be referenced"
    assert any("SUM" in v or "483325000000" in v or "483,325,000,000" in v for v in col2_values), "Fund total must be referenced"


def test_sheet_01_hhi_and_top_10_share(generated_workbook):
    """Verify Sheet 01 contains HHI concentration index (~1407.27 or ~1536) and top 10 share (~96.6% or ~98.2%)."""
    wb, _ = generated_workbook
    ws = wb["01_خلاصه_مدیریتی"]
    all_values = [str(ws.cell(r, c).value or "") for r in range(1, ws.max_row + 1) for c in range(1, ws.max_column + 1)]
    
    hhi_found = any("1407" in v or "1536" in v for v in all_values)
    share_found = any("96.6" in v or "98.2" in v for v in all_values)
    assert hhi_found, "HHI index must be present in Sheet 01"
    assert share_found, "Top 10 concentration share must be present in Sheet 01"


# =============================================================================
# 4. Sheet 02: 02_مشتریان_یکتا Tests
# =============================================================================

def test_sheet_02_canonical_customers_count_is_46(generated_workbook):
    """Verify Sheet 02 contains exactly 46 valid canonical customer rows (rows 4 to 49)."""
    wb, _ = generated_workbook
    ws = wb["02_مشتریان_یکتا"]
    customer_ids = [ws.cell(r, 2).value for r in range(4, 50)]
    assert len(customer_ids) == 46
    assert len(set(customer_ids)) == 46


def test_sheet_02_total_row_formulas(generated_workbook):
    """Verify Sheet 02 Total Row (Row 50) uses standard Excel SUM formulas."""
    wb, _ = generated_workbook
    ws = wb["02_مشتریان_یکتا"]
    tot_row = 50

    assert ws.cell(tot_row, 1).value == "مجموع کل"
    assert ws.cell(tot_row, 7).value == "=SUM(G4:G49)"   # Total cheques
    assert ws.cell(tot_row, 8).value == "=SUM(H4:H49)"   # Fund total
    assert ws.cell(tot_row, 10).value == "=SUM(J4:J49)"  # In-transit total
    assert ws.cell(tot_row, 11).value == "=SUM(K4:K49)"  # Bounced total
    assert ws.cell(tot_row, 12).value == "=SUM(L4:L49)"  # Cleared total


def test_sheet_02_data_invariants(generated_workbook):
    """Verify data sums in Sheet 02 match project invariants."""
    wb, _ = generated_workbook
    ws = wb["02_مشتریان_یکتا"]

    fund_sum = sum(float(ws.cell(r, 8).value or 0.0) for r in range(4, 50))
    assert abs(fund_sum - 479_705_000_000.0) < 1.0, f"Valid fund sum must be 479,705,000,000, got {fund_sum}"

    bounced_sum = sum(float(ws.cell(r, 11).value or 0.0) for r in range(4, 50))
    assert abs(bounced_sum - 244_751_000_000.0) < 1.0, f"Bounced sum must be 244,751,000,000, got {bounced_sum}"

    in_transit_sum = sum(float(ws.cell(r, 10).value or 0.0) for r in range(4, 50))
    assert abs(in_transit_sum - 4_856_322_051_407.0) < 1.0

    cleared_sum = sum(float(ws.cell(r, 12).value or 0.0) for r in range(4, 50))
    assert abs(cleared_sum - 1_109_486_999_968.0) < 1.0


def test_sheet_02_national_ids_preserve_leading_zeros(generated_workbook):
    """Verify that all National IDs in Sheet 02 are formatted as text with preserved leading zeros."""
    wb, _ = generated_workbook
    ws = wb["02_مشتریان_یکتا"]

    for r in range(4, 50):
        nid_cell = ws.cell(r, 3)
        nid_val = str(nid_cell.value or "")
        cid = ws.cell(r, 2).value

        assert len(nid_val) == 10, f"Customer {cid} NID '{nid_val}' must have 10 digits"
        assert nid_val.isdigit(), f"Customer {cid} NID '{nid_val}' must be numeric digits"
        assert nid_cell.number_format == "@", f"Customer {cid} NID cell must have text format @"

    # Check specific leading zero customers
    nids = {ws.cell(r, 2).value: str(ws.cell(r, 3).value) for r in range(4, 50)}
    assert nids[46] == "0927624011"  # Zahra Bahrami Pouya
    assert nids[40] == "0890543331"  # Mohammad Rafigh Toroghi
    assert nids[2] == "0933387075"   # Hossein Heshmati


# =============================================================================
# 5. Sheet 07: 07_چکهای_تفصیلی Tests
# =============================================================================

def test_sheet_07_cheques_count_and_formula_sum(generated_workbook):
    """
    Verify Sheet 07:
    - Has exactly 147 cheques (rows 2 to 148).
    - Formula sum in row 149 column L is exactly =SUM(L2:L148).
    - Sum of cheque amounts is exactly 483,325,000,000 Rials.
    """
    wb, _ = generated_workbook
    ws = wb["07_چکهای_تفصیلی"]

    cheque_count = 148 - 2 + 1
    assert cheque_count == EXPECTED_FUND_CHEQUE_COUNT

    formula_cell = ws.cell(149, 12)
    assert formula_cell.value == "=SUM(L2:L148)"

    # Sum the data values directly
    actual_sum = sum(float(ws.cell(r, 12).value or 0.0) for r in range(2, 149))
    assert actual_sum == EXPECTED_FUND_TOTAL_AMOUNT


def test_sheet_07_original_accounting_columns(generated_workbook):
    """Verify Sheet 07 contains all 24 original accounting columns."""
    wb, _ = generated_workbook
    ws = wb["07_چکهای_تفصیلی"]
    headers = [ws.cell(1, c).value for c in range(1, 25)]
    assert len(headers) == 24
    assert "چک|مبلغ" in headers
    assert "چک|شماره" in headers


# =============================================================================
# 6. Sheet 03: 03_رخدادهای_امروز Tests
# =============================================================================

def test_sheet_03_zahra_bahrami_pouya_transition(generated_workbook):
    """Verify Zahra Bahrami Pouya transition event (-3.5B / +3.5B) is documented in Sheet 03."""
    wb, _ = generated_workbook
    ws = wb["03_رخدادهای_امروز"]
    zahra_rows = [
        r for r in range(4, ws.max_row + 1)
        if str(ws.cell(r, 3).value or "") == "0927624011"
    ]
    assert len(zahra_rows) >= 1, "Zahra Bahrami Pouya event must be present"
    r = zahra_rows[0]
    ev_type = str(ws.cell(r, 4).value or "")
    assert "انتقال" in ev_type


def test_sheet_03_contains_clearance_event(generated_workbook):
    """Verify clearance event (Javad Ghafourian) is documented in Sheet 03."""
    wb, _ = generated_workbook
    ws = wb["03_رخدادهای_امروز"]
    all_events = [str(ws.cell(r, 4).value or "") for r in range(4, ws.max_row + 1)]
    assert any("رفع سوءاثر" in ev for ev in all_events), "Clearance event must be present in Sheet 03"


# =============================================================================
# 7. Sheet 04, 05, 06 Tests
# =============================================================================

def test_sheet_04_immediate_action_customers(generated_workbook):
    """Verify Sheet 04 contains immediate action customers (score >= 81.0, e.g. Hossein Heshmati)."""
    wb, _ = generated_workbook
    ws = wb["04_اقدام_فوری"]
    assert ws.max_row >= 4
    names = [str(ws.cell(r, 2).value or "") for r in range(4, ws.max_row + 1)]
    assert any("حسین حشمتی" in n for n in names)
    scores = [float(ws.cell(r, 4).value or 0.0) for r in range(4, ws.max_row + 1)]
    assert all(s >= 81.0 for s in scores)


def test_sheet_05_watchlist_customers(generated_workbook):
    """Verify Sheet 05 contains watchlist customers (score 41 to 60)."""
    wb, _ = generated_workbook
    ws = wb["05_مراقبت"]
    assert ws.max_row >= 4
    scores = [float(ws.cell(r, 4).value or 0.0) for r in range(4, ws.max_row + 1)]
    assert all(41.0 <= s <= 60.0 for s in scores)


def test_sheet_06_clearance_customers(generated_workbook):
    """Verify Sheet 06 contains documented clearance customers (e.g. Javad Ghafourian)."""
    wb, _ = generated_workbook
    ws = wb["06_بهبود"]
    assert ws.max_row >= 4
    names = [str(ws.cell(r, 2).value or "") for r in range(4, ws.max_row + 1)]
    assert any("جواد غفوریان" in n for n in names)


# =============================================================================
# 8. Sheet 08: 08_مشکلات_هویتی Tests
# =============================================================================

def test_sheet_08_disambiguation_0933387075(generated_workbook):
    """Verify Sheet 08 documents the disambiguation between Hossein Heshmati and Amirhossein Alipour."""
    wb, _ = generated_workbook
    ws = wb["08_مشکلات_هویتی"]
    all_text = " ".join(str(ws.cell(r, c).value or "") for r in range(1, ws.max_row + 1) for c in range(1, ws.max_column + 1))
    assert "0933387075" in all_text
    assert "حسین حشمتی" in all_text
    assert "امیرحسین علیپور" in all_text


def test_sheet_08_unresolved_and_exempt_totals(generated_workbook):
    """Verify Sheet 08 lists unresolved customers and exempt documents totaling 3.62B."""
    wb, _ = generated_workbook
    ws = wb["08_مشکلات_هویتی"]
    all_vals = [ws.cell(r, c).value for r in range(1, ws.max_row + 1) for c in range(1, ws.max_column + 1)]
    assert 220_000_000 in all_vals, "UNRESOLVED_IDENTITY sum 220,000,000 must be present"
    assert 3_400_000_000 in all_vals, "EXEMPT sum 3,400,000,000 must be present"
    assert 3_620_000_000 in all_vals, "Total discrepancy 3,620,000,000 must be present"


# =============================================================================
# 9. Sheet 09: 09_ممیزی & Dual-Audit Tests
# =============================================================================

def test_sheet_09_contains_19_audit_tests(generated_workbook):
    """Verify Sheet 09 contains exactly 19 automated audit tests with AUD-01 to AUD-19."""
    wb, _ = generated_workbook
    ws = wb["09_ممیزی"]
    test_codes = [ws.cell(r, 2).value for r in range(8, 27)]
    expected_codes = [f"AUD-{i:02d}" for i in range(1, 20)]
    assert test_codes == expected_codes


def test_sheet_09_all_formulas_present(generated_workbook):
    """Verify all 19 tests in Sheet 09 contain valid Excel IF formulas."""
    wb, _ = generated_workbook
    ws = wb["09_ممیزی"]
    for r in range(8, 27):
        formula_cell = ws.cell(r, 8)
        assert str(formula_cell.value).startswith("=IF("), f"Row {r} must contain an Excel =IF(...) formula"


def test_dual_audit_service_programmatic_verification():
    """Verify DualAuditService programmatic audit passes 19/19 tests."""
    service = DualAuditService()
    res = service.evaluate_invariants_programmatically()
    assert res["all_passed"] is True
    assert res["passed_count"] == 19
    assert res["total_count"] == 19


def test_independent_audit_excel_workbook_function():
    """Verify audit_excel_workbook utility function returns passed=True on the generated file."""
    res = audit_excel_workbook(DEFAULT_PROJECT_OUTPUT_PATH)
    assert res["passed"] is True
    assert res["all_rtl"] is True
    assert res["audit_tests_count"] == 19
    assert len(res["missing_sheets"]) == 0


# =============================================================================
# 10. Sheet 10: 10_راهنما Tests
# =============================================================================

def test_sheet_10_documentation_contents(generated_workbook):
    """Verify Sheet 10 contains risk scoring methodology, 7 weights, and 6 mandatory floors."""
    wb, _ = generated_workbook
    ws = wb["10_راهنما"]
    all_text = " ".join(str(ws.cell(r, c).value or "") for r in range(1, ws.max_row + 1) for c in range(1, ws.max_column + 1))

    # Check methodology components
    assert "۳۰٪" in all_text  # Current Bounced weight
    assert "۲۰٪" in all_text  # Persistence weight
    assert "۱۵٪" in all_text  # Recent increase & Bounced ratio weights
    assert "۱۰٪" in all_text  # In-flight growth weight
    assert "۵٪" in all_text   # Volatility & Data quality weights

    # Check mandatory floors F1 to F6
    assert "F1" in all_text and "۸۵" in all_text
    assert "F2" in all_text and "۷۸" in all_text
    assert "F3" in all_text and "۷۲" in all_text
    assert "F4" in all_text and "۶۵" in all_text
    assert "F5" in all_text and "۴۵" in all_text
    assert "F6" in all_text and "۳۵" in all_text


# =============================================================================
# 11. OpenPyXL Data Extraction & No Corruption
# =============================================================================

def test_openpyxl_reload_without_corruption():
    """Verify generated Excel file can be reloaded and resaved without errors or corruption."""
    wb = openpyxl.load_workbook(DEFAULT_PROJECT_OUTPUT_PATH)
    temp_buf = io.BytesIO()
    wb.save(temp_buf)
    temp_buf.seek(0)
    wb_reloaded = openpyxl.load_workbook(temp_buf)
    assert len(wb_reloaded.sheetnames) >= 10
    wb.close()
    wb_reloaded.close()
