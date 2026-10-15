# BOSS SF — AI CONTEXT

> Dokumen ini adalah konteks utama untuk Agent AI dalam pengembangan BOSS SF.
> Dibuat berdasarkan audit aktual project, bukan asumsi.

## 1. PROJECT IDENTITY

* **Nama project:** BOSS SF - Service System
* **Tujuan:** POS & Service Management untuk toko servis HP (tertulis di `jalankan.bat` dan deskripsi FastAPI `BOSS SF - Service System API`).
* **Kondisi project saat ini:** SUDAH BERJALAN. Inti servis (login, terima unit baru, transaksi, pelanggan, dashboard hitung order) sudah terhubung database. Modul Garansi, Sparepart, Keuangan, Kelola Akun masih UI/mock/static tanpa backend.
* **Status:** Prototype berjalan menuju production. Layak dipakai untuk operasional dasar servis, belum lengkap untuk stok/keuangan/garansi.

## 2. TECHNOLOGY STACK

* **Backend:** FastAPI `0.128.8`, Uvicorn `[standard]==0.39.0`, Python `3.9+` (dicek di `jalankan.bat`).
* **Frontend:** Vanilla HTML + CSS + JavaScript (tanpa build step). File: `frontend/index.html`, `frontend/script.js` (~1570 baris), `frontend/style.css`. CDN: `cdn.tailwindcss.com`, `apexcharts`, `font-awesome 6.5.1`, font `Inter`.
* **Database:** SQLite file `servisku.db` di root project.
* **ORM:** SQLAlchemy `2.0.52` (`declarative_base`, `sessionmaker`, `joinedload`). Tanpa Alembic.
* **Server:** Uvicorn `main:app`, port `8000`. Lokal/LAN via `jalankan.bat` (`0.0.0.0`), online via `jalankan-online.bat` (`127.0.0.1` + Cloudflare Tunnel).
* **Library utama:** `sqlalchemy==2.0.52`, `fastapi==0.128.8`, `uvicorn[standard]==0.39.0`, `greenlet==2.0.2`, `python-multipart==0.0.20` (lihat `backend/requirements.txt`).

## 3. PROJECT STRUCTURE

```
BOSS SF/
  backend/
    main.py            # entry point FastAPI, gabung router + static + startup seed/migrasi
    database.py        # engine SQLite + SessionLocal + get_db()
    models.py          # definisi tabel SQLAlchemy (sumber kebenaran DB)
    schemas.py         # Pydantic request/response
    dependencies.py    # wrapper get_db_session
    seed.py            # seed superadmin + dummy customer/order
    requirements.txt   # versi pinned
    routers/
      __init__.py      # kosong
      auth.py          # login/logout/me + hashing + token
      dashboard.py     # overview + statistics
      orders.py        # service order CRUD + receive + history + technicians
      customers.py     # customer CRUD + summary
    venv/              # virtualenv lokal, seharusnya di-ignore
    srv.log, srv_err.log # log server (di-ignore)
  frontend/
    index.html         # satu-satunya halaman, semua menu dalam satu file
    script.js          # seluruh logika SPA (API layer + navigasi + render)
    style.css          # class custom: star-card, panel, tx-table, float-window, dll
    assets/
      logo.png         # logo toko + favicon
      *-reference.png  # 6 file mockup desain (aksi, cekdeh, jarak, konten, login, warna)
  tools/
    cloudflared.exe    # binary tunnel (di-ignore di .gitignore)
    run_tunnel.bat     # run tunnel manual
    cf_out.log, cf_err.log, dll # log tunnel
  docs/
    AI_CONTEXT.md      # file ini
  jalankan.bat         # run lokal/LAN
  jalankan-online.bat  # run online via tunnel
  matikan.bat          # stop server + tunnel
  setup-online.bat     # setup tunnel sekali saja (berisi secret)
  servisku.db          # database aktual (di-ignore, jangan dihapus)
  .gitignore           # ignore venv, *.db, *.log, .env, cloudflared.exe
```

## 4. SYSTEM ARCHITECTURE

Alur aktual:

```
Browser
→ Frontend (frontend/index.html + script.js, diserve sebagai static)
→ API (fetch '/api/...' dengan header Authorization: Bearer <token>)
→ FastAPI (backend/main.py: mount router + static + CORS)
→ Router (backend/routers/auth.py, dashboard.py, orders.py, customers.py)
→ SQLAlchemy (Session via dependencies.get_db_session → database.get_db)
→ SQLite (servisku.db)
```

Authentication:
* Login `POST /api/auth/login` dengan `username + passcode`.
* Hash `PBKDF2-HMAC-SHA256` 200.000 iterasi + salt 16 byte hex (`backend/routers/auth.py`).
* Token acak `secrets.token_hex(32)`, disimpan di tabel `auth_tokens`, TTL 7 hari (`TOKEN_TTL_DAYS = 7`).
* Token disimpan frontend di `localStorage bsf_token` (Ingat Saya) atau `sessionStorage bsf_token` (`frontend/script.js:8-18`).
* Setiap request via `apiGet()` / `apiPost()` kirim `Authorization: Bearer <token>`. Jika 401 → `AuthError('Sesi tidak valid')`.
* Proteksi di `backend/main.py:76-79`: `auth.router` terbuka, `dashboard/orders/customers` wajib `Depends(get_authenticated_user)`.
* Role (`ADMIN/SUPERADMIN/Teknisi`) tersimpan di `users.role` tapi TIDAK dicek di router saat audit. Semua user login bisa akses semua endpoint.

Static file:
* `GET /` → `FileResponse frontend/index.html` (`backend/main.py:83-88`).
* `app.mount("/static", NoCacheStaticFiles(...))` (`backend/main.py:91-92`). Class custom memaksa header `Cache-Control: no-cache, no-store, must-revalidate`.
* URL aktual yang dibuka: `http://127.0.0.1:8000/static/index.html` (laptop) dan `http://<IP-LAN>:8000/static/index.html` (HP).
* `GET /favicon.ico` → `frontend/assets/logo.png`.

## 5. DATABASE OVERVIEW

Engine: `sqlite:///../servisku.db` + `check_same_thread=False` (`backend/database.py`). Tanpa migration framework. Migrasi ringan manual di `backend/main.py:_migrate_schema()` tambah kolom `device_password`, `repair_plan` via `PRAGMA table_info` + `ALTER TABLE`.

Tabel yang benar-benar ada (lihat `backend/models.py`):

* **users** — akun login.
  Fungsi: autentikasi. Kolom: `id, username(unique), display_name, role, passcode_hash, passcode_salt, active, last_login, created_at`. Relasi: satu user punya banyak `auth_tokens` (via `AuthToken.user_id`).
* **auth_tokens** — sesi login persisten.
  Fungsi: simpan token Bearer. Kolom: `id, token(unique), user_id(FK users.id), created_at, expires_at`. Relasi: `many-to-one` ke `users`.
* **customers** — master pelanggan.
  Fungsi: identitas pelanggan. Kolom: `id, name, phone, email, address, created_at`. Relasi: `one-to-many` ke `service_orders` (`service_orders.customer_id`).
* **service_orders** — inti transaksi servis.
  Fungsi: satu baris = satu unit servis. Kolom: `id, no_servis(unique, format SV-YYYYMMDD-XXXX), customer_id(FK), device, brand, model, damagetype, device_password, repair_plan, technician, status, estimate, payment, service_date, created_at`. Status aktual di seed/dashboard: `RECEIVED, ANALISA, DIAGNOSIS, REPAIR, QC, WAITING_PART, WAITING_APPROVAL, READY, COMPLETED`. Relasi: `many-to-one` ke `customers`, `one-to-many` ke `payments`.
* **payments** — pembayaran per order.
  Fungsi: riwayat bayar (sudah ada model, dipakai di seed untuk order READY/COMPLETED, belum ada UI/API khusus). Kolom: `id, service_order_id(FK service_orders.id), amount, method(default CASH), note, created_at`. Relasi: `many-to-one` ke `service_orders`.

Tidak ada tabel untuk sparepart, garansi, keuangan/beban, maupun manajemen akun. Itu sebabnya modul tersebut masih mock.

## 6. API OVERVIEW

Base: `API_BASE = '/api'` (`frontend/script.js:5`). Semua kecuali auth wajib Bearer.

### Auth (`backend/routers/auth.py`, prefix `/api/auth`, TERBUKA)
* `POST /api/auth/login` — REAL. Body `{username, passcode}` → `{token, user}`.
* `POST /api/auth/logout` — REAL. Hapus token saat ini.
* `GET /api/auth/me` — REAL. Validasi token + kembalikan user.

### Dashboard (`backend/routers/dashboard.py`, prefix `/api`, WAJIB LOGIN)
* `GET /api/overview` — PARTIALLY REAL. `total/done/active/pending/ready`, `omset/piutang/cash` dihitung dari `service_orders` (REAL). `laba_kotor=8750000, total_beban=3750000, laba_bersih, target_gaji=15000000` hardcode dummy (MOCK).
* `GET /api/statistics/status` — MOCK. Kembalikan 7 hari + series `Masuk/Selesai/Pending` dengan angka hardcode `[12,10,14,13,16,15,18]` dll.
* `GET /api/statistics/damage` — MOCK. Kembalikan 6 kategori + data `[14,9,7,5,4,3]` hardcode.

### Orders (`backend/routers/orders.py`, prefix `/api/orders`, WAJIB LOGIN)
* `GET /api/orders?page&limit` — REAL. Pagination backend, `DEFAULT_LIMIT=10, MAX_LIMIT=10`.
* `GET /api/orders/latest?limit` — REAL.
* `GET /api/orders/technicians` — REAL (static list). Return `["Budi","Andi","Rizky","Dedi","Fajar"]`.
* `GET /api/orders/history/{phone}` — REAL. 20 order terakhir per no HP, dipakai History Cerdas.
* `POST /api/orders/receive` — REAL. Buat customer + order sekaligus, dipakai Servis Baru. Auto-generate `no_servis`.
* `POST /api/orders` — REAL. Butuh `customer_id` valid.
* `GET /api/orders/{order_id}` — REAL.
* `PUT /api/orders/{order_id}` — REAL.
* `DELETE /api/orders/{order_id}` — REAL.

### Customers (`backend/routers/customers.py`, prefix `/api/customers`, WAJIB LOGIN)
* `GET /api/customers` — REAL. List full order by `created_at desc`.
* `GET /api/customers/summary?page&limit` — REAL. Agregat `count + max(created_at)` per customer + detail servis terakhir, pagination backend max 10.
* `GET /api/customers/{customer_id}` — REAL.
* `POST /api/customers` — REAL.
* `PUT /api/customers/{customer_id}` — REAL.
* `DELETE /api/customers/{customer_id}` — REAL.

### Static (`backend/main.py`)
* `GET /` — REAL. Serve `index.html` atau JSON error jika tidak ada.
* `GET /static/*` — REAL. Serve folder `frontend/` tanpa cache.
* `GET /favicon.ico` — REAL. Serve `assets/logo.png` atau 404.

Tidak ditemukan endpoint aktif untuk: sparepart, garansi, keuangan, users/akun.

## 7. CURRENT FEATURES

### REAL / DATABASE CONNECTED
* **Login/Logout/Session:** Form username+passcode, remember me, validasi 401, AKUN ADMIN TIDAK LAGI DIBUAT OTOMATIS. `backend/seed.py` hanya mengecek, tidak pernah membuat akun. Akun pertama dibuat lewat `python bootstrap_superadmin.py` (passcode diketik sendiri, tidak pernah dicetak).
* **Servis Baru (Penerimaan Unit):** Modal floating, `POST /orders/receive`, reuse customer by phone, field `customer_name, customer_phone, device, device_password, damagetype, repair_plan, estimate, dp, technician, status(default ANALISA)`. History Cerdas + dropdown teknisi REAL.
* **Transaksi:** Tabel dari `GET /orders`, pagination backend 10/page, kolom No/Tanggal/Device/User-WA/Status/Kerusakan/Perbaikan/Teknisi/Laba/Aksi.
* **Pelanggan:** Tabel dari `GET /customers/summary`, kolom Nama/WA/Device Terakhir/Tindakan Terakhir/Harga Terakhir/Total Servis.
* **Dashboard hitung order:** `total/done/active/pending/ready`, `omset` (sum payment), insight Unit Masuk/Selesai/Cash/Pending dari DB.

### PARTIALLY REAL
* **Dashboard finansial & chart:** Star Cards Laba Kotor/Beban/Bersih/Target + line chart status + bar chart kerusakan masih angka dummy hardcode di `dashboard.py` dan `script.js`. Jangan dianggap data toko.
* **Transaksi detail/edit/hapus:** `txDetail(id)` masih `alert('belum diimplementasikan')` (`frontend/script.js`). Endpoint PUT/DELETE ada di backend tapi belum dipanggil UI.
* **Quick Actions:** 4 kartu (Servis Baru, Input Kas, Input Beban, Sparepart). Hanya Servis Baru berfungsi (`onclick="openServisBaru()"`), sisanya tanpa aksi backend.

### MOCK / STATIC
* **Garansi:** `GR_MOCK` 14 baris (`frontend/script.js`), pagination lokal, tanpa fetch. Komentar kode: `tahap UI, tanpa backend`.
* **Sparepart:** `SP_MOCK` 14 baris + search lokal + badge Qty Habis/Menipis. Edit/hapus hanya `alert`. Komentar kode: `tahap UI, tanpa backend`.
* **Keuangan:** `KU_KAS` 4 baris + `KU_ALLOC` 4 alokasi (Bonus 10%, Pengelola 30%, Investor 30%, Kas Aset 30%) + `KU_RIWAYAT` 12 baris + donut ApexCharts. Form tambah kas hanya push ke array in-memory, hilang saat refresh. Komentar kode: `tahap UI, tanpa backend`.
* **Kelola Akun:** Tabel 5 akun hardcode di `frontend/index.html` (Andi, Budi, Citra, Doni, Eko), summary `5/4/2` hardcode, search/filter tanpa fungsi, form Tambah Akun floating tanpa API. Tidak ada `GET/POST /api/users`.

## 8. IMPORTANT FILES

* **`backend/main.py`** — entry point. Fungsi: gabung router + static + CORS + startup seed/migrasi. Baca saat: ubah routing global, tambah router baru, ubah proteksi auth, debug startup. Perhatikan: `include_router(... dependencies)`, `NoCacheStaticFiles`, `_migrate_schema()`, `on_startup()`.
* **`backend/models.py`** — sumber kebenaran tabel. Baca saat: kerja DB/ORM/relasi. Perhatikan: nama `__tablename__`, FK, `relationship`, kolom baru `device_password/repair_plan`.
* **`backend/schemas.py`** — kontrak API. Baca saat: ubah payload/response. Perhatikan: bedakan `ServiceReceiveIn` (input servis baru) vs `ServiceOrderCreate/Update`, `CustomerSummary/Page`, `ServiceOrderList/Page`.
* **`backend/routers/auth.py`** — auth. Baca saat: login/session/role. Perhatikan: `hash_passcode/verify_passcode`, `TOKEN_TTL_DAYS`, `get_authenticated_user`, `get_bearer_token`.
* **`backend/routers/orders.py`** — logika order. Baca saat: fitur transaksi/servis baru. Perhatikan: `_generate_no_servis()`, `receive_unit()`, `_to_list_schema()` (saat audit tidak memetakan `device_password/repair_plan`), `_page_clamp()`, `TECHNICIANS`, `MAX_LIMIT=10`.
* **`backend/routers/customers.py`** — logika pelanggan. Baca saat: fitur pelanggan. Perhatikan: query agregat `func.count/max`, `summary()` pagination.
* **`backend/routers/dashboard.py`** — dashboard. Baca saat: ubah KPI/chart. Perhatikan: bagian mana REAL (count order) vs dummy hardcode (finansial + series chart).
* **`backend/database.py`** — path DB + session. Baca saat: masalah koneksi/path. Perhatikan: `DB_PATH = ../servisku.db`, `check_same_thread=False`.
* **`backend/seed.py`** — seed. Baca saat: butuh akun/data awal. Perhatikan: `SUPERADMIN_USERNAME/PASSCODE`, idempotent, skip jika `Customer.count>0`, 10 customer + 12 order dummy.
* **`backend/dependencies.py`** — wrapper DB session. Baca saat: tambah dependency baru. Kecil, hanya teruskan `get_db`.
* **`frontend/index.html`** — struktur SPA. Baca saat: ubah layout/menu/ID. Perhatikan: ID page `pageDashboard, pageTransaksi, pagePelanggan, pageGaransi, pageSparepart, pageKeuangan, pageAkun, pageFormAkun`, ID tbody `txBody, plBody, grBody, spBody, kuBody, kuKasBody`, nav `data-page`, modal floating.
* **`frontend/script.js`** — logika SPA monolit. Baca selektif per fitur, jangan sekaligus. Perhatikan: `API_BASE`, `apiGet/apiPost`, `VALID_PAGES`, `navigateTo/showPage`, `renderStarCards/renderInsights/renderTransaksi/renderPelanggan/renderGaransi/renderSparepart/renderKeuangan`, konstanta mock `GR_MOCK, SP_MOCK, KU_KAS, KU_ALLOC, KU_RIWAYAT`.
* **`frontend/style.css`** — styling custom. Baca saat: ubah UI. Perhatikan: `star-card, panel, tx-table, float-window, qa-card, kpi-*`.
* **`jalankan.bat`, `jalankan-online.bat`, `matikan.bat`, `setup-online.bat`** — operasional. Baca saat: masalah run/stop/tunnel. Perhatikan: berisi secret tunnel + port hardcode, jangan ubah tanpa alasan jelas.
* **`servisku.db`** — data aktual. Jangan dihapus/di-reset tanpa backup. Di-ignore git tapi ada di working dir.

## 9. DEVELOPMENT / RUNNING

* **jalankan.bat (lokal/LAN):** Cek `python` → buat/aktifkan `backend/venv` → cek `import fastapi, sqlalchemy` else `pip install -r requirements.txt` → `python seed.py` → set `HOST=0.0.0.0 PORT=8000` → tampilkan IP LAN dari `ipconfig` → buka `http://<IP-LAN>:8000/static/index.html` → `python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload` dari folder `backend`. Loop restart otomatis via label `:CONNECT`.
* **setup-online.bat (sekali saja):** Cek/download `tools/cloudflared.exe` → buat `%USERPROFILE%\.cloudflared\` → tulis `<TUNNEL_ID>.json` (AccountTag/TunnelID/TunnelSecret) + `config.yml` (`jon.bosssf.my.id → http://127.0.0.1:8000`) → validasi `ingress validate`. Public URL: `https://jon.bosssf.my.id`.
* **jalankan-online.bat (online):** Cek `cloudflared.exe` → cek port 8000 via `netstat`, jika kosong start `backend\venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000` minimized → tunggu max 30 detik → cek `tasklist cloudflared.exe`, jika kosong start `cloudflared tunnel run` minimized → buka browser public URL → exit.
* **matikan.bat (stop):** `taskkill cloudflared.exe` → cari PID `LISTENING` di port 8000 via `netstat` lalu `taskkill /PID` → tutup window `BOSS SF - Server/Tunnel` by title.
* **Tambahan aktual:** Startup FastAPI juga `Base.metadata.create_all + _migrate_schema + seed()`. Tidak ada `.env`, Docker, atau test runner. Semua bat Windows-only (`ipconfig, netstat, taskkill, start`).

## 10. DEVELOPMENT RULES

1. Jangan membaca seluruh source code jika tidak diperlukan.
2. Mulai pekerjaan dengan membaca AI_CONTEXT.md.
3. Setelah memahami konteks, identifikasi file yang relevan dengan fitur.
4. Baca hanya file yang relevan sebelum melakukan perubahan.
5. Jangan mengubah fitur yang tidak berhubungan dengan pekerjaan.
6. Jangan menghapus data database aktual.
7. Jangan mengubah file .bat operasional tanpa alasan yang jelas.
8. Bedakan data REAL dan MOCK.
9. Setelah feature selesai, dokumentasi harus diperbarui.
10. Testing dilakukan sebelum menyatakan feature selesai.

## 11. CURRENT SYSTEM LIMITATIONS

* **Modul masih mock:** Garansi, Sparepart, Keuangan hanya `GR_MOCK/SP_MOCK/KU_*` di `script.js`; Kelola Akun hardcode di HTML. Belum ada tabel, schema, router, endpoint untuk keempatnya.
* **Dummy data:** Finansial overview (`8750000/3750000/15000000`), chart status/damage 7 hari, seluruh isi garansi/sparepart/keuangan adalah angka contoh, bukan data toko.
* **Frontend monolit:** `script.js` ~1570 baris satu file, tanpa modul/bundler. Navigasi via `hidden` + `localStorage bsf_page` + hash `#/...`. `VALID_PAGES` tidak mencakup `akun`/`servisbaru` (modal), rawan bug route. Detail/edit/hapus transaksi, edit/hapus sparepart, edit keuangan masih `alert`.
* **Authentication/authorization:** PBKDF2 200k + token 7 hari sudah ada, tapi tanpa rate-limit, tanpa cek role di router, CORS `allow_origins=["*"] + allow_credentials=True` kontradiktif untuk browser modern. Secret tunnel terekspos plain di `setup-online.bat`.
* **Database migration:** Tanpa Alembic. Hanya `create_all` + `ALTER TABLE` manual untuk 2 kolom. Bug saat audit: `_to_list_schema()` tidak memetakan `device_password/repair_plan` sehingga list selalu null. Pagination keras max 10. Tabel `payments` ada tapi tanpa API/UI khusus. Tidak ada backup strategy, file DB di root.
* **Git:** Banyak perubahan belum di-commit (`M backend/main.py, routers/*, schemas.py, frontend/*`) + file baru belum di-track (`jalankan-online.bat, matikan.bat, setup-online.bat, tools/, *-reference.png`). `.gitignore` meng-ignore `*.db/*.log/venv/` tapi file tersebut tetap ada di working dir.
* **Konfigurasi online:** Windows-only, port hardcode 8000, path absolut `E:\PRAKTEK MJPRO` di `tools/run_tunnel.bat`, dependensi pada binary `cloudflared.exe` + config di `%USERPROFILE%\.cloudflared\`.
* **Lainnya:** Tidak ada `.env`, tidak ada test, `requirements.txt` pinned ketat, `NoCacheStaticFiles` memaksa no-cache (boros bandwidth tapi memudahkan dev), `servisku.db` 57KB campur data real + dummy seed.

## 12. CURRENT DEVELOPMENT PRIORITY

Berdasarkan kondisi audit:
1. Buat backend persisten untuk Sparepart (tabel + CRUD + search + stok).
2. Buat backend persisten untuk Keuangan (tabel kas/beban + alokasi profit, ganti `KU_*` in-memory).
3. Buat backend persisten untuk Garansi (relasi ke `service_orders`).
4. Buat backend manajemen Akun (`GET/POST/PUT /api/users`, ganti tabel hardcode, terapkan cek role).
5. Ganti angka dummy dashboard (`overview`, `statistics/status`, `statistics/damage`) dengan agregat nyata dari DB.
6. Sambungkan aksi UI yang masih `alert` (detail/transaksi edit-hapus, sparepart edit-hapus, keuangan edit) ke endpoint yang sudah ada/baru.
7. Perbaiki `_to_list_schema()` agar `device_password/repair_plan` tidak hilang, evaluasi `MAX_LIMIT=10`, dan ganti migrasi manual dengan Alembic jika skema makin sering berubah.
8. Amankan secret tunnel (pindah ke `.env` yang di-ignore), rapikan git (commit/track yang perlu, pastikan `*.db/*.log/venv/` tidak ikut), dan dokumentasikan backup `servisku.db`.

## 13. AI WORKING PRINCIPLE

"Dokumentasi adalah konteks utama. Source code dibaca secara selektif berdasarkan pekerjaan."

Aturan kerja:

BEFORE CODING
→ baca AI_CONTEXT.md
→ identifikasi modul
→ identifikasi file relevan
→ baca file relevan
→ pahami dependency
→ baru coding

AFTER CODING
→ testing
→ update dokumentasi
→ update changelog
→ git commit

## 14. LAST AUDIT STATUS

* Tanggal audit: 2026-09-07 (UTC).
* Dokumen ini dibuat berdasarkan audit aktual project BOSS SF yang baru saja dilakukan: struktur folder, `backend/requirements.txt`, `main.py`, `database.py`, `models.py`, `schemas.py`, `seed.py`, `routers/auth.py`, `dashboard.py`, `orders.py`, `customers.py`, `frontend/index.html`, `frontend/script.js`, `tools/run_tunnel.bat`, `jalankan.bat`, `jalankan-online.bat`, `matikan.bat`, `setup-online.bat`, `.gitignore`, dan `git log/status`.
* Jika kode berubah signifikan setelah tanggal ini, audit ulang dan perbarui AI_CONTEXT.md.
