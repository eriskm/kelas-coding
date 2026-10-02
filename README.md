# SUKABUMI FLASHER — Business Operating System

Dokumentasi utama project. Disusun dari **audit source code aktual**
(`frontend/`, `backend/`, `servisku.db`, file `.bat`).
Jika ada perbedaan dengan dokumen lama di `docs/`, yang berlaku adalah source code.

## 1. Project Overview

| | |
|---|---|
| Nama | **SUKABUMI FLASHER — Business Operating System** |
| Jenis | Aplikasi web POS & Service Management untuk toko servis smartphone |
| Tujuan | Digitalisasi alur servis: pendaftaran unit → nota → tracking status → edit data, dalam satu sistem |
| Masalah yang diselesaikan | Pencatatan servis manual diganti form terstruktur; setiap unit punya **No. Servis** unik sebagai kunci lacak; nota thermal + nota digital (gambar PNG, share WA) dihasilkan dari data yang sama |

Fungsi utama:

- Pendaftaran unit baru (**Servis Baru**) dengan No. Servis otomatis (`SV-YYYYMMDD-XXXX`)
- Edit data servis (**Update Data Servis**) berbasis No. Servis yang sama (GET → PUT, tanpa transaksi baru)
- Daftar transaksi + hapus, histori pelanggan per No. WA
- Nota penerimaan (thermal print + digital PNG + share WhatsApp + QR verifikasi)
- Login multi-akun (token), dark theme, SPA hash-routing tahan refresh

## 2. Arsitektur Sistem

```text
Browser (HP/Laptop)
   │  HTTP
   ▼
FastAPI (uvicorn, port 8000)
   ├── /              → frontend/index.html (FileResponse)
   ├── /static/*      → frontend/ (NoCacheStaticFiles)
   └── /api/*         → routers (auth wajib Bearer, kecuali login)
          │
          ▼
   SQLAlchemy ORM → SQLite (servisku.db)
```

Akses:

- Lokal/LAN via `jalankan.bat` → `http://127.0.0.1:8000/` atau `http://<IP-LAN>:8000/`
- Publik via `jalankan-online.bat` → tunnel Cloudflare (`tools/cloudflared.exe`) ke URL publik

Teknologi yang benar-benar dipakai:

| Lapisan | Teknologi |
|---|---|
| Frontend | HTML + CSS + JavaScript vanilla (tanpa framework), Tailwind via CDN, ApexCharts, html2canvas 1.4.1, Font Awesome 6.5.1, font Inter |
| Backend | FastAPI 0.128.8, uvicorn 0.39.0, SQLAlchemy 2.0.52 (`backend/requirements.txt`), Python 3.9+ |
| Auth | Token acak 64-hex di DB (`auth_tokens`), TTL 7 hari, hash PBKDF2-SHA256 200.000 iterasi |
| Database | SQLite file `servisku.db` (di-ignore git) |

## 3. Struktur Folder

```text
E:\PRAKTEK MJPRO
├── README.md               ← file ini (baseline dokumentasi)
├── frontend/
│   ├── index.html          ← seluruh halaman SPA (login + semua modul + popup)
│   ├── script.js           ← seluruh logic frontend (~3600 baris)
│   ├── style.css           ← seluruh styling (~2700 baris)
│   └── assets/             ← logo toko + gambar referensi desain (*-reference.png)
├── backend/
│   ├── main.py             ← entry FastAPI, static mount, _migrate_schema(), seed saat startup
│   ├── database.py         ← engine SQLite (servisku.db di root), SessionLocal, Base
│   ├── models.py           ← tabel: users, auth_tokens, customers, service_orders, payments
│   ├── schemas.py          ← kontrak Pydantic request/response
│   ├── seed.py             ← superadmin + data contoh (jalan bila DB kosong)
│   ├── dependencies.py     ← get_db_session
│   ├── requirements.txt    ← fastapi, uvicorn, sqlalchemy, greenlet, multipart
│   └── routers/            ← auth.py, orders.py, customers.py, dashboard.py
├── docs/                   ← AI_CONTEXT, ARCHITECTURE, DATABASE, API, FRONTEND, MODULES (arsip lama)
├── tools/                  ← cloudflared.exe + run_tunnel.bat (tunnel online)
├── servisku.db             ← database aktif (tidak masuk git)
├── jalankan.bat            ← run lokal/LAN (venv + seed + uvicorn --reload)
├── jalankan-online.bat     ← run server + tunnel Cloudflare
├── setup-online.bat        ← setup tunnel sekali saja
└── matikan.bat             ← matikan server + tunnel
```

Tidak ada test suite / CI di repo. Testing yang pernah dilakukan tercatat di bagian 19.

## 4. Modul / Menu Aplikasi

Sidebar (`frontend/index.html`, `data-page`) — hanya ini yang ada, jangan tambah yang lain:

| Menu | Sumber data aktual |
|---|---|
| Dashboard | Real: star cards + insight dari `GET /api/overview`; grafik status dari agregat real `GET /api/statistics/status` (`by_status`); tren kerusakan dari agregat real `GET /api/statistics/damage` |
| Servis Baru | **Realtime** → `POST /api/orders/receive`; histori cerdas → `GET /api/orders/history/{phone}` (tanpa fallback dummy) |
| Transaksi | **Realtime** → `GET /api/orders` (pagination backend) + `GET /api/orders/latest` (filter client-side); hapus → `DELETE /api/orders/{id}` |
| Pelanggan | **Realtime** → `GET /api/customers/summary` + detail/PUT/DELETE by ID |
| Garansi | **Realtime** → `GET /api/claims/warranty-summary` (order CASH bergaransi + klaim berjalan); klaim baru → `POST /api/claims/receive` |
| Sparepart | **Realtime** → `GET/POST/PUT/DELETE /api/spareparts` (tersimpan permanen) |
| Keuangan | **Realtime** — Buku Kas turunan order CASH + expenses + jurnal manual (`GET /api/kas/riwayat` + `GET /api/overview.finance`); Tutup Kas → `POST /api/kas/close` (snapshot + arsip `GET /api/kas/periods`); Beban → CRUD `/api/expenses` |
| Kelola Akun | **Realtime** → `GET/POST/PUT /api/auth/users` (khusus Admin/Superadmin; hapus = nonaktifkan) |
| Login, Nota, popup Histori/Detail | Login/logout/me **realtime**; nota dirender dari data transaksi terakhir (placeholder teknisi difilter, tanpa nota dummy) |

## 5. Alur Servis

```text
SERVIS BARU (POST /api/orders/receive)
 Data Konsumen (Nama*, WA*)
 → Device* → Password/Pola → IMEI
 → Checklist Unit (fisik + kelengkapan)
 → Analisa Kerusakan* → Rencana Tindakan
 → Estimasi & DP → Teknisi → Status awal
 → No. Servis baru (SV-YYYYMMDD-XXXX)
 → popup sukses + Cetak Nota
      │
      │  No. Servis SAMA (bukan transaksi baru)
      ▼
UPDATE DATA SERVIS (GET /api/orders/{id} → PUT /api/orders/{id})
 Urutan panel 2 identik: Device → Password → IMEI
 → Checklist → Analisa → Rencana
 + panel lanjutan (kanan): Rincian Biaya (lokal) + Status & Aksi
```

Aturan baku: Update **mengambil data berdasarkan No. Servis/ID yang sama**,
mengirim PUT ke ID yang sama, No. Servis tidak berubah, tidak ada duplikasi transaksi.

## 6. Data Service Order

Field aktual di DB/API (`backend/models.py`, `backend/schemas.py`):

| Field | DB (`service_orders`) | API | Keterangan |
|---|---|---|---|
| `no_servis` | unique, index | semua schema | Kunci lacak, format `SV-YYYYMMDD-XXXX` |
| `customer_id` | FK → customers | + nested `customer` di `ServiceOrderOut` | Relasi master (bagian 7) |
| `device` | VARCHAR(120) | ya | Device / Model HP |
| `brand`, `model` | VARCHAR(60) | ya | Ada di schema, **tidak diisi form** (selalu NULL) |
| `device_password` | VARCHAR(120) | ya | Password / Pola |
| `imei` | VARCHAR(80) | ya (GET/POST/PUT) | IMEI / Serial, permanen per No. Servis |
| `check_fisik`, `check_len` | JSON | ya (list string) | Permanen per No. Servis (bagian 8) |
| `damagetype` | VARCHAR(120) | ya | Analisa Kerusakan |
| `repair_plan` | TEXT | ya | Rencana Tindakan |
| `technician` | VARCHAR(60) | ya | Daftar dari `GET /api/orders/technicians` (`Budi, Andi, Rizky, Dedi, Fajar`) |
| `status` | VARCHAR(30) | ya | Bagian 10 |
| `estimate` | FLOAT | ya | Estimasi Biaya |
| `payment` | FLOAT | ya | DP saat receive (`dp` → `payment`); kolom DP di Update |
| `service_date`, `created_at` | DATE / DATETIME | ya | Tgl servis + waktu buat |

Alur data wajib: `UI → Payload → API → Database → API Response → UI`.
`ServiceOrderList` (tabel/transaksi) juga membawa `imei` + checklist + `customer_name/phone`.

## 7. Customer

Konsep **Customer Master** (`backend/models.py: Customer`, `backend/routers/orders.py: receive_unit`):

- Satu customer (`customers.id`) dapat memiliki **banyak** service order (one-to-many via `customer_id`).
- Pencarian/identifikasi **berdasarkan nomor WhatsApp**: receive mencari `Customer.phone` terbaru yang cocok lalu pakai ulang row-nya (tidak bikin duplikat).
- Aturan existing aktual (**opsi a**): bila WA cocok tapi nama yang diketik berbeda → **nama customer di-update** ke input terbaru. Dampak: semua order dengan `customer_id` itu menampilkan nama baru (histori transaksi tiap order tidak berubah).
- Update Data Servis mengubah nama/WA via `PUT /api/customers/{id}` — efek berbagi row yang sama berlaku.
- Kasus langka: dua orang berbeda memakai satu nomor WA → nama bisa flip-flop (label saja, data transaksi aman).

## 8. Checklist Unit

Satu sumber definisi (`frontend/script.js`: `CHECK_FISIK`, `CHECK_LEN`, `renderChecklist`) dipakai kedua halaman — item selalu identik:

Kondisi Fisik: LCD Pecah, LCD Terbuka, Frame/Case Bengkok, Frame/Case Gompal,
Tombol Tidak Ada, Bekas Air.
Kelengkapan: Unit Saja, Case, SIM Card, Memory Card, Box, Charger.

- Disimpan **permanen per No. Servis** (`check_fisik`, `check_len`).
- Default: fisik `[]`, kelengkapan `["unit_saja"]` ("Unit Saja" = hanya unit dibawa).
- **Tanpa dummy fallback**: data lama/NULL dinormalisasi ke default di atas.
- **Dirty-guard di Update**: checklist hanya ikut PUT bila user benar-benar mengubahnya (dibanding baseline saat dibuka); bila tidak disentuh, field dihilangkan dari payload agar data server tidak tertimpa.

## 9. IMEI

IMEI adalah bagian data Service Order (`imei`, VARCHAR(80)), **disimpan permanen
terikat No. Servis**: Servis Baru mengirim → GET/PUT membawa → Update menampilkan
dan bisa mengedit (`usImei`, sejajar setelah Password, sama di kedua halaman).

## 10. Status Servis

Nilai aktual dari select di kedua form (`rcStatus`, `usStatus`, `usQuickStatus`):

`ANALISA, KONFIRMASI, WAIT PART, REPAIR, DONE, CASH, FILED, CANCEL`

- Default awal: `ANALISA`.
- Tampilan label Indonesia via `TX_STATUS_LABEL` (mis. RECEIVED→Diterima, DONE→Selesai,
CASH→Cash/Lunas) + badge warna `st-STATUS`.
- Satu sumber state di Update: tulis via `usSetStatus()`, baca via `usGetStatus()`
(kedua select hanya mirror). Badge header (`usHeadStatus`) ikut sinkron;
tombol cetak ulang nota muncul khusus saat `CASH`.
- Nilai historis lain (RECEIVED, DIAGNOSIS, QC, READY, COMPLETED, WAITING_*)
hanya dikenal di mapping/chart, bukan opsi form.

## 11. Keuangan

Kondisi aktual — **terintegrasi backend**:

| Fitur | Kondisi aktual |
|---|---|
| Buku Kas (Masuk/Keluar/Saldo) | Real turunan: order CASH + expenses + jurnal manual, scope periode kas aktif (`GET /api/kas/riwayat?period=current`, ringkasan `GET /api/overview.finance`: `total_masuk/total_keluar/saldo`) |
| Jurnal manual | Tabel `kas_entries` (`Masuk/Keluar`, kategori, keterangan, nominal, tanggal); kategori `Saldo Awal` = saldo awal lintas periode. Rumah untuk pemasukan non-servis & penyesuaian |
| Tutup Kas & Arsip | Real → `POST /api/kas/close` (snapshot `compute_finance` + hitungan laci + selisih → `kas_periods.snapshot`, status CLOSED, periode baru OPEN); arsip → `GET /api/kas/periods` |
| Beban (Gaji/Operasional/...) | Real CRUD `/api/expenses` (popup Beban Harian, migrasi-sekali data lokal lama, fallback lokal bila offline) |
| Alokasi Profit | Real dari `overview.finance.alokasi` (10/30/30/sisa, **terbentuk hanya bila CTO tercapai & laba bersih > 0** — bila belum, UI menampilkan status jujur, bukan angka) |
| Rincian Biaya di Update (`usFin*`) | Hitungan lokal tersimpan via PUT ke order (`final_price`, `part_cost`, `modal_jasa`, `modal_lainnya`); tombol bernama jujur **"Simpan Perubahan Servis"** |
| Riwayat | Real gabungan (order CASH + expenses + jurnal manual) + saldo berjalan (`GET /api/kas/riwayat`, filter/jenis/tanggal server-side); baris otomatis digembok, hanya jurnal manual bisa edit/hapus |

Aturan: `payments` dorman (hanya seed) — sumber pemasukan servis adalah `service_orders` CASH, bukan tabel payments.

## 12. API

Base: `/api`. Selain login, semua butuh `Authorization: Bearer <token>`.
Hanya endpoint yang benar-benar ada di `backend/routers/`:

| Method | Endpoint | Fungsi | Input utama → Output utama |
|---|---|---|---|
| POST | `/api/auth/login` | Login | `username, passcode` → `token + user` |
| POST | `/api/auth/logout` | Logout (hapus token) | Bearer → `{ok:true}` |
| GET | `/api/auth/me` | Cek sesi | Bearer → user |
| POST | `/api/orders/receive` | Daftarkan unit (customer+order) | `ServiceReceiveIn` → `ServiceOrderOut` (+customer) |
| GET | `/api/orders?page&limit` | Transaksi paginasi (maks 10/halaman) | — → `ServiceOrderPage` |
| GET | `/api/orders/latest?limit` | Transaksi terbaru (filter/search client) | — → list |
| GET | `/api/orders/technicians` | Daftar teknisi | — → `["Budi","Andi",...]` |
| GET | `/api/orders/history/{phone}` | Histori cerdas per WA | phone → list order |
| GET | `/api/orders/{id}` | **Sumber data Update** | id → `ServiceOrderOut` lengkap |
| POST | `/api/orders` | Buat order mentah (tidak dipakai frontend) | `ServiceOrderCreate` → order |
| PUT | `/api/orders/{id}` | **Simpan Update** (parsial, `exclude_unset`) | field berubah → order |
| DELETE | `/api/orders/{id}` | Hapus transaksi | id → `{ok:true}` |
| GET | `/api/customers` | List customer | — → list |
| GET | `/api/customers/summary` | Ringkasan + servis terakhir (**tidak dipakai frontend**) | page/limit → page |
| GET/POST/PUT/DELETE | `/api/customers[/{id}]` | CRUD customer (frontend hanya pakai **PUT** nama/WA) | … |
| GET | `/api/overview` | Star cards + insight | — → JSON (campuran real+dummy) |
| GET | `/api/statistics/status` | Tren status (**tidak dipakai frontend**) | — → dummy mingguan |
| GET | `/api/statistics/damage` | Tren kerusakan (**angka statis**) | — → 6 kategori statis |

## 13. Database

- SQLite file `servisku.db` di root (di-ignore git, lihat `.gitignore`).
- Tabel: `users`, `auth_tokens`, `customers`, `service_orders`, `payments`.
- Relasi penting: `customers 1—N service_orders`; `service_orders 1—N payments`
(`cascade delete-orphan`); `users 1—N auth_tokens`.
- Field penting: lihat tabel bagian 6 + `customers(name, phone, email, address)`.
- Migrasi schema: `Base.metadata.create_all()` + `_migrate_schema()` di
`backend/main.py` (cek `PRAGMA table_info` → `ALTER TABLE ADD COLUMN` bila belum ada;
backfill checklist default). Berjalan otomatis tiap startup — aman untuk data lama.
- Seed (`backend/seed.py`, idempotent): superadmin default
`superadmin / Admin4100` + 10 customer + 12 order contoh bila DB kosong.

## 14. Frontend

- **Vanilla SPA satu file**: `index.html` (markup semua halaman) + `script.js`
(logic) + `style.css` (styling). Tanpa build step, tanpa framework.
- Navigasi: hash `#/dashboard|transaksi|pelanggan|garansi|sparepart|keuangan`
+ `localStorage bsf_page`; Servis Baru adalah **floating overlay** (`#pageReceive`)
dengan flag terpisah `bsf_receive_open` + draft autosave `bsf_receive_draft`
(tahan refresh).
- Login overlay → token di `localStorage` (Ingat Saya) / `sessionStorage`;
401 → AuthError → kembali ke login.
- Komponen penting: sidebar + topbar (jam/tanggal live), panel, `tx-table`,
`float-window` (drag via titlebar, tutup via Escape/X), stepper Servis Baru,
Histori Cerdas, popup sukses Servis Baru, Nota (thermal print + digital),
toast `notaFlash`, shortcut keyboard (Enter/F2/F4/F8, Ctrl+S).
- Popup sukses Servis Baru (`#receiveSuccessPopup`): No. Servis + Cetak Nota
(`openNota()` via `_lastNota`) + Input Lagi; tombol nota inline tetap ada
sebagai cadangan.

## 15. Design System

- **Dark theme** via class `dark` di `<html>` (toggle + tersimpan `localStorage theme`,
default ikut OS). Semua komponen punya varian `.dark`.
- **Accent utama crimson/deep red**: `#dc2626` (brand-500), `#b91c1c`, `#991b1b`;
gradasi merah untuk header penting.
- Warna semantik: hijau pemasukan/sukses, biru finansial utama, amber beban,
merah batal/gagal, ungu/teal status khusus (lihat `.tx-status.st-*`, `.kpi-*`).
- Tipografi: Inter (Google Fonts), judul 800, label 11–13px.
- Pola spacing: gap panel 12px; radius panel 12–16px, tombol 9–13px, pill penuh.
- Komponen: `.panel`, `.tx-table`, `.float-window` + `.float-titlebar` + `.float-close`,
`.receive-input`, `.receive-submit-btn` (hijau) / `.receive-back-btn`,
`.tx-status` pill, **inline checkbox polos** (checkbox + label sejajar horizontal,
tanpa pill/chip), skala kompak `zoom: 0.9` pada body Servis Baru & Update.
- Nota digital: sheet putih ≤920px, header merah, footer hitam; export PNG
**dinamis target ±1080px** (`scale = min(1080/lebarAktual, 2)`) untuk WhatsApp —
hanya proses export, preview tidak diubah.

## 16. Aturan Pengembangan

1. Audit source code aktual sebelum coding; source code > dokumentasi lama.
2. Jangan mengubah logic yang tidak berkaitan dengan tugas.
3. Jangan membuat duplikat data (customer: reuse by WA; order: satu No. Servis).
4. Jangan membuat API baru bila endpoint existing masih bisa dipakai.
5. Jangan membuat field UI tanpa sumber data yang jelas.
6. Setiap data penting wajib punya alur jelas:
`UI → Payload → API → Database → API Response → UI`.
7. Update Data Servis wajib ambil data dari No. Servis yang sama (GET by id).
8. Dilarang memakai dummy sebagai fallback data yang seharusnya dari database.
9. Perubahan frontend/backend/database wajib terdokumentasi.
10. Setelah perubahan: testing + `git status`/`git diff` review sebelum commit.

## 17. Workflow Pengembangan

```text
Analisa Masalah → Requirement → Audit Source → Design/UX
 → Implementasi → Testing → Dokumentasi → Git Commit
```

## 18. Current Development Status

Berdasarkan source aktual (bukan tebakan):

**Selesai / realtime:**

- Auth (login/logout/sesi) + Kelola Akun (CRUD user, guard Admin/Superadmin, nonaktifkan-bukan-hapus)
- Servis Baru end-to-end (validasi, Histori Cerdas tanpa fallback dummy, draft autosave tahan refresh, popup sukses)
- Update Data Servis (IMEI + checklist permanen per No. Servis, dirty-guard, urutan panel selaras)
- Transaksi (list paginasi backend, search/filter tanggal client-side, hapus)
- Pelanggan (summary/detail/edit/hapus real), Garansi (warranty-summary real + klaim via `/claims/receive`), Sparepart (CRUD real)
- Keuangan real: Buku Kas turunan + jurnal manual + Tutup Kas bersnapshot/arsip + Beban CRUD + Alokasi gated
- Dashboard real: overview finance, grafik status + tren kerusakan agregat DB
- Nota thermal + digital (PNG ±1080px, QR, share WA, warna nomor per jenis, tanpa Estimasi Selesai, tanpa nota dummy, placeholder teknisi difilter) + header Update compact
- Dark theme, routing tahan refresh (tanpa render ganda), popup sukses, inline checkbox, pagination icon panah

**Belum terintegrasi / manual:**
- Grafik tren status mingguan memakai hitungan real per hari (bukan dummy); angka per status real-time
- Endpoint yang ada tapi belum dipakai frontend: `POST /api/orders`, `GET /api/statistics/status` versi lama (sudah diganti agregat real)

## 19. Testing

- Tidak ada test suite otomatis di repo (tanpa pytest/CI).
- Yang terlaksana: **E2E audit backend via skrip sekali-pakai** (dependensi
di-override ke DB temp, fungsi endpoint dipanggil langsung) — termasuk suite
29/29 pasca-integrasi kas/sparepart/akun/garansi: jurnal manual + saldo awal,
riwayat gabungan 3 sumber + saldo berjalan, tutup kas + arsip periode,
sparepart CRUD + search, user CRUD + guard role, statistik real, warranty-summary.
Skrip tidak disimpan di repo.
- Pemeriksaan rutin: `node --check frontend/script.js`, `import main` backend,
`PRAGMA table_info(service_orders)`, dan review `git diff`.

## 20. Cara Menjalankan Project

Butuh Python 3.9+ (venv + `requirements.txt` disiapkan otomatis oleh `.bat`):

| File | Fungsi |
|---|---|
| `jalankan.bat` | Standar: buat/aktifkan `backend/venv`, install deps, `seed.py`, `uvicorn main:app --host 0.0.0.0 --port 8000 --reload`; buka `http://<IP-LAN>:8000/static/index.html` (HP via WiFi yang sama) |
| `jalankan-online.bat` | Server + tunnel Cloudflare → URL publik (maks 30 dtk tunggu server) |
| `setup-online.bat` | Sekali saja: unduh cloudflared, tulis config tunnel |
| `matikan.bat` | Matikan cloudflared + proses port 8000 |

Root `/` juga serve `index.html` langsung. Login default (seed):
`superadmin / Admin4100`.

## 21. Git

- Branch aktif: `main`. Belum ada branch fitur lain.
- Alur: `git status` → `git diff` → `git add` file yang dimaksud →
`git commit -m "..."` (pesan mengikuti gaya existing, mis. `feat: ...`, `fix: ...`).
- `git push` / PR hanya bila diminta. Jangan ubah config, skip hooks,
atau force-push tanpa instruksi.
- Di-ignore: `venv/`, `*.db`, `*.log`, `.env`, `tools/cloudflared.exe`
(lihat `.gitignore`).
