# BOSS SF — API

> Dokumentasi API AKTUAL yang benar-benar ada di source code.
> Frontend tidak perlu dibaca ulang setiap kali; gunakan dokumen ini sebagai peta.
> Source code router + `schemas.py` tetap sumber kebenaran.

## 1. API OVERVIEW

* **Backend menggunakan FastAPI** (`backend/main.py`, `title="BOSS SF - Service System API"`, `version="1.0.0"`).
* **Base path API aktual:** `/api`. Frontend mendefinisikan `const API_BASE = '/api'` (`frontend/script.js:5`) dan memanggil `fetch(API_BASE + path)`.
* **Cara frontend berkomunikasi:** `fetch()` JSON. Helper `apiGet(path)` untuk GET + Bearer otomatis, `apiPost(path, body)` untuk POST JSON + Bearer otomatis. Auth (`/auth/login`, `/auth/me`, `/auth/logout`) memakai `fetch` langsung dengan header manual.
* **Format request/response umum:** JSON. Request body divalidasi Pydantic (`schemas.py` + `LoginRequest` di `auth.py`). Response divalidasi `response_model` FastAPI. Error berbentuk `{"detail": "..."}` bawaan `HTTPException`.
* **Authentication yang digunakan:** Bearer token acak persisten di DB (`auth_tokens`), dikirim via header `Authorization: Bearer <token>`. Tanpa cookie, tanpa OAuth, tanpa API key lain.
* **HTTP method yang digunakan:** `GET` (baca/list/detail), `POST` (login/logout/receive/create), `PUT` (update), `DELETE` (hapus). Tidak ada `PATCH`.
* **JSON sebagai format data:** Ya. `Content-Type: application/json` pada POST. Query string hanya untuk pagination (`?page&limit`) dan path param (`{phone}`, `{order_id}`, `{customer_id}`).

## 2. API ARCHITECTURE

Diagram aktual:

```
Browser / Frontend (script.js: apiGet/apiPost/fetch)
↓
fetch() (API_BASE + path, headers Authorization + Content-Type)
↓
HTTP Request (JSON, Bearer, query/path param)
↓
FastAPI (main.py: CORS + include_router + static)
↓
Router (auth.py / dashboard.py / orders.py / customers.py)
↓
Dependency / Authentication (get_bearer_token + get_authenticated_user + get_db_session; kecuali POST /login)
↓
SQLAlchemy (models.py via Session)
↓
SQLite (servisku.db)
↓
HTTP Response JSON (response_model atau dict/list)
```

Proteksi dipasang di `main.py:76-79`: `auth.router` terbuka, tiga router lain dibungkus `dependencies=[Depends(get_authenticated_user)]`. Di dalam router, setiap handler yang butuh DB memakai `db: Session = Depends(get_db_session)`.

## 3. AUTHENTICATION

Mekanisme aktual (`backend/routers/auth.py` + `dependencies.py`):

* **Login:** `POST /api/auth/login` dengan `{username, passcode}`. Cari `users` by username. Jika tidak ada atau `active` falsy → 401. Verifikasi `PBKDF2-HMAC-SHA256` 200.000 iterasi via `verify_passcode`. Jika salah → 401. Jika benar → `create_token()` (token acak `secrets.token_hex(32)`, `expires_at = utcnow + 7 hari`, simpan `auth_tokens`, update `users.last_login`) → return `{token, user}`.
* **Bearer token:** string hex 64 char, disimpan di `auth_tokens.token` (unique). Frontend simpan di `localStorage bsf_token` (Ingat Saya) atau `sessionStorage bsf_token`.
* **Header Authorization:** wajib format `Bearer <token>`. Diambil via `get_bearer_token(authorization: str = Header(None))` → `require_authorization_header`. Tanpa header atau tanpa prefix → 401 `Tidak terautentikasi.`
* **Cara backend mengambil user:** `get_authenticated_user(token, db)` → `get_current_user(db, token)`: cari `auth_tokens` by token → cek expired → cari `users` by `user_id` → cek aktif → return `User`.
* **Token expiration:** `TOKEN_TTL_DAYS = 7`. Jika `expires_at < utcnow` → hapus token + commit → 401 `Sesi telah kedaluwarsa.`
* **Logout:** `POST /api/auth/logout` (butuh Bearer valid + user valid). Hapus baris token saat ini → `{"ok": True}`.
* **Kondisi token invalid:** token tidak ada di DB → 401 `Sesi tidak valid.`
* **Kondisi token expired:** lihat expiration di atas → 401 `Sesi telah kedaluwarsa.`
* **Kondisi akun inactive:** user tidak ditemukan atau `active` falsy saat login maupun saat validasi token → 401 (`Username atau passcode salah.` saat login, `Akun tidak aktif.` saat validasi token).

Token/credential aktual tidak ditulis di dokumen ini.

## 4. ENDPOINT INVENTORY

Total **21 endpoint API** (3 auth + 3 dashboard + 9 orders + 6 customers) + 3 static. Status REAL = terimplementasi di source; MOCK = response hardcode tetapi endpoint nyata.

### AUTH (`backend/routers/auth.py`, prefix `/api/auth`)

| Method | Endpoint | Auth | Fungsi | Status |
| ------ | -------- | ---- | ------ | ------ |
| POST | /api/auth/login | Tidak | Login, kembalikan token + user | REAL |
| POST | /api/auth/logout | Ya | Hapus token saat ini | REAL |
| GET | /api/auth/me | Ya | Validasi sesi, kembalikan user | REAL |

### DASHBOARD (`backend/routers/dashboard.py`, prefix `/api`)

| Method | Endpoint | Auth | Fungsi | Status |
| ------ | -------- | ---- | ------ | ------ |
| GET | /api/overview | Ya | Star cards + insight + stats order | REAL (hitung) + MOCK (finansial) |
| GET | /api/statistics/status | Ya | Series Masuk/Selesai/Pending 7 hari | MOCK (angka hardcode) |
| GET | /api/statistics/damage | Ya | Kategori + data kerusakan | MOCK (angka hardcode) |

### ORDERS / TRANSACTIONS (`backend/routers/orders.py`, prefix `/api/orders`)

| Method | Endpoint | Auth | Fungsi | Status |
| ------ | -------- | ---- | ------ | ------ |
| GET | /api/orders | Ya | List paged (page/limit, max 10) | REAL |
| GET | /api/orders/latest | Ya | N terbaru (query limit) | REAL, belum dipakai frontend |
| GET | /api/orders/technicians | Ya | List teknisi statis | REAL |
| GET | /api/orders/history/{phone} | Ya | 20 order terakhir per no HP | REAL |
| POST | /api/orders/receive | Ya | Terima unit baru (customer+order) | REAL |
| POST | /api/orders | Ya | Buat order generik (butuh customer_id) | REAL, belum dipakai frontend |
| GET | /api/orders/{order_id} | Ya | Detail satu order | REAL, belum dipakai frontend |
| PUT | /api/orders/{order_id} | Ya | Update parsial order | REAL, belum dipakai frontend |
| DELETE | /api/orders/{order_id} | Ya | Hapus order (cascade payment) | REAL, belum dipakai frontend |

### CUSTOMERS (`backend/routers/customers.py`, prefix `/api/customers`)

| Method | Endpoint | Auth | Fungsi | Status |
| ------ | -------- | ---- | ------ | ------ |
| GET | /api/customers | Ya | List semua customer | REAL, belum dipakai frontend |
| GET | /api/customers/summary | Ya | Master + ringkasan servis, paged max 10 | REAL |
| GET | /api/customers/{customer_id} | Ya | Detail satu customer | REAL, belum dipakai frontend |
| POST | /api/customers | Ya | Buat customer | REAL, belum dipakai frontend |
| PUT | /api/customers/{customer_id} | Ya | Update customer | REAL, belum dipakai frontend |
| DELETE | /api/customers/{customer_id} | Ya | Hapus customer | REAL, belum dipakai frontend |

Static (bukan API JSON, dicatat agar tidak dikira API): `GET /` → index.html, `GET /static/*` → frontend/, `GET /favicon.ico` → logo.

## 5. DETAIL SETIAP ENDPOINT

### POST /api/auth/login

**Fungsi:** Login, buat sesi baru.

**Authentication:** Not required.

**Request:**
```json
{
  "username": "string (required)",
  "passcode": "string (required)"
}
```
Schema: `LoginRequest` (`auth.py:23-25`).

**Response:**
```json
{
  "token": "string hex",
  "user": { "id": 1, "username": "string", "display_name": "string", "role": "string" }
}
```
Schema: `LoginResponse{token, user: UserOut}`. `UserOut` hanya 4 field (tanpa hash/salt).

**HTTP Status:** 200 sukses (default POST tanpa `status_code` khusus); 401 gagal; 422 validasi kosong.

**Error:** 401 `Username atau passcode salah.` (user tidak ada / nonaktif / passcode salah).

**Database:** `users` (baca + update `last_login`), `auth_tokens` (insert).

### POST /api/auth/logout

**Fungsi:** Hapus token sesi saat ini.

**Authentication:** Required (Bearer + user valid, dua dependency sekaligus).

**Request:** Tanpa body. Header `Authorization: Bearer <token>` wajib.

**Response:**
```json
{ "ok": true }
```
Tanpa `response_model`.

**HTTP Status:** 200 sukses; 401 tanpa/invalid/expired token atau akun nonaktif.

**Error:** 401 `Tidak terautentikasi.` / `Sesi tidak valid.` / `Sesi telah kedaluwarsa.` / `Akun tidak aktif.`

**Database:** `auth_tokens` (delete by token).

### GET /api/auth/me

**Fungsi:** Validasi sesi + kembalikan user saat ini.

**Authentication:** Required (`Depends(get_authenticated_user)`).

**Request:** Header Bearer saja.

**Response:**
```json
{ "id": 1, "username": "string", "display_name": "string", "role": "string" }
```
Schema: `UserOut`.

**HTTP Status:** 200 sukses; 401 sesuai kondisi token/akun.

**Error:** Sama seperti logout.

**Database:** `auth_tokens` (baca), `users` (baca).

### GET /api/overview

**Fungsi:** Data star cards + insight + stats untuk dashboard.

**Authentication:** Required (global di `main.py`).

**Request:** Tanpa param. Handler: `get_overview(db)`.

**Response (bentuk aktual dari `dashboard.py:34-49`):**
```json
{
  "star_cards": [
    { "label": "Omset Hari Ini", "value": 0, "change": "+12% dari kemarin", "up": true },
    { "label": "Laba Kotor", "value": 8750000, "change": null, "up": null },
    { "label": "Total Beban", "value": 3750000, "change": null, "up": null },
    { "label": "Laba Bersih", "value": 5000000, "change": "+8% dari bulan lalu", "up": true },
    { "label": "Target Gaji (CTS)", "value": 15000000, "change": "Tercapai 83%", "up": true }
  ],
  "insight": [
    { "value": 0, "label": "Unit Masuk", "color": "text-cyan-600" },
    { "value": 0, "label": "Unit Selesai", "color": "text-green-600" },
    { "value": 0, "label": "Unit Cash", "color": "text-emerald-600" },
    { "value": 0, "label": "Unit Pending", "color": "text-amber-600" }
  ],
  "stats": { "total": 0, "done": 0, "active": 0, "pending": 0, "ready": 0 }
}
```
Hanya `star_cards[0].value` (sum `payment`), seluruh `insight` dan `stats` dihitung dari `service_orders` (REAL). `star_cards[1..4]` hardcode (MOCK). `piutang/cash` dihitung di variabel tetapi tidak dikembalikan (hanya dipakai internal `cash` untuk insight).

**HTTP Status:** 200; 401 tanpa token. Tanpa `response_model` (dict bebas).

**Error:** 401 standar. Tidak ada 404/422.

**Database:** `service_orders` (baca semua via ORM, hitung di Python).

### GET /api/statistics/status

**Fungsi:** Series line chart tren 7 hari.

**Authentication:** Required.

**Request:** Tanpa param.

**Response:**
```json
{
  "categories": ["...7 nama hari..."],
  "series": [
    { "name": "Masuk", "data": [12, 10, 14, 13, 16, 15, 18] },
    { "name": "Selesai", "data": [8, 9, 11, 10, 12, 13, 12] },
    { "name": "Pending", "data": [4, 3, 5, 6, 5, 4, 7] }
  ]
}
```
`categories` dinamis dari tanggal (REAL tanggal, MOCK isi). `series` full hardcode.

**HTTP Status:** 200; 401.

**Database:** Tidak query tabel (hanya `db` diinjeksi tanpa dipakai).

### GET /api/statistics/damage

**Fungsi:** Data bar chart kerusakan.

**Authentication:** Required.

**Request:** Tanpa param.

**Response:**
```json
{
  "categories": ["Layar Pecah", "Baterai", "Charging", "Speaker", "Kamera", "Water"],
  "data": [14, 9, 7, 5, 4, 3]
}
```
Full hardcode.

**HTTP Status:** 200; 401.

**Database:** Tidak query.

### GET /api/orders

**Fungsi:** Daftar order paged backend-side.

**Authentication:** Required.

**Request:** Query `?page=1&limit=10`. Default `page=1, limit=10`, clamp `page>=1, 1<=limit<=10` (`_page_clamp`).

**Response:** `ServiceOrderPage{total, page, limit, total_pages, items: ServiceOrderList[]}`. Tiap item: `id, no_servis, customer_id, device, brand, model, damagetype, device_password, repair_plan, technician, status, estimate, payment, service_date, created_at, customer_name, customer_phone`. Catatan aktual: `_to_list_schema()` tidak mengisi `device_password/repair_plan` (selalu null di list) — terverifikasi dari source, jangan diperbaiki di sini.

**HTTP Status:** 200; 401; 422 jika page/limit bukan int.

**Error:** 401 standar.

**Database:** `service_orders` (count + select `joinedload(customer)` order `created_at desc`), `customers` (join untuk nama/phone).

### GET /api/orders/latest

**Fungsi:** N order terbaru tanpa pagination metadata.

**Authentication:** Required.

**Request:** Query `?limit=10` (tanpa clamp `MAX_LIMIT`, langsung dipakai di `.limit(limit)`).

**Response:** `list[ServiceOrderList]` (bentuk item sama, tetapi kode ini mengisi tanpa `device_password/repair_plan` juga — hanya field yang ditulis eksplisit).

**HTTP Status:** 200; 401.

**Database:** `service_orders + customers`.

### GET /api/orders/technicians

**Fungsi:** Daftar teknisi statis untuk dropdown.

**Authentication:** Required (global; tanpa `Depends` tambahan di handler tetapi tetap protected oleh mount).

**Request:** Tanpa param/db.

**Response:**
```json
["Budi", "Andi", "Rizky", "Dedi", "Fajar"]
```
Konstanta `TECHNICIANS` (`orders.py:14`).

**HTTP Status:** 200; 401.

**Database:** Tidak ada.

### GET /api/orders/history/{phone}

**Fungsi:** History Cerdas — 20 order terakhir untuk satu nomor WA.

**Authentication:** Required.

**Request:** Path `phone: str` (exact match `Customer.phone == phone`).

**Response:** `list[ServiceOrder]` serialisasi ORM langsung (bukan `ServiceOrderList`; mencakup semua kolom model + relasi lazy sesuai `from_attributes`). Kosong `[]` jika phone tidak dikenal.

**HTTP Status:** 200; 401. Tidak ada 404 (phone tak dikenal → `[]`).

**Database:** `customers` (cari semua id by phone), `service_orders` (`where customer_id IN cids`, order `created_at desc`, limit 20).

### POST /api/orders/receive

**Fungsi:** Pendaftaran unit servis baru (buat/reuse customer + buat order).

**Authentication:** Required.

**Request (`ServiceReceiveIn`):**
```json
{
  "customer_name": "string (required)",
  "customer_phone": "string|null",
  "device": "string (required)",
  "device_password": "string|null",
  "damagetype": "string|null",
  "repair_plan": "string|null",
  "estimate": 0,
  "dp": 0,
  "technician": "string|null",
  "status": "ANALISA"
}
```

**Response:** `ServiceOrderOut` + `customer: CustomerOut|null`, status 201. `no_servis` auto `SV-YYYYMMDD-XXXX`, `service_date=today`, `payment=dp`, `brand/model` null (tidak diisi handler ini).

**HTTP Status:** 201 sukses; 401; 422 validasi.

**Error:** 401 standar; 422 jika field required kosong.

**Database:** `customers` (select by phone desc / insert), `service_orders` (insert).

### POST /api/orders

**Fungsi:** Buat order generik (caller tentukan semua field termasuk `no_servis`).

**Authentication:** Required.

**Request:** `ServiceOrderCreate` (= `ServiceOrderBase`: `no_servis required, customer_id required, device required, brand/model/damagetype/device_password/repair_plan/technician opsional, status default RECEIVED, estimate/payment default 0, service_date opsional`).

**Response:** `ServiceOrderOut`, status 201.

**HTTP Status:** 201; 400 jika `customer_id` tidak ada (`Customer tidak ditemukan`); 401; 422.

**Database:** `customers` (validasi), `service_orders` (insert).

### GET /api/orders/{order_id}

**Fungsi:** Detail satu order by id.

**Authentication:** Required.

**Request:** Path `order_id: int`.

**Response:** `ServiceOrderOut`.

**HTTP Status:** 200; 404 `Service order tidak ditemukan`; 401.

**Database:** `service_orders` (+ `customers` via relationship untuk response).

### PUT /api/orders/{order_id}

**Fungsi:** Update parsial (`exclude_unset=True`).

**Authentication:** Required.

**Request:** `ServiceOrderUpdate` (semua opsional: `customer_id/device/brand/model/damagetype/device_password/repair_plan/technician/status/estimate/payment`).

**Response:** `ServiceOrderOut` setelah commit+refresh.

**HTTP Status:** 200; 404 jika id tidak ada; 401.

**Database:** `service_orders` (update; tanpa validasi `customer_id` baru di handler ini).

### DELETE /api/orders/{order_id}

**Fungsi:** Hapus order (ikut hapus payment via cascade ORM).

**Authentication:** Required.

**Request:** Path id.

**Response:** `{"ok": True}` (tanpa response_model).

**HTTP Status:** 200; 404; 401.

**Database:** `service_orders` (delete), `payments` (cascade).

### GET /api/customers

**Fungsi:** List semua customer tanpa pagination.

**Authentication:** Required.

**Request:** Tanpa param.

**Response:** `list[CustomerOut]` (`id, name, phone, email, address, created_at`, order `created_at desc`).

**HTTP Status:** 200; 401.

**Database:** `customers`.

### GET /api/customers/summary

**Fungsi:** Master pelanggan + ringkasan servis terakhir, paged.

**Authentication:** Required.

**Request:** Query `?page=1&limit=10`, clamp sama (max 10).

**Response:** `CustomerSummaryPage{total, page, limit, total_pages, items: CustomerSummary[]}`. Item: `id, name, phone, last_device (o.device), last_action (o.repair_plan), last_price (o.estimate), total_servis (count)`. Sorting: `last_at desc nullslast, created_at desc`.

**HTTP Status:** 200; 401; 422.

**Database:** `customers` (count + page), `service_orders` (agregat `count/max(created_at)` + select terbaru per `customer_id` di halaman).

### GET /api/customers/{customer_id}

**Fungsi:** Detail satu customer.

**Authentication:** Required. Catatan routing: didefinisikan setelah `/summary`, sehingga `/summary` tidak tertelan path param (FastAPI match berurutan; aktual aman).

**Request:** Path id int.

**Response:** `CustomerOut`.

**HTTP Status:** 200; 404 `Customer tidak ditemukan`; 401.

**Database:** `customers`.

### POST /api/customers

**Fungsi:** Buat customer.

**Authentication:** Required.

**Request:** `CustomerCreate{name required, phone/email/address opsional}`.

**Response:** `CustomerOut`, status 201.

**HTTP Status:** 201; 401; 422.

**Database:** `customers` (insert).

### PUT /api/customers/{customer_id}

**Fungsi:** Update parsial customer.

**Authentication:** Required.

**Request:** `CustomerUpdate` (semua opsional).

**Response:** `CustomerOut`.

**HTTP Status:** 200; 404; 401.

**Database:** `customers`.

### DELETE /api/customers/{customer_id}

**Fungsi:** Hapus customer.

**Authentication:** Required.

**Request:** Path id.

**Response:** `{"ok": True}`.

**HTTP Status:** 200; 404; 401.

**Database:** `customers` (delete; tanpa cascade terdefinisi — hapus customer ber-order perlu verifikasi FK).

## 6. AUTH API

Alur aktual sesuai source:

```
Frontend (#loginForm: username + passcode)
→ POST /api/auth/login {username, passcode}
→ validasi user (ada + active)
→ validasi password (PBKDF2 verify)
→ create token (insert auth_tokens + update last_login)
→ token + user dikembalikan {token, user:{id,username,display_name,role}}
→ frontend menyimpan token (localStorage jika Ingat Saya else sessionStorage) + username/remember
→ token digunakan pada request berikutnya (apiGet/apiPost/fetch me/logout)
→ GET /api/auth/me untuk validasi sesi saat load
→ POST /api/auth/logout untuk keluar (hapus token)
```

Hanya langkah di atas yang ada. Tidak ada register, reset password, refresh token, OAuth, atau role check.

## 7. DASHBOARD API

* `GET /api/overview` — Tanpa parameter. Response `star_cards[5] + insight[4] + stats`. Dihitung dari DB: `total/done/active/pending/ready` (filter status), `omset = sum(payment)`, `cash = count(payment>0)`, insight 4 nilai. Masih hardcoded: `laba_kotor=8750000`, `total_beban=3750000`, `laba_bersih=laba-total`, `target_gaji=15000000`, seluruh `change/up` badge. Komentar source: `dummy finansial (karena belum ada tabel expenses)`.
* `GET /api/statistics/status` — Tanpa parameter. Response `categories[7 hari dinamis] + series[Masuk/Selesai/Pending]`. Data series hardcode, bukan agregat DB.
* `GET /api/statistics/damage` — Tanpa parameter. Response `categories[6] + data[6]` hardcode.

Jangan menganggap angka finansial/chart sebagai data toko. Schema `DashboardOverview/OverviewItem` di `schemas.py` terdefinisi tetapi tidak dipakai oleh ketiga endpoint ini (mereka return dict bebas).

## 8. ORDERS / SERVICE API

Sembilan endpoint di section 4–5. Ringkasan operasional:

* **Create/intake:** `POST /receive` (dipakai UI Servis Baru; reuse customer by phone; auto nomor; default status `ANALISA`) vs `POST /` generik (tidak dipakai UI; caller wajib isi `no_servis+customer_id`; default status `RECEIVED`). Keduanya return `ServiceOrderOut` 201 dan menyentuh `customers + service_orders`.
* **List:** `GET /` (paged, dipakai Transaksi; clamp max 10; join customer) vs `GET /latest` (limit mentah, tidak dipakai UI).
* **Detail/update/delete:** `GET/PUT/DELETE /{order_id}` tersedia tetapi belum dipanggil frontend (detail UI masih `alert`).
* **Helper:** `GET /technicians` (dipakai dropdown Servis Baru), `GET /history/{phone}` (dipakai History Cerdas).
* **Schema:** request `ServiceReceiveIn` (intake) / `ServiceOrderCreate` (generik) / `ServiceOrderUpdate` (parsial); response `ServiceOrderOut` (detail/intake) / `ServiceOrderList` (list) / `ServiceOrderPage` (paged).
* **Parameter:** path `order_id:int`, `phone:str`; query `page:int`, `limit:int` (clamp hanya di `GET /`, tidak di `/latest`).
* **Auth:** semua required (via mount global).
* **Table:** `service_orders` utama + `customers` (validasi/join/reuse). `payments` hanya tersentuh indirect via cascade delete.
* **Status:** bebas teks di DB; default model `RECEIVED`, default intake `ANALISA`; seed memakai 8 status lain; dashboard grouping tidak mencakup `ANALISA` (ketidaksesuaian terdokumentasi di `DATABASE.md`, tidak diperbaiki di sini).

## 9. CUSTOMERS API

Enam endpoint di section 4–5. Hubungan `Customer → Service Orders` (1→N):

* **List:** `GET /` (full list, tidak dipakai UI) vs `GET /summary` (dipakai UI Pelanggan; agregat count/max + order terakhir per halaman; `last_action=repair_plan`, `last_price=estimate`).
* **Detail/CRUD:** `GET/POST/PUT/DELETE` tersedia tetapi belum dipanggil frontend (UI Pelanggan read-only summary).
* **History:** tidak ada di router customers; history by phone hidup di `GET /api/orders/history/{phone}`.
* Schema: request `CustomerCreate` (full required name) / `CustomerUpdate` (parsial); response `CustomerOut` / `CustomerSummary` / `CustomerSummaryPage`.

## 10. SCHEMA / REQUEST / RESPONSE

Ringkasan dari `schemas.py` + `LoginRequest/UserOut/LoginResponse` di `auth.py`. Tipe Pydantic aktual.

Auth schemas (request + response, di `auth.py`):

| Field | Type | Required | Default | Keterangan |
| ----- | ---- | -------- | ------- | ---------- |
| LoginRequest.username | str | Ya | — | Request login |
| LoginRequest.passcode | str | Ya | — | Request login, plain di JSON |
| UserOut.id | int | Ya | — | Response |
| UserOut.username | str | Ya | — | Response |
| UserOut.display_name | str | Ya | — | Response |
| UserOut.role | str | Ya | — | Response, tanpa enforcement |
| LoginResponse.token | str | Ya | — | Response |
| LoginResponse.user | UserOut | Ya | — | Response |

Service Order schemas (`schemas.py`):

| Field | Type | Required | Default | Keterangan |
| ----- | ---- | -------- | ------- | ---------- |
| ServiceOrderBase.no_servis | str | Ya | — | Request generik + response |
| ServiceOrderBase.customer_id | int | Ya | — | Request generik + response |
| ServiceOrderBase.device | str | Ya | — | Request + response |
| ServiceOrderBase.brand/model/damagetype/device_password/repair_plan/technician | str/Text/null | Tidak | None | Request + response |
| ServiceOrderBase.status | str/null | Tidak | RECEIVED | Request generik + response |
| ServiceOrderBase.estimate/payment | float/null | Tidak | 0 | Request + response |
| ServiceOrderBase.service_date | date/null | Tidak | None | Request + response |
| ServiceReceiveIn.customer_name | str | Ya | — | Request intake saja |
| ServiceReceiveIn.customer_phone | str/null | Tidak | None | Request intake, dipakai reuse |
| ServiceReceiveIn.device | str | Ya | — | Request intake |
| ServiceReceiveIn.device_password/damagetype/repair_plan/technician | str/null | Tidak | None | Request intake |
| ServiceReceiveIn.estimate/dp | float/null | Tidak | 0 | Request intake (`dp`→`payment`) |
| ServiceReceiveIn.status | str/null | Tidak | ANALISA | Request intake |
| ServiceOrderUpdate.* | masing-masing opsional | Tidak | — (exclude_unset) | Request update parsial saja |
| ServiceOrderOut.id/created_at/customer | int/datetime/CustomerOut-null | Ya (response) | — | Response detail/intake |
| ServiceOrderList.* | lihat detail endpoint | Ya (response) | — | Response list (termasuk customer_name/phone denormalisasi) |
| ServiceOrderPage.total/page/limit/total_pages/items | int/int/int/int/list | Ya (response) | — | Response paged |

Customer schemas:

| Field | Type | Required | Default | Keterangan |
| ----- | ---- | -------- | ------- | ---------- |
| CustomerBase.name | str | Ya | — | Request create + response |
| CustomerBase.phone/email/address | str/Text/null | Tidak | None | Request + response |
| CustomerUpdate.name/phone/email/address | str/null | Tidak | None (parsial) | Request update saja |
| CustomerOut.id/created_at | int/datetime | Ya (response) | — | Response |
| CustomerSummary.id/name/phone/last_device/last_action/last_price/total_servis | mixed | Ya (response, nullable kecuali id/name/total) | — | Response summary |
| CustomerSummaryPage.total/page/limit/total_pages/items | int/list | Ya (response) | — | Response paged |

Payment/Dashboard schemas (terdefinisi, belum dipakai endpoint):

| Field | Type | Required | Default | Keterangan |
| ----- | ---- | -------- | ------- | ---------- |
| PaymentBase.service_order_id/amount | int/float | Ya | — | Schema saja, tanpa router |
| PaymentBase.method/note | str/null | Tidak | CASH/None | Schema saja |
| PaymentOut.id/created_at | int/datetime | Ya (response) | — | Schema saja |
| OverviewItem.label/value | str/float | Ya | — | Schema saja |
| DashboardOverview.* | mixed | Ya | — | Schema saja, endpoint overview return dict bebas |

## 11. AUTHORIZATION VS AUTHENTICATION

Kondisi aktual:

**Authentication (apakah user sudah login?):** Ya, enforced. Semua router kecuali `POST /login` wajib Bearer valid via `get_authenticated_user`. Gagal → 401 dengan pesan spesifik (tidak terautentikasi / sesi tidak valid / kedaluwarsa / akun nonaktif).

**Authorization (apakah role membatasi akses?):** BELUM ADA. Kolom `users.role` tersimpan dan dikembalikan di `UserOut`, tetapi tidak ada `Depends` peran, tidak ada cek `role == ...` di router mana pun, tidak ada perbedaan endpoint per peran. Teknisi dan admin memiliki akses API identik saat ini.

Ditulis eksplisit agar tidak diperbaiki sekarang: jangan menambahkan role guard tanpa instruksi.

## 12. FRONTEND ↔ API

Komunikasi yang benar-benar ada (terverifikasi `script.js`):

```
Frontend → endpoint → request → response → update UI
- loadDashboard/renderStarCards/renderInsights → GET /overview → star_cards/insight/stats → kartu KPI + insight
- renderStatusMini + chart → GET /statistics/status → categories/series → ApexCharts line
- renderDamageSection → GET /statistics/damage → categories/data → bar kerusakan
- loadTxPage → GET /orders?page&limit → ServiceOrderPage → txBody/txInfo/txPageBtns
- loadPlPage → GET /customers/summary?page&limit → CustomerSummaryPage → plBody/plInfo/plPageBtns
- checkSession → GET /auth/me (fetch manual + Bearer) → UserOut atau AuthError → tetap login / kembali login
- loginForm → POST /auth/login (fetch manual JSON) → {token,user} → simpan token → loadDashboard
- logout → POST /auth/logout (fetch manual + Bearer) → clearToken
- loadSmartHistory → GET /orders/history/{phone} → list order → History Cerdas
- form Servis Baru init → GET /orders/technicians → list teknisi → dropdown
- submit Servis Baru → POST /orders/receive (apiPost) → ServiceOrderOut → tutup modal + reload transaksi
```

Garansi/Sparepart/Keuangan/Kelola Akun tidak memanggil API (render mock/static lokal). Endpoint `POST/GET/PUT/DELETE` generik orders/customers + `GET /orders/latest` tersedia tetapi belum dipanggil frontend.

## 13. API YANG BELUM TERSEDIA

`## API YANG BELUM TERSEDIA` — gap terverifikasi dari source (router tidak ditemukan, tabel tidak ada di `models.py`):

* **Sparepart API** — BELUM ADA. Tidak ada router/tabel/schema. UI (`SP_MOCK`) mock.
* **Garansi API** — BELUM ADA. Tidak ada router/tabel/schema. UI (`GR_MOCK`) mock.
* **Keuangan API (kas/alokasi/riwayat)** — BELUM ADA. Tidak ada router/tabel. UI (`KU_*`) in-memory.
* **Expense/Beban API** — BELUM ADA. Beban hanya angka hardcode overview + option form mock.
* **User Management API** — BELUM ADA. Tidak ada `GET/POST/PUT /api/users`. UI akun hardcode.
* **Payment API mandiri** — BELUM ADA sebagai router. Schema `Payment*` ada di `schemas.py` tetapi tanpa endpoint; tabel `payments` hanya ditulis via seed dan cascade delete.

Klasifikasi: di atas adalah PLANNED API (dibutuhkan UI) atau setidaknya gap; saat ini UI terkait adalah MOCK UI, bukan REAL API. Jangan membuat endpoint tersebut tanpa instruksi.

## 14. API LIMITATIONS / TECHNICAL DEBT

Terverifikasi dari source:

* **Authorization role belum enforced** (`role` hanya data, tanpa guard).
* **Pagination batas keras:** `MAX_LIMIT=10` di orders/customers list/summary (`_page_clamp`/clamp manual). `GET /orders/latest` tanpa clamp tetapi UI tidak memakainya.
* **Endpoint tersedia tetapi belum digunakan frontend:** `POST /api/orders`, `GET /api/orders/{id}`, `PUT/DELETE /api/orders/{id}`, `GET /api/orders/latest`, seluruh CRUD generik customers kecuali summary. Risiko endpoint tak teruji UI.
* **Mapping response belum lengkap:** `_to_list_schema()` (list paged) dan builder manual `/latest` tidak mengisi `device_password/repair_plan` meski ada di `ServiceOrderList` (hasilnya null). `GET /overview` menghitung `piutang` tetapi tidak mengembalikannya.
* **Validation sederhana:** `status/technician/method` teks bebas tanpa enum; `no_servis` acak tanpa cek collision unik (mengandalkan constraint DB); `PUT /orders` tidak validasi `customer_id` baru; `service_date` default model dievaluasi saat import; CORS `allow_origins=["*"] + allow_credentials=True` kontradiktif untuk browser.
* **`DashboardOverview` tidak dipakai**, `func` diimpor di `dashboard.py` tanpa dipakai, `GET /` dan static di luar skema OpenAPI (`include_in_schema=False` implisit untuk static).

## 15. API DEVELOPMENT WORKFLOW

```text
BEFORE API CHANGE

→ baca AI_CONTEXT.md
→ baca ARCHITECTURE.md
→ baca DATABASE.md
→ baca API.md
→ identifikasi router
→ identifikasi schema
→ identifikasi dependency/auth
→ identifikasi database yang terdampak
→ identifikasi frontend yang menggunakan API
→ baru rencanakan perubahan
```

```text
AFTER API CHANGE

→ test endpoint
→ test request
→ test response
→ test authentication
→ test frontend integration
→ update API.md
→ update CHANGELOG.md
→ git commit
```

## 16. SOURCE OF TRUTH

Untuk API:

1. Source code router = sumber kebenaran endpoint
2. `schemas.py` = sumber kebenaran request/response schema
3. `dependencies.py` + auth router = sumber kebenaran authentication
4. `API.md` = dokumentasi pemahaman API

Jika dokumentasi berbeda dengan source code:
→ verifikasi source code
→ jangan menebak
→ update dokumentasi

## 17. LAST VERIFIED

* Tanggal dokumentasi: 2026-09-07 (UTC).
* Konteks dibaca: `docs/AI_CONTEXT.md`, `docs/ARCHITECTURE.md`, `docs/DATABASE.md`.
* Source diperiksa langsung: `backend/main.py` (penuh), `backend/schemas.py` (penuh), `backend/dependencies.py` (penuh), `backend/routers/auth.py` (penuh), `backend/routers/dashboard.py` (penuh), `backend/routers/orders.py` (penuh), `backend/routers/customers.py` (penuh); selektif `frontend/script.js` (hanya baris API layer + pemanggilan `apiGet/apiPost/auth`).
* Source code tidak diubah. Database tidak diubah. Endpoint baru tidak dibuat. Credential/token/secret tidak ditulis.
