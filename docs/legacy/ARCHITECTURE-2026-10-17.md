# BOSS SF — SYSTEM ARCHITECTURE

> Dokumen ini menjelaskan arsitektur AKTUAL BOSS SF.
> Sumber utama: `docs/AI_CONTEXT.md` + hasil audit project.
> Source code tetap menjadi sumber kebenaran implementasi.

## 1. ARCHITECTURE OVERVIEW

BOSS SF adalah aplikasi monolit sederhana: satu backend FastAPI melayani API JSON sekaligus file frontend statis, dengan satu database SQLite.

```
Browser
↓
Frontend (index.html + script.js + style.css, tanpa build step)
↓
HTTP / API (fetch '/api/...', JSON + Bearer token)
↓
FastAPI (main.py: CORS + router + static + startup seed/migrasi)
↓
Router (auth / dashboard / orders / customers)
↓
Business Logic (langsung di dalam router, tanpa service layer)
↓
SQLAlchemy (Session via dependencies → database)
↓
SQLite (servisku.db di root project)
```

Karakter arsitektur aktual:
* Satu proses Uvicorn (`main:app`, port `8000`) menangani API + static.
* Tidak ada service/repository layer, tidak ada migration framework, tidak ada test runner.
* Frontend SPA vanilla dalam satu file HTML, logika dalam satu file JS monolit.

## 2. COMPONENTS

### Frontend

* **index.html** — satu-satunya halaman. Tanggung jawab: kerangka SPA (login overlay, sidebar, topbar, semua section page `pageDashboard/pageTransaksi/pagePelanggan/pageGaransi/pageSparepart/pageKeuangan/pageAkun`, modal floating Servis Baru dan Form Akun, mobile nav). Semua page dibedakan via class `hidden`, bukan file terpisah.
* **script.js** — logika utama SPA (~1570 baris). Tanggung jawab: API helper (`apiGet/apiPost`), auth/token storage, navigasi (`showPage/navigateTo`), render per halaman (`renderStarCards/renderInsights/renderTransaksi/renderPelanggan/renderGaransi/renderSparepart/renderKeuangan`), pagination lokal/backend, chart ApexCharts, form Servis Baru.
* **style.css** — styling custom. Tanggung jawab: class `star-card, panel, tx-table, float-window, qa-card, kpi-*`, tema dark/light, layout app-window/sidebar.
* **assets** — `logo.png` (logo toko + favicon) dan 6 file `*-reference.png` sebagai mockup desain (aksi, cekdeh, jarak, konten, login, warna). Tidak dipakai logika bisnis.

### Backend

* **main.py** — entry point. Tanggung jawab: buat `FastAPI(title="BOSS SF - Service System API")`, pasang CORS, daftarkan router (auth terbuka, sisanya protected), definisikan `GET /` dan `GET /favicon.ico`, mount `/static` via `NoCacheStaticFiles`, jalankan `create_all + _migrate_schema + seed` saat startup.
* **routers** — `auth.py`, `dashboard.py`, `orders.py`, `customers.py` (`__init__.py` kosong). Tanggung jawab: definisi endpoint + validasi + query DB langsung. Business logic (generate nomor servis, reuse customer, agregat dashboard/pelanggan) ada di sini.
* **schemas.py** — kontrak Pydantic. Tanggung jawab: `Customer*`, `ServiceReceiveIn/ServiceOrderCreate/Update/Out/List/Page`, `Payment*`, `DashboardOverview` (terdefinisi tapi overview aktual pakai dict manual).
* **models.py** — sumber kebenaran tabel. Tanggung jawab: `User, AuthToken, Customer, ServiceOrder, Payment` + FK + `relationship`.
* **dependencies.py** — wrapper tipis `get_db_session` yang meneruskan `database.get_db`. Tanggung jawab: menyediakan `Session` ke router via `Depends`.
* **database.py** — koneksi DB. Tanggung jawab: `engine = create_engine("sqlite:///../servisku.db", check_same_thread=False)`, `SessionLocal`, `Base`, generator `get_db()`.
* **seed.py** — data awal. Tanggung jawab: buat tabel, buat akun admin default secara idempotent (kredensial aktual ada di file ini, tidak ditulis di dokumen), seed customer/order dummy jika tabel customer kosong, buat payment untuk order READY/COMPLETED.

### Database

* **SQLite** — tanpa server terpisah. Tanggung jawab: persistensi seluruh data.
* **servisku.db** — file DB aktual di root project. Path di-hardcode di `database.py`. Berisi 5 tabel aktual: `users, auth_tokens, customers, service_orders, payments`. Tidak ada tabel sparepart/garansi/keuangan/akun.

## 3. REQUEST FLOW

Pola umum setiap aksi user:

```
User
→ klik tombol / submit form
→ JavaScript (event handler di script.js)
→ apiGet() / apiPost() (tambah Authorization: Bearer <token> otomatis)
→ HTTP request ke /api/...
→ FastAPI (main.py: routing + CORS + static)
→ Router (auth/dashboard/orders/customers)
→ Dependency (get_bearer_token + get_authenticated_user + get_db_session, kecuali auth)
→ SQLAlchemy (query models.py)
→ SQLite (servisku.db)
→ response JSON
→ JavaScript (parse JSON / tangani 401 → AuthError)
→ update UI (innerHTML tabel, chart, pagination, modal close)
```

Contoh aktual:

* **Login:** user submit `#loginForm` → `fetch('/api/auth/login', POST {username, passcode})` → `auth.login()` verifikasi hash → `create_token()` simpan `auth_tokens` + update `last_login` → return `{token, user}` → JS simpan token (`localStorage` jika Ingat Saya, else `sessionStorage`) → `loadDashboard()` → `showPage('dashboard')`.
* **Servis Baru:** user buka modal Servis Baru → isi form → `apiPost('/orders/receive', ServiceReceiveIn)` → `orders.receive_unit()` cari customer by phone else buat baru → buat `ServiceOrder` dengan `no_servis` auto-generate → commit → return `ServiceOrderOut` → JS tutup modal → refresh Transaksi.
* **Transaksi:** user buka menu Transaksi → `showTransaksi()` → `renderTransaksi()` → `loadTxPage(1)` → `apiGet('/orders?page&limit')` → `orders.list_orders()` (`joinedload(customer)`, order by `created_at desc`, offset/limit, max 10) → return `ServiceOrderPage` → JS render `txBody`, `txInfo`, `txPageBtns`.
* **Pelanggan:** user buka menu Pelanggan → `showPelanggan()` → `renderPelanggan()` → `loadPlPage(1)` → `apiGet('/customers/summary?page&limit')` → `customers.customer_summary()` (agregat `count/max(created_at)` per customer + servis terakhir) → return `CustomerSummaryPage` → JS render `plBody`.

## 4. AUTHENTICATION FLOW

Alur aktual:

```
Login
→ input username + passcode (frontend #loginForm)
→ FastAPI POST /api/auth/login
→ cari users by username + cek active
→ verifikasi password (PBKDF2-HMAC-SHA256, 200.000 iterasi, compare_digest)
→ generate token (secrets.token_hex(32))
→ simpan ke auth_tokens (user_id + expires_at = now + 7 hari) + update users.last_login
→ token + user dikirim ke frontend
→ frontend simpan token di localStorage (remember) / sessionStorage + username/remember flag
→ request berikutnya kirim header Authorization: Bearer <token> via apiGet/apiPost
→ get_bearer_token (wajib prefix "Bearer ") → get_authenticated_user → get_current_user (cek token ada, belum expired, user aktif)
→ akses endpoint protected diizinkan; jika gagal → 401 → frontend lempar AuthError → kembali ke login
→ logout: POST /api/auth/logout hapus token saat ini
→ validasi sesi: GET /api/auth/me
```

Batasan aktual (tidak ditambah-tambah):
* `users.role` tersimpan (`ADMIN/SUPERADMIN/Teknisi`) tetapi tidak digunakan untuk authorization. Semua user login bisa akses semua endpoint protected.
* Token TTL 7 hari (`TOKEN_TTL_DAYS = 7`). Expired token dihapus saat diakses.
* Tidak ada rate limiting login, tidak ada lockout, tidak ada refresh token, tidak ada OAuth (tombol Google/Microsoft/fingerprint di login disabled).

## 5. FRONTEND ARCHITECTURE

SPA monolit tanpa build framework:

* **Satu `index.html`:** berisi login overlay (`#loginScreen`), app window (title-bar, sidebar `#appSidebar`, topbar, content `pageDashboard/...`), modal floating (`pageFormAkun`, form Servis Baru), mobile bottom nav. Page switching hanya toggle class `hidden`.
* **`script.js` sebagai logika utama:** satu file global, tanpa modul/import. Berisi konstanta (`API_BASE='/api'`, `VALID_PAGES`, `TX_PER_PAGE/PL_PER_PAGE/GR_PER_PAGE/SP_PER_PAGE/KU_PER_PAGE`, mock `GR_MOCK/SP_MOCK/KU_KAS/KU_ALLOC/KU_RIWAYAT`), helper (`getToken/setToken/clearToken`, `escapeHtml`, `txDate`, rupiah formatter), API layer, render function per page, chart init, form handler.
* **Navigasi page:** `showPage(name)` + `navigateTo(key)` + `showDashboard/showTransaksi/showPelanggan/showGaransi/showSparepart/showKeuangan/showAkun`. Servis Baru dan Form Akun adalah modal (`openServisBaru/openFormAkun`), bukan page.
* **API helper:** `apiGet(path)` (GET + Bearer) dan `apiPost(path, body)` (POST JSON + Bearer). Keduanya lempar `AuthError` saat 401. Auth langsung pakai `fetch` ke `/auth/me`, `/auth/login`, `/auth/logout`.
* **Render function:** `renderStarCards/renderQuickActions/renderInsights/renderStatusMini/renderDamageSection` (dashboard), `renderTransaksi/loadTxPage` (backend paged), `renderPelanggan/loadPlPage` (backend paged), `renderGaransi/renderSparepart/renderKeuangan/renderBukuKas/renderAlloc/renderRiwayat` (mock lokal).
* **localStorage:** `bsf_token` (jika remember) vs `sessionStorage bsf_token`, `bsf_username`, `bsf_remember`, `bsf_page` (route terakhir).
* **Hash routing:** dipakai (`#/dashboard`, `#/transaksi`, ...). `pageFromHash()`, `savePage()`, `getSavedPage()` menjaga posisi saat refresh. `VALID_PAGES = ['dashboard','transaksi','pelanggan','garansi','sparepart','keuangan']` — tidak mencakup `akun` dan `servisbaru`.
* **Modal/floating window:** Servis Baru dan Form Akun berupa `float-window` dengan titlebar + body + form. Hanya Servis Baru yang terhubung backend; Form Akun belum.

## 6. BACKEND ARCHITECTURE

Lapisan aktual:

```
main.py
→ routers (auth.py / dashboard.py / orders.py / customers.py)
→ dependencies (get_db_session)
→ schemas (Pydantic in/out)
→ models (SQLAlchemy tables)
→ database (engine + SessionLocal + Base)
```

Fungsi setiap layer:
* **main.py:** komposisi. Daftarkan router, atur proteksi global (`Depends(get_authenticated_user)` untuk dashboard/orders/customers), serve static, startup hook. Tidak berisi business logic transaksi.
* **routers:** endpoint + business logic. Contoh: `orders.py` berisi generate nomor, reuse customer, clamp pagination, mapping ke schema list; `customers.py` berisi agregat summary; `dashboard.py` berisi hitung status + angka dummy; `auth.py` berisi hash/verify + token lifecycle.
* **dependencies:** menyediakan `Session`. Tidak ada otorisasi peran, caching, atau validasi tambahan.
* **schemas:** validasi input dan bentuk output. `ServiceReceiveIn` untuk form servis baru, `ServiceOrderCreate/Update` untuk CRUD generik, `*Page` untuk pagination backend.
* **models:** definisi tabel + relasi. Tidak berisi query.
* **database:** koneksi + session factory.

Kondisi aktual: business logic langsung berada di router. Tidak ada `services/`, `repositories/`, atau use-case layer. Perubahan fitur order/customer/dashboard berarti edit file router yang bersangkutan.

## 7. DATABASE ARCHITECTURE

```
users (1) ───< (N) auth_tokens
  id ─────────── user_id (FK users.id)

customers (1) ───< (N) service_orders
  id ─────────────── customer_id (FK customers.id)

service_orders (1) ───< (N) payments
  id ─────────────────── service_order_id (FK service_orders.id)
```

Foreign key dan relasi aktual (`backend/models.py`):
* `auth_tokens.user_id → users.id`, `relationship("User")`. Satu user bisa punya banyak token aktif.
* `service_orders.customer_id → customers.id`, `Customer.service_orders ↔ ServiceOrder.customer`. Satu customer bisa punya banyak order.
* `payments.service_order_id → service_orders.id`, `ServiceOrder.payments ↔ Payment.service_order` dengan `cascade="all, delete-orphan"`. Hapus order menghapus payment-nya.
* `users.username` dan `service_orders.no_servis` dan `auth_tokens.token` unique + indexed.
* Tidak ada FK dari/ke sparepart/garansi/keuangan/akun karena tabelnya belum ada.

## 8. API ARCHITECTURE

Pembagian router aktual:

* **`/api/auth` → `routers/auth.py` (public):** `POST /login`, `POST /logout` (butuh Bearer valid), `GET /me` (butuh Bearer valid). Satu-satunya grup yang bisa diakses tanpa token adalah `POST /login`.
* **`/api` → `routers/dashboard.py` (protected):** `GET /overview`, `GET /statistics/status`, `GET /statistics/damage`.
* **`/api/orders` → `routers/orders.py` (protected):** list/paged, latest, technicians, history by phone, receive, create, get/update/delete by id.
* **`/api/customers` → `routers/customers.py` (protected):** list, summary/paged, get/create/update/delete.

Endpoint public:
* `POST /api/auth/login`
* `GET /`, `GET /static/*`, `GET /favicon.ico`

Endpoint protected (wajib `Authorization: Bearer <token>` valid):
* Semua `/api/auth/logout`, `/api/auth/me`, `/api/overview`, `/api/statistics/*`, `/api/orders*`, `/api/customers*`.

Tidak ada endpoint baru di dokumen ini. Tidak ada `/api/sparepart`, `/api/garansi`, `/api/keuangan`, `/api/users`.

## 9. STATIC FILE ARCHITECTURE

FastAPI merangkap sebagai web server statis (tanpa nginx/CDN):

* **`/` → `frontend/index.html`:** handler `root()` di `main.py` mengembalikan `FileResponse(index.html)` jika file ada, else JSON `{"detail": "Frontend index.html tidak ditemukan"}`. `include_in_schema=False`.
* **`/static/*` → `frontend/`:** `app.mount("/static", NoCacheStaticFiles(directory=FRONTEND_DIR))`. Setiap `FileResponse` diberi header no-cache. URL yang dipakai operasional: `/static/index.html`, `/static/script.js`, `/static/style.css`, `/static/assets/logo.png`.
* **`/favicon.ico` → logo:** handler `favicon()` mengembalikan `frontend/assets/logo.png` (`image/png`) atau 404.

## 10. DATA FLOW

### Contoh: Servis Baru

```
Customer (user toko isi form Servis Baru: nama, WA, device, password device, kerusakan, rencana repair, estimasi, DP, teknisi)
→ Form Servis Baru (modal floating, validasi dasar di JS)
→ POST /api/orders/receive (apiPost, Bearer + JSON ServiceReceiveIn)
→ customers (cari by phone desc; jika tidak ada → INSERT Customer baru)
→ service_orders (INSERT dengan no_servis auto SV-YYYYMMDD-XXXX, service_date=today, status default ANALISA)
→ response ServiceOrderOut (termasuk customer)
→ UI (tutup modal, reload halaman Transaksi → GET /api/orders terlihat di baris teratas)
```

### Contoh: Customer History (History Cerdas)

```
No WhatsApp (diketik di form Servis Baru)
→ GET /api/orders/history/{phone} (apiGet, Bearer)
→ service_orders (cari semua Customer dengan phone sama → ambil cids → query ServiceOrder where customer_id IN cids order by created_at desc limit 20)
→ response list ServiceOrder (bisa kosong [])
→ History Cerdas (JS render riwayat unit sebelumnya untuk bantu teknisi)
```

## 11. REAL VS MOCK ARCHITECTURE

Agar Agent tidak salah menganggap UI sebagai backend:

REAL (request → router → SQLAlchemy → SQLite):
* Login (`/api/auth/*` ↔ `users/auth_tokens`)
* Servis Baru (`POST /api/orders/receive`, `GET /api/orders/history/{phone}`, `GET /api/orders/technicians` ↔ `customers/service_orders`)
* Transaksi (`GET /api/orders` ↔ `service_orders + join customers`)
* Pelanggan (`GET /api/customers/summary` ↔ `customers + agregat service_orders`)

PARTIALLY REAL:
* Dashboard (`GET /api/overview` hitung order REAL, finansial dummy; `GET /statistics/status|damage` full dummy tetapi lewat endpoint protected sehingga terlihat seperti API real)

MOCK/STATIC (hanya JS/HTML, tanpa request backend):
* Garansi (`GR_MOCK` di `script.js` → render `grBody`, pagination lokal)
* Sparepart (`SP_MOCK` → render `spBody` + search lokal, edit/hapus `alert`)
* Keuangan (`KU_KAS/KU_ALLOC/KU_RIWAYAT` → render `kuKasBody/kuAllocList/kuBody` + chart donut, tambah kas hanya array in-memory)
* Kelola Akun (5 baris hardcode di `index.html`, summary hardcode, form tanpa submit backend)

## 12. OPERATIONAL ARCHITECTURE

LOCAL/LAN (via `jalankan.bat`):

```
PC (Windows, Python + backend/venv)
→ FastAPI/Uvicorn (0.0.0.0:8000, --reload, dari folder backend/)
→ SQLite (servisku.db di root)
→ Browser laptop (127.0.0.1:8000/static/index.html) + Browser HP (IP-LAN:8000/static/index.html, satu WiFi/AP)
```

ONLINE (via `jalankan-online.bat` setelah `setup-online.bat`):

```
PC (Uvicorn 127.0.0.1:8000, minimized)
→ Cloudflare Tunnel (cloudflared.exe di tools/, config di direktori user)
→ Public hostname (dokumen operasional, tanpa secret di sini)
→ Browser publik (https)
```

Stop via `matikan.bat` (kill tunnel + PID port 8000 + tutup window Server/Tunnel). Detail secret/credential tunnel dan akun default tidak ditulis di dokumen ini — lihat file operasional dan `seed.py` langsung saat diperlukan dengan izin.

## 13. ARCHITECTURE RULES FOR AI AGENT

1. Sebelum mengubah arsitektur, baca `AI_CONTEXT.md` dan `ARCHITECTURE.md`.
2. Jangan membuat layer baru tanpa alasan.
3. Jangan membuat endpoint baru jika endpoint yang ada masih dapat digunakan.
4. Jangan mengubah database tanpa memahami relasinya.
5. Jangan mengubah frontend global untuk kebutuhan satu fitur jika perubahan lokal sudah cukup.
6. Jangan menganggap UI sebagai fitur backend.
7. Jangan mengubah komponen yang tidak berkaitan dengan pekerjaan.
8. Source code dibaca selektif berdasarkan komponen yang sedang dikerjakan.

## 14. CURRENT ARCHITECTURE LIMITATIONS

* Frontend monolit: satu HTML + satu JS besar, tanpa modul/build/test frontend.
* Business logic langsung di router: tanpa service/repository layer, sulit reuse dan test.
* SQLite: file tunggal di root, tanpa concurrent write yang kuat, tanpa backup otomatis, path hardcode.
* Belum ada migration framework: hanya `create_all` + `ALTER TABLE` manual 2 kolom; rawan drift skema.
* Belum ada test runner: tanpa unit/integration test backend maupun frontend.
* Role belum digunakan untuk authorization: semua user login setara.
* Modul tertentu masih mock: Garansi/Sparepart/Keuangan/Kelola Akun tanpa tabel/API; dashboard finansial dan chart dummy.
* Batasan operasional: Windows-only bat, port hardcode 8000, CORS `*` + credentials kontradiktif, static no-cache selalu, `MAX_LIMIT=10` keras, secret tunnel di file operasional.

## 15. DOCUMENTATION PRINCIPLE

"Dokumentasi menjelaskan kondisi sistem saat ini.
Source code tetap menjadi sumber kebenaran implementasi.
Dokumentasi membantu Agent menentukan source code mana yang perlu dibaca."

Jika dokumentasi dan source code berbeda:
→ jangan menebak
→ verifikasi source code
→ perbarui dokumentasi.
