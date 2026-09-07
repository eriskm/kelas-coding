# BOSS SF — DATABASE

> Dokumentasi struktur database AKTUAL BOSS SF.
> Sumber kebenaran: `backend/models.py` dan `servisku.db`.
> Dokumen ini hanya pemahaman, bukan pengganti source code.

## 1. DATABASE OVERVIEW

* **Database yang digunakan:** SQLite (tanpa server terpisah).
* **Nama file database:** `servisku.db`.
* **Lokasi:** root project (`E:\PRAKTEK MJPRO\servisku.db`). Path di-hardcode di `backend/database.py` sebagai `DB_PATH = <root>/servisku.db` dengan URL `sqlite:///{DB_PATH}`.
* **ORM:** SQLAlchemy `2.0.52` (`declarative_base`, `sessionmaker`, `joinedload`). Model di `backend/models.py`, session di `backend/database.py`, dependency di `backend/dependencies.py`.
* **Cara koneksi:** `create_engine(..., connect_args={"check_same_thread": False})` + `SessionLocal(autocommit=False, autoflush=False, bind=engine)` + generator `get_db()` yang di-wrap `get_db_session()` untuk FastAPI `Depends`.
* **Migration framework:** BELUM ADA (tanpa Alembic).
* **Kondisi migration aktual:** `Base.metadata.create_all(bind=engine)` setiap startup + migrasi ringan manual `_migrate_schema()` di `backend/main.py` (cek `PRAGMA table_info(service_orders)` lalu `ALTER TABLE ADD COLUMN` untuk `device_password` dan `repair_plan` jika belum ada). Seed idempotent di `backend/seed.py` dijalankan dari `jalankan.bat` dan dari `on_startup`.

## 2. DATABASE ARCHITECTURE

Diagram relasi aktual (100% sesuai `backend/models.py`):

```
users
↓ (1 users → N auth_tokens via auth_tokens.user_id)
auth_tokens

customers
↓ (1 customers → N service_orders via service_orders.customer_id)
service_orders
↓ (1 service_orders → N payments via payments.service_order_id, delete-orphan)
payments
```

Tidak ada relasi lain. Tidak ada tabel silang. `users` tidak berelasi langsung ke `customers/service_orders/payments`.

## 3. TABLES

### users

Fungsi:
Akun sistem untuk login. Satu-satunya tabel identitas pengguna.

Primary Key:
`id`

Columns:

| Column | Type | Nullable | Default | Unique | Description |
| ------ | ---- | -------- | ------- | ------ | ----------- |
| id | Integer | NO (PK) | autoincrement | NO (indexed) | Primary key |
| username | String(80) | NO | — | YES (indexed) | Username login, unik |
| display_name | String(120) | NO | — | NO | Nama tampil di UI |
| role | String(40) | YES | ADMIN | NO | Peran teks, default ADMIN |
| passcode_hash | String(255) | NO | — | NO | Hash PBKDF2 passcode, jangan ditampilkan |
| passcode_salt | String(64) | NO | — | NO | Salt hex, jangan ditampilkan |
| active | Integer | YES | 1 | NO | 1=aktif, 0=nonaktif; login ditolak jika tidak aktif |
| last_login | DateTime | YES | — | NO | Diupdate saat login berhasil |
| created_at | DateTime | YES | datetime.utcnow | NO | Waktu buat akun |

Foreign Key:
BELUM ADA (tidak punya FK keluar).

Relationship:
Implisit `1 users → N auth_tokens` via `AuthToken.user_id`. Tidak ada `relationship` didefinisikan di sisi `User`.

Catatan:
Nilai `role` aktual di seed mencakup `SUPERADMIN`, di model default `ADMIN`, di UI hardcode ada `Admin/Teknisi`. Perlu verifikasi/konsistensi. Kolom `active` bertipe Integer bukan Boolean.

### auth_tokens

Fungsi:
Sesi login persisten (Bearer token).

Primary Key:
`id`

Columns:

| Column | Type | Nullable | Default | Unique | Description |
| ------ | ---- | -------- | ------- | ------ | ----------- |
| id | Integer | NO (PK) | autoincrement | NO (indexed) | Primary key |
| token | String(64) | NO | — | YES (indexed) | Token acak hex, jangan ditampilkan |
| user_id | Integer | NO | — | NO | FK ke users.id |
| created_at | DateTime | YES | datetime.utcnow | NO | Waktu token dibuat |
| expires_at | DateTime | NO | — | NO | Waktu kedaluwarsa (now + TTL) |

Foreign Key:
`user_id → users.id` (`ForeignKey("users.id")`, nullable=False).

Relationship:
`user = relationship("User")` (many-to-one ke `User`).

Catatan:
Token dibuat dengan `secrets.token_hex(32)`. Satu user dapat memiliki banyak token aktif. Token kedaluwarsa dihapus saat diakses.

### customers

Fungsi:
Master data pelanggan (identitas, bukan transaksi).

Primary Key:
`id`

Columns:

| Column | Type | Nullable | Default | Unique | Description |
| ------ | ---- | -------- | ------- | ------ | ----------- |
| id | Integer | NO (PK) | autoincrement | NO (indexed) | Primary key |
| name | String(100) | NO | — | NO | Nama pelanggan |
| phone | String(30) | YES | — | NO | No WA, dipakai reuse + history, tidak unik di DB |
| email | String(120) | YES | — | NO | Email, jarang diisi seed |
| address | Text | YES | — | NO | Alamat teks bebas |
| created_at | DateTime | YES | datetime.utcnow | NO | Waktu buat master |

Foreign Key:
BELUM ADA (tidak punya FK keluar).

Relationship:
`service_orders = relationship("ServiceOrder", back_populates="customer")` (1 customer → N order).

Catatan:
`phone` tidak unik, sehingga satu nomor WA bisa dimiliki beberapa baris customer. Reuse mengandalkan query, bukan constraint.

### service_orders

Fungsi:
Tabel inti. Satu baris = satu unit servis yang diterima.

Primary Key:
`id`

Columns:

| Column | Type | Nullable | Default | Unique | Description |
| ------ | ---- | -------- | ------- | ------ | ----------- |
| id | Integer | NO (PK) | autoincrement | NO (indexed) | Primary key |
| no_servis | String(50) | NO | — | YES (indexed) | Nomor servis unik, format SV-YYYYMMDD-XXXX (generate acak) |
| customer_id | Integer | NO | — | NO | FK ke customers.id |
| device | String(120) | NO | — | NO | Nama device, mis. Galaxy A55 |
| brand | String(60) | YES | — | NO | Merek |
| model | String(60) | YES | — | NO | Model |
| damagetype | String(120) | YES | — | NO | Jenis kerusakan teks bebas |
| device_password | String(120) | YES | — | NO | Password/pola device, ditambah via migrasi manual |
| repair_plan | Text | YES | — | NO | Rencana perbaikan, ditambah via migrasi manual |
| technician | String(60) | YES | — | NO | Nama teknisi teks bebas (bukan FK ke users) |
| status | String(30) | YES | RECEIVED | NO | Status order teks bebas |
| estimate | Float | YES | 0 | NO | Estimasi biaya |
| payment | Float | YES | 0 | NO | DP/pembayaran tercatat di order (terpisah dari tabel payments) |
| service_date | Date | YES | datetime.utcnow().date | NO | Tanggal servis (dievaluasi saat import, perlu verifikasi) |
| created_at | DateTime | YES | datetime.utcnow | NO | Waktu buat order, dipakai sorting desc |

Foreign Key:
`customer_id → customers.id` (`ForeignKey("customers.id")`, nullable=False).

Relationship:
`customer = relationship("Customer", back_populates="service_orders")`; `payments = relationship("Payment", back_populates="service_order", cascade="all, delete-orphan")`.

Catatan:
Hapus order menghapus payment terkait (delete-orphan). `technician` bukan FK. Ada dua pencatatan uang: `service_orders.payment/estimate` dan `payments.amount` — relasinya tidak dijaga otomatis oleh DB.

### payments

Fungsi:
Riwayat pembayaran yang terkait satu service order.

Primary Key:
`id`

Columns:

| Column | Type | Nullable | Default | Unique | Description |
| ------ | ---- | -------- | ------- | ------ | ----------- |
| id | Integer | NO (PK) | autoincrement | NO (indexed) | Primary key |
| service_order_id | Integer | NO | — | NO | FK ke service_orders.id |
| amount | Float | NO | — | NO | Nominal bayar |
| method | String(30) | YES | CASH | NO | Metode, default CASH |
| note | String(200) | YES | — | NO | Catatan pendek |
| created_at | DateTime | YES | datetime.utcnow | NO | Waktu bayar |

Foreign Key:
`service_order_id → service_orders.id` (`ForeignKey("service_orders.id")`, nullable=False).

Relationship:
`service_order = relationship("ServiceOrder", back_populates="payments")`.

Catatan:
Model sudah ada dan dipakai seed, tetapi API/UI khusus pembayaran BELUM ADA sebagai fitur mandiri. Lihat section 9.

## 4. USERS

* Fungsi tabel: satu-satunya identitas akun sistem untuk login.
* `username`: `String(80)`, unik + indexed, `nullable=False`. Dipakai sebagai key login di `POST /api/auth/login`.
* `role`: `String(40)`, default model `ADMIN`. Nilai aktual yang ditemukan: `SUPERADMIN` (seed), `ADMIN` (default), `Admin/Teknisi` (UI hardcode Kelola Akun). Kolom ini tersimpan tetapi belum dipakai untuk authorization di router. Perlu verifikasi/konsistensi.
* `active`: `Integer` default `1`. Login ditolak jika user tidak ada, `active` falsy, atau passcode salah. Nonaktif dipakai untuk blokir akun tanpa hapus baris.
* Passcode hash: `passcode_hash String(255) nullable=False` + `passcode_salt String(64) nullable=False`. Dibuat/diverifikasi dengan `hash_passcode/verify_passcode` (PBKDF2-HMAC-SHA256, 200.000 iterasi, `hmac.compare_digest`). Nilai aktual tidak ditulis di dokumen ini.
* Salt: hex acak per user (`secrets.token_hex(16)` di seed).
* `last_login`: `DateTime` nullable, diupdate ke `utcnow` setiap `create_token` berhasil.
* `created_at`: `DateTime` default `utcnow`.
* Relationship dengan auth_tokens: `1 users → N auth_tokens` via `auth_tokens.user_id`. Sisi `User` tidak mendefinisikan `relationship`; sisi `AuthToken` mendefinisikan `user = relationship("User")`.
* JANGAN menulis credential/password aktual di dokumentasi mana pun.

## 5. AUTH_TOKENS

* Fungsi token: sesi Bearer persisten. Frontend mengirim `Authorization: Bearer <token>` di `apiGet/apiPost`; backend memvalidasi via `get_bearer_token → get_authenticated_user → get_current_user`.
* Hubungan dengan users: `auth_tokens.user_id → users.id` (many-to-one).Из `AuthToken.user` dapat diakses user pemilik.
* `created_at`: default `utcnow`.
* `expires_at`: wajib diisi, `nullable=False`, dihitung `utcnow + TTL` saat `create_token`.
* TTL berdasarkan implementasi aktual: `TOKEN_TTL_DAYS = 7` di `backend/routers/auth.py`. Jika `expires_at < utcnow` saat diakses, token dihapus + commit lalu 401 `Sesi telah kedaluwarsa`. Jika token tidak ada → 401 `Sesi tidak valid`. Jika user tidak ada/tidak aktif → 401 `Akun tidak aktif`.
* Jangan menampilkan token aktual di dokumentasi, log, atau commit.

## 6. CUSTOMERS

* Customer sebagai master data: identitas (`name/phone/email/address`) terpisah dari transaksi. Transaksi hidup di `service_orders`.
* Kolom customer: lihat tabel di section 3 (`id, name required, phone/email/address opsional, created_at`).
* Hubungan dengan service_orders: `1 customers → N service_orders`. Akses via `Customer.service_orders` dan `ServiceOrder.customer`. Summary pelanggan (`GET /api/customers/summary`) menghitung `count(service_orders)` + `max(created_at)` + order terakhir per customer.
* Prinsip: satu customer dapat memiliki banyak service order. Buktinya: seed memakai customer index `0` dan `3` untuk dua order berbeda; summary menampilkan `total_servis`.
* Reuse customer berdasarkan nomor WhatsApp (sesuai `routers/orders.py:receive_unit`): jika `customer_phone` diisi, cari `Customer` dengan `phone` sama `order_by(id desc)` dan pakai baris pertama; jika tidak ketemu, buat `Customer(name, phone)` baru lalu commit. Karena `phone` tidak unik, duplikat nomor dimungkinkan dan history menggabungkan semua `customer_id` dengan phone sama (`GET /api/orders/history/{phone}` cari semua customer by phone lalu `service_order.customer_id IN cids`).

## 7. SERVICE_ORDERS

Tabel inti sistem servis. Seluruh kolom aktual dari `models.py`:

* `id`: PK autoincrement, dipakai di URL `/{order_id}` untuk get/update/delete.
* `no_servis`: unik + indexed, `nullable=False`. Format aktual `SV-YYYYMMDD-XXXX` (`_generate_no_servis`: tanggal hari ini + random 1000–9999). Seed memakai format sama dengan tanggal tetap.
* `customer_id`: FK wajib ke `customers.id`. `POST /api/orders` generik menolak jika customer tidak ada (400).
* `device`: wajib, nama device lengkap (mis. `Samsung Galaxy A54`). Dipakai kolom Device di UI Transaksi/Pelanggan.
* `brand`: opsional (`Samsung/Apple/Xiaomi/...`). Diisi seed, tetapi `receive_unit` aktual tidak mengisi brand/model (hanya device) — kolom bisa null untuk order baru. Perlu verifikasi/konsistensi.
* `model`: opsional (`A54/14 Pro/...`). Sama seperti brand.
* `damagetype`: teks bebas jenis kerusakan (`Layar Pecah/Baterai/Charging/Speaker/Kamera`). Dipakai chart tren kerusakan (saat ini chart masih dummy, bukan agregat kolom ini).
* `device_password`: `String(120)` opsional. Password/pola untuk buka device. Tidak ada di model awal, ditambah via `_migrate_schema`. Diinput di form Servis Baru, tersimpan di `receive` dan `update`, tetapi mapping list backend saat audit tidak meneruskannya (perlu verifikasi di `orders.py` sebelum mengandalkan list).
* `repair_plan`: `Text` opsional. Rencana/tindakan perbaikan. Sama seperti `device_password`: migrasi manual + ada di schema create/update/out, dipakai summary pelanggan sebagai `last_action`.
* `technician`: teks bebas, bukan FK. Daftar statis `TECHNICIANS = ["Budi","Andi","Rizky","Dedi","Fajar"]` di `orders.py`; seed memakai subset 4 nama. Tidak ada validasi FK ke `users`.
* `status`: `String(30)` default model `RECEIVED`. Nilai bebas di DB (tanpa check constraint). Default berbeda per entry: schema `ServiceOrderBase` default `RECEIVED`, `ServiceReceiveIn` default `ANALISA`. Lihat section 8 untuk daftar aktual.
* `estimate`: `Float` default `0`. Estimasi biaya. Dipakai kolom Laba UI dan hitung piutang (`estimate - payment`).
* `payment`: `Float` default `0`. Uang muka/pembayaran yang dicatat langsung di order. Diisi dari `dp` saat receive. Terpisah dari tabel `payments`; tidak ada trigger sinkronisasi.
* `service_date`: `Date` default `datetime.utcnow().date`. Catatan: ekspresi ini dievaluasi sekali saat import model, bukan per baris — perlu verifikasi jika tanggal menjadi usang pada proses lama. `receive_unit` selalu menimpa dengan `date.today()`.
* `created_at`: `DateTime` default `utcnow`. Dipakai sorting `order_by(created_at desc)` di list/latest/history/summary dan agregat pelanggan.

## 8. SERVICE ORDER STATUS

Status yang benar-benar ditemukan dalam source code (tanpa tambahan):

* `RECEIVED` — default `models.ServiceOrder.status` dan `schemas.ServiceOrderBase.status`.
* `ANALISA` — default `schemas.ServiceReceiveIn.status` (form Servis Baru).
* `DIAGNOSIS` — seed 1 baris + grup `active` di dashboard.
* `REPAIR` — seed 3 baris + grup `active` di dashboard.
* `QC` — seed 1 baris + grup `active` di dashboard.
* `WAITING_PART` — seed 1 baris + grup `pending` di dashboard.
* `WAITING_APPROVAL` — seed 1 baris + grup `pending` di dashboard.
* `READY` — seed 2 baris + grup `ready` di dashboard; dipakai seed payment (READY/COMPLETED yang amount>0 dibuatkan `Payment`).
* `COMPLETED` — seed 2 baris + grup `done` di dashboard.

Pemetaan dashboard aktual (`routers/dashboard.py`): `done = [COMPLETED]`, `active = [REPAIR,QC,RECEIVED,DIAGNOSIS]`, `pending = [WAITING_PART,WAITING_APPROVAL]`, `ready = [READY]`. `ANALISA` tidak masuk grup mana pun di dashboard. Perbedaan default (`RECEIVED` vs `ANALISA`) dan status tak terpetakan ini dicatat sebagai "Perlu verifikasi/konsistensi." Jangan menambahkan status baru di dokumen ini.

## 9. PAYMENTS

* Fungsi tabel: mencatat pembayaran per service order (`service_order_id`, `amount`, `method`, `note`, `created_at`).
* Hubungan dengan service_orders: `N payments → 1 service_orders` via `service_order_id → service_orders.id`, `back_populates` dua arah, hapus order cascade hapus payment.
* `amount`: `Float nullable=False`. Wajib diisi.
* `method`: `String(30)` default `CASH`. Seed selalu memakai `CASH`.
* `note`: `String(200)` opsional.
* `created_at`: default `utcnow`.
* Kondisi penggunaan saat ini: model sudah tersedia dan dipakai `seed.py` (setiap order seed dengan status READY/COMPLETED dan amount>0 dibuatkan satu `Payment` CASH). API/UI pembayaran mandiri BELUM ADA sebagai fitur: tidak ada router `payments.py`, tidak ada endpoint `/api/payments`, tidak ada form bayar di frontend. Angka `payment` yang terlihat di UI Transaksi berasal dari kolom `service_orders.payment/estimate`, bukan agregat tabel `payments`.

## 10. RELATIONSHIPS

* `users 1 → N auth_tokens`: FK `auth_tokens.user_id → users.id` (`nullable=False`). Akses balik `AuthToken.user`. Tidak ada cascade delete terdefinisi; hapus user dengan token aktif akan melanggar FK di SQLite jika enforced. Verifikasi perilaku hapus sebelum memakai.
* `customers 1 → N service_orders`: FK `service_orders.customer_id → customers.id` (`nullable=False`). Akses `Customer.service_orders` dan `ServiceOrder.customer` (`back_populates`). Tidak ada cascade terdefinisi; hapus customer dengan order aktif perlu verifikasi (risiko FK error atau orphan, tergantung enforcement SQLite).
* `service_orders 1 → N payments`: FK `payments.service_order_id → service_orders.id` (`nullable=False`). Akses `ServiceOrder.payments` dan `Payment.service_order` dengan `cascade="all, delete-orphan"` di sisi parent. Hapus order otomatis hapus payment-nya melalui ORM.
* Tidak ada relasi lain yang terdefinisi di `models.py`.

## 11. DATA OWNERSHIP / MASTER DATA

Berdasarkan kondisi aktual:

* `Customer → master customer`: pemilik identitas (`name/phone/email/address`). Hidup lebih lama dari transaksi. Tidak boleh dihapus sembarangan jika masih punya order (relasi FK).
* `Service Order → transaksi/unit servis`: pemilik data operasional (`no_servis/device/status/estimate/payment/technician/...`). Selalu menunjuk satu `customer_id`. Satu nomor servis unik.
* `Payment → pembayaran yang terkait service order`: anak dari order. Tidak berdiri sendiri; selalu menunjuk satu `service_order_id`. Hapus mengikuti parent.
* `User → akun sistem`: pemilik kredensial login (`username/role/active/hash/salt`). Tidak memiliki order/customer secara langsung di model.
* `Auth Token → session login`: anak dari user. Berumur pendek (TTL 7 hari). Boleh dihapus saat logout/expired tanpa memengaruhi user.

Jangan membuat konsep master baru (mis. master teknisi, master sparepart) karena belum ada di model.

## 12. CURRENTLY MISSING TABLES

BELUM ADA di `models.py` / `servisku.db` (gap sistem, UI sudah menunjukkan kebutuhan):

* `spareparts` → BELUM ADA. UI Sparepart (`SP_MOCK` + search + stok) 100% lokal, tanpa tabel/endpoint.
* `garansi` / warranties → BELUM ADA. UI Garansi (`GR_MOCK`) 100% lokal, tanpa relasi ke `service_orders`.
* `finance/cash` / buku kas → BELUM ADA. UI Keuangan (`KU_KAS/KU_RIWAYAT` + form tambah) in-memory, hilang saat refresh.
* `expenses/beban` (gaji, operasional, modal) → BELUM ADA. Angka beban dashboard hardcode; kategori beban hanya ada sebagai option di form mock.
* `profit_allocations` → BELUM ADA. Alokasi Bonus/Pengelola/Investor/Kas Aset hanya konstanta `KU_ALLOC` + chart.
* `user management detail` (auditing, peran rinci, teknisi master) → BELUM ADA sebagai tabel. Hanya kolom `users.role` + UI hardcode 5 akun tanpa backend.

Jangan membuat tabel tersebut sekarang. Section ini hanya dokumentasi gap agar Agent tidak mengira tabel sudah tersedia.

## 13. DATABASE MIGRATION

Kondisi aktual:

* `SQLAlchemy create_all`: `Base.metadata.create_all(bind=engine)` dipanggil di `seed.py:seed()` dan `main.py:on_startup`. Membuat tabel yang belum ada, tidak mengubah tabel yang sudah ada, tidak menghapus kolom.
* Migration manual: `_migrate_schema()` di `backend/main.py`. Loop daftar `migrations = [("service_orders","device_password","VARCHAR(120)"), ("service_orders","repair_plan","TEXT")]`. Untuk setiap entri: `PRAGMA table_info(service_orders)` → ambil nama kolom → jika belum ada → `ALTER TABLE service_orders ADD COLUMN ...`.
* `PRAGMA table_info`: dipakai untuk introspeksi kolom SQLite saat runtime.
* `ALTER TABLE`: hanya tambah kolom, tanpa ubah tipe, rename, drop, index, atau backfill.
* Kolom yang pernah ditambahkan: `service_orders.device_password VARCHAR(120)` dan `service_orders.repair_plan TEXT`.
* Belum ada Alembic, tanpa file revisi, tanpa downgrade, tanpa riwayat versi skema.

RISIKO (tanpa perbaikan di tahap ini): drift antara `models.py` dan DB lama jika kolom diubah/dihapus (create_all tidak sinkron); `ALTER TABLE` manual tidak atomik terdokumentasi dan tidak tercatat versinya; default `service_date` dievaluasi saat import sehingga proses lama bisa menulis tanggal basi; tidak ada backup otomatis sebelum migrasi; perubahan nama kolom memutus API/frontend (`schemas.py`, `orders.py`, `script.js`) tanpa deteksi compile-time.

## 14. DATABASE SAFETY RULES FOR AI AGENT

1. Jangan menghapus `servisku.db`.
2. Jangan reset database tanpa backup dan izin eksplisit.
3. Jangan mengubah struktur tabel tanpa memahami relasi.
4. Jangan membuat migration hanya untuk mengatasi error sementara.
5. Jangan mengubah nama kolom yang sudah digunakan API/frontend tanpa analisis dampak.
6. Setiap perubahan schema harus didokumentasikan.
7. Perubahan database harus diuji.
8. Jangan menganggap data seed sebagai data bisnis nyata.
9. Jangan menampilkan credential/token/password di dokumentasi.
10. Jika struktur database aktual berbeda dengan dokumentasi, verifikasi `models.py` terlebih dahulu lalu update dokumentasi.

## 15. DATABASE DEVELOPMENT WORKFLOW

BEFORE DATABASE CHANGE
→ baca AI_CONTEXT.md
→ baca ARCHITECTURE.md
→ baca DATABASE.md
→ baca models.py
→ identifikasi relasi
→ identifikasi dampak API/schema/frontend
→ baru rencanakan perubahan

AFTER DATABASE CHANGE
→ update models/schema/migration sesuai kebutuhan
→ test database
→ test API
→ update DATABASE.md
→ update CHANGELOG.md
→ git commit

## 16. SOURCE OF TRUTH

Untuk struktur database:

1. `backend/models.py` = sumber kebenaran struktur ORM
2. `servisku.db` = database aktual/data
3. `docs/DATABASE.md` = dokumentasi pemahaman database

Jika dokumentasi berbeda dengan source code:
→ verifikasi source code
→ jangan menebak
→ update dokumentasi.

## 17. LAST VERIFIED

* Tanggal dokumentasi: 2026-09-07 (UTC).
* File source yang diverifikasi: `backend/models.py` (penuh), `backend/database.py` (penuh), `backend/seed.py` (bagian user/customer/order), `backend/main.py` (bagian `_migrate_schema/on_startup`), `backend/routers/auth.py` (bagian `TOKEN_TTL_DAYS/create_token`), `backend/schemas.py` + `routers/orders.py/dashboard.py` (bagian status/default).
* Konteks dibaca: `docs/AI_CONTEXT.md`, `docs/ARCHITECTURE.md`.
* Dokumen dibuat berdasarkan kondisi aktual saat ini tanpa mengubah code/DB, tanpa menampilkan credential/token/password aktual.
