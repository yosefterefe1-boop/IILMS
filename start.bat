@echo off
title IILMS — Starting...

echo ============================================
echo   IILMS - Inventory Management System
echo ============================================
echo.

echo [1/3] Opening firewall port 5000...
netsh advfirewall firewall delete rule name="Flask 5000" >nul 2>&1
netsh advfirewall firewall add rule name="Flask 5000" dir=in action=allow protocol=TCP localport=5000 >nul 2>&1
echo     Done.

echo [2/3] Installing dependencies...
pip install -r requirements.txt --quiet
echo     Done.

echo [3/3] Starting server...
echo.
echo ============================================
echo   Open your browser and go to:
echo   http://127.0.0.1:5000
echo.
echo   On phone (same WiFi):
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4 Address"') do (
    set IP=%%a
    goto :found
)
:found
set IP=%IP: =%
echo   http://%IP%:5000
echo ============================================
echo.
python app.py
pause
