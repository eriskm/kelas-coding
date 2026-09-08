@echo off
setlocal EnableExtensions EnableDelayedExpansion
title BOSS SF - RUN ONLINE
cd /d "%~dp0"
color 0B

set "CFLARED=%CD%\tools\cloudflared.exe"
set "CLOUDFLARED_CONFIG=%USERPROFILE%\.cloudflared\config.yml"
set "SERVER_PORT=8000"
set "PUBLIC_URL=https://jon.bosssf.my.id"
set /a WAIT_MAX=30

REM ============================================================
REM  1) Cek cloudflared
REM ============================================================
if not exist "%CFLARED%" (
    echo [!] cloudflared.exe tidak ditemukan di tools\cloudflared.exe
    echo     Jalankan setup-online.bat dulu.
    timeout /t 8 /nobreak >nul
    exit /b 1
)

REM ============================================================
REM  2) Start server FastAPI (jika belum running)
REM     Jalankan python venv langsung, tanpa cmd /k, dan
REM     redirect output ke file log agar tidak butuh console.
REM ============================================================
netstat -ano | findstr ":%SERVER_PORT%" | findstr LISTENING >nul 2>nul
if not errorlevel 1 (
    echo [OK] Server FastAPI sudah berjalan di port %SERVER_PORT%.
    goto :start_tunnel
)

echo [*] Menjalankan server FastAPI (port %SERVER_PORT%)...
pushd "%~dp0backend"
start "BOSS SF - Server" /min "%~dp0backend\venv\Scripts\python.exe" -m uvicorn main:app --host 127.0.0.1 --port %SERVER_PORT%
popd
goto :wait_server

REM ============================================================
REM  3) Tunggu server siap
REM ============================================================
:wait_server
set /a tries=0
:wait_loop
set /a tries+=1
if %tries% gtr %WAIT_MAX% goto :server_timeout
netstat -ano | findstr ":%SERVER_PORT%" | findstr LISTENING >nul 2>nul
if not errorlevel 1 goto :server_ok
timeout /t 1 /nobreak >nul
goto :wait_loop

:server_timeout
echo [!] Server tidak siap di port %SERVER_PORT%. Cek jendela "BOSS SF - Server".
timeout /t 8 /nobreak >nul
exit /b 1

:server_ok
echo [OK] Server FastAPI siap.
goto :start_tunnel

REM ============================================================
REM  4) Start cloudflared tunnel (jika belum running)
REM ============================================================
:start_tunnel
tasklist /fi "imagename eq cloudflared.exe" | findstr /i "cloudflared.exe" >nul 2>nul
if not errorlevel 1 (
    echo [OK] cloudflared sudah berjalan.
    goto :finish
)

echo [*] Menjalankan cloudflared tunnel...
pushd "%~dp0tools"
start "BOSS SF - Tunnel" /min "%CFLARED%" tunnel --config "%CLOUDFLARED_CONFIG%" run
popd
goto :finish

REM ============================================================
REM  5) Buka browser & keluar
REM ============================================================
:finish
start "" "%PUBLIC_URL%"
exit /b 0
