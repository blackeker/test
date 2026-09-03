@echo off
cd /d "%~dp0"
title Windows Guvenlik Duvari Izni

:: Yonetici yetkisi kontrolu ve otomatik yukseltme
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo Yonetici yetkisi aliniyor...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

echo ============================================================
echo   Dosya Aktarim Sunucusu icin Guvenlik Duvari Izni Aciliyor
echo ============================================================
echo.
netsh advfirewall firewall add rule name="WiFi Dosya Sunucusu (Port 8000)" dir=in action=allow protocol=TCP localport=8000
echo.
echo ============================================================
echo [BASARILI] Port 8000 izni basariyla tanimlandi!
echo ============================================================
echo.
pause
