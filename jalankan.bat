@echo off
setlocal
title BOSS SF - Service System
cd /d "%~dp0"
color 0B

echo ================================================
echo   BOSS SF - Service System
echo   POS ^& Service Management Toko Servis HP
echo ================================================
echo.

REM ---------- Cek Python ----------
where python >nul 2>nul
if errorlevel 1 goto :nopython
goto :py_ok

:nopython
echo [!] Python tidak ditemukan. Install Python 3.9+ dulu.
pause
exit /b 1

:py_ok
REM ---------- Cek dan install dependencies ----------
cd backend
if exist venv goto :have_venv

echo [*] Membuat virtual environment...
python -m venv venv
if errorlevel 1 goto :venv_fail
call venv\Scripts\activate.bat
if errorlevel 1 goto :venv_fail
goto :check_deps

:venv_fail
echo [!] Gagal membuat/mengaktifkan virtual environment.
pause
exit /b 1

:have_venv
call venv\Scripts\activate.bat

:check_deps
echo [*] Memeriksa dependencies...
python -c "import fastapi, sqlalchemy" >nul 2>nul
if errorlevel 1 goto :install_deps
goto :seed

:install_deps
echo [*] Menginstall dependencies (sekali saja)...
pip install -r requirements.txt
if errorlevel 1 goto :dep_fail
echo [OK] Dependencies terinstall.
goto :seed

:dep_fail
echo.
echo [!] Gagal install dependencies.
echo     Coba jalankan manual: pip install -r requirements.txt
pause
exit /b 1

:seed
REM ---------- Seed database ----------
echo [*] Menyiapkan database...
python seed.py
if errorlevel 1 goto :seed_fail
goto :run

:seed_fail
echo [!] Gagal menjalankan seed database.
pause
exit /b 1

:run
REM ---------- Jalankan server ----------
echo.
:CONNECT
echo [*] Menyiapkan akses publik (LAN)...
set "HOST=0.0.0.0"
set "PORT=8000"

REM Tampilkan alamat lokal agar bisa dibuka dari HP
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /i "IPv4"') do set "LOCAL_IP=%%a"
set "LOCAL_IP=%LOCAL_IP: =%"

echo.
echo ================================================================
echo   SERVER SEDANG BERJALAN
echo ----------------------------------------------------------------
echo   Dari laptop  : http://127.0.0.1:%PORT%/static/index.html
echo   Dari HP      : http://%LOCAL_IP%:%PORT%/static/index.html
echo.
echo   [Gunakan alamat "Dari HP" di browser smartphone]
echo   [Pastikan HP dan laptop terhubung WiFi/AP yang sama]
echo ================================================================
echo.
start "" "http://%LOCAL_IP%:%PORT%/static/index.html"
python -m uvicorn main:app --host %HOST% --port %PORT% --reload

echo.
echo [!] Server berhenti. Tekan tombol apapun untuk restart...
pause >nul
goto CONNECT
