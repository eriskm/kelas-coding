# BOSS SF — BLUEPRINT ROMBAK STATUS (FINAL DECISION LOCK)

Status dokumen: **DRAFT FOR APPROVAL — belum diimplementasi.**
Prinsip: **AUDIT → MATRIX → DISCUSS → DECIDE → APPROVE → IMPLEMENT.**
Dilarang: migrasi, alter table, tambah kolom/tabel, ubah source code sebelum blueprint ini disetujui.

Keputusan desain (FINAL, tidak didebat ulang):

* Bahasa Indonesia resmi; 9 status servis; 3 dimensi terpisah
  (SERVIS ≠ PEMBAYARAN ≠ UNIT).
* `FILED` = typo `FAILED` → seragamkan ke `GAGAL`. Tidak ada status FILED.
* `CASH` dihapus sebagai status (bukan sekadar rename ke LUNAS).
* `payments` diaktifkan (DP + PELUNASAN). `status_history` wajib.
* BATAL = keputusan konsumen. GAGAL = hasil proses. Keduanya ≠ LUNAS otomatis,
  ≠ DIAMBIL otomatis.

---

## §1. STATUS SERVIS FINAL (9 nilai, Bahasa Indonesia)

```text
DITERIMA → ANALISA → DIAGNOSA → KONFIRMASI → PERBAIKAN → SELESAI
                          ↘ MENUNGGU SPAREPART ↗ (opsional)
KONFIRMASI → BATAL            PERBAIKAN → GAGAL
MENUNGGU SPAREPART → GAGAL (sparepart tak tersedia)
```

Matriks transisi yang diizinkan (backend enforce):

| Dari | Ke yang diizinkan |
|---|---|
| DITERIMA | ANALISA |
| ANALISA | DIAGNOSA |
| DIAGNOSA | KONFIRMASI |
| KONFIRMASI | MENUNGGU SPAREPART, PERBAIKAN, BATAL |
| MENUNGGU SPAREPART | PERBAIKAN, GAGAL |
| PERBAIKAN | SELESAI, GAGAL |
| SELESAI, GAGAL, BATAL | terminal (terkunci) |

Aturan tambahan:

* Lompat mundur (mis. KONFIRMASI → ANALISA) hanya bila `catatan` diisi
  (tercatat di `status_history`, dapat diaudit). Tanpa catatan → 400.
* Status terminal terkunci: perubahan wajib lewat endpoint khusus + catatan
  (mis. koreksi admin), tidak lewat PUT biasa.
* Guard per status (gabungan aturan lama + definisi baru):
  * KONFIRMASI: `rencana + estimasi > 0` (aturan lama, dipertahankan).
  * PERBAIKAN: `teknisi` wajib (baru — penanggung jawab jelas).
  * SELESAI: `rencana/tindakan + teknisi` (aturan lama DONE, nama label ikut).
  * GAGAL: `catatan` wajib (alasan/penyebab — baru, sesuai definisi).
  * BATAL: `catatan` wajib (alasan penolakan konsumen — baru, sesuai definisi).
  * SELESAI ≠ LUNAS, GAGAL/BATAL ≠ LUNAS, semua ≠ DIAMBIL (tidak ada efek
    samping ke pembayaran/unit).

---

## §2. SKEMA DATABASE FINAL

### 2.1 `service_orders` — kolom diubah/ditambah

| Kolom | Tipe | Aturan | Keterangan |
|---|---|---|---|
| `status` | VARCHAR(30) | **whitelist 9 nilai §1**, default `DITERIMA` | Nama kolom dipertahankan (minim churn); nilai full-ID |
| `payment_status` | — | **TIDAK DISIMPAN (derive)** | Lihat §2.4. Dihitung dari `payments` vs kewajiban |
| `unit_status` | VARCHAR(10) | `DI TOKO` / `DIAMBIL`, default `DI TOKO`, NOT NULL | Baru |
| `taken_at` | DATETIME | NULL = belum diambil | Baru; diisi saat transisi → DIAMBIL |
| `lunas_date` | DATE | rename dari `cash_date` | Momen LUNAS pertama (dikunci sekali) |
| `lunas_at` | DATETIME | rename dari `cash_at` | Momen LUNAS presisi (scope kas) |
| `warranty_months` | INTEGER | 1/3/6/0, NULL = legacy 30 hari | Dipertahankan; dipilih saat SELESAI (dulu saat CASH) |
| `estimate, payment(DP legacy), final_price, part_cost, modal_jasa, modal_lainnya, service_date, created_at` | — | tidak berubah | `payment` = DP era lama, read-only setelah migrasi |
| `brand, model` | — | diputuskan terpisah (matriks: kolom tanpa UI) | Di luar scope rombak status; direkomendasikan hapus/bekukan belakangan |
| `device_password` | — | tidak berubah | Kebijakan privasi terpisah |

Keputusan `payment_status` derive (bukan kolom): satu sumber kebenaran =
jurnal `payments`. Helper backend `payment_summary(order)`:

```text
kewajiban  = final_price ?? estimate   (harus > 0 agar bisa LUNAS)
total_bayar = SUM(payments.amount WHERE kind IN (DP, PELUNASAN))
sisa        = max(0, kewajiban − total_bayar)
payment_status = LUNAS  jika total_bayar >= kewajiban dan kewajiban > 0
                 BELUM LUNAS selain itu
```

Diekspos di schema response (`payment_status, total_bayar, sisa`), tidak
disimpan. Alasan: menghindari sumber ketiga yang basi (kolom + jurnal +
angka order). Cache kolom hanya bila filter BOSS terbukti lambat (nanti).

### 2.2 `payments` — AKTIF (jurnal per order)

Kolom existing dipakai + 1 kolom baru:

| Kolom | Tipe | Aturan |
|---|---|---|
| `id` | INTEGER PK | ada |
| `service_order_id` | FK → service_orders.id NOT NULL | ada; cascade hapus ikut order (dipertahankan) |
| `kind` | VARCHAR(10): `DP` / `PELUNASAN` | **BARU**, NOT NULL |
| `amount` | FLOAT NOT NULL, > 0 | ada; validasi > 0 |
| `method` | VARCHAR(30), default `CASH` | ada (tunai/transfer/QRIS — bebas teks tahap awal) |
| `note` | VARCHAR(200) | ada (keterangan bebas) |
| `created_at` | DATETIME | ada = momen bayar = momen kas |

Aturan: tolak bila `total_bayar + amount > kewajiban` (anti-overpay, 400).
Satu-satunya penulis: `POST /api/payments` (+ backfill migrasi). Edit/hapus
baris dilarang (koreksi = baris penyesuaian via jurnal manual kas, bukan
ubah ledger). Tanpa cicilan kompleks tahap ini.

### 2.3 `status_history` — BARU, wajib

| Kolom | Tipe | Aturan |
|---|---|---|
| `id` | INTEGER PK | — |
| `service_order_id` | FK → service_orders.id NOT NULL, index | cascade ikut order |
| `dari_status` | VARCHAR(30), NULL = awal (DITERIMA saat receive) | — |
| `ke_status` | VARCHAR(30) NOT NULL, whitelist §1 | — |
| `oleh` | VARCHAR(60) | username aktor (dari token auth) |
| `waktu` | DATETIME, default now, index | — |
| `catatan` | TEXT | wajib untuk GAGAL/BATAL/lompat-mundur/koreksi terminal |

Ditulis di: `POST /receive` (NULL → DITERIMA), setiap PUT yang mengubah
status, koreksi terminal. Tanpa ini §10 (acceptance histori) gagal.

### 2.4 Tabel lain — tidak berubah struktur

`customers, users, auth_tokens, expenses, kas_entries, kas_periods,
warranty_claims, spareparts` tetap. `kas_periods.snapshot` historis
**dibekukan** (tidak dihitung ulang — arsip periode lama merujuk dunia CASH).

---

## §3. MAPPING LEGACY → FINAL (eksplisit, tanpa replace global)

Inventaris aktual 16 string (audit): 9 UI + `RECEIVED` + 8 seed legacy
(`WAITING_PART QC READY COMPLETED RECEIVED DIAGNOSIS WAITING_APPROVAL`,
overlap `REPAIR`).

| Legacy | Final | Dasar |
|---|---|---|
| RECEIVED | DITERIMA | default model generik = penerimaan |
| ANALISA | ANALISA | identik |
| DIAGNOSIS | DIAGNOSA | padanan Inggris→Indonesia |
| KONFIRMASI | KONFIRMASI | identik |
| WAIT PART, WAITING_PART | MENUNGGU SPAREPART | padanan (spasi vs underscore disatukan) |
| REPAIR | PERBAIKAN | padanan |
| DONE, COMPLETED | SELESAI | nilai sukses (COMPLETED = seed selesai) |
| READY | SELESAI | seed = selesai siap ambil + berbayar (asumsi, diverifikasi hitungan) |
| QC | PERBAIKAN | seed = tahap cek dalam proses (asumsi, diverifikasi) |
| WAITING_APPROVAL | KONFIRMASI | padanan menunggu persetujuan |
| FAILED, FILED | GAGAL | **FINAL LOCK: FILED = typo FAILED** |
| CANCEL, CANCELLED | BATAL | padanan |
| CASH | SELESAI + audit pembayaran (lihat §3.1) | bukan status; ditentukan dari kondisi bayar aktual |

### §3.1 Aturan migrasi data CASH (tanpa mengarang)

Untuk tiap order `status = CASH`:

1. `status` → `SELESAI`.
2. Backfill `payments`: baris `DP` sebesar `payment` bila > 0; baris
   `PELUNASAN` sebesar `max(0, (final_price ?? estimate) − payment)`.
   Jika `payment > kewajiban` → tandai flag `OVERPAY_REVIEW`, PELUNASAN = 0.
3. `cash_date/cash_at` → `lunas_date/lunas_at` (rename kolom, nilai ikut).
4. `payment_status` = hasil derive (mayoritas akan LUNAS; yang tidak —
   jujur tercatat BELUM LUNAS, ditandai `CASH_UNPAID_REVIEW`).
5. `unit_status` → `DI TOKO`, `taken_at` = NULL (fisik tak diketahui —
   jangan dikarang).

Untuk non-CASH: status ikut tabel §3; `unit_status` = `DI TOKO`,
`taken_at` = NULL; `payments` tidak dibuat (DP kolom `payment` tetap apa
adanya sebagai arsip angka).
`status_history`: 1 baris per order (`dari` = NULL, `ke` = status final,
`oleh` = `migrasi`, `waktu` = `created_at`, catatan `migrasi awal`).

Verifikasi (hitungan sebelum/sesudah, nol selisih selain mapping):
`COUNT(*)`, `COUNT per status lama vs baru`, `SUM(final_price) vs
SUM(payments)`, relasi yatim (`payments/order tanpa customer`,
`claim tanpa order`), garansi (re-derive daftar penerima).

---

## §4. API SCHEMA (perubahan)

* `ServiceReceiveIn.status`: default `DITERIMA` (dulu ANALISA); whitelist §1.
  Menerima tanpa status → DITERIMA + baris history.
* `ServiceOrderUpdate.status`: whitelist §1 + enforce matriks transisi §1
  (400 + pesan bila edge dilarang / catatan kosong untuk GAGAL/BATAL/mundur).
* Response order (`List/Out`): tambah `payment_status, total_bayar, sisa`
  (derive, §2.1), `unit_status, taken_at`; `cash_date/cash_at` diganti
  `lunas_date/lunas_at` (rename; FE lama yang baca `cash_*` ikut diubah §11).
* `POST /api/payments` (BARU): `{service_order_id, kind: DP|PELUNASAN,
  amount>0, method?, note?}` → 201 + ringkasan bayar. Tolak overpay (400).
  GET daftar payments per order (untuk panel bayar + nota).
  Tanpa PUT/DELETE baris (ledger append-only).
* `POST /api/orders/{id}/handover` (BARU): `unit_status → DIAMBIL`,
  `taken_at = now` (atau tanggal diinput). Idempoten. Alternatif: via PUT
  field `unit_status` — dipilih endpoint khusus agar `taken_at` terkontrol
  server (anti tanggal karangan).
* `GET /api/orders/{id}/history` (BARU): list `status_history` order
  (untuk timeline UI minimal).
* `GET /api/statistics/status`: `by_status` = 9 nilai §1 (ganti list lama).
* Hapus/asingkan: referensi `cash_*` di schema response diganti `lunas_*`.

## §5. STATUS TRANSITION (business logic, `routers/orders.py`)

* `receive_unit`: tulis `status=DITERIMA` (bila tak dikirim), tulis history
  (NULL → DITERIMA, oleh=user token).
* `update_order`: bila `status` berubah → (1) cek whitelist, (2) cek edge
  matriks §1 terhadap status kini, (3) cek guard per status, (4) `setattr`,
  (5) tulis history (`dari, ke, oleh, now, catatan`).
* Guard dipertahankan: KONFIRMASI (rencana+estimasi), SELESAI
  (rencana/tindakan+teknisi). Guard baru: PERBAIKAN (teknisi),
  GAGAL/BATAL (catatan wajib). Guard CASH dihapus bersama statusnya.
* Kunci `lunas_date/lunas_at` sekali saat derive pertama LUNAS
  (pengganti lock `cash_*` lama, `orders.py:256-261`).
* `warranty_months` dipilih saat SELESAI (validasi 0/1/3/6 tetap);
  default 1 bila NULL (aturan lama dipertahankan).

## §6. STATUS HISTORY (penulis + pembaca)

* Penulis: receive + update-berubah-status + koreksi terminal (satu helper
  `log_transition(db, order, dari, ke, oleh, catatan)`).
* `oleh` = username dari token auth (jaksa: tanpa auth tak bisa PUT —
  sudah berlaku kini via Bearer).
* Pembaca: `GET /{id}/history` + timeline minimal di Detail Transaksi
  (§11). Backfill migrasi 1 baris/order (§3.1).

## §7. PAYMENTS (endpoint + aturan)

* `POST /api/payments`: validasi order ada; `kind ∈ {DP, PELUNASAN}`;
  `amount > 0`; tolak bila `total + amount > kewajiban` (kewajiban =
  `final_price ?? estimate`, harus > 0); `method` bebas teks
  (CASH/TRANSFER/QRIS); tulis `created_at = now` (momen kas).
* Response tiap bayar: `{total_bayar, sisa, payment_status}` — FE langsung
  tampilkan tanpa hitung sendiri.
* DP lama (`service_orders.payment`): read-only arsip; ditampilkan di
  panel bayar sebagai baris "DP awal (legacy)" dan **dihitung dalam
  total_bayar** (agar CASH-lama yang cuma punya DP tidak dianggap nol).
  Aturan derive final: `total_bayar = payment_legacy + SUM(payments)`.
* Tanpa cicilan kompleks: hanya DP + PELUNASAN (bisa >1 baris PELUNASAN?
  diputuskan TIDAK — satu PELUNASAN; kelebihan = overpay ditolak).

---

## §8. KAS (`routers/kas.py` + `dashboard.compute_finance`)

* Pemasukan servis = `SUM(payments.amount WHERE created_at ∈ periode)`,
  bukan filter `status=CASH`. Baris Buku Kas per pembayaran
  (label: `DP — <no>` / `Pelunasan — <no>`), nominal = amount.
* DP legacy (`service_orders.payment`): masuk kas bila order terkait
  dilunasi dalam periode? Prinsip jujur: DP legacy tanpa `created_at`
  pembayaran → **tidak** dimasukkan arus periode berjalan; tercatat di
  `total_bayar` order saja. (Mencegah uang hantu di kas hari ini.)
* `kas_entries/expenses/kas_periods`/snapshot: tidak berubah. Periode dan
  Tutup Kas tidak berubah (kasus arsip otomatis: lihat keputusan terbuka D).
* `_cash_moment` diganti `_paid_moment` (momen bayar per baris payments).

## §9. DASHBOARD

* `overview` grouping baru: `selesai=[SELESAI]`, `aktif=[DITERIMA, ANALISA,
  DIAGNOSA, KONFIRMASI, MENUNGGU SPAREPART, PERBAIKAN]`,
  `gagal_batal=[GAGAL, BATAL]`. Grup legacy (`COMPLETED/READY/QC/...`)
  dihapus setelah migrasi.
* `star omset` = SUM payments periode; `n_lunas` = order mencapai LUNAS
  periode ini; tren `selesai` = LUNAS per hari (ganti cash_days).
* `STATUS_META` frontend = 9 nilai §1 (warna/icon diperbarui, Bahasa
  Indonesia). `pending_set` tren = 6 status aktif.

## §10. GARANSI (lepas dari CASH)

* Syarat baru: `status=SELESAI` AND `payment_status=LUNAS` AND
  `warranty_months != 0` (ganti `status=CASH` di `claims.py:278`).
* Awal garansi: `taken_at ?? lunas_date ?? service_date`
  (ganti `cash_date`, `claims.py:32-34,46-65`). Akhir = awal + months
  (NULL legacy = 30 hari, dipertahankan).
* Klaim (`receive/update`) tidak berubah struktur; `origin` tetap order.
* Panel `Closing & Masa Garansi` tampil saat SELESAI (ganti trigger CASH);
  nota garansi terbit saat SELESAI+LUNAS (ganti guard CASH).

## §11. NOTA + FRONTEND INTEGRATION

* Snapshot stages = 7 utama (`DITERIMA→…→SELESAI`) + cabang terminal
  (BATAL/GAGAL tampil merah informatif, bukan netral-buta).
* Blok pembayaran nota: `Estimasi / DP / Pelunasan / Total Bayar / Sisa /
  Status Pembayaran` (dari API, bukan hitung FE). Blok serah terima:
  `DI TOKO / DIAMBIL + tanggal`.
* Dropdown: receive 5 awal (`DITERIMA* ANALISA DIAGNOSA KONFIRMASI` +
  langsung? receive = DITERIMA default; opsi lanjutan tetap ada? —
  diputuskan: receive sediakan DITERIMA..KONFIRMASI + PERBAIKAN? minimal
  DITERIMA default; izinkan sampai KONFIRMASI seperti pola lama 5 opsi).
  Update: 9 nilai §1 (mirror dua dropdown dipertahankan).
* Badge/label/chart Bahasa Indonesia penuh; legacy map dipertahankan
  read-only untuk arsip tampilan (tidak bisa ditulis).
* Panel bayar baru di Update: daftar payments + tombol Bayar
  (kind+amount+method) + ringkasan LUNAS/sisa dari server.
* Tombol `Serahkan Unit (DIAMBIL)` di Update + Detail (confirm; isi
  `taken_at`; idempoten).
* Timeline minimal di Detail Transaksi: list `waktu — dari → ke — oleh —
  catatan` (dari `GET /history`).
* Validasi FE mengikuti §5 (catatan wajib GAGAL/BATAL; teknisi wajib
  PERBAIKAN; tanda `*` dinamis diperluas).
* doneWa: picu saat SELESAI (ganti trigger DONE) + cantumkan sisa bayar
  bila BELUM LUNAS.

---

## §12. RENCANA MIGRASI (aman, non-destruktif, terkontrol)

Urutan: backup → skema → data → verifikasi. Dilarang: DELETE massal,
truncate, reset DB.

1. **Backup**: salin `servisku.db` → `backup-servisku-<timestamp>.db`
   (pola repo ada). Catat `COUNT(*)` + `COUNT per status` + `SUM` awal.
2. **Skema** (via `_migrate_schema`, pola repo — `PRAGMA` + `ADD COLUMN`
   bila belum ada; rename `cash_date→lunas_date`, `cash_at→lunas_at`
   via `RENAME COLUMN` SQLite; tabel baru `status_history`; kolom baru
   `payments.kind`, `service_orders.unit_status`, `taken_at`):
   semua idempoten, aman diulang.
3. **Data** (skrip sekali-pakai, bukan kode aplikasi): mapping §3 +
   backfill payments CASH (§3.1) + unit DI TOKO + history 1 baris/order.
   Khusus `CASH_UNPAID_REVIEW` / `OVERPAY_REVIEW` / asumsi QC/READY:
   cetak daftarnya untuk keputusan manual, jangan diam-diam.
4. **Verifikasi**: ulangi hitungan (1); nol relasi yatim baru; re-derive
   daftar garansi (bandingkan sebelum/sesudah); snapshot `kas_periods`
   lama byte-identik (tak tersentuh); smoke API (receive→lunas→diambil→
   kas→garansi→nota).

## §13. REGRESSION TEST (skenario wajib lolos)

1. Servis normal DITERIMA→…→SELESAI→LUNAS→DIAMBIL (nota + WA + garansi).
2. Sparepart: via MENUNGGU SPAREPART → GAGAL (part tak ada, catatan wajib).
3. Tolak estimasi: → BATAL (catatan wajib) + unit DIAMBIL.
4. DP lalu pelunasan: status BELUM LUNAS → LUNAS tepat di angka pas;
   overpay ditolak.
5. Transisi ilegal ditolak (SELESAI→PERBAIKAN tanpa catatan; terminal
   tanpa endpoint koreksi).
6. History lengkap per order (7+ baris, aktor + waktu benar).
7. Kas: pembayaran masuk periode benar; Tutup Kas snapshot konsisten.
8. Data legacy: CASH lama → SELESAI + payments backfill + garansi tetap
   jalan; READY/COMPLETED lama tampil SELESAI.
9. Kriteria §15 FINAL LOCK dicek satu per satu (status legacy nol aktif,
   pembayaran dari payments, DI TOKO vs DIAMBIL, histori tercatat, kas
   dari pembayaran, garansi tanpa CASH, dashboard baru, data utuh).

## §14. KEPUTUSAN TERBUKA (perlu jawaban kamu sebelum implementasi)

* **A. Pengganti FILED/arsip.** FILED dihapus total → tujuan "Transaksi
  clean" kemarin kehilangan mekanisme. Opsi: (a) default Transaksi
  sembunyikan `SELESAI/GAGAL/BATAL + DIAMBIL` + toggle "arsip" (rekomen —
  tanpa status baru, murni filter); (b) halaman Riwayat terpisah; (c)
  tampil semua. Rekomendasi: (a).
* **B. Opsi receive.** 5 opsi awal versi baru = ? Rekomendasi:
  `DITERIMA* ANALISA DIAGNOSA KONFIRMASI` (+ `MENUNGGU SPAREPART`?) —
  tanpa terminal & tanpa PERBAIKAN? pola lama izinkan sampai DONE.
  Rekomendasi: `DITERIMA, ANALISA, DIAGNOSA, KONFIRMASI, PERBAIKAN`
  (kerja bisa langsung jalan; terminal tetap via Update).
* **C. `payment` (DP legacy) dalam total_bayar.** Rekomendasi: YA dihitung
  (keuangan jujur untuk CASH lama), ditandai baris legacy.
* **D. Tutup Kas + arsip otomatis.** Rekomendasi: TIDAK ada perubahan
  status saat Tutup Kas (arsip = filter (a)). Aturan kemarin (auto-FILED)
  batal demi hukum karena FILED tidak ada.
* **E. Rename `cash_*` → `lunas_*` vs pertahankan nama.** Rekomendasi:
  rename (jelas, migration RENAME aman) + FE ikut.
* **F. `brand/model`, `email/address`, `Setor Ke`, metode-% jasa.**
  Rekomendasi: di luar rombak ini; catat sebagai tech-debt batch berikut
  (bekukan, jangan hapus).

---

*Akhir blueprint. Menunggu APPROVE (atau revisi per poin) sebelum
IMPLEMENTATION ORDER §14 FINAL LOCK dijalankan.*
