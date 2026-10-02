# deploy-ubuntu.ps1 — sinkron source ke server Ubuntu + restart service
# Pakai:  .\deploy-ubuntu.ps1          (update kode saja, DB server tidak disentuh)
#         .\deploy-ubuntu.ps1 -WithDb  (ikut ganti servisku.db dengan versi lokal)
param([switch]$WithDb)

$ErrorActionPreference = "Stop"
$src = $PSScriptRoot
$stage = Join-Path $env:TEMP "opencode\bosssf-deploy.tar.gz"
$host_ = "sf@192.168.18.132"

$ex = @(
  "--exclude=.git", "--exclude=venv", "--exclude=__pycache__",
  "--exclude=backup-*.db", "--exclude=*.log", "--exclude=cloudflared.exe",
  "--exclude=referensi-nota", "--exclude=deploy-ubuntu.ps1"
)
if (-not $WithDb) { $ex += "--exclude=servisku.db" }

Write-Host "[1/4] Membuat arsip..."
tar @ex -czf $stage -C $src .
if (-not $?) { throw "gagal membuat arsip" }

Write-Host "[2/4] Upload ke $host_ ..."
scp $stage "${host_}:/tmp/bosssf-deploy.tar.gz"
if (-not $?) { throw "gagal upload" }

Write-Host "[3/4] Extract..."
& ssh $host_ "tar -xzf /tmp/bosssf-deploy.tar.gz -C /home/sf/bosssf && rm /tmp/bosssf-deploy.tar.gz && echo EXTRACT_OK"

Write-Host "[4/4] Restart service..."
& ssh $host_ "systemctl --user restart bosssf.service && sleep 4 && systemctl --user is-active bosssf.service && curl -s -o /dev/null -w 'local=%{http_code}' http://127.0.0.1:8000/"
Write-Host ""
Write-Host "Selesai. Publik: https://bosssf.sukabumitechflasher.com"
