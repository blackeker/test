@echo off
cd /d "%~dp0"
title Wi-Fi Dosya Aktarim Sunucusu

echo =======================================================
echo   Wi-Fi Dosya Aktarim Sunucusu Baslatiliyor...
echo =======================================================
echo.

where python >nul 2>&1
if %errorlevel% equ 0 (
    python -u file_server.py
    goto :done
)

where py >nul 2>&1
if %errorlevel% equ 0 (
    py -u file_server.py
    goto :done
)

echo [HATA] Bilgisayarda Python bulunamadi!
echo Lutfen python.org adresinden Python yukleyin.
echo.

:done
if %errorlevel% neq 0 (
    echo.
    echo [BILGI] Sunucu kapandi veya bir hata meydana geldi.
)
echo.
pause
