@echo off
setlocal EnableExtensions
title BOSS SF - MATIKAN SEMUA
cd /d "%~dp0"
color 0C

echo ================================================
echo   BOSS SF - Matikan Server + Tunnel
echo ================================================
echo.

REM ---------- 1) Matikan cloudflared (tunnel) ----------
echo [*] Mematikan cloudflared (tunnel)...
taskkill /FI "IMAGENAME eq cloudflared.exe" /F >nul 2>nul
if errorlevel 1 (
    echo     - cloudflared tidak ditemukan / sudah mati.
) else (
    echo     [OK] cloudflared dimatikan.
)

REM ---------- 2) Matikan server FastAPI di port 8000 ----------
set "SERVER_PORT=8000"
echo [*] Mematikan server FastAPI (port %SERVER_PORT%)...
netstat -ano | findstr ":%SERVER_PORT%" | findstr LISTENING >nul 2>nul
if errorlevel 1 (
    echo     - Server di port %SERVER_PORT% tidak ditemukan / sudah mati.
    goto :finish
)

rem Kumpulkan PID yang memegang port 8000
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%SERVER_PORT%" ^| findstr LISTENING') do (
    echo     [OK] Menghentikan proses PID %%a...
    taskkill /PID %%a /F >nul 2>nul
)

REM Tutup jendela cmd server & tunnel (by title)
echo [*] Menutup jendela cmd Server & Tunnel...
taskkill /FI "WINDOWTITLE eq BOSS SF - Server*" /F >nul 2>nul
taskkill /FI "WINDOWTITLE eq BOSS SF - Tunnel*" /F >nul 2>nul

:finish
echo.
echo ================================================
echo   SELESAI. Semua sudah dimatikan.
echo   Akses lokal/public sudah tidak tersedia.
echo ================================================
timeout /t 4 /nobreak >nul
exit /b 0
