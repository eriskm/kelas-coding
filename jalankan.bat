@echo off
title BOSS SF - Service System
cd /d "%~dp0"
color 0B

echo ================================================
echo   BOSS SF - Service System
echo   POS & Service Management Toko Servis HP
echo ================================================
echo.

REM ---------- Cek Python ----------
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [!] Python tidak ditemukan. Install Python 3.9+ dulu.
    pause
    exit /b 1
)

REM ---------- Cek dan install dependencies ----------
cd backend
if exist venv (
    call venv\Scripts\activate.bat
) else (
    echo [*] Membuat virtual environment...
    python -m venv venv
    call venv\Scripts\activate.bat
)

echo [*] Memeriksa dependencies...
python -c "import fastapi, sqlalchemy" >nul 2>nul
if %errorlevel% neq 0 (
    echo [*] Menginstall dependencies (sekali saja)...
    pip install -r requirements.txt >nul 2>nul
    if %errorlevel% neq 0 (
        echo [!] Gagal install dependencies. Coba jalankan manual:
        echo     pip install -r requirements.txt
        pause
        exit /b 1
    )
    echo [OK] Dependencies terinstall.
)

REM ---------- Seed database ----------
echo [*] Menyiapkan database...
python seed.py

REM ---------- Jalankan server ----------
echo.
echo [*] Starting server di http://127.0.0.1:8000
echo.
start "" http://127.0.0.1:8000/static/index.html
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload

pause
