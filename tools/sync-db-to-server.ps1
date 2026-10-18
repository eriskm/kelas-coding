# sync-db-to-server.ps1 - salin data SQLite lokal ke PostgreSQL di server Ubuntu.
#
# Pakai:
#     .\sync-db-to-server.ps1                # mode fill  (aman, hanya tabel kosong)
#     .\sync-db-to-server.ps1 -Mode upsert   # mode upsert (perbarui per primary key)
#     .\sync-db-to-server.ps1 -Mode upsert -Tables service_orders,status_history
#
# Bedanya dengan deploy-ubuntu.ps1:
# - deploy-ubuntu.ps1 menyinkronkan KODE dan me-restart service
# - script ini menyinkronkan DATA (servisku.db -> PostgreSQL); service tidak
#   di-restart karena backend membaca DB langsung pada setiap request
#
# Sifat penting:
# - TIDAK menghapus baris. Baris di server yang tidak ada di SQLite tetap ada.
# - auth_tokens tidak pernah disalin (sesi login mesin lokal tidak relevan).
# - Selalu ambil backup PostgreSQL ke server sebelum mengubah apa pun.
#
# Kredensial TIDAK disimpan di repo ini. DATABASE_URL diambil dari unit systemd
# `bosssf.service` di server saat runtime.
param(
  [ValidateSet("fill", "upsert")][string]$Mode = "fill",
  [string]$Tables = "",
  [string]$Host_ = "sf@192.168.18.132",
  [switch]$SkipBackup
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$db = Join-Path $root "servisku.db"
if (-not (Test-Path -LiteralPath $db)) { throw "servisku.db tidak ada: $db" }

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$remote = "/tmp/servisku-sync-$stamp.db"
$pgdump = "/tmp/pgurl-$stamp.txt"

# Tarik DATABASE_URL dari unit systemd, lalu ubah ke format yang.dimahami pg_dump
# (SQLAlchemy memakai postgresql+psycopg://, pg_dump hanya postgresql://).
$pre = "eval `"`$(systemctl --user show bosssf.service -p Environment --value)`" ; " +
       "if [ -z `"`$DATABASE_URL`" ]; then echo 'DATABASE_URL tidak ada di unit service' >&2; exit 1; fi ; " +
       "export DATABASE_URL ; " +
       "echo `"`$DATABASE_URL`" | sed 's/postgresql+psycopg:/postgresql:/' > $pgdump ; "

Write-Host "[1/4] Backup PostgreSQL di server..." -ForegroundColor Cyan
if (-not $SkipBackup) {
  & ssh $Host_ ($pre + "PGURL=`$(cat $pgdump) ; pg_dump `"`$PGURL`" -F p -f pre-sync-$stamp.sql && ls -la pre-sync-$stamp.sql")
  if ($LASTEXITCODE -ne 0) { throw "pg_dump gagal, sync dibatalkan" }
} else {
  Write-Host "   (dilewati karena -SkipBackup)"
}

Write-Host "[2/4] Upload servisku.db..." -ForegroundColor Cyan
& scp $db "${Host_}:$remote"
if ($LASTEXITCODE -ne 0) { throw "scp gagal" }

Write-Host "[3/4] Jalankan migrasi mode=$Mode ..." -ForegroundColor Cyan
$tableArg = ""
if ($Tables) { $tableArg = "--tables $Tables" }
& ssh $Host_ ($pre +
  "cd /home/sf/bosssf/backend && SQLITE_PATH=$remote " +
  "./venv/bin/python migrate_sqlite_to_postgres.py --mode $Mode $tableArg ; rc=`$? ; " +
  "rm -f $remote $pgdump ; exit `$rc")
if ($LASTEXITCODE -ne 0) { throw "migrasi gagal" }

Write-Host "[4/4] Verifikasi cepat..." -ForegroundColor Cyan
& ssh $Host_ "curl -s -o /dev/null -w 'api/health=%{http_code}\n' http://127.0.0.1:8000/api/health"

Write-Host ""
Write-Host "Selesai. Mode=$Mode, backup: pre-sync-$stamp.sql" -ForegroundColor Green