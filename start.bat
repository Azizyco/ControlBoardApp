@echo off
setlocal
title Soundboard Pentas - server
cd /d "%~dp0"

if "%SOUNDBOARD_PORT%"=="" set "SOUNDBOARD_PORT=8765"

rem ---- 1. Cari Python -------------------------------------------------------
set "PY="
py -3 --version >nul 2>&1 && set "PY=py -3"
if not defined PY (
    python --version >nul 2>&1 && set "PY=python"
)
if not defined PY goto :nopython

rem ---- 2. Pasang Flask kalau belum ada --------------------------------------
%PY% -c "import flask" >nul 2>&1
if not errorlevel 1 goto :run

echo.
echo  Memasang kebutuhan program (Flask). Ini hanya sekali...
echo.
if exist "wheels\" (
    rem Tanpa internet: pakai file paket yang sudah diunduh ke folder wheels\
    %PY% -m pip install --disable-pip-version-check --no-index --find-links wheels -r requirements.txt
) else (
    %PY% -m pip install --disable-pip-version-check -r requirements.txt
)
%PY% -c "import flask" >nul 2>&1
if not errorlevel 1 goto :run
rem Coba sekali lagi untuk akun ini saja (kalau Python dipasang untuk semua pengguna)
if exist "wheels\" (
    %PY% -m pip install --disable-pip-version-check --user --no-index --find-links wheels -r requirements.txt
) else (
    %PY% -m pip install --disable-pip-version-check --user -r requirements.txt
)
%PY% -c "import flask" >nul 2>&1
if errorlevel 1 goto :nopip

rem ---- 3. Jalankan server, browser dibuka otomatis setelah server siap -------
:run
%PY% app.py --buka --port %SOUNDBOARD_PORT%
if errorlevel 1 (
    echo.
    echo  Server berhenti karena ada masalah. Baca pesan di atas.
    echo.
    pause
)
exit /b

:nopython
echo.
echo  ================================================================
echo   PYTHON BELUM TERPASANG di laptop ini.
echo.
echo   Cara memasang:
echo   1. Buka https://www.python.org/downloads/ lalu unduh Python 3
echo      (atau pasang "Python 3.12" dari Microsoft Store).
echo   2. Saat memasang, CENTANG "Add python.exe to PATH".
echo   3. Setelah selesai, klik dua kali start.bat lagi.
echo  ================================================================
echo.
pause
exit /b 1

:nopip
echo.
echo  ================================================================
echo   GAGAL MEMASANG FLASK.
echo.
echo   Biasanya karena laptop belum tersambung ke internet.
echo   Sambungkan ke internet sekali saja, lalu klik dua kali start.bat lagi.
echo   Setelah terpasang, soundboard bisa dipakai tanpa internet.
echo  ================================================================
echo.
pause
exit /b 1
