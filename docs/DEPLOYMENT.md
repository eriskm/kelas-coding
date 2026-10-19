# DEPLOYMENT - BOSS SF

[FAKTA] **Tidak ada CI/CD. Tidak ada Docker. Tidak ada file `.env`.**
Deploy adalah manual, lewat script `.bat` / `.ps1` di root.

---

## 1. Prasyarat

| Kebutuhan | Keterangan |
|---|---|
| Python | 3.9+ |
| Git | Untuk deploy |
| Node.js | **Hanya** untuk `node --check` (validasi sintaks JS) |
| PowerShell | Untuk `deploy-ubuntu.ps1` |

---

## 2. Instalasi

```powershell
git clone https://github.com/eriskm/kelas-coding.git
cd kelas-coding
python -m pip install -r backend\requirements.txt
```

Isi `backend/requirements.txt`: fastapi, uvicorn[standard], sqlalchemy,
greenlet, python-multipart, psycopg[binary].

---

## 3. Menjalankan lokal

### Mode dev (reload aktif)

```powershell
.\jalankan.bat
```

Menjalankan `seed.py` lebih dulu (aman - tidak membuat akun default), lalu
`uvicorn main:app --host 0.0.0.0 --port 8000 --reload`.

### Manual

```powershell
cd backend
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Buka `http://localhost:8000`.

### Versi app

`APP_VERSION` di `backend/main.py`, dibaca lewat `GET /api/health`.

---

## 4. Akun pertama

[TERKUNCI] **Tidak ada akun default.** Ini anti-backdoor.

```powershell
cd backend
python bootstrap_superadmin.py
```

Script membuat satu akun Super Admin dan mencatatnya ke journal.

[FAKTA] `seed.py` hanya mengisi data demo bila env `SUKABUMI_DEMO_SEED=1`
aktif. Jangan aktifkan di produksi.

---

## 5. Environment variable

Tidak ada file `.env` - konfigurasi lewat environment variable OS.

| Variabel | Fungsi | Default |
|---|---|---|
| `DATABASE_URL` | Ganti SQLite ke PostgreSQL | `sqlite:///servisku.db` |
| `NOTIF_PROVIDER_ENABLED` | Aktifkan provider notifikasi | nonaktif |
| `NOTIF_PRIVATE_ID` | Tujuan notifikasi | - |
| `SUKABUMI_DEMO_SEED` | Isi data demo saat seed | nonaktif |

[FAKTA] Provider notifikasi **tidak ada**. Mematikannya hanya mengubah label
status di outbox, bukan mengirim apa pun.

---

## 6. Mode online (Cloudflare Tunnel)

Untuk menjalankan BOSS SF lewat URL publik dari mesin lokal.

```powershell
.\setup-online.bat     # sekali: unduh cloudflared, tulis konfigurasi tunnel
.\jalankan-online.bat   # start uvicorn + tunnel, buka browser
.\matikan.bat          # stop cloudflared + proses port 8000
```

`jalankan-online.bat` hanya menyalakan uvicorn kalau port 8000 belum dipakai,
lalu menunggu maksimal 30 detik sebelum membuka tunnel.

⚠️ **`setup-online.bat` memuat kredensial tunnel dalam bentuk base64 dan file
itu ter-track di git.** Lihat [AUDIT_FINDINGS.md](AUDIT_FINDINGS.md).
**Jangan pernah menyalin nilai secret itu ke dokumen mana pun.**

---

## 7. Deploy ke server Ubuntu

```powershell
.\deploy-ubuntu.ps1              # deploy kode saja
.\deploy-ubuntu.ps1 -WithDb      # deploy kode + servisku.db
```

Mekanisme:

1. `tar` arsip source (exclude `.git`, `venv`, `__pycache__`, `backup-*.db`,
   `*.log`, file log).
2. `scp` ke server.
3. `extract` ke direktori aplikasi.
4. `systemctl --user restart bosssf.service`.
5. Health check `curl http://127.0.0.1:8000/`.

[TERKUNCI] **Tanpa `-WithDb`, file `servisku.db` TIDAK ikut terkirim.**
Server mempertahankan salinan DB-nya sendiri.

[FAKTA] Konfigurasi unit `bosssf.service` **tidak ada di repo** - hanya
namanya yang disebut di script.

[FAKTA] `tools/run_tunnel.bat` memakai path drive yang tidak ada di mesin ini -
script itu rusak.

---

## 8. Backup

[TERKUNCI] Backup otomatis **setiap start backend**, sebelum migrasi apa pun.

- SQLite: `backup-servisku-<timestamp>.db` di folder yang sama dengan DB.
- PostgreSQL: `pg_dump` via subprocess.
- Prune: 10 terbaru, **hanya** pola `backup-servisku-*`.

[FAKTA] Backup dengan pola lain (`backup-pre*`, `checkpoint-*`, `archive-*`)
tidak pernah di-prune. Root repo sudah terakumulasis banyak file `.db` usang.

Untuk backup manual sebelum operasi berisiko:

```powershell
Copy-Item servisku.db "backup-sebelum-<deskripsi>-<tanggal>.db"
```

---

## 9. Migrasi database

[TERKUNCI] **Tidak ada Alembic.** Migrasi = script kustom di `on_startup`.

Semua migrasi wajib idempotent dan dibungkus `try/except`, supaya kegagalan
tidak mematikan start aplikasi.

`create_all` **tidak** meng-update tabel yang sudah ada. Menambah kolom baru
wajib menyertakan script migrasi.

Test: `python -m pytest tests\test_migration_idempotent.py -q`

---

## 10. Checklist sebelum deploy

- [ ] `python -m pytest tests -q` -> 411 passed
- [ ] `python -m compileall -q backend`
- [ ] `node --check frontend\script.js`
- [ ] Backup DB sudah diambil
- [ ] `git status --short` bersih (tidak ada perubahan tak sengaja)
- [ ] Tidak ada secret yang baru masuk ke kode
- [ ] Kalau migrasi skema: test migrasi sudah dijalankan

---

## 11. Rollback

Tidak ada rollback otomatis. Recovery:

1. Hentikan service.
2. Kembalikan file DB dari backup terdekat (`backup-servisku-*.db`).
3. Kembalikan source ke commit sebelumnya.
4. Start ulang service.

[FAKTA] `git log --oneline` untuk melihat commit terakhir.

---

## 12. Isu keamanan yang diketahui

| Isu | Status |
|---|---|
| Kredensial Cloudflare Tunnel ter-commit ke git | **Belum diselesaikan** - perlu rotasi + purge history |
| Tidak ada rate limiting di login | Belum diselesaikan |
| CORS `allow_origins=["*"]` | Belum diselesaikan |
| `GET /api/health` publik membocorkan versi | Belum diselesaikan |

Rincian dan bukti: [AUDIT_FINDINGS.md](AUDIT_FINDINGS.md).

Perbaikan semua isu di atas **membutuskan keputusan Owner**.