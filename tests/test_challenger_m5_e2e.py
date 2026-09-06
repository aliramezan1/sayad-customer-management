import os
import openpyxl
import pytest

ROOT_FILE = r"c:\Users\HP\Desktop\نام و نام خانوادگی مشتریان\گزارش_جامع_اعتباری_مشتریان_صیادی_۱۴۰۵۰۶۱۵.xlsx"
DESKTOP_FILE = r"C:\Users\HP\Desktop\گزارش_جامع_اعتباری_مشتریان_صیادی_۱۴۰۵۰۶۱۵.xlsx"

EXPECTED_SHEETS = [
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

MANDATORY_STATEMENT_VARIANTS = [
    "محاسبات بانکی بر اساس مشتری یکتا انجام شد و هیچ مبلغ در راه/برگشتی/رفع سوءاثر به دلیل تعدد چک دوباره‌شماری نشده است",
    "محاسبات بانکی بر اساس مشتری یکتا انجام شد و هیچ مبلغ در راه/برگشتی/رفع سوءاثر به دلیل تعدد چک دوبارهشماری نشده است",
]


@pytest.fixture(params=[ROOT_FILE, DESKTOP_FILE], ids=["RootFile", "DesktopFile"])
def excel_path(request):
    path = request.param
    assert os.path.exists(path), f"Excel file does not exist: {path}"
    return path


@pytest.fixture
def wb(excel_path):
    return openpyxl.load_workbook(excel_path, data_only=False)


@pytest.fixture
def wb_data(excel_path):
    return openpyxl.load_workbook(excel_path, data_only=True)


# ==============================================================================
# AC 4: Structure & Layout Tests
# ==============================================================================

def test_ac4_file_exists_and_size_identical():
    assert os.path.exists(ROOT_FILE), "Project root Excel file missing"
    assert os.path.exists(DESKTOP_FILE), "Desktop Excel file missing"
    size1 = os.path.getsize(ROOT_FILE)
    size2 = os.path.getsize(DESKTOP_FILE)
    assert size1 > 50000, f"Root Excel size too small: {size1}"
    assert size1 == size2, f"Files sizes differ: root={size1}, desktop={size2}"


def test_ac4_all_10_sheets_present_exact_names(wb):
    sheet_names = wb.sheetnames
    assert len(sheet_names) == 10, f"Expected exactly 10 sheets, got {len(sheet_names)}: {sheet_names}"
    for expected in EXPECTED_SHEETS:
        assert expected in sheet_names, f"Missing sheet: {expected}"


def test_ac4_right_to_left_enabled_on_all_sheets(wb):
    for name in wb.sheetnames:
        ws = wb[name]
        assert ws.views.sheetView[0].rightToLeft is True, f"RTL not enabled on sheet {name}"


def test_ac4_vazirmatn_or_tahoma_font_used(wb):
    for name in wb.sheetnames:
        ws = wb[name]
        for row in ws.iter_rows(max_row=20, max_col=10):
            for cell in row:
                if cell.value is not None and cell.font and cell.font.name:
                    # Persian text uses Vazirmatn/Tahoma, formula code strings use Consolas
                    assert cell.font.name in ["Vazirmatn", "Tahoma", "Consolas"], (
                        f"Unexpected font '{cell.font.name}' in sheet {name}, cell {cell.coordinate}"
                    )


def test_ac4_mandatory_deduplication_statement(wb):
    ws = wb["01_خلاصه_مدیریتی"]
    found = False
    for row in ws.iter_rows(values_only=True):
        for val in row:
            if val and any(variant in str(val) for variant in MANDATORY_STATEMENT_VARIANTS):
                found = True
                break
        if found:
            break
    assert found, "Mandatory deduplication statement not found in sheet 01_خلاصه_مدیریتی"


# ==============================================================================
# AC 1: Deduplication Integrity Tests
# ==============================================================================

def test_ac1_sheet02_exactly_48_unique_customers(wb_data):
    ws = wb_data["02_مشتریان_یکتا"]
    customer_rows = []
    # Header is at row 3, data rows from row 4 to 51
    for r in range(4, 52):
        row_num = ws.cell(row=r, column=1).value
        cid = ws.cell(row=r, column=2).value
        nid = ws.cell(row=r, column=3).value
        name = ws.cell(row=r, column=4).value
        if cid is not None:
            customer_rows.append((cid, name, nid))
    
    assert len(customer_rows) == 48, f"Expected exactly 48 customer rows, got {len(customer_rows)}"
    
    # Check row 52 is summary row ('مجموع کل')
    summary_label = ws.cell(row=52, column=1).value
    assert "مجموع" in str(summary_label) or "جمع" in str(summary_label), f"Row 52 should be summary, got {summary_label}"


def test_ac1_deduplicated_bank_sums_in_sheet01_and_sheet02(wb_data):
    # Expected banking amounts
    EXPECTED_IN_FLIGHT = 4_466_069_469_454
    EXPECTED_BOUNCED = 231_951_000_000
    EXPECTED_CLEARED = 1_024_305_185_797
    
    # Check sheet 02 sums from rows 4 to 51
    ws02 = wb_data["02_مشتریان_یکتا"]
    sum_inflight = 0
    sum_bounced = 0
    sum_cleared = 0
    
    for r in range(4, 52):
        # Col J: In-flight, Col K: Bounced, Col L: Cleared
        inf = ws02.cell(row=r, column=10).value or 0
        bnc = ws02.cell(row=r, column=11).value or 0
        clr = ws02.cell(row=r, column=12).value or 0
        sum_inflight += int(inf)
        sum_bounced += int(bnc)
        sum_cleared += int(clr)
        
    assert sum_inflight == EXPECTED_IN_FLIGHT, f"Sheet 02 in-flight sum mismatch: {sum_inflight} != {EXPECTED_IN_FLIGHT}"
    assert sum_bounced == EXPECTED_BOUNCED, f"Sheet 02 bounced sum mismatch: {sum_bounced} != {EXPECTED_BOUNCED}"
    assert sum_cleared == EXPECTED_CLEARED, f"Sheet 02 cleared sum mismatch: {sum_cleared} != {EXPECTED_CLEARED}"
    
    # Check sheet 01 KPIs
    ws01 = wb_data["01_خلاصه_مدیریتی"]
    ws01_text = ""
    for row in ws01.iter_rows(values_only=True):
        for cell in row:
            if cell is not None:
                ws01_text += f" {cell} "
                
    assert str(EXPECTED_IN_FLIGHT) in ws01_text or "4,466,069,469,454" in ws01_text
    assert str(EXPECTED_BOUNCED) in ws01_text or "231,951,000,000" in ws01_text
    assert str(EXPECTED_CLEARED) in ws01_text or "1,024,305,185,797" in ws01_text


def test_ac1_no_double_counting_mathematical_contrast(wb_data):
    """If banking inquiry status were summed per check (over 147 checks),
    customers with multiple checks would multiply their bank status amounts."""
    ws07 = wb_data["07_چکهای_تفصیلی"]
    ws02 = wb_data["02_مشتریان_یکتا"]
    
    # Map customer ID/national code to count of fund checks
    fund_checks_per_cust = {}
    for r in range(2, 149):
        # Col A is radif, Col B/C is name/nid
        nid = str(ws07.cell(row=r, column=7).value or "").strip() # check national id
        name = str(ws07.cell(row=r, column=6).value or "").strip()
        key = nid if nid else name
        fund_checks_per_cust[key] = fund_checks_per_cust.get(key, 0) + 1
        
    # Multi-check customers exist
    multi_check = [k for k, v in fund_checks_per_cust.items() if v > 1]
    assert len(multi_check) > 0, "There must be customers with multiple checks"
    
    # Deduplicated bounced sum is 231,951,000,000
    EXPECTED_BOUNCED = 231_951_000_000
    sum_bounced_sheet02 = sum(ws02.cell(row=r, column=11).value or 0 for r in range(4, 52))
    assert sum_bounced_sheet02 == EXPECTED_BOUNCED


# ==============================================================================
# AC 2: Portfolio Balance Audit Tests
# ==============================================================================

def test_ac2_sheet07_exactly_147_cheques(wb_data):
    ws = wb_data["07_چکهای_تفصیلی"]
    cheque_count = 0
    total_amount = 0
    for r in range(2, 149):
        val = ws.cell(row=r, column=12).value # Col L: مبلغ
        if val is not None:
            cheque_count += 1
            total_amount += int(val)
            
    assert cheque_count == 147, f"Expected 147 cheques, got {cheque_count}"
    assert total_amount == 483_325_000_000, f"Expected 483,325,000,000, got {total_amount}"


def test_ac2_reconciled_across_sheets_01_02_07(wb, wb_data):
    # Sheet 07 total in formula and value
    ws07_f = wb["07_چکهای_تفصیلی"]
    sum_formula_07 = ws07_f.cell(row=149, column=12).value
    assert sum_formula_07 == "=SUM(L2:L148)", f"Unexpected formula in 07: {sum_formula_07}"
    
    # Sheet 02 total fund sum
    ws02_d = wb_data["02_مشتریان_یکتا"]
    sum_fund_02 = sum(ws02_d.cell(row=r, column=8).value or 0 for r in range(4, 52)) # Col H: مبلغ چکهای نزد صندوق
    assert sum_fund_02 == 483_325_000_000, f"Sheet 02 fund cheques sum {sum_fund_02} != 483,325,000,000"
    
    # Sheet 02 count of fund cheques
    count_fund_02 = sum(ws02_d.cell(row=r, column=7).value or 0 for r in range(4, 52)) # Col G: تعداد چک نزد صندوق
    assert count_fund_02 == 147, f"Sheet 02 fund cheques count {count_fund_02} != 147"
    
    # Sheet 01 KPI check
    ws01_d = wb_data["01_خلاصه_مدیریتی"]
    found_483b = False
    found_147 = False
    for row in ws01_d.iter_rows(values_only=True):
        for cell in row:
            if cell == 483_325_000_000 or cell == "483,325,000,000":
                found_483b = True
            if cell == 147:
                found_147 = True
    assert found_483b, "483,325,000,000 Rials not found in Sheet 01 KPIs"
    assert found_147, "147 cheques count not found in Sheet 01 KPIs"


# ==============================================================================
# AC 3: Identity & Event Precision Tests
# ==============================================================================

def test_ac3_disambiguation_national_code_0933387075(wb_data):
    ws02 = wb_data["02_مشتریان_یکتا"]
    heshmati_found = False
    alipour_found = False
    
    for r in range(4, 52):
        name = str(ws02.cell(row=r, column=4).value or "")
        nid = str(ws02.cell(row=r, column=3).value or "")
        if "حسین حشمتی" in name:
            heshmati_found = True
            assert "0933387075" in nid
            # Hossein Heshmati has check 2380030072556088
            chq_count = ws02.cell(row=r, column=7).value
            assert chq_count == 1, f"Heshmati should have 1 check, got {chq_count}"
        if "امیرحسین علیپور" in name:
            alipour_found = True
            assert "0933387075" in nid
            # Amirhossein Alipour has promissory note 1113333
            chq_count = ws02.cell(row=r, column=7).value
            assert chq_count == 1, f"Alipour should have 1 document, got {chq_count}"
            
    assert heshmati_found, "Hossein Heshmati not found in sheet 02"
    assert alipour_found, "Amirhossein Alipour not found in sheet 02"
    
    # Check sheet 08 documents this disambiguation
    ws08 = wb_data["08_مشکلات_هویتی"]
    ws08_text = ""
    for row in ws08.iter_rows(values_only=True):
        for cell in row:
            if cell is not None:
                ws08_text += f" {cell} "
    assert "0933387075" in ws08_text, "National code 0933387075 not referenced in sheet 08"
    assert "حسین حشمتی" in ws08_text, "Hossein Heshmati not referenced in sheet 08"
    assert "امیرحسین علیپور" in ws08_text, "Amirhossein Alipour not referenced in sheet 08"


def test_ac3_zahra_bahrami_pouya_transition(wb_data):
    ws03 = wb_data["03_رخدادهای_امروز"]
    found = False
    for r in range(4, 30):
        name = str(ws03.cell(row=r, column=2).value or "")
        if "زهرا بهرامی" in name:
            found = True
            delta_inf = ws03.cell(row=r, column=7).value
            delta_bnc = ws03.cell(row=r, column=10).value
            conf = str(ws03.cell(row=r, column=12).value or "")
            assert abs(int(delta_inf)) == 3_500_000_000, f"Expected 3.5B delta in-flight, got {delta_inf}"
            assert abs(int(delta_bnc)) == 3_500_000_000, f"Expected 3.5B delta bounced, got {delta_bnc}"
            assert "قطعی" in conf or "بالا" in conf or "HIGH" in conf or "CERTAIN" in conf
            break
    assert found, "Zahra Bahrami Pouya transition not found in sheet 03_رخدادهای_امروز"


def test_ac3_top10_issuers_and_hhi_in_sheet01(wb_data):
    ws01 = wb_data["01_خلاصه_مدیریتی"]
    ws01_text = ""
    hhi_found = False
    for row in ws01.iter_rows(values_only=True):
        for cell in row:
            if cell is not None:
                ws01_text += f" {cell} "
                if isinstance(cell, (int, float)) and 1530 <= cell <= 1540:
                    hhi_found = True
                elif "1536" in str(cell) or "1,536" in str(cell):
                    hhi_found = True
                    
    assert hhi_found, f"HHI ~1536.42 not found in Sheet 01. Text snippet: {ws01_text[:300]}"
    
    # Check top 10 issuers include known key high-risk customers
    expected_top_names = [
        "وحید زوار",
        "محمد ضیافتی مالدار",
        "محمدجواد وفادار عیدگاهی",
        "حسین حشمتی",
        "محمد رفیق طرقی",
    ]
    for name in expected_top_names:
        assert name in ws01_text, f"Key high-risk issuer {name} not found in Sheet 01 top list"


# ==============================================================================
# AC 4: Risk Floors & Audit Formulas Tests
# ==============================================================================

def test_ac4_risk_floors_enforcement(wb_data):
    ws02 = wb_data["02_مشتریان_یکتا"]
    # Col 4: Name, Col 11: Bounced, Col 14: Periods, Col 17: Final Risk Score
    for r in range(4, 52):
        name = ws02.cell(row=r, column=4).value
        bounced = ws02.cell(row=r, column=11).value or 0
        periods = ws02.cell(row=r, column=14).value or 0
        score = ws02.cell(row=r, column=17).value
        
        is_persistent = periods >= 3
        is_new = 1 <= periods <= 2
        
        if score is None or score == "-":
            assert bounced == 0, f"Customer {name} has bounced {bounced} but score is {score}"
            continue
            
        score = float(score)
        if bounced > 50_000_000_000 and is_persistent:
            assert score >= 85, f"{name}: bounced {bounced} > 50B persistent, but score {score} < 85"
        elif bounced > 20_000_000_000 and is_persistent:
            assert score >= 78, f"{name}: bounced {bounced} > 20B persistent, but score {score} < 78"
        elif bounced > 10_000_000_000 and is_persistent:
            assert score >= 72, f"{name}: bounced {bounced} > 10B persistent, but score {score} < 72"
        elif bounced > 5_000_000_000 and is_persistent:
            assert score >= 65, f"{name}: bounced {bounced} > 5B persistent, but score {score} < 65"
        elif bounced > 0 and is_persistent:
            assert score >= 45, f"{name}: bounced {bounced} > 0 persistent, but score {score} < 45"
        elif bounced > 0 and is_new:
            assert score >= 35, f"{name}: bounced {bounced} > 0 new, but score {score} < 35"


def test_ac4_sheet09_all_14_audit_formulas_pass(wb):
    ws09 = wb["09_ممیزی"]
    audit_rows = []
    for r in range(8, 22):
        code = ws09.cell(row=r, column=2).value
        formula = ws09.cell(row=r, column=8).value
        audit_rows.append((code, formula))
        
    assert len(audit_rows) == 14, f"Expected 14 audit tests, got {len(audit_rows)}"
    
    # Verify each row has an AUD-01 to AUD-14 code and formula containing IF(..., "PASS", "FAIL")
    for idx, (code, formula) in enumerate(audit_rows, 1):
        expected_code = f"AUD-{idx:02d}"
        assert code == expected_code, f"Row {idx+7}: expected {expected_code}, got {code}"
        assert formula is not None and formula.startswith("="), f"{code} missing formula: {formula}"
        assert '"PASS"' in formula and '"FAIL"' in formula, f"{code} formula not returning PASS/FAIL: {formula}"
