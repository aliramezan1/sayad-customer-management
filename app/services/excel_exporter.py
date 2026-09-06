# -*- coding: utf-8 -*-
"""
Comprehensive Multi-Sheet Excel Exporter for Sayad Customer & Cheque Management System.
Features:
- Sheet 1: Executive Dashboard & Key Metrics Summary (خلاصه داشبورد و شاخص‌های کلیدی)
- Sheet 2: Detailed Cheques & Today's Bank Inquiries (گزارش تفصیلی چک‌ها و استعلام امروز)
- Sheet 3: Customer Credit Analysis & Risk Matrix (تحلیل اعتباری و سلامت مالی مشتریان)
- Full Persian/RTL layout, professional styling, auto-column widths, and formatted monetary values.
"""
import io
import os
import sqlite3
from datetime import datetime
from typing import Optional, Dict, Any, List

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from app.database import get_db
from app.services.pasargad import calculate_days_until_due
from app.services.smart_logger import gregorian_to_jalali
from app.services.risk_engine import calculate_customer_fhs, get_risk_matrix

# Color Palette
NAVY_HEADER_FILL = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
BLUE_SECTION_FILL = PatternFill(start_color="0284C7", end_color="0284C7", fill_type="solid")
SLATE_HEADER_FILL = PatternFill(start_color="334155", end_color="334155", fill_type="solid")
TOTAL_ROW_FILL = PatternFill(start_color="E2E8F0", end_color="E2E8F0", fill_type="solid")
ZEBRA_FILL = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")

WHITE_BOLD_FONT = Font(name="Tahoma", size=11, bold=True, color="FFFFFF")
SECTION_BOLD_FONT = Font(name="Tahoma", size=12, bold=True, color="FFFFFF")
TITLE_FONT = Font(name="Tahoma", size=16, bold=True, color="1E3A8A")
SUBTITLE_FONT = Font(name="Tahoma", size=10, italic=True, color="64748B")
REGULAR_FONT = Font(name="Tahoma", size=10, color="0F172A")
BOLD_FONT = Font(name="Tahoma", size=10, bold=True, color="0F172A")

THIN_BORDER_SIDE = Side(style='thin', color='CBD5E1')
THIN_BORDER = Border(left=THIN_BORDER_SIDE, right=THIN_BORDER_SIDE, top=THIN_BORDER_SIDE, bottom=THIN_BORDER_SIDE)
TOTAL_BORDER = Border(
    left=THIN_BORDER_SIDE, right=THIN_BORDER_SIDE, 
    top=Side(style='thin', color='94A3B8'), 
    bottom=Side(style='double', color='1E293B')
)

ALIGN_CENTER = Alignment(horizontal='center', vertical='center', wrap_text=True)
ALIGN_RIGHT = Alignment(horizontal='right', vertical='center', wrap_text=True)
ALIGN_LEFT = Alignment(horizontal='left', vertical='center')


def _format_jalali_date(date_str: Optional[str]) -> str:
    """Format YYYYMMDD string to YYYY/MM/DD."""
    if not date_str:
        return ""
    s = str(date_str).strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}/{s[4:6]}/{s[6:]}"
    return s


def generate_comprehensive_excel(output_path: Optional[str] = None) -> bytes:
    """
    Generate comprehensive 3-sheet Excel report with current live inquiry data.
    If output_path is provided, writes file to disk. Returns bytes.
    """
    conn = get_db()
    cursor = conn.cursor()

    # 1. Fetch Cheques with Customer, Holder, and Latest Inquiry details
    cursor.execute("""
    SELECT 
        c.id as customer_id,
        c.full_name as customer_name,
        c.national_id as customer_nid,
        c.phone as customer_phone,
        c.credit_color,
        ch.id as cheque_id,
        ch.sayadi_id,
        ch.cheque_number,
        ch.amount,
        ch.cheque_date,
        ch.bank_name,
        h.full_name as holder_name,
        p.in_transit_amount,
        p.cleared_amount,
        p.bounced_amount,
        p.status as inquiry_status,
        p.inquiry_time,
        p.raw_response
    FROM cheques ch
    LEFT JOIN customers c ON ch.customer_id = c.id
    LEFT JOIN holders h ON ch.holder_id = h.id
    LEFT JOIN pasargad_inquiries p ON p.id = (
        SELECT id FROM pasargad_inquiries 
        WHERE sayadi_id = ch.sayadi_id 
        ORDER BY id DESC LIMIT 1
    )
    ORDER BY c.full_name ASC, ch.cheque_date ASC
    """)
    cheques_data = [dict(r) for r in cursor.fetchall()]

    # 2. Fetch Customers list
    cursor.execute("SELECT * FROM customers ORDER BY full_name ASC")
    customers_data = [dict(r) for r in cursor.fetchall()]

    # 3. Fetch Aggregate Stats
    total_customers = len(customers_data)
    total_cheques = len(cheques_data)
    total_amount = sum(float(r["amount"] or 0) for r in cheques_data)
    
    # Live inquiries stats
    total_in_transit = 0.0
    total_cleared = 0.0
    total_bounced = 0.0
    success_count = 0
    unchanged_count = 0
    passed_count = 0
    exempt_count = 0

    for ch in cheques_data:
        sayadi = str(ch["sayadi_id"] or "").strip()
        inq_stat = str(ch.get("inquiry_status") or "").lower()
        d_due = calculate_days_until_due(ch.get("cheque_date"))
        
        in_t = float(ch.get("in_transit_amount") or 0)
        clr = float(ch.get("cleared_amount") or 0)
        bnc = float(ch.get("bounced_amount") or 0)
        
        total_in_transit += in_t
        total_cleared += clr
        total_bounced += bnc

        if len(sayadi) != 16:
            exempt_count += 1
        elif inq_stat == "success":
            success_count += 1
        elif d_due is not None and d_due < 0:
            passed_count += 1
        else:
            unchanged_count += 1

    # Credit colors breakdown
    credit_colors = {}
    for c in customers_data:
        color = c.get("credit_color") or "سفید"
        credit_colors[color] = credit_colors.get(color, 0) + 1

    # Risk matrix and customer scores
    risk_matrix = get_risk_matrix().get("quadrants", {})
    customer_scores = []
    for c in customers_data:
        fhs = calculate_customer_fhs(c["id"])
        customer_scores.append(fhs)

    conn.close()

    # Now create OpenPyXL Workbook
    wb = openpyxl.Workbook()
    wb.remove(wb.active)  # Remove default blank sheet

    now = datetime.now()
    jy, jm, jd = gregorian_to_jalali(now.year, now.month, now.day)
    jalali_today = f"{jy:04d}/{jm:02d}/{jd:02d}"
    time_str = now.strftime("%H:%M:%S")

    # ════════════════════════════════════════════════════════════════
    # 📑 SHEET 1: خلاصه داشبورد و شاخص‌های کلیدی
    # ════════════════════════════════════════════════════════════════
    ws1 = wb.create_sheet(title="خلاصه داشبورد و شاخص‌ها")
    ws1.views.sheetView[0].rightToLeft = True
    ws1.sheet_properties.tabColor = "1E3A8A"

    # Title & Header
    ws1.merge_cells("A1:G1")
    ws1["A1"] = "گزارش جامع وضعیت چک‌ها و استعلام‌های بانک مرکزی و پاسارگاد"
    ws1["A1"].font = TITLE_FONT
    ws1["A1"].alignment = ALIGN_RIGHT

    ws1.merge_cells("A2:G2")
    ws1["A2"] = f"سامانه صیاد پرو ۳.۱ | تاریخ تهیه گزارش: {jalali_today} ساعت {time_str} | منبع داده: درگاه رسمی بانک مرکزی و بانک پاسارگاد"
    ws1["A2"].font = SUBTITLE_FONT
    ws1["A2"].alignment = ALIGN_RIGHT

    # Metric Cards Table
    ws1["A4"] = "شاخص کلیدی"
    ws1["B4"] = "مقدار عددی"
    ws1["C4"] = "واحد"
    ws1["D4"] = "توضیحات و تفکیک"
    
    for col in ["A", "B", "C", "D"]:
        cell = ws1[f"{col}4"]
        cell.font = WHITE_BOLD_FONT
        cell.fill = NAVY_HEADER_FILL
        cell.alignment = ALIGN_CENTER
        cell.border = THIN_BORDER

    metrics = [
        ("تعداد کل مشتریان طرف حساب", total_customers, "نفر", "مشتریان فعال دارای تعهد و پرونده اعتباری"),
        ("تعداد کل اسناد و چک‌های صندوق", total_cheques, "فقره", f"{total_cheques - exempt_count} چک صیادی + {exempt_count} سند سفته/معاف"),
        ("مجموع ارزش ریالی چک‌های صندوق", total_amount, "ریال", f"{total_amount / 10_000_000:,.0f} تومان (حجم تعهدات نزد صندوق)"),
        ("مجموع مبلغ چک‌های در راه استعلام‌شده", total_in_transit, "ریال", f"{total_in_transit / 10_000_000:,.0f} تومان (تعهدات صادرکنندگان در شبکه بانکی)"),
        ("مجموع مبالغ رفع سوءاثر شده صادرکنندگان", total_cleared, "ریال", f"{total_cleared / 10_000_000:,.0f} تومان (سابقه تسویه موفق)"),
        ("مجموع مبالغ چک‌های برگشتی صادرکنندگان", total_bounced, "ریال", f"{total_bounced / 10_000_000:,.0f} تومان (چک‌های برگشتی ثبت‌شده بانک مرکزی)"),
        ("استعلام‌های موفق لحظه‌ای درگاه", success_count, "فقره", "استعلام مستقیم موفق از وب‌سرویس پاسارگاد امروز"),
        ("چک‌های با حفظ سابقه معتبر", unchanged_count, "فقره", "حفظ ارقام معتبر پیشین بر اساس پایگاه داده"),
        ("چک‌های تسویه یا سررسید گذشته", passed_count, "فقره", "سررسید گذشته و تسویه‌شده خارج از کارتابل"),
        ("اسناد معاف از استعلام صیادی", exempt_count, "فقره", "سفته‌ها و اسناد ضمانتی فاقد شناسه ۱۶ رقمی صیاد"),
    ]

    for idx, (title, val, unit, desc) in enumerate(metrics, start=5):
        fill = ZEBRA_FILL if idx % 2 == 0 else PatternFill(fill_type=None)
        
        ws1[f"A{idx}"] = title
        ws1[f"A{idx}"].font = BOLD_FONT
        ws1[f"A{idx}"].alignment = ALIGN_RIGHT
        ws1[f"A{idx}"].fill = fill
        ws1[f"A{idx}"].border = THIN_BORDER

        ws1[f"B{idx}"] = val
        ws1[f"B{idx}"].font = BOLD_FONT
        ws1[f"B{idx}"].alignment = ALIGN_CENTER
        ws1[f"B{idx}"].fill = fill
        ws1[f"B{idx}"].border = THIN_BORDER
        if isinstance(val, (int, float)) and val > 1000:
            ws1[f"B{idx}"].number_format = "#,##0"

        ws1[f"C{idx}"] = unit
        ws1[f"C{idx}"].font = REGULAR_FONT
        ws1[f"C{idx}"].alignment = ALIGN_CENTER
        ws1[f"C{idx}"].fill = fill
        ws1[f"C{idx}"].border = THIN_BORDER

        ws1[f"D{idx}"] = desc
        ws1[f"D{idx}"].font = REGULAR_FONT
        ws1[f"D{idx}"].alignment = ALIGN_RIGHT
        ws1[f"D{idx}"].fill = fill
        ws1[f"D{idx}"].border = THIN_BORDER

    # Section 2: Credit Color Distribution
    r_start = len(metrics) + 6
    ws1.merge_cells(f"A{r_start}:D{r_start}")
    ws1[f"A{r_start}"] = "توزیع وضعیت رنگ اعتباری بانک مرکزی (CBI)"
    ws1[f"A{r_start}"].font = SECTION_BOLD_FONT
    ws1[f"A{r_start}"].fill = BLUE_SECTION_FILL
    ws1[f"A{r_start}"].alignment = ALIGN_RIGHT

    ws1[f"A{r_start+1}"] = "رنگ اعتباری"
    ws1[f"B{r_start+1}"] = "تعداد مشتریان"
    ws1[f"C{r_start+1}"] = "درصد از کل"
    ws1[f"D{r_start+1}"] = "ارزیابی ریسک"

    for col in ["A", "B", "C", "D"]:
        c_cell = ws1[f"{col}{r_start+1}"]
        c_cell.font = WHITE_BOLD_FONT
        c_cell.fill = SLATE_HEADER_FILL
        c_cell.alignment = ALIGN_CENTER
        c_cell.border = THIN_BORDER

    color_rows = [
        ("سفید (خوش‌حساب بدون برگشتی)", credit_colors.get("سفید", 0), "کمترین ریسک اعتباری، فاقد هرگونه سوءاثر در سیستم بانکی"),
        ("قرمز (دارای چک برگشتی فعال)", credit_colors.get("قرمز", 0), "ریسک بالا؛ دارای چک برگشتی رفع سوءاثر نشده در شبکه بانکی"),
        ("قهوه‌ای (سابقه چک‌های متعدد)", credit_colors.get("قهوه ای", 0) + credit_colors.get("قهوه‌ای", 0), "هشدار؛ سابقه چک‌های برگشتی مکرر یا حجم بالای نکول"),
    ]

    for c_idx, (c_label, count, c_desc) in enumerate(color_rows, start=r_start+2):
        pct = (count / total_customers) if total_customers else 0
        c_fill = ZEBRA_FILL if c_idx % 2 == 0 else PatternFill(fill_type=None)

        ws1[f"A{c_idx}"] = c_label
        ws1[f"A{c_idx}"].font = BOLD_FONT
        ws1[f"A{c_idx}"].alignment = ALIGN_RIGHT
        ws1[f"A{c_idx}"].fill = c_fill
        ws1[f"A{c_idx}"].border = THIN_BORDER

        ws1[f"B{c_idx}"] = count
        ws1[f"B{c_idx}"].font = BOLD_FONT
        ws1[f"B{c_idx}"].alignment = ALIGN_CENTER
        ws1[f"B{c_idx}"].fill = c_fill
        ws1[f"B{c_idx}"].border = THIN_BORDER

        ws1[f"C{c_idx}"] = pct
        ws1[f"C{c_idx}"].font = REGULAR_FONT
        ws1[f"C{c_idx}"].alignment = ALIGN_CENTER
        ws1[f"C{c_idx}"].fill = c_fill
        ws1[f"C{c_idx}"].border = THIN_BORDER
        ws1[f"C{c_idx}"].number_format = "0.0%"

        ws1[f"D{c_idx}"] = c_desc
        ws1[f"D{c_idx}"].font = REGULAR_FONT
        ws1[f"D{c_idx}"].alignment = ALIGN_RIGHT
        ws1[f"D{c_idx}"].fill = c_fill
        ws1[f"D{c_idx}"].border = THIN_BORDER

    # Section 3: Risk Matrix Quadrants
    rm_start = r_start + len(color_rows) + 3
    ws1.merge_cells(f"A{rm_start}:D{rm_start}")
    ws1[f"A{rm_start}"] = "ماتریس دوبعدی تحلیل ریسک اعتباری (Fintech Risk Matrix)"
    ws1[f"A{rm_start}"].font = SECTION_BOLD_FONT
    ws1[f"A{rm_start}"].fill = BLUE_SECTION_FILL
    ws1[f"A{rm_start}"].alignment = ALIGN_RIGHT

    ws1[f"A{rm_start+1}"] = "رده ریسک مشتریان"
    ws1[f"B{rm_start+1}"] = "تعداد مشتری"
    ws1[f"C{rm_start+1}"] = "مجموع مبالغ تعهدات (ریال)"
    ws1[f"D{rm_start+1}"] = "راهبرد پیشنهادی وصول و تعامل"

    for col in ["A", "B", "C", "D"]:
        c_cell = ws1[f"{col}{rm_start+1}"]
        c_cell.font = WHITE_BOLD_FONT
        c_cell.fill = SLATE_HEADER_FILL
        c_cell.alignment = ALIGN_CENTER
        c_cell.border = THIN_BORDER

    quadrants = [
        ("ستاره‌ها (پرتراکنش و کم‌ریسک)", len(risk_matrix["stars"]["customers"]), risk_matrix["stars"]["total_amount"], "توسعه همکاری و اعطای حداکثر تسهیلات و اعتبار تجاری"),
        ("فرصت‌ها (کم‌تراکنش و کم‌ریسک)", len(risk_matrix["opportunities"]["customers"]), risk_matrix["opportunities"]["total_amount"], "افزایش حجم تراکنش و تشویق به همکاری بیشتر"),
        ("تحت نظر (پرریسک با مبالغ خرد)", len(risk_matrix["watchlist"]["customers"]), risk_matrix["watchlist"]["total_amount"], "کنترل مستمر و پایش وصولی‌ها قبل از سررسید"),
        ("بحرانی (پرریسک با تعهدات سنگین)", len(risk_matrix["critical"]["customers"]), risk_matrix["critical"]["total_amount"], "اولویت فوری وصول؛ توقف پذیرش چک جدید و پیگیری حقوقی"),
    ]

    for q_idx, (q_label, q_cnt, q_amt, q_strat) in enumerate(quadrants, start=rm_start+2):
        q_fill = ZEBRA_FILL if q_idx % 2 == 0 else PatternFill(fill_type=None)

        ws1[f"A{q_idx}"] = q_label
        ws1[f"A{q_idx}"].font = BOLD_FONT
        ws1[f"A{q_idx}"].alignment = ALIGN_RIGHT
        ws1[f"A{q_idx}"].fill = q_fill
        ws1[f"A{q_idx}"].border = THIN_BORDER

        ws1[f"B{q_idx}"] = q_cnt
        ws1[f"B{q_idx}"].font = BOLD_FONT
        ws1[f"B{q_idx}"].alignment = ALIGN_CENTER
        ws1[f"B{q_idx}"].fill = q_fill
        ws1[f"B{q_idx}"].border = THIN_BORDER

        ws1[f"C{q_idx}"] = q_amt
        ws1[f"C{q_idx}"].font = BOLD_FONT
        ws1[f"C{q_idx}"].alignment = ALIGN_CENTER
        ws1[f"C{q_idx}"].fill = q_fill
        ws1[f"C{q_idx}"].border = THIN_BORDER
        ws1[f"C{q_idx}"].number_format = "#,##0"

        ws1[f"D{q_idx}"] = q_strat
        ws1[f"D{q_idx}"].font = REGULAR_FONT
        ws1[f"D{q_idx}"].alignment = ALIGN_RIGHT
        ws1[f"D{q_idx}"].fill = q_fill
        ws1[f"D{q_idx}"].border = THIN_BORDER


    # ════════════════════════════════════════════════════════════════
    # 📑 SHEET 2: گزارش تفصیلی چک‌ها و استعلام امروز
    # ════════════════════════════════════════════════════════════════
    ws2 = wb.create_sheet(title="گزارش تفصیلی چک‌ها و استعلام")
    ws2.views.sheetView[0].rightToLeft = True
    ws2.sheet_properties.tabColor = "0284C7"

    cheque_headers = [
        "ردیف",
        "نام مشتری (صادرکننده)",
        "کدملی صادرکننده",
        "رنگ اعتباری (CBI)",
        "شناسه ۱۶ رقمی صیادی",
        "شماره چک",
        "مبلغ چک (ریال)",
        "تاریخ سررسید",
        "وضعیت موعد",
        "بانک صادرکننده",
        "دارنده چک در صندوق (هولدر)",
        "وضعیت استعلام امروز",
        "مبلغ چک در راه (ریال)",
        "مبلغ رفع سوءاثر (ریال)",
        "مبلغ برگشتی (ریال)",
        "زمان آخرین استعلام",
        "پیام تشخیصی درگاه"
    ]

    for col_idx, h_text in enumerate(cheque_headers, start=1):
        cell = ws2.cell(row=1, column=col_idx, value=h_text)
        cell.font = WHITE_BOLD_FONT
        cell.fill = NAVY_HEADER_FILL
        cell.alignment = ALIGN_CENTER
        cell.border = THIN_BORDER

    for row_idx, ch in enumerate(cheques_data, start=2):
        r_fill = ZEBRA_FILL if row_idx % 2 == 0 else PatternFill(fill_type=None)
        
        sayadi = str(ch.get("sayadi_id") or "").strip()
        ch_date = _format_jalali_date(ch.get("cheque_date"))
        days_due = calculate_days_until_due(ch.get("cheque_date"))
        inq_status = str(ch.get("inquiry_status") or "").lower()

        # Status translation
        if len(sayadi) != 16:
            status_text = "سند سفته / فاقد صیاد (معاف)"
            msg_text = "سند تضمینی یا سفته فاقد شناسه ۱۶ رقمی صیاد"
        elif inq_status == "success":
            status_text = "موفق (درگاه زنده)"
            msg_text = "استعلام زنده از درگاه پاسارگاد با موفقیت ثبت شد"
        elif days_due is not None and days_due < 0:
            status_text = "سررسید گذشته / تسویه"
            msg_text = f"سررسید چک در تاریخ {ch_date} منقضی شده و از کارتابل خارج است"
        else:
            status_text = "حفظ تاریخچه معتبر"
            msg_text = "اطلاعات معتبر آخرین استعلام موفق حفظ شد"

        # Due status text
        if days_due is None:
            due_text = "نامشخص"
        elif days_due < 0:
            due_text = f"منقضی ({abs(days_due)} روز گذشته)"
        elif days_due == 0:
            due_text = "سررسید امروز"
        elif days_due <= 7:
            due_text = f"سررسید نزدیک ({days_due} روز مانده)"
        else:
            due_text = f"{days_due} روز مانده"

        amount_val = float(ch.get("amount") or 0)
        in_t_val = float(ch.get("in_transit_amount") or 0)
        clr_val = float(ch.get("cleared_amount") or 0)
        bnc_val = float(ch.get("bounced_amount") or 0)

        row_values = [
            row_idx - 1,
            ch.get("customer_name") or "",
            ch.get("customer_nid") or "",
            ch.get("credit_color") or "سفید",
            sayadi,
            ch.get("cheque_number") or "",
            amount_val,
            ch_date,
            due_text,
            ch.get("bank_name") or "",
            ch.get("holder_name") or "",
            status_text,
            in_t_val,
            clr_val,
            bnc_val,
            ch.get("inquiry_time") or "",
            msg_text
        ]

        for col_idx, val in enumerate(row_values, start=1):
            cell = ws2.cell(row=row_idx, column=col_idx, value=val)
            cell.font = REGULAR_FONT
            cell.fill = r_fill
            cell.border = THIN_BORDER
            
            # Alignments & formats
            if col_idx in (1, 3, 5, 6, 8, 9, 16):
                cell.alignment = ALIGN_CENTER
            elif col_idx in (7, 13, 14, 15):
                cell.alignment = ALIGN_CENTER
                cell.number_format = "#,##0"
                cell.font = BOLD_FONT
            else:
                cell.alignment = ALIGN_RIGHT

            # Highlight specific columns
            if col_idx == 4:  # Credit color
                c_val = str(val).strip()
                if "قرمز" in c_val:
                    cell.fill = PatternFill(start_color="FEE2E2", end_color="FEE2E2", fill_type="solid")
                    cell.font = Font(name="Tahoma", size=10, bold=True, color="B91C1C")
                elif "سفید" in c_val:
                    cell.fill = PatternFill(start_color="DCFCE7", end_color="DCFCE7", fill_type="solid")
                    cell.font = Font(name="Tahoma", size=10, color="15803D")

    # Add Summary / Total Row at the bottom
    tot_row = len(cheques_data) + 2
    ws2.cell(row=tot_row, column=1, value="مجموع")
    ws2.cell(row=tot_row, column=1).font = WHITE_BOLD_FONT
    ws2.cell(row=tot_row, column=1).fill = NAVY_HEADER_FILL
    ws2.cell(row=tot_row, column=1).alignment = ALIGN_CENTER
    ws2.cell(row=tot_row, column=1).border = TOTAL_BORDER

    for c_i in range(2, len(cheque_headers) + 1):
        cell = ws2.cell(row=tot_row, column=c_i)
        cell.fill = TOTAL_ROW_FILL
        cell.border = TOTAL_BORDER
        cell.font = BOLD_FONT

    # Sum formulas
    col_letter_amt = get_column_letter(7)
    ws2.cell(row=tot_row, column=7, value=f"=SUM({col_letter_amt}2:{col_letter_amt}{tot_row-1})")
    ws2.cell(row=tot_row, column=7).number_format = "#,##0"
    ws2.cell(row=tot_row, column=7).alignment = ALIGN_CENTER

    col_letter_int = get_column_letter(13)
    ws2.cell(row=tot_row, column=13, value=f"=SUM({col_letter_int}2:{col_letter_int}{tot_row-1})")
    ws2.cell(row=tot_row, column=13).number_format = "#,##0"
    ws2.cell(row=tot_row, column=13).alignment = ALIGN_CENTER

    col_letter_clr = get_column_letter(14)
    ws2.cell(row=tot_row, column=14, value=f"=SUM({col_letter_clr}2:{col_letter_clr}{tot_row-1})")
    ws2.cell(row=tot_row, column=14).number_format = "#,##0"
    ws2.cell(row=tot_row, column=14).alignment = ALIGN_CENTER

    col_letter_bnc = get_column_letter(15)
    ws2.cell(row=tot_row, column=15, value=f"=SUM({col_letter_bnc}2:{col_letter_bnc}{tot_row-1})")
    ws2.cell(row=tot_row, column=15).number_format = "#,##0"
    ws2.cell(row=tot_row, column=15).alignment = ALIGN_CENTER


    # ════════════════════════════════════════════════════════════════
    # 📑 SHEET 3: تحلیل اعتباری و سلامت مالی مشتریان
    # ════════════════════════════════════════════════════════════════
    ws3 = wb.create_sheet(title="تحلیل اعتباری و سلامت مشتریان")
    ws3.views.sheetView[0].rightToLeft = True
    ws3.sheet_properties.tabColor = "10B981"

    cust_headers = [
        "ردیف",
        "نام و نام خانوادگی مشتری",
        "کدملی",
        "رتبه اعتباری بانک مرکزی",
        "نمره سلامت مالی FHS (۰-۱۰۰)",
        "سطح سلامت مالی",
        "رده در ماتریس ریسک",
        "تعداد چک در صندوق",
        "مجموع تعهدات به صندوق (ریال)",
        "مبلغ چک‌های در راه بانکی (ریال)",
        "مبلغ چک‌های برگشتی بانکی (ریال)",
        "توصیه هوش مالی سیستم"
    ]

    for col_idx, h_text in enumerate(cust_headers, start=1):
        cell = ws3.cell(row=1, column=col_idx, value=h_text)
        cell.font = WHITE_BOLD_FONT
        cell.fill = NAVY_HEADER_FILL
        cell.alignment = ALIGN_CENTER
        cell.border = THIN_BORDER

    # Map customer ID to risk quadrant
    customer_quadrant_map = {}
    for q_key, q_data in risk_matrix.items():
        q_name = q_data.get("title") or q_key
        for cust_item in q_data.get("customers", []):
            cid = cust_item.get("customer_id") or cust_item.get("id")
            if cid:
                customer_quadrant_map[cid] = q_name

    for row_idx, fhs in enumerate(customer_scores, start=2):
        r_fill = ZEBRA_FILL if row_idx % 2 == 0 else PatternFill(fill_type=None)
        c_id = fhs["customer_id"]
        q_name = customer_quadrant_map.get(c_id, "عادی")
        factors = fhs.get("factors", {})

        row_vals = [
            row_idx - 1,
            fhs.get("full_name") or "",
            fhs.get("national_id") or "",
            fhs.get("cbi_rating") or "سفید",
            fhs.get("fhs_score", 0),
            fhs.get("level") or "متوسط",
            q_name,
            factors.get("total_cheques", 0),
            factors.get("total_amount", 0),
            factors.get("in_transit_amount", 0),
            factors.get("bounced_amount", 0),
            fhs.get("recommendation") or ""
        ]

        for col_idx, val in enumerate(row_vals, start=1):
            cell = ws3.cell(row=row_idx, column=col_idx, value=val)
            cell.font = REGULAR_FONT
            cell.fill = r_fill
            cell.border = THIN_BORDER

            if col_idx in (1, 3, 5, 6, 7, 8):
                cell.alignment = ALIGN_CENTER
            elif col_idx in (9, 10, 11):
                cell.alignment = ALIGN_CENTER
                cell.number_format = "#,##0"
                cell.font = BOLD_FONT
            else:
                cell.alignment = ALIGN_RIGHT

            # Highlight FHS level
            if col_idx == 6:
                lvl = str(val)
                if "عالی" in lvl or "خوب" in lvl:
                    cell.fill = PatternFill(start_color="DCFCE7", end_color="DCFCE7", fill_type="solid")
                    cell.font = Font(name="Tahoma", size=10, bold=True, color="15803D")
                elif "پرخطر" in lvl:
                    cell.fill = PatternFill(start_color="FEE2E2", end_color="FEE2E2", fill_type="solid")
                    cell.font = Font(name="Tahoma", size=10, bold=True, color="B91C1C")

    # Add Summary Row to Sheet 3
    tot_c_row = len(customer_scores) + 2
    ws3.cell(row=tot_c_row, column=1, value="مجموع")
    ws3.cell(row=tot_c_row, column=1).font = WHITE_BOLD_FONT
    ws3.cell(row=tot_c_row, column=1).fill = NAVY_HEADER_FILL
    ws3.cell(row=tot_c_row, column=1).alignment = ALIGN_CENTER
    ws3.cell(row=tot_c_row, column=1).border = TOTAL_BORDER

    for c_i in range(2, len(cust_headers) + 1):
        cell = ws3.cell(row=tot_c_row, column=c_i)
        cell.fill = TOTAL_ROW_FILL
        cell.border = TOTAL_BORDER
        cell.font = BOLD_FONT

    col_let_c_chq = get_column_letter(8)
    ws3.cell(row=tot_c_row, column=8, value=f"=SUM({col_let_c_chq}2:{col_let_c_chq}{tot_c_row-1})")
    ws3.cell(row=tot_c_row, column=8).alignment = ALIGN_CENTER

    col_let_c_amt = get_column_letter(9)
    ws3.cell(row=tot_c_row, column=9, value=f"=SUM({col_let_c_amt}2:{col_let_c_amt}{tot_c_row-1})")
    ws3.cell(row=tot_c_row, column=9).number_format = "#,##0"
    ws3.cell(row=tot_c_row, column=9).alignment = ALIGN_CENTER

    col_let_c_int = get_column_letter(10)
    ws3.cell(row=tot_c_row, column=10, value=f"=SUM({col_let_c_int}2:{col_let_c_int}{tot_c_row-1})")
    ws3.cell(row=tot_c_row, column=10).number_format = "#,##0"
    ws3.cell(row=tot_c_row, column=10).alignment = ALIGN_CENTER

    col_let_c_bnc = get_column_letter(11)
    ws3.cell(row=tot_c_row, column=11, value=f"=SUM({col_let_c_bnc}2:{col_let_c_bnc}{tot_c_row-1})")
    ws3.cell(row=tot_c_row, column=11).number_format = "#,##0"
    ws3.cell(row=tot_c_row, column=11).alignment = ALIGN_CENTER

    # ════════════════════════════════════════════════════════════════
    # 📐 Auto-Fit Column Widths for all Sheets
    # ════════════════════════════════════════════════════════════════
    for ws in [ws1, ws2, ws3]:
        for col in ws.columns:
            max_len = 0
            col_letter = get_column_letter(col[0].column)
            for cell in col:
                val_str = str(cell.value or "")
                if val_str.startswith("="):
                    val_str = "123,456,789,000"
                # Persian characters width approximation
                cell_len = len(val_str)
                if cell_len > max_len:
                    max_len = cell_len
            ws.column_dimensions[col_letter].width = max(max_len + 4, 12)

    # Save to memory and optionally to file
    buffer = io.BytesIO()
    wb.save(buffer)
    excel_bytes = buffer.getvalue()

    if output_path:
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(excel_bytes)

    return excel_bytes
