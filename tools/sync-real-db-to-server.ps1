# tools/sync-real-db-to-server.ps1 — Sinkronisasi data riil servisku.db ke PostgreSQL Ubuntu
param(
  [string]$Host_ = "sf@192.168.18.132"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$db = Join-Path $root "servisku.db"
$script = Join-Path $root "backend\migrate_real_data_to_postgres.py"

if (-not (Test-Path -LiteralPath $db)) { throw "servisku.db tidak ada: $db" }
if (-not (Test-Path -LiteralPath $script)) { throw "script migrasi tidak ada: $script" }

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$remoteDb = "/tmp/servisku-sync-$stamp.db"
$remoteScript = "/home/sf/bosssf/backend/migrate_real_data_to_postgres.py"

Write-Host "[1/5] Backup PostgreSQL di server..." -ForegroundColor Cyan
& ssh $Host_ "PGPASSWORD=Quin76 pg_dump -h 127.0.0.1 -U bosssf -d bosssf -F p -f /home/sf/backup-before-realsync-$stamp.sql && ls -lh /home/sf/backup-before-realsync-$stamp.sql"
if ($LASTEXITCODE -ne 0) { throw "pg_dump gagal, sync dibatalkan demi keamanan" }

Write-Host "[2/5] Upload servisku.db dan script migrasi..." -ForegroundColor Cyan
scp -O $db "${Host_}:$remoteDb"
if ($LASTEXITCODE -ne 0) { throw "scp servisku.db gagal" }

scp -O $script "${Host_}:$remoteScript"
if ($LASTEXITCODE -ne 0) { throw "scp script migrasi gagal" }

scp -O (Join-Path $root "backend\models.py") "${Host_}:/home/sf/bosssf/backend/models.py"
if ($LASTEXITCODE -ne 0) { throw "scp models.py gagal" }

Write-Host "[3/5] Menjalankan migrasi data riil ke PostgreSQL..." -ForegroundColor Cyan
& ssh $Host_ "cd /home/sf/bosssf/backend && DATABASE_URL='postgresql+psycopg://bosssf:Quin76@127.0.0.1:5432/bosssf' SQLITE_PATH=$remoteDb ./venv/bin/python migrate_real_data_to_postgres.py ; rc=`$? ; rm -f $remoteDb ; exit `$rc"
if ($LASTEXITCODE -ne 0) { throw "Migrasi gagal di server" }

Write-Host "[4/5] Restart bosssf.service di server..." -ForegroundColor Cyan
& ssh $Host_ "systemctl --user restart bosssf.service && sleep 4 && systemctl --user is-active bosssf.service"

Write-Host "[5/5] Verifikasi respon API server..." -ForegroundColor Cyan
& ssh $Host_ "curl -s -o /dev/null -w 'HTTP Status Root: %{http_code}\n' http://127.0.0.1:8000/ && curl -s -o /dev/null -w 'HTTP Status Health: %{http_code}\n' http://127.0.0.1:8000/api/health"

Write-Host ""
Write-Host "Sinkronisasi database data riil selesai dengan aman! Backup: backup-before-realsync-$stamp.sql" -ForegroundColor Green
