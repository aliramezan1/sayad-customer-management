import sqlite3
import pandas as pd

conn = sqlite3.connect('customers.db')
cursor = conn.cursor()

print('=== 📊 آمار کلی پایگاه داده SQLite ===')
total_cheques = cursor.execute('SELECT COUNT(*) FROM cheques').fetchone()[0]
total_inquiries = cursor.execute('SELECT COUNT(*) FROM inquiry_results').fetchone()[0]
success_inquiries = cursor.execute("SELECT COUNT(*) FROM inquiry_results WHERE status='success'").fetchone()[0]
not_found = cursor.execute("SELECT COUNT(*) FROM inquiry_results WHERE status='not_found'").fetchone()[0]
total_customers = cursor.execute("SELECT COUNT(DISTINCT full_name) FROM inquiry_results WHERE full_name IS NOT NULL AND full_name != ''").fetchone()[0]

print(f'تعداد کل رکوردهای چک در دیتابیس: {total_cheques}')
print(f'تعداد استعلام‌های صیادی: {total_inquiries}')
print(f'استعلام‌های موفق (دارای نام تاییدشده بانک مرکزی): {success_inquiries}')
print(f'شناسه‌های یافت‌نشده در سامانه: {not_found}')
print(f'تعداد مشتریان یکتا شناسایی‌شده: {total_customers}')

print('\n=== 👥 فهرست مشتریان شناسایی‌شده، تعداد چک‌ها و مجموع مبالغ ===')
query = '''
SELECT 
    ir.full_name as "نام رسمی مشتری (بانک مرکزی)",
    c.original_name as "نام اولیه در اکسل",
    COUNT(c.id) as "تعداد چک",
    PRINTF("%,d", CAST(SUM(c.amount) AS INT)) as "مجموع مبالغ (ریال)"
FROM inquiry_results ir
JOIN cheques c ON ir.sayadi_id = c.sayadi_id
WHERE ir.full_name IS NOT NULL AND ir.full_name != ''
GROUP BY ir.full_name
ORDER BY COUNT(c.id) DESC, SUM(c.amount) DESC
'''
df = pd.read_sql_query(query, conn)
print(df.to_string(index=False))
