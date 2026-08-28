@echo off
chcp 65001 > nul
title سامانه جامع صیاد پرو
cd /d "C:\Users\HP\Desktop\نام و نام خانوادگی مشتریان"

echo ====================================================================
echo   سامانه جامع صیاد پرو (نسخه ۲.۰)
echo   اتصال مستقیم به درگاه بانک مرکزی (CBI) و بانک پاسارگاد (vBank)
echo ====================================================================
echo.
echo در حال آزادسازی پورت و راه‌اندازی سرور هوشمند...

for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8000" ^| findstr "LISTENING"') do taskkill /f /pid %%a > nul 2>&1

echo در حال باز کردن صفحه سامانه در مرورگر شما...
echo.
timeout /t 1 > nul
start http://127.0.0.1:8000

echo سرور هوشمند فعال شد. این پنجره مشکی را تا پایان کار نبندید.
echo.
"C:\Users\HP\AppData\Local\Programs\Python\Python312\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
pause
