@echo off
setlocal
title BOSS SF - SETUP TUNNEL
cd /d "%~dp0"
color 0B

echo ================================================
echo   BOSS SF - Setup Tunnel Cloudflare
echo ================================================
echo.

set "CFLARED=%~dp0tools\cloudflared.exe"
set "CFDIR=%USERPROFILE%\.cloudflared"
set "TUNNEL_ID=158b3999-3bd1-4e72-bdc3-d2c3fe7cca04"

REM ---------- 1. Download cloudflared ----------
if exist "%CFLARED%" goto :have_cflared
echo [*] Mendownload cloudflared.exe ...
powershell -Command "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -Uri 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe' -OutFile '%CFLARED%' -UseBasicParsing"
if errorlevel 1 goto :dl_fail
if not exist "%CFLARED%" goto :dl_fail
echo [OK] cloudflared terunduh.
goto :have_cflared

:dl_fail
echo [!] Gagal mendownload cloudflared. Cek koneksi internet.
pause
exit /b 1

:have_cflared
echo [OK] cloudflared tersedia.

REM ---------- 2. Buat folder config ----------
if not exist "%CFDIR%" mkdir "%CFDIR%"

REM ---------- 3. Tulis credentials JSON ----------
echo [*] Menulis credentials tunnel ...
> "%CFDIR%\%TUNNEL_ID%.json" (
    echo {
    echo   "AccountTag": "349fa1bdccf64974655fa0a3863e295a",
    echo   "TunnelID": "%TUNNEL_ID%",
    echo   "TunnelSecret": "NGJiOGI0MjMtOWZkNi00MzBiLTg5MTgtMTc5OTcwNDE3NjUy"
    echo }
)

REM ---------- 4. Tulis config.yml ----------
echo [*] Menulis config.yml ...
> "%CFDIR%\config.yml" (
    echo tunnel: %TUNNEL_ID%
    echo credentials-file: %CFDIR%\%TUNNEL_ID%.json
    echo.
    echo ingress:
    echo   - hostname: jon.bosssf.my.id
    echo     service: http://127.0.0.1:8000
    echo   - service: http_status:404
)

echo.
echo [*] Validasi config ...
"%CFLARED%" tunnel --config "%CFDIR%\config.yml" ingress validate
if errorlevel 1 (
    echo [!] Validasi config gagal.
    pause
    exit /b 1
)

echo.
echo ================================================================
echo   SETUP SELESAI
echo   Jalankan file  "jalankan-online.bat"  untuk mulai.
echo   Public URL  : https://jon.bosssf.my.id
echo ================================================================
echo.
pause
endlocal
