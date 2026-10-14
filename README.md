# SUKABUMI FLASHER — Business Operating System

> ### 🔒 Aturan bisnis yang terkunci Owner
>
> Sumber kebenaran bisnis BOSS SF ada di
> **`docs/OWNER_DECISIONS.md`** — memuat FR-01, FR-02, dan OD-LOCK-01
> sampai OD-LOCK-05 dengan status **LOCKED**.
>
> Dokumen itu **berada di atas** dokumen lain, termasuk README ini. Kalau ada
> perbedaan antara yang tertulis di sini dengan keputusan Owner yang
> terkunci, **keputusan Owner yang berlaku** dan README ini yang perlu
> diperbarui.
>
> Catatan penting untuk pembaca dokumen ini: bagian di bawah ditulis dari
> audit source code, sehingga **ada beberapa bagian yang sudah usang**
> dibanding keputusan Owner terbaru (mis. pemicu distribusi, dan aturan
> transisi status CASH). Lihat bagian **Ketidaksesuaian Implementasi** di
> `docs/OWNER_DECISIONS.md` untuk daftar lengkapnya.

Dokumentasi utama project. Disusun dari **audit source code aktual**
(`frontend/`, `backend/`, `tests/`, file `.bat`).
Jika ada perbedaan dengan dokumen lama di `docs/`, yang berlaku adalah source code.

## 1. Project Overview

| | |
|---|---|
| Nama | **SUKABUMI FLASHER — Business Operating System** (BOSS SF) |
| Jenis | Aplikasi web POS & Service Management untuk toko servis smartphone |
| Tujuan | Digitalisasi alur servis: pendaftaran unit → nota → tracking status → edit data, dalam satu sistem, dengan modul keuangan (buku kas, tutup kas, distribusi laba) yang mengikuti **Owner Cash Model** |
| Masalah yang diselesaikan | Pencatatan servis manual diganti form terstruktur; setiap unit punya **No. Servis** unik sebagai kunci lacak; nota thermal + nota digital (gambar PNG, share WA) dihasilkan dari data yang sama |

Fungsi utama:

- Pendaftaran unit baru (**Servis Baru**) dengan No. Servis otomatis (`SV-YYYYMMDD-XXXX`) dan **initial path** (TITIP/PERBAIKAN/SPAREPART/TUNGGU)
- Edit data servis (**Update Data Servis**) berbasis No. Servis yang sama (GET → PUT, tanpa transaksi baru)
- Daftar transaksi + hapus, histori pelanggan per No. WA, histori status append-only
- Nota penerimaan (thermal print + digital PNG + share WhatsApp + QR verifikasi)
- Login multi-akun (token) dengan **authority matrix per aksi**, dark theme, SPA hash-routing tahan refresh
- Keuangan: Buku Kas 16:00→16:00, Kas Aset (Laci vs Pengelola), Tutup Kas, distribusi laba, refund, hutang beban, inventaris

## 2. Arsitektur Sistem

```text
Browser (HP/Laptop)
   │  HTTP
   ▼
FastAPI (uvicorn, port 8000)  — backend/main.py
   ├── /              → frontend/index.html (FileResponse, no-cache)
   ├── /static/*      → frontend/ (NoCacheStaticFiles)
   ├── /api/health    → versi + daftar route auth (tanpa login)
   └── /api/*         → 13 router (auth wajib Bearer, kecuali login & health)
          │
          ▼
   Domain layer (backend/*.py): statusflow, money, finance, cash,
   distribution, closing, refunds, expense_debt, inventory,
   notifications, idempotency, journal, authority
          │
          ▼
   SQLAlchemy ORM → SQLite (default) atau PostgreSQL (env DATABASE_URL)
```

Akses:

- Lokal/LAN via `jalankan.bat` → `http://127.0.0.1:8000/` atau `http://<IP-LAN>:8000/`
- Publik via `jalankan-online.bat` → tunnel Cloudflare (`tools/cloudflared.exe`) ke URL publik
- Produksi Ubuntu via `deploy-ubuntu.ps1` → sinkron source + `systemctl --user restart`

Teknologi yang benar-benar dipakai:

| Lapisan | Teknologi |
|---|---|
| Frontend | HTML + CSS + JavaScript vanilla (tanpa framework), Tailwind via CDN, ApexCharts, html2canvas 1.4.1, Font Awesome 6.5.1, font Inter |
| Backend | FastAPI 0.128.8, uvicorn 0.39.0, SQLAlchemy 2.0.52, greenlet, python-multipart, psycopg[binary] (`backend/requirements.txt`), Python 3.9+ |
| Auth | Token acak 64-hex (`secrets.token_hex(32)`) di DB (`auth_tokens`), TTL 7 hari, hash PBKDF2-SHA256 200.000 iterasi + salt; otorisasi per aksi ditegakkan `backend/authority.py` (bukan string permission) |
| Database | SQLite file `servisku.db` (default, di-ignore git) **atau** PostgreSQL via `DATABASE_URL` |
| Test | pytest, 42 test di `tests/` |

## 3. Struktur Folder

```text
D:\PRAKTEK MJPRO
├── README.md               ← file ini (baseline dokumentasi)
├── app.py                  ← prototipe Flask awal (sistem keuangan, port 5000,
│                              DB `keuangan_praktek.db`) — BUKAN runtime BOSS SF
│                              dan tidak dijalankan oleh .bat mana pun
│                              (catatan: "Project A" yang dikutip di backend/*.py
│                              adalah aplikasi referensi lain di luar repo ini)
├── frontend/
│   ├── index.html          ← markup seluruh halaman SPA (2383 baris)
│   ├── script.js           ← seluruh logic frontend (6948 baris)
│   ├── style.css           ← seluruh styling (3405 baris)
│   └── assets/             ← logo toko + gambar referensi desain (*-reference.png)
├── backend/
│   ├── main.py             ← entry FastAPI, mount router + static, backup, migrasi
│   ├── database.py         ← engine (SQLite/PostgreSQL via DATABASE_URL), SessionLocal, Base
│   ├── models.py           ← 21 tabel ORM
│   ├── schemas.py          ← kontrak Pydantic request/response (602 baris)
│   ├── dependencies.py     ← get_db_session (rollback eksplisit saat exception)
│   ├── seed.py             ← pastikan superadmin; data demo hanya bila SUKABUMI_DEMO_SEED=1
│   ├── requirements.txt
│   ├── money.py            ← Q10: nilai uang Decimal/Numeric, bukan Float
│   ├── statusflow.py       ← SSOT status servis, 3 dimensi, matriks transisi, initial path
│   ├── authority.py        ← SSOT authority matrix (role × aksi)
│   ├── finance.py          ← SSOT financial core: Omzet/Modal/Beban/Laba Bersih
│   ├── cash.py             ← Owner Cash Model v4: layer Laci & Kas Aset
│   ├── distribution.py     ← SSOT distribusi 10/30/30/30
│   ├── closing.py          ← orkestrasi Tutup Kas
│   ├── refunds.py          ← 3 jenis refund, 3 sumber dana, 1 efek
│   ├── expense_debt.py     ← SSOT-8 Hutang Beban (terpisah dari Buku Kas)
│   ├── inventory.py        ← stok, pemakaian part, jurnal stock_moves
│   ├── notifications.py    ← outbox WA/Telegram + anti-duplikat
│   ├── idempotency.py      ← Idempotency-Key untuk endpoint money/closing
│   ├── journal.py          ← journal audit append-only lintas domain
│   ├── migrate_sqlite_to_postgres.py ← alat migrasi DB → PostgreSQL
│   ├── migrations_money.py         ← P2-02 rapikan presisi uang
│   ├── migrations_cash_layers.py   ← P2-06 tambah kolom layer/sumber kas
│   ├── migrations_warranty_claims.py ← P2-09 kolom lifecycle klaim
│   └── routers/            ← auth, orders, customers, dashboard, claims, expenses,
│                              kas, spareparts, payments, refunds, expense_debt,
│                              inventory, notifications (80 endpoint)
├── tests/                  ← pytest: 7 file, 42 test (domain/finance/ledger/distribusi)
├── docs/                   ← AI_CONTEXT, ARCHITECTURE, DATABASE, API, FRONTEND, MODULES,
│                              BOSS_SF_BLUEPRINT, WORKFLOW_GAP, referensi-nota/
├── tools/                  ← cloudflared.exe + run_tunnel.bat (tunnel online)
├── servisku.db             ← database aktif (tidak masuk git)
├── backup-servisku-*.db    ← backup otomatis tiap startup (tidak masuk git)
├── deploy-ubuntu.ps1       ← sinkron source ke server Ubuntu + restart service
├── jalankan.bat            ← run lokal/LAN (venv + deps + seed + uvicorn --reload)
├── jalankan-online.bat     ← run server + tunnel Cloudflare
├── setup-online.bat        ← setup tunnel sekali saja
└── matikan.bat             ← matikan server + tunnel
```

Tidak ada CI. Menjalankan test: `python -m pytest tests -q` (butuh `pytest` terinstall,
venv `backend/venv` belum memuatnya). Detail di bagian 20.

## 4. Modul / Menu Aplikasi

Sidebar (`frontend/index.html`, `data-page`) — hanya ini yang ada, jangan tambah yang lain:

| Menu | Sumber data aktual |
|---|---|
| Dashboard | Real: star cards + insight dari `GET /api/overview`; grafik tren 7 hari dari agregat real `GET /api/statistics/status`; tren kerusakan = 6 `damagetype` teratas dari `GET /api/statistics/damage` |
| Servis Baru | **Realtime** → `POST /api/orders/receive` (dengan initial path + guard); histori cerdas → `GET /api/orders/history/{phone}` (tanpa fallback dummy) |
| Transaksi | **Realtime** → `GET /api/orders` (pagination backend) + `GET /api/orders/latest` (filter client-side); **semua status tampil, termasuk CASH + DIAMBIL**; detail/update via `GET`/`PUT /api/orders/{id}`; hapus → `DELETE /api/orders/{id}` |
| Pelanggan | **Realtime** → `GET /api/customers/summary` + detail/PUT/DELETE by ID |
| Garansi | **Realtime** → `GET /api/claims/warranty-summary` — servis **CASH + LUNAS + bergaransi yang periodenya sudah CLOSED**; lookup & klaim baru → `GET /api/claims/lookup`, `POST /api/claims/receive`; ubah klaim → `PUT /api/claims/{id}` |
| Sparepart | **Realtime** → `GET/POST/PUT/DELETE /api/spareparts` + movements `GET/POST /api/inventory/*` |
| Keuangan | **Realtime** — Buku Kas turunan 3 sumber (`GET /api/kas/riwayat`), saldo & posisi kas (`GET /api/kas/saldo`), mutasi Kas Aset (`/api/kas/aset/*`), Tutup Kas (`POST /api/kas/close`) + arsip (`GET /api/kas/periods`), distribusi (`GET /api/kas/distribusi`), Beban CRUD (`/api/expenses`), Hutang Beban (`/api/beban-hutang/*`) |
| Kelola Akun | **Realtime** → `GET/POST/PUT /api/auth/users` (khusus Admin; hapus = nonaktifkan) |

## 5. Alur Servis

```text
SERVIS BARU (POST /api/orders/receive)
 Data Konsumen (Nama*, WA*)
 → Device* → Password/Pola → IMEI
 → Checklist Unit (fisik + kelengkapan)
 → Analisa Kerusakan* → Rencana Tindakan
 → Estimasi & DP → Teknisi
 → Initial path* (TITIP | PERBAIKAN | SPAREPART | TUNGGU)
 → No. Servis baru (SV-YYYYMMDD-XXXX) + histori status sesuai path
 → popup sukses + Cetak Nota
      │
      │  No. Servis SAMA (bukan transaksi baru)
      ▼
UPDATE DATA SERVIS (GET /api/orders/{id} → PUT /api/orders/{id})
 Urutan panel 2 identik: Device → Password → IMEI
 → Checklist → Analisa → Rencana
 + panel lanjutan: Rincian Biaya, Status & Aksi, Pembayaran, Serah-terima
```

Initial path bukan status bebas — memetakan kondisi operasional ke status awal
dan histori yang benar-benar terjadi (`backend/statusflow.py: INITIAL_PATHS`):

| Path | Status awal | Histori yang ditulis | Guard wajib |
|---|---|---|---|
| TITIP | `DITERIMA` | DITERIMA | — |
| PERBAIKAN | `REPAIR` | DITERIMA→ANALISA→KONFIRMASI→REPAIR | rencana + estimasi > 0 + teknisi |
| SPAREPART | `WAIT PART` | DITERIMA→ANALISA→KONFIRMASI→WAIT PART | rencana + estimasi > 0 + teknisi |
| TUNGGU | `DONE` | DITERIMA→ANALISA→KONFIRMASI→REPAIR→DONE | rencana + teknisi + harga final (boleh 0) |

Tanpa `initial_path` → `DITERIMA` (legacy). Path juga dideteksi otomatis dari
field yang terisi, tapi **SPAREPART tidak pernah auto** (butuh keputusan eksplisit).

Aturan baku: Update **mengambil data berdasarkan No. Servis/ID yang sama**,
mengirim PUT ke ID yang sama, No. Servis tidak berubah, tidak ada duplikasi transaksi.

## 6. Data Service Order

Field aktual di DB/API (`backend/models.py`, `backend/schemas.py`). Semua kolom
uang bertipe `MONEY = Numeric(18, 2)` — **bukan Float**:

| Field | DB (`service_orders`) | Keterangan |
|---|---|---|
| `no_servis` | unique, index | Kunci lacak, format `SV-YYYYMMDD-XXXX` |
| `customer_id` | FK → customers | Relasi master (bagian 7); nested `customer` di response |
| `device` | VARCHAR(120), NOT NULL | Device / Model HP |
| `brand`, `model` | VARCHAR(60) | Ada di schema, **tidak diisi form** (selalu NULL) |
| `device_password` | VARCHAR(120) | Password / Pola |
| `imei` | VARCHAR(80) | IMEI / Serial, permanen per No. Servis |
| `check_fisik`, `check_len` | JSON | Permanen per No. Servis (bagian 8) |
| `damagetype` | VARCHAR(120) | Analisa Kerusakan |
| `repair_plan` | TEXT | Rencana Tindakan |
| `technician` | VARCHAR(60) | Dari `GET /api/orders/technicians` (nama unik di order + user aktif ber-role TEKNISI/ADMIN/SUPERADMIN, **data nyata, bukan daftar hardcode**) |
| `status` | VARCHAR(30), default `DITERIMA` | Dimensi 1, bagian 10 |
| `unit_status` | VARCHAR(10), default `DI TOKO` | `DI TOKO` / `DIAMBIL` (dimensi ke-3) |
| `taken_at` | DATETIME | Dikunci saat pencatatan serah-terima (`POST /api/orders/{id}/handover`) |
| `estimate`, `final_price` | MONEY | Estimasi & harga final; kewajiban = `final_price ?? estimate` |
| `part_cost`, `modal_jasa`, `modal_lainnya` | MONEY | Tiga komponen modal terpisah, diisi di Update Data Servis |
| `laba_bersih` | MONEY | **Dihitung backend**, bukan input user |
| `payment` | MONEY | DP era legacy, read-only arsip. Sumber baru = tabel `payments` |
| `lunas_date`, `lunas_at` | DATE / DATETIME | Momen LUNAS pertama, dikunci sekali (`lock_lunas_moment`) |
| `warranty_months` | INTEGER | Pilihan toko 1/3/6; 0 = tanpa garansi; NULL = legacy (30 hari) |
| `service_date`, `created_at` | DATE / DATETIME | Tgl servis + waktu buat |

Alur data wajib: `UI → Payload → API → Database → API Response → UI`.
`PUT /api/orders/{id}` bersifat parsial (`exclude_unset`).

### Metode Modal Jasa di Update Data Servis

Field `Modal Jasa - Metode` (`usFinJasaMode`) punya 3 pilihan: `Manual`, `40%`, `50%`.
Untuk mode persentase, dasar hitungannya **laba kotor setelah Modal Part**, bukan Harga Final:

```text
bruto_jasa = Harga Final − Modal Part
Modal Jasa = bruto_jasa × persen          (40% atau 50%)
Sisa       = Harga Final − Modal Part − Modal Jasa − Lain-Lain
```

Baris "Sisa (Final − Part − Jasa − Lain-Lain)" di ringkasan Rincian Biaya adalah
**laba kotor per transaksi**, dan rumus ini sama persis dengan yang dipakai backend
(`statusflow.order_profit` = kewajiban − part_cost − modal_jasa − modal_lainnya).

Contoh: Harga Final 1.000.000, Modal Part 200.000, mode 50% → Modal Jasa 400.000,
Lain-Lain 50.000 → Sisa 350.000. (Mode `Manual` mengisi nominal sendiri;
`usFinUpdate()` tidak menimpanya.) Fungsi: `usFinUpdate()` di `frontend/script.js`.

Makna berbeda ada di popup **Detail Transaksi** (`txdFinance`): baris "Sisa (Final − DP)"
di sana berarti sisa **tagihan pelanggan**, bukan laba.

## 7. Customer

Konsep **Customer Master** (`backend/models.py: Customer`, `backend/routers/orders.py`):

- Satu customer (`customers.id`) dapat memiliki **banyak** service order (one-to-many via `customer_id`).
- Pencarian/identifikasi **berdasarkan nomor WhatsApp**: receive mencari `Customer.phone` terbaru yang cocok lalu pakai ulang row-nya (tidak bikin duplikat).
- Aturan existing aktual: bila WA cocok tapi nama diketik berbeda → **nama customer di-update** ke input terbaru. Dampak: semua order dengan `customer_id` itu menampilkan nama baru (histori transaksi tiap order tidak berubah).
- Update Data Servis mengubah nama/WA via `PUT /api/customers/{id}` — efek berbagi row yang sama berlaku.
- Kasus langka: dua orang berbeda memakai satu nomor WA → nama bisa flip-flop (label saja, data transaksi aman).

## 8. Checklist Unit

Satu sumber definisi (`frontend/script.js`: `CHECK_FISIK`, `CHECK_LEN`,
`ACTIVE_FISIK_KEYS`, `ACTIVE_LEN_KEYS`) dipakai kedua halaman.

Kondisi Fisik (master 6): LCD Pecah, LCD Terbuka, Frame/Caseengkok, Frame/Case Gompal,
Tombol Tidak Ada, Bekas Air.
Kelengkapan (master 6): Unit Saja, Case, SIM Card, Memory Card, Box, Charger.

- **Subset aktif** yang tampil di form Servis Baru & Update: fisik
  `Frame/Case Benthok`, `Tombol Tidak Ada`, `Bekas Air`; kelengkapan
  `Unit Saja`, `Case`, `SIM Card`, `Memory Card`. Item yang pensiun
  (`lcd_pecah`, `lcd_terbuka`, `frame_gompal`, `box`, `charger`) dibuang dari
  data tersimpan saat startup (`_migrate_checklist_subset`); master list tetap
  utuh sebagai kamus label histori/nota, dan form **Klaim** masih memakai daftar penuh.
- Disimpan **permanen per No. Servis** (`check_fisik`, `check_len`).
- Default: fisik `[]`, kelengkapan `["unit_saja"]`.
- **Tanpa dummy fallback**: data lama/NULL dinormalisasi ke default di atas.
- **Dirty-guard di Update**: checklist hanya ikut PUT bila user benar-benar mengubahnya.

## 9. IMEI

IMEI adalah bagian data Service Order (`imei`, VARCHAR(80)), **disimpan permanen
terikat No. Servis**: Servis Baru mengirim → GET/PUT membawa → Update menampilkan
dan bisa mengedit (`usImei`, sejajar setelah Password, sama di kedua halaman).

## 10. Status Servis — 3 Dimensi (FINAL DECISION LOCK)

Sumber kebenaran tunggal: `backend/statusflow.py`. UI **tidak** bebas memilih status.

**Dimensi 1 — Status Servis** (9 nilai, Bahasa Indonesia):

`DITERIMA, ANALISA, KONFIRMASI, WAIT PART, REPAIR, DONE, CASH, CANCEL, FAILED`

Matriks transisi yang ditegakkan backend (`check_transition`):

```text
DITERIMA → ANALISA
ANALISA  → KONFIRMASI
KONFIRMASI → WAIT PART | REPAIR | CANCEL
WAIT PART → REPAIR | FAILED
REPAIR   → DONE | FAILED
DONE     → CASH
CASH | FAILED | CANCEL = terminal
```

- Lompat mundur atau keluar matriks **boleh bila ada `catatan`** (tercatat di `status_history`). Tanpa catatan → 400.
- Status terminal terkunci: perubahan wajib menyertakan catatan koreksi.
- `CASH` = **event realisasi transaksi + serah-terima unit**, bukan bypass pembayaran. CASH hanya boleh dari DONE dan hanya oleh role ber-authority closing (Admin/Kasir).
- `CANCEL` = keputusan konsumen; `FAILED` = hasil proses (termasuk kegagalan `WAIT PART`/`REPAIR`). Keduanya **wajib `catatan`** saat diaktifkan (`status_note` di payload; router menolak tanpa alasan).
- `FILED` **tidak ada** (dipetakan ke `FAILED`); status legacy lain dipetakan lewat `LEGACY_STATUS_MAP` (mis. `RECEIVED→DITERIMA`, `DIAGNOSIS/DIAGNOSA→ANALISA`, `QC/PERBAIKAN→REPAIR`, `COMPLETED/READY/SELESAI→DONE`) saat startup. Data lama tidak dihapus, hanya dipetakan.

**Dimensi 2 — Status Bayar** (`BELUM LUNAS` / `LUNAS`): **tidak disimpan**,
diturunkan dari Payment Ledger (`statusflow.payment_summary`). Kewajiban =
`final_price ?? estimate`; DP dari jurnal `payments` (kind `DP`) dan kolom legacy
`service_orders.payment` digabung tanpa double count.

**Dimensi 3 — Status Unit** (`DI TOKO` / `DIAMBIL` + `taken_at`): dicatat saat
handover, terpisah dari status servis.

Setiap perubahan status append-only ke `status_history`
(`dari_status`, `ke_status`, `oleh`, `waktu`, `catatan`).

## 11. Keuangan — Owner Cash Model

**Financial Core (SSOT, `backend/finance.py`)**

```text
OMZET       = penjualan SETTLED (status CASH) + LUNAS, momen settlement di periode 16:00→16:00
              (DP BUKAN Omzet, BUKAN Laba)
MODAL       = Modal Part + Modal Jasa + Modal Lain-lain (3 komponen terpisah)
BEBAN       = Gaji + Operasional (kategori lain tidak masuk Beban)
LABA BERSIH = OMZET − MODAL PART − MODAL JASA − MODAL LAIN-LAIN − BEBAN
```

- Laba transaksi per-order (`statusflow.order_profit`) hanya terbentuk bila
  order **CASH DAN LUNAS**; selain itu 0. Unit yang sudah LUNAS tapi belum CASH
  belum merealisasikan omzet.
- Gate CTO/CTS **hanya indikator**, tidak lagi mengatur distribusi. `overview`
  mengirim dua bentuk alokasi: `alokasi` (dari baris `distributions` yang sudah
  terbentuk) dan `alokasi_preview` (`distribution.preview`, tampilan saja —
  bukan pembukuan).
- Kategori beban recognized hanya `gaji` dan `operasional` (`finance.BEBAN_KATEGORI`).
  Catatan: label sub star-card di `dashboard.py` masih menulis "Gaji + operasional
  + lainnya" padahal `beban_lainnya` sengaja di-set `0` (SSOT-4) — teks label
  tersebut usang, angkanya benar.
- Beban dibebankan **sekali per periode kas** via snapshot beku
  `expense_periods` (idempotent) — menambah/mengubah `expenses` setelah periode
  dibekukan tidak mengubah beban periode itu.

**Posisi Kas (Cash Model v4, `backend/cash.py`)**

```text
MASTER KAS = KAS ASET
  ├─ SALDO LACI  → "Kas Aset Kecil (Laci)"     : uang fisik di toko
  └─ SALDO ASET  → "Kas Aset Besar (Pengelola)" : uang dipegang Pengelola
MASTER KAS = SALDO LACI + SALDO ASET
```

Aturan yang ditegakkan modul ini:

| Fitur | Kondisi aktual |
|---|---|
| Buku Kas (Laci) | Turunan 3 sumber (`routers/kas.py: period_rows`): **(a)** seluruh baris `payments` (DP + Pelunasan, kategori "DP"/"Pelunasan", source `order`), **(b)** `expenses` (source `expense`), **(c)** jurnal manual `kas_entries` **hanya** `layer=LACI` dan `sumber` ∈ `SUMBER_BUKU_KAS` (source `manual`). Baris kategori `Saldo Awal` tidak ditampilkan (sudah tercakup di opening). Saldo berjalan dihitung dari opening + seluruh baris sebelum `start` + baris periode, lalu difilter ke `[start, end)`; endpoint `GET /api/kas/riwayat`, ringkasan di `GET /api/overview` → `finance` |
| Layer kas | Tiap mutasi `kas_entries` punya `layer` (`LACI`/`KAS_ASET`), `sumber`, `oleh`, `ref_type/ref_id`, `saldo_setelah`. Laci & Kas Aset **tidak pernah dijumlahkan** untuk satu keputusan |
| Anti double count | Mutasi kas diberi `sumber` khusus. Buku Kas hanya menghitung `sumber` ∈ `cash.SUMBER_BUKU_KAS` = `{MANUAL, CASH_OUT, REFUND_DP, FAILED_CANCEL}` pada layer LACI; sisanya (`PAYMENT`, `MODAL`, `BEBAN`, `REFUND_GARANSI`, `TRANSFER`, `INJEKSI`, `REKONSILIASI`, `PENYESUAIAN`, `HUTANG_BEBAN`) **tidak** dihitung ganda sebagai arus kas |
| Transfer | Laci↓ Aset↑ (Master Kas tetap); endpoint menjaga Master Kas tidak berubah |
| Rekonsiliasi | `cash_counted` hanya pembanding; selisih jadi **penyesuaian Laci eksplisit**, tidak menyuntik opening |
| Injeksi | Admin memilih posisi (Laci/Aset); tanpa posisi valid → ditolak |
| Tutup Kas | `POST /api/kas/close`: snapshot `compute_finance` + hitungan laci + selisih → `kas_periods.snapshot`, status `CLOSED`, periode baru `OPEN`; arsip → `GET /api/kas/periods`. **Tutup Kas adalah batas arsip**: order tetap tampil di Transaksi setelah `CASH`, dan baru masuk halaman Garansi setelah periodenya `CLOSED` |
| Distribusi laba | SSOT-6: `10% Karyawan / 30% Pengelola / 30% Investor / 30% Hak Kas Aset` (total 100%, sisa pembulatan di Hak Kas Aset). **Dipicu Tutup Kas, bukan CTO.** Hanya bila Laba Bersih > 0, satu baris per periode (idempotent). 70% = cash-out (dieksekusi saat Tutup Kas), 30% = alokasi (dicatat sebagai mutasi Kas Aset, bukan uang) |
| Refund | 3 jenis / 3 sumber dana / **1 efek finansial**: `DP` (Laci, Admin/Kasir), `GARANSI` (Kas Aset + pre-check, **Admin**), `FAILED_CANCEL` (Laci, Admin/Kasir). `kas_entry_id` menunjuk satu-satunya efek saldo |
| Hutang Beban (SSOT-8) | Alur LOCKED: defisit Beban → Kas Aset menutup (sepenuhnya yang bisa) → sisa = Hutang Beban (carry forward). **Terpisah dari Buku Kas**, `expense_debt_periods` + `expense_debt_entries`; Kas Perputaran tidak pernah disentuh; hutang tidak pernah jadi Omzet/Laba |
| Inventaris | Stok `spareparts` + jurnal `stock_moves` (MASUK/PAKAI/BATAL) + link `service_order_parts`; decrement **atomik** dengan guard qty cukup (409 bila tidak cukup); pembatalan idempoten. `part_cost` tetap input manual — stok tidak memengaruhi Financial Core |
| Notifikasi | Outbox `notifications` + journal, anti-duplikat berbasis `dedup_key` + jendela waktu. Provider **nonaktif secara default** (`NOTIF_PROVIDER_ENABLED`) sehingga tidak pernah mengirim ke luar saat verifikasi |
| Idempotency | `Idempotency-Key` pada endpoint money/closing: retry dengan key sama mengembalikan response pertama (`replayed=True`), tidak menggandakan efek; key sama + request berbeda → 409 |
| Journal | `journal_entries` append-only lintas domain (tanpa FK ke tabel domain agar tidak terhapus cascade); semua mutasi uang mencatat ke sini |

Aturan uang (Q10): semua kolom uang `Numeric(18,2)`, konversi lewat
`money.to_decimal()` (berbasis str, tidak pernah lewat float), pembulatan
ROUND_HALF_UP hanya bila perlu. Ada regression test khusus yang memastikan
tidak ada kolom Float pada tabel moneter.

`service_orders.payment` (kolom DP legacy) **read-only arsip**; sumber
pemasukan servis adalah Payment Ledger `payments` (jurnal, append-only, tanpa
PUT/DELETE baris) + `kas_entries`.

## 12. API

Base: `/api`. Selain login, semua butuh `Authorization: Bearer <token>`.
Endpoint yang benar-benar ada di `backend/routers/` (80 total):

| Prefix | Endpoint | Fungsi |
|---|---|---|
| `/api/auth` | `POST /login`, `POST /logout`, `GET /me` | Login/logout/cek sesi (tanpa Bearer untuk login) |
| `/api/auth` | `GET /users`, `POST /users`, `PUT /users/{id}` | Kelola akun (Admin; "hapus" = `active=0`) |
| `/api/orders` | `POST /receive` | Daftarkan unit (customer+order+histori path) |
| `/api/orders` | `GET` (paginated), `GET /latest`, `GET /technicians`, `GET /history/{phone}` | Transaksi, terbaru, teknisi, histori per WA |
| `/api/orders` | `GET /{id}`, `PUT /{id}` (parsial), `DELETE /{id}` | Sumber data & simpan Update; hapus transaksi (Admin, diblokir bila sudah ada uang/klaim) |
| `/api/orders` | `POST` | Buat order mentah dari `customer_id` (**tidak dipakai frontend**) |
| `/api/orders` | `POST /{id}/handover`, `GET /{id}/history` | Serah-terima unit (DIAMBIL + `taken_at`); histori status |
| `/api/customers` | `GET`, `GET /summary`, `GET /{id}`, `GET /{id}/detail` | List, ringkasan, detail |
| `/api/customers` | `POST`, `PUT /{id}`, `DELETE /{id}` | CRUD customer (frontend pakai PUT nama/WA & DELETE) |
| `/api/claims` | `GET /lookup`, `POST /receive`, `GET`, `GET /warranty-summary` | Lookup servis, klaim garansi baru, daftar klaim, garansi aktif |
| `/api/claims` | `GET /{id}`, `PUT /{id}`, `DELETE /{id}` | Detail/ubah/hapus klaim (frontend pakai **PUT**; `GET`/`DELETE` by-id belum dipakai) |
| `/api/claims` | `GET /by-service/{id}`, `GET /warranty/detail/{service_id}` | Klaim per unit; detail garansi unit |
| `/api/expenses` | `GET`, `POST`, `PUT /{id}`, `DELETE /{id}` | CRUD beban |
| `/api/kas` | `GET /entries`, `POST /entries`, `PUT /entries/{id}`, `DELETE /entries/{id}` | Jurnal kas manual |
| `/api/kas` | `GET /riwayat`, `GET /saldo` | Buku Kas gabungan + saldo/posisi |
| `/api/kas` | `GET /aset/riwayat`, `POST /aset/masuk`, `POST /aset/keluar`, `POST /aset/transfer`, `GET /aset/cukup` | Mutasi Kas Aset (Pengelola) |
| `/api/kas` | `GET /distribusi`, `POST /close`, `GET /periods` | Distribusi laba, Tutup Kas, arsip periode |
| `/api/spareparts` | `GET`, `POST`, `PUT /{id}`, `DELETE /{id}` | CRUD stok sparepart |
| `/api/payments` | `GET /by-order/{id}`, `POST` | Jurnal pembayaran (DP/PELUNASAN) |
| `/api/refunds` | `POST /dp`, `POST /garansi`, `POST /failed-cancel` | 3 jenis refund |
| `/api/refunds` | `GET /precheck/dp/{so_id}`, `GET /precheck/garansi/{claim_id}`, `GET`, `GET /{id}` | Pre-check kecukupan dana, daftar, detail |
| `/api/beban-hutang` | `POST /proses`, `POST /lunas`, `GET`, `GET /precheck`, `GET /defisit/{kas_period_id}` | Hutang Beban (proses/lunas/daftar/pre-check/defisit) |
| `/api/inventory` | `POST /masuk`, `POST /pakai`, `POST /pakai/{id}/batal`, `GET /moves`, `GET /pemakaian/{so_id}` | Barang masuk, pemakaian part, pembatalan, jurnal & link |
| `/api/notifications` | `GET`, `GET /events` | Log notifikasi |
| `/api` | `GET /period`, `GET /overview`, `GET /statistics/status`, `GET /statistics/damage` | Periode kas, star cards+insight+finance, tren status 7 hari, tren kerusakan |
| — | `GET /api/health` | Versi + daftar route auth (tanpa login, di `main.py`) |
| — | `GET /` , `GET /static/*`, `GET /favicon.ico` | Frontend statis (di `main.py`) |

Endpoint yang ada di backend tapi **belum dipakai frontend**:
`GET /api/period`, `GET /api/claims/warranty/detail/{id}`,
`GET /api/beban-hutang/defisit/{id}`, `GET /api/notifications/events`,
`DELETE /api/claims/{id}`, `POST /api/orders` (order mentah).

## 13. Database

- **SQLite** file `servisku.db` di root (default), atau **PostgreSQL** bila env
  `DATABASE_URL` di-set (lihat `backend/database.py`). Tabel dan definisi kolom
  disesuaikan lintas dialek (`DATETIME` → `TIMESTAMP`).
- Migrasi SQLite → PostgreSQL: `backend/migrate_sqlite_to_postgres.py`.
- Tabel (21): `users`, `auth_tokens`, `customers`, `service_orders`, `payments`,
  `expenses`, `kas_periods`, `warranty_claims`, `spareparts`, `kas_entries`,
  `status_history`, `journal_entries`, `expense_periods`, `distributions`,
  `refunds`, `expense_debt_periods`, `expense_debt_entries`, `stock_moves`,
  `service_order_parts`, `notifications`, `idempotency_keys`.
- Relasi penting: `customers 1—N service_orders`; `service_orders 1—N payments`
  & `1—N status_history` (cascade delete-orphan); `service_orders 1—N warranty_claims`,
  `refunds`, `stock_moves`, `service_order_parts`; `users 1—N auth_tokens`;
  `spareparts 1—N stock_moves`. `journal_entries` **tanpa FK** (tetap utuh).
- Migrasi schema: `Base.metadata.create_all()` + `_migrate_schema()` di
  `backend/main.py` (cek kolom via inspector → `ALTER TABLE ADD COLUMN` bila belum ada;
  rename `cash_*` → `lunas_*`; backfill checklist default). Berjalan tiap startup —
  aman untuk data lama.
- Migrasi domain (startup, idempotent, non-destruktif):
  `migrations_money` (presisi uang), `migrations_warranty_claims` (kolom lifecycle klaim),
  `migrations_cash_layers` (layer/sumber kas), `_migrate_status_data`
  (petakan status legacy, backfill Payment Ledger untuk order CASH **yang ledger-nya
  masih kosong**, seed `status_history`), `_migrate_checklist_subset`.
  Log migrasi lewat `_log()` — tidak pernah `print()` polos, karena `UnicodeEncodeError`
  di console cp1252 dulu membuat `except` membatalkan `commit()` dan rollback seluruh
  migrasi tanpa jejak.
  Regresi idempotensi migrasi dikunci di `tests/test_migration_idempotent.py`.
- **Backup otomatis tiap startup** sebelum migrasi apa pun: SQLite → salin
  `backup-servisku-<ts>.db`; PostgreSQL → `pg_dump` ke `backup-servisku-<ts>.sql`
  (butuh `pg_dump` di PATH). Bila backup gagal, migrasi **data** dilewati
  (schema & migrasi non-destruktif tetap jalan) — data tidak disentuh.
- Seed (`backend/seed.py`, idempotent): hanya memastikan superadmin
  `superadmin / Admin4100`. Data demo hanya bila env `SUKABUMI_DEMO_SEED=1`
  (tidak lagi otomatis).

## 14. Frontend

- **Vanilla SPA**: `index.html` (2383 baris markup semua halaman) + `script.js`
  (6948 baris logic) + `style.css` (3405 baris styling). Tanpa build step,
  tanpa framework.
- **7 halaman utama** (bukan float-window): `#pageDashboard` (div, bukan
  section), `#pageTransaksi`, `#pagePelanggan`, `#pageGaransi`, `#pageSparepart`,
  `#pageKeuangan`, `#pageAkun`. Sisanya 11 `float-window` (lihat di bawah).
- Navigasi: hash `#/dashboard|transaksi|pelanggan|garansi|sparepart|keuangan|akun`
  + `localStorage bsf_page`; Servis Baru adalah **floating overlay** (`#pageReceive`)
  dengan flag terpisah `bsf_receive_open` + draft autosave `bsf_receive_draft`
  (tahan refresh).
- Login overlay → token di `localStorage` (Ingat Saya) / `sessionStorage`;
  401 → AuthError → kembali ke login.
- **Authority di UI**: otorisasi sesungguhnya ditegakkan backend
  (`backend/authority.py`, dependency `require_authority(Action.X)`). Frontend
  hanya **cermin** untuk menyembunyikan aksi: `BSSF_CAPS` per role
  (admin/kasir/teknisi/pengelola) diisi dari `user.role` saat bootstrap, lalu
  `applyRoleUI` menyetel `hidden` pada elemen ber-atribut `data-cap`.
  Menu Kelola Akun juga disembunyikan bila role bukan Admin/Superadmin.
  Visibilitas saldo: hanya admin/pengelola melihat saldo Aset + Master Kas.
  Role yang tidak dikenal → `ROLE_CUSTOM` (fail-closed untuk semua aksi tulis).

  ⚠️ **Cermin frontend belum 100% sinkron dengan `authority.py`** (backend tetap
  penjaga utama; selisih hanya menyebabkan tombol terlihat lalu kena 403):
  `EXPENSE_WRITE` — backend Admin saja, `BSSF_CAPS.kasir` masih memuatnya;
  `CLAIM_WRITE` — backend Admin/Kasir, `BSSF_CAPS.teknisi` masih memuatnya.
- **11 `float-window`** (drag via `.float-titlebar`, tutup via Escape/X):
  `#pageHistory` (Histori Cerdas), `#pageWarranty` (Detail Garansi),
  `#pageClaim` (Klaim Garansi), `#pageClaimReceive` (Penerimaan Klaim),
  `#pageTxDetail` (Detail Transaksi), `#pageSpare` (Form Sparepart),
  `#pageKeu` (Form Transaksi Keuangan), `#pageFormAkun` (Form Akun),
  `#pageReceive` (Servis Baru), `#pageUpdateServis` (Update Data Servis),
  `#pageNota` (Nota Penerimaan).
- Komponen lain: sidebar + topbar (jam/tanggal live), panel, `tx-table`,
  stepper Servis Baru, popup sukses Servis Baru, toast.
  Shortcut (di dalam Servis Baru): `F2` fokus Nama, `F4` fokus Device,
  `F8` / `Ctrl+S` submit form, `Enter`-next-field; `Escape` menutup window
  float yang sedang aktif.

## 15. Design System

- **Dark theme** via class `dark` di `<html>`, disimpan di `localStorage theme`
  (`dark`/`light`); bila belum pernah disimpan, mengikuti OS
  (`prefers-color-scheme: dark`). Semua komponen punya varian `.dark`.
- **Accent utama crimson/deep red** via palette Tailwind `brand`:
  `50:#fef2f2`, `100:#fee2e2`, `500:#dc2626`, `600:#b91c1c`, `700:#991b1b`;
  `darkMode: 'class'`; 202 selector `.dark` di `style.css`.
- Warna semantik: hijau pemasukan/sukses, biru finansial utama, amber beban,
  merah batal/gagal, ungu/teal status khusus (lihat `.tx-status.st-*`, `.kpi-*`).
- Tipografi: Inter (Google Fonts, weight 400–800), judul `font-weight: 800`,
  label kecil. `.rsp-no` memakai monospace 20px/800 warna `#b91c1c`.
- Pola spacing: `gap: 12px` sering dipakai antar panel/kartu; `.panel`
  `border-radius: 10px`, `padding: 14px` (16px di ≥640px).
- Komponen: `.panel`, `.tx-table`, `.float-window` + `.float-titlebar` + `.float-close`,
  `.receive-input`, `.receive-submit-btn` (hijau) / `.receive-back-btn`,
  `.tx-status` pill (26 varian `.tx-status.st-*`), `.kpi-*` (29 varian),
  **inline checkbox polos**. Skala kompak `zoom: 0.9` pada
  `#pageUpdateServis .float-body` dan `.dash-card`.
- Nota digital: `#notaDigital` lebar `min(920px, 100%)`, sheet export `.nps-sheet`
  lebar tetap **1066px** (min-height 1600px, latar titik radial), header merah,
  footer hitam. `notaSaveDigitalImage()` melepas `transform` preview lalu
  `html2canvas(sheet, {scale: 1})` — jadi PNG keluar **1:1 pada 1066px**, bukan
  skala dinamis. (README lama menyebut "±1080px + scale dinamis" — sudah usang.)

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
9. **Uang tidak boleh lewat Float** — pakai `money.to_decimal()` / `Numeric(18,2)`.
10. **Satu efek finansial per aksi** — refund/distribusi/payment menulis tepat satu
    baris kas, tercatat idempoten; jangan tambah debit kedua.
11. **Laci ≠ Kas Aset** — jangan pernah menjumlahkan atau mencampur keduanya untuk
    satu keputusan; mutasi selalu bertagging `layer` + `sumber`.
12. **Payment Ledger append-only tapi TIDAK boleh baris ganda** — satu kewajiban
    yang sudah _closed_ hanya boleh punya baris yang menutup sisanya. `payment_summary`
    menjumlahkan semua baris dan Buku Kas ikut menjumlahkannya, jadi satu
    baris ganda = uang fiktif yang ikut ter-Tutup Kas. Migrasi apa pun harus
    idempoten (lihat regression test).
13. Perubahan frontend/backend/database wajib terdokumentasi.
14. Setelah perubahan: testing (`pytest tests`) + `git status`/`git diff` review
    sebelum commit.

## 17. Workflow Pengembangan

```text
Analisa Masalah → Requirement → Audit Source → Design/UX
 → Implementasi → Testing → Dokumentasi → Git Commit
```

## 18. Current Development Status

Berdasarkan source aktual:

**Selesai / realtime:**

- Auth (login/logout/sesi) + Kelola Akun (CRUD user, guard authority, nonaktifkan-bukan-hapus)
- Servis Baru end-to-end (initial path + guard, validasi, Histori Cerdas tanpa fallback
  dummy, draft autosave tahan refresh, popup sukses)
- Status 3-dimensi + matriks transisi + authority per aksi + histori append-only
- Update Data Servis (IMEI + checklist permanen, dirty-guard, panel selaras, serah-terima unit)
- Transaksi (list paginasi backend, search/filter client-side, hapus, detail, histori status)
- Pelanggan (summary/detail/edit/hapus real)
- Garansi (warranty-summary real, lookup, klaim baru, ubah klaim)
- Sparepart CRUD real + inventaris (barang masuk, pemakaian part, pembatalan, jurnal)
- Keuangan real: Financial Core, Buku Kas 3 sumber, layer Laci/Kas Aset, transfer,
  rekonsiliasi, Tutup Kas bersnapshot + arsip, distribusi 10/30/30/30, Beban CRUD,
  Hutang Beban, refund 3 jenis, idempotency, notifikasi outbox, journal audit
- Dashboard real: overview finance, tren status 7 hari, tren kerusakan agregat DB
- Nota thermal (canvas, `notaPrint()` → iframe `window.print()`) + digital
  (PNG 1066px 1:1), QR verifikasi via `api.qrserver.com`, share `wa.me`,
  warna nomor per jenis, tanpa nota dummy, placeholder teknisi difilter
  (`notaTechnician()` membuang "- Pilih Teknisi -"), header Update compact
- Dark theme, routing tahan refresh, popup sukses, inline checkbox, pagination icon
- Dukungan PostgreSQL (`DATABASE_URL`, `pg_dump`, migrasi SQLite→PG) + deploy Ubuntu
- 42 regression test (finance core, ledger uang, cash model v4, distribusi,
  realisasi CASH, domain, blocker fix) — 41 hijau, 1 gagal karena isolasi test
  vs isi DB produksi (lihat bagian 19)

**Belum dipakai frontend:** `GET /api/period`,
`GET /api/claims/warranty/detail/{id}`, `GET /api/beban-hutang/defisit/{id}`,
`GET /api/notifications/events`, `DELETE /api/claims/{id}`,
`GET /api/claims/{id}`, `POST /api/orders` (order mentah).

**Bekas di root:** `_tmp_copy_from_A.db-shm` / `_tmp_copy_from_A.db-wal`
(sisa proses mirror DB, untracked, tidak masuk `.gitignore` karena suffix
bukan `.db`) — aman dihapus setelah tidak ada proses SQLite yang memakainya.

**Catatan dokumentasi `docs/` (semua basi — source code yang berlaku):**

| Dokumen | Isi yang sudah usang |
|---|---|
| `AI_CONTEXT.md` | Masih menyebut "Modul Garansi, Sparepart, Keuangan, Kelola Akun = UI/mock tanpa backend" — semuanya sudah real |
| `BOSS_SF_BLUEPRINT.md` | Bertulis "DRAFT FOR APPROVAL / belum diimplementasi"; majority isinya sudah masuk `statusflow.py` + `models.py`. Isinya juga menyebut `CASH` dihapus dan 9 status bernama `DIAGNOSA`/`PERBAIKAN`/`SELESAI`/`MENUNGGU SPAREPART`/`BATAL`/`GAGAL` — keputusan final yang benar-benar dipakai berbeda (lihat bagian 10) |
| `WORKFLOW_GAP.md` | Analisis 2026-09-10, sebelum status 3-dimensi & Cash Model v4; sebagian gap sudah tertutup |
| `ARCHITECTURE.md`, `DATABASE.md`, `API.md`, `FRONTEND.md`, `MODULES.md` | Ditulis sebelum layer domain + PostgreSQL ada; dipakai sebagai sejarah desain, bukan spesifikasi |

Kata kuncinya: `DIAGNOSA`/`PERBAIKAN`/`SELESAI`/`MENUNGGU SPAREPART`/`BATAL`/`GAGAL`
adalah **nama lama**; yang aktif sekarang `ANALISA`/`REPAIR`/`DONE`/`WAIT PART`/`CANCEL`/`FAILED`.

## 19. Testing

- **Ada test suite** di `tests/` (pytest): 7 file, **42 test**
  (dijalankan dengan `python -m pytest tests -q`; butuh `pytest` terinstall —
  venv `backend/venv` belum memuatnya, jalankan dengan Python global atau
  `pip install pytest`).
- ⚠️ **Ketergantungan isi DB produksi.** `tests/conftest.py` menyalin
  `servisku.db` ke folder temp lalu mengarahkan `DATABASE_URL` ke salinan itu,
  jadi DB produksi tidak pernah ditulis. fallout: test yang mengasumsikan
  kondisi awal DB kosong bisa gagal bila DB produksi sudah berisi transaksi
  pada periode aktif.
  Contoh nyata (terverifikasi 2026-10-08): `test_cash_realisasi.py::
  test_done_lunas_belum_masuk_omzet` **gagal** (`assert core["omset"] == 0`
  → `Decimal('1000000.00')`) karena `servisku.db` sudah punya 1 order `CASH`
  lunas Rp1.000.000 yang momen settlement-nya jatuh di periode kas aktif.
 Hasil saat ini: **41 passed / 1 failed**. Dengan DB kosong atau setelah order `CASH`
  tersebut dihapus, test **lolos** (sudah diverifikasi). Jadi ini masalah
  isolasi test, **bukan** bug financial core.
- Cakupan:
  - `test_finance_core.py` — Omzet hanya dari CASH, modal terpisah, DP tidak masuk
    Omzet, beban hanya gaji+operasional.
  - `test_money_ledger.py` — aritmetika uang tanpa floating error, LUNAS hanya dari
    Payment Ledger, endpoint payment menolak setelah LUNAS, tidak ada kolom Float.
  - `test_cash_model_v4.py` — Master Kas = Laci + Aset, transfer tidak mengubah
    Master Kas, injeksi memilih posisi, alokasi 30% bukan uang, rekonsiliasi jadi
    penyesuaian, visibilitas saldo per role.
  - `test_cash_distribution.py` — Laci/Kas Aset terpisah, pre-check menolak kurang,
    distribusi 10/30/30/30 = 100%, idempotent per periode, replay Tutup Kas 409.
  - `test_cash_realisasi.py` — DONE+LUNAS belum masuk Omzet, CASH masuk Omzet,
    CASH hanya dari DONE, teknisi tidak boleh CASH, replay idempoten, garansi aktif
    mulai CASH, kegagalan CASH tidak meninggalkan state setengah.
  - `test_domains.py` — warranty hanya dari unit LUNAS+bergaransi, 3 refund sumber
    dana berbeda, hutang beban tidak muncul di Buku Kas, inventaris decrement +
    pembatalan idempoten, notifikasi anti-duplikat, idempotency-key mencegah retry ganda.
  - `test_p215_blocker_fix.py` — distribusi unik per kas_period, replay tidak
    menggandakan, entry_id aman untuk dict & ORM, snapshot berbasis ledger.
- Pemeriksaan lain: `node --check frontend/script.js`, `import main` backend,
  `GET /api/health` untuk versi, dan review `git diff`.

## 20. Cara Menjalankan Project

Butuh Python 3.9+ (venv + `requirements.txt` disiapkan otomatis oleh `.bat`):

| File | Fungsi |
|---|---|
| `jalankan.bat` | Standar: buat/aktifkan `backend/venv`, install deps, `seed.py`, `uvicorn main:app --host 0.0.0.0 --port 8000 --reload`; buka `http://<IP-LAN>:8000/static/index.html` (HP via WiFi yang sama) |
| `jalankan-online.bat` | Server + tunnel Cloudflare → URL publik (maks 30 dtk tunggu server) |
| `setup-online.bat` | Sekali saja: unduh cloudflared, tulis config tunnel |
| `matikan.bat` | Matikan cloudflared + proses port 8000 |
| `deploy-ubuntu.ps1` | Sinkron source ke server Ubuntu (`sf@192.168.18.132`), extract, restart service (`bosssf.service`); `-WithDb` ikut ganti DB |

Test suite: `python -m pytest tests -q`.

Root `/` juga serve `index.html` langsung. Diagnosa cepat: `GET /api/health`.
Login default (seed): `superadmin / Admin4100`.

Env yang relevan:

| Env | Fungsi |
|---|---|
| `DATABASE_URL` | PostgreSQL URL (default: SQLite `servisku.db`) |
| `SUKABUMI_DEMO_SEED=1` | Isi data demo saat `seed.py` (default: hanya superadmin) |
| `NOTIF_PROVIDER_ENABLED` | Nyalakan pengiriman notifikasi (default: nonaktif, outbox saja) |
| `NOTIF_PRIVATE_ID` | Tujuan notifikasi |

## 21. Git

- Branch aktif: `main`.
- Alur: `git status` → `git diff` → `git add` file yang dimaksud →
  `git commit -m "..."` (pesan mengikuti gaya existing: `feat: ...`, `fix: ...`,
  `chore: ...`).
- `git push` / PR hanya bila diminta. Jangan ubah config, skip hooks,
  atau force-push tanpa instruksi.
- Di-ignore: `venv/`, `.venv/`, `*.db`, `*.sqlite3`, `*.log`, `.env`,
  `__pycache__/`, `*.py[cod]`, `.vscode/`, `.idea/`, `.DS_Store`,
  `tools/cloudflared.exe` (lihat `.gitignore`; `.pytest_cache/` self-ignore oleh
  pytest, bukan oleh `.gitignore`).