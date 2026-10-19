# FIN-MIRROR — Laporan Mirroring Financial Logic Project A → Project B

Tanggal: 2026-10-10
Sumber kebenaran: **Project A** (`D:\PAKE SAAT INI`)
Target: **Project B** (`D:\PRAKTEK MJPRO`)

---

## 0. Temuan paling penting: A yang hidup adalah `app.py`, bukan `blueprints/`

Sebelum mapping lain, satu fakta yang mengubah seluruh pendekatan:

`D:\PAKE SAAT INI\blueprints\*.py` **tidak pernah dipakai**. Tidak ada
`register_blueprint(...)` di seluruh repo. Semua financial logic yang benar-benar
berjalan ada di `app.py` (3247 baris) + `engine/kalkulator.py`. Kalau mirroring
mengacu ke `blueprints/keuangan.py`, hasilnya salah.

| Sumber | Status |
|---|---|
| `app.py` | ✅ APP YANG JALAN (`Run`, `jalankan.bat`) |
| `engine/kalkulator.py` | ✅ dipakai (`app.py:2374,2794,2813`) |
| `blueprints/*.py` | ❌ dead code (hasil slicing AST) |
| `engine/operasional.py` | ⚠️ import tapi tidak pernah dipanggil |

Aplikasi A di-backup dengan `jalankan.bat` / `python app.py`, bukan blueprint.

---

## 1. Ringkasan: berapa banyak yang benar-benar berbeda?

Dari seluruh financial logic A, **hanya 3 aturan yang benar-benar berbeda
dari B**. Sisanya sudah identik lebih dulu.

| # | Aturan A | A | B (sebelum) | Status |
|---|---|---|---|---|
| 1 | Beban permanen | `SUM(nilai) FROM beban` tanpa filter tanggal | `expenses` ber-tanggal, di-freeze per periode | ❌ **berbeda** → sudah dimirror |
| 2 | Gate Omzet | CASH saja | CASH **DAN** LUNAS | ❌ **berbeda** → sudah dimirror |
| 3 | Bagi hasil 30% Kas Aset | ditambahkan ke saldo laci (bug berlipat) | alokasi, tanpa mutasi | ⚠️ **tidak dimirror** (disetujui owner) |
| 4 | Arsip + hard delete | `DELETE FROM servis` saat tutup kas | Q14: tidak ada hard delete | ⚠️ **tidak dimirror** (disetujui owner) |
| 5 | Rumus Laba Kotor | `Harga Jual − ModalPart − ModalJasa − Lain-lain` bila `Status='Cash'` | sama | ✅ sudah sama |
| 6 | Rasio bagi hasil | 10 / 30 / 30 / 30 | 10 / 30 / 30 / 30 | ✅ sudah sama |
| 7 | Kategori beban | hanya `Gaji` + `Operasional` | sama | ✅ sudah sama |
| 8 | Eksklusi kas kecil | `uraian != 'MODAL KAS KECIL (LACI)'` | sudah jadi layer `LACI` | ✅ sudah konvergen |
| 9 | DP | kolom pasif, tidak masuk hitungan | sudah jadi escrow, tidak masuk Omzet | ✅ sudah konvergen |
| 10 | **Transaksi kas manual → laba** | **masuk** ke laba (rumus A-1) | **tidak masuk** (perilaku A-2) | ❌ **berbeda** → sudah dimirror |

---

## 2. Aturan yang DIMIRROR

### FIN-MIRROR-1 — Beban permanen

**Bukti A** — `app.py:983-984` dan `app.py:1017`:
```python
g_hari = conn.execute("SELECT SUM(nilai) FROM beban WHERE kategori = 'Gaji'").fetchone()[0] or 0
o_hari = conn.execute("SELECT SUM(nilai) FROM beban WHERE kategori = 'Operasional'").fetchone()[0] or 0
...
beban_tetap = g_hari + o_hari
saldo_berjalan -= beban_tetap
```
Tidak ada `WHERE tanggal`. Tabel `beban` tidak punya kolom tanggal sama sekali
(skimanya: `id, kategori, nama_beban, nilai`). Nilai 605.000 dipotong dari
siklus mana pun, setiap hari, selamanya.

**Bukti B (sebelum)** — `finance.freeze_expenses_for_period` hanya membekukan
expense yang `created_at`-nya jatuh di periode itu.

**Dampak nyata di produksi Anda:** periode `2026-10-11` dan seterusnya tidak
punya expense baru → beban = 0 → `laba_bersih = laba_kotor` → distribusi
10/30/30/70 berjalan **dari laba kotor**, bukan laba bersih. Verifikasi:

| | sebelum | sesudah |
|---|---|---|
| periode 2026-10-10 `laba_bersih` | `0` | `-605.000` |

**Implementasi B:**
- `models.Expense.recurring` (Boolean, `nullable=False`, default `True`) —
  opt-in flag: `True` = permanen (default, sama dengan A),
  `False` = satu-off bertanggal (kapabilitas lama B, tetap dipertahankan).
- `finance.freeze_expenses_for_period` membekukan setiap expense `recurring`
  ke **setiap** periode; expense `recurring=False` tetap memakai filter
  moment seperti sebelumnya.
- Migrasi `migrations_expense_recurring.py` — hanya `ADD COLUMN`, idempotent.
- API `POST/PUT /api/expenses` kini menerima dan mengembalikan `recurring`.

**Perlindungan histori:** sifat beku satu-shot **tidak** diubah. Kalau periode
sudah punya baris `expense_periods`, fungsi itu tidak melakukan apa-apa — jadi
Laba Bersih periode closed tidak akan berubah karena ada beban baru yang dibuat
belakangan. Periode yang belum punya baris beku (termasuk periode berjalan)
tetap terbawa katalog `recurring`.

### FIN-MIRROR-2 — Gate Omzet = CASH

**Bukti A** — `app.py:1715`:
```python
laba_final = h_jual - m_part - m_jasa - m_lain if stat == 'Cash' else 0
```
Satu-satunya tempat `Laba Kotor` ditulis di A. Tidak ada syarat pelunasan.

**Bukti B (sebelum)** — `finance.settled_orders` memfilter
`payment_summary(...)["payment_status"] == "LUNAS"`, dan
`statusflow.order_profit` punya gate LUNAS yang sama.

**Implementasi B:**
- `finance.settled_orders` — gate LUNAS dihapus; cohort = unit `CASH` saja.
- `statusflow.order_profit` — gate LUNAS dihapus; gate tersisa hanya `CASH`.
- `statusflow.cash_moment()` (baru) — momen CASH = `taken_at` → `lunas_at` →
  `lunas_date@12:00` → `service_date@12:00` → `created_at`. `taken_at` harus
  jadi sumber pertama karena order CASH yang belum LUNAS **tidak punya**
  `lunas_at`, sehingga tidak bisa diatribusikan ke periodenya tanpa ini.

Konsekuensi yang perlu disadari: **pengakuan laba pada B sekarang tidak
menunggu uang benar-benar diterima.** Sesuai keputusan owner, ini disengaja.

### FIN-MIRROR-3 — `kewajiban` sebagai satu sumber Omzet

**Bug yang ditemukan, bukan aturan baru.** `finance.compute_finance_core`
sebelumnya:
```python
omset += to_decimal(getattr(o, "final_price", None)) or to_decimal(getattr(o, "estimate", 0))
```
Operator `or` membuat `final_price = 0` diam-diam jatuh ke `estimate`, padahal
`statusflow.kewObligation` sudah null-coalescing (`??`). Dua sumber kebenaran
untuk angka yang sama. Diganti ke `kewajiban(o)` supaya sama dengan
`order_profit` dan dengan A (`sum(s['Harga Jual'] or 0)` — nol tetap nol).

---

## 3. Aturan yang TIDAK dimirror (disetujui owner)

### 3.0 FIN-MIRROR-4 — Transaksi kas manual masuk laba (rumus A-1)

Ini gap paling material yang pernah ada, dan sekarang sudah ditutup.

**Project A punya dua rumus laba yang SALING BERTENTANGAN:**

| | Sumber | `transaksi_tambahan` |
|---|---|---|
| **A-1** | `app.py:369-376`, `engine/kalkulator.py:15-27`, bot Telegram, milestone CTS/CTO/CTH | **MASUK** ke laba |
| **A-2** | `app.py:1004-1019`, `dashboard.html:48`, basis bagi hasil | **TIDAK** masuk laba |

```python
# A-1 (app.py:372-376)
res_tambahan = conn.execute("SELECT SUM(CASE WHEN jenis='Masuk' THEN nominal ELSE -nominal END) "
                            "FROM transaksi_tambahan WHERE uraian != 'MODAL KAS KECIL (LACI)')...
laba_tambahan = res_tambahan.fetchone()[0] or 0
laba_kotor = laba_servis + laba_tambahan      # <-- tambahan MASUK ke laba
```

A-1 dan A-2 berbeda **hanya** di suku `tambahan`; selisih `omset − modal` sama
karena A menulis `Laba Kotor = Harga Jual − modal` untuk setiap unit Cash.

**Dampak yang sudah diukur (sebelum fix):** setoran kas manual Rp 100.000
menambah `laba_bersih` sebesar Rp 100.000 di A, tetapi **Rp 0** di B.

**Pemetaan presisi ke B:**

| Proyek A | Project B |
|---|---|
| `transaksi_tambahan` | `kas_entries` dengan `sumber = MANUAL`, `layer = LACI` |
| `uraian != 'MODAL KAS KECIL (LACI)'` | `kategori != 'Saldo Awal'` |
| `jenis` Masuk/Keluar | `jenis` Masuk/Keluar |

Keduanya menandai hal yang sama: baris float kas fisik awal siklus (di A uraian
sentinel, di B kategori opening).

**Yang sengaja TIDAK dihitung** (cegah double count dengan suku lain):
`PAYMENT` (sudah masuk Omzet), `MODAL` (sudah masuk Modal), `BEBAN` (sudah masuk
Beban), `CASH_OUT` (di A, bagi hasil hanya jadi baris `history_kas` di memori
`app.py:1029-1036` dan **tidak pernah** ditulis ke `transaksi_tambahan`),
serta layer `KAS_ASET` (bukan arus Laci).

**Batas periode:** A tidak punya dimensi waktu — `transaksi_tambahan` di-`DELETE`
seluruhnya saat tutup buku (`app.py:2533`), jadi A selalu memakai seluruh isi
tabel. B tetap memperiodisasi agar kas tidak dihitung ganda antar siklus.

Rumus final B sekarang: `LABA BERSIH = OMZET − MODAL_PART − MODAL_JASA −
MODAL_LAIN + TAMBAHAN − BEBAN`. Ambang CTS/CTO di `routers/dashboard.py` juga
mengikuti A-1 (ambang di A dibandingkan terhadap `laba_servis + tambahan`).

### 3.1 Bug Kas Aset 30% — tidak dimirror

`app.py:1036` menampilkan Setoran Kas Aset 30% sebagai DEBIT tapi **tidak**
mengurangi `saldo_berjalan`. Akibatnya 30% itu tetap di laci, menjadi
`kas_awal` siklus berikutnya, lalu **di-split 10/30/30/30 lagi setiap hari** —
bug berlipat yang menginflasi laba bersih pada siklus-siklus berikutnya.

B sudah benar (`distribution.py:161-165`): 30% Hak Kas Aset adalah **alokasi**,
bukan uang baru; posisi tetap di Laci sampai terjadi transfer fisik.

### 3.2 Arsip + hard delete — tidak dimirror

`app.py:2526` `DELETE FROM servis WHERE rowid = ?` saat tutup buku. B punya
aturan Q14 (historical record tidak boleh hard delete) dan batasan tugas
"jangan menghapus data historis Project B". Periode `CLOSED` di B menyimpan
snapshot lengkap tanpa menghapus apa pun.

### 3.3 Gate LUNAS pada arsip garansi — **GAP, belum diputuskan**

A membuat record garansi untuk **setiap** unit Cash saat tutup buku
(`app.py:2490: if stts == 'cash'`), tanpa syarat LUNAS.

B hanya membuat arsip garansi untuk order **LUNAS**
(`routers/claims.py:48-51`), dan daftar garansi hanya menampilkan periode
`CLOSED` (`claims.py:346-353`).

**Tidak saya ubah.** Alasannya: di B gate ini juga membatasi
`refund_garansi` (ceiling refund berbasis `claim.customer_cost`), sedangkan di A
tidak ada jalur keuangan pengembalian dana garansi sama sekali. Mengganti gate
B berarti mengarang aturan yang tidak ada buktinya di A — melanggar aturan
"jangan menebak perilaku A yang belum terbukti". Perlu keputusan owner.

---

## 4. File yang diubah

| File | Perubahan |
|---|---|
| `backend/finance.py` | M1 (freeze recurring), M2 (gate CASH), M3 (`kewajiban`), **M4 (`tambahan_kas`)**, helper `_expense_moment` / `_kas_moment` |
| `backend/statusflow.py` | M2 (`cash_moment()`, `_as_datetime()`, hapus gate LUNAS di `order_profit`) |
| `backend/models.py` | kolom `Expense.recurring` + import `Boolean` |
| `backend/migrations_expense_recurring.py` | **baru** — `ADD COLUMN` idempotent |
| `backend/main.py` | daftarkan migrasi di `on_startup` |
| `backend/schemas.py` | `recurring` di `ExpenseCreate` / `Update` / `Out` |
| `backend/routers/expenses.py` | terima `recurring` saat create/update |
| `backend/routers/dashboard.py` | M4 — ambang CTS/CTO memakai `laba_kotor + tambahan` (A-1) |
| `tests/conftest.py` | jalankan migrasi baru di fixture boot |
| `tests/test_fin_mirror.py` | **baru** — 18 regression test |

**Tidak disentuh:** `frontend/` (UI, layout, identitas visual),
`routers/orders.py`, `routers/kas.py`, `cash.py`, `distribution.py`,
`closing.py`, `refunds.py`, `expense_debt.py`, `inventory.py`, `journal.py`.

> Catatan: `git status` juga menunjukkan `frontend/index.html`,
> `script.js`, `style.css` sebagai modified. Waktu modifikasi 15:44–16:02,
> **sebelum** sesi ini dimulai — itu perubahan uncommitted milik Anda sendiri,
> bukan hasil mirroring ini.

---

## 5. Hasil pengujian

### 5.1 Baseline vs sesudah

| |Sebelum | Sesudah |
|---|---|---|
| Test suite | 58 passed | **76 passed** (58 lama + 18 baru) |

 Nol regresi.

### 5.2 Verifikasi kesetaraan A vs B (data produksi, pada salinan)

```
[1] SELURUH DATA (setara A: semua baris Cash yang masih di tabel)
   A omzet              2,550,000
   A modal              1,775,000
   A beban                605,000
   A laba kotor           775,000
   A laba bersih          170,000
   -> A Bagi Hasil: bonus=17,000 kelola=51,000 investor=51,000 aset=51,000

[2] PERIODE CLOSED  [2026-10-08 16:00 -> 2026-10-10 16:04]   status CLOSED
                                  A                  B    COCOK
  omzet                   2,550,000          2,550,000       YA
  modal                   1,775,000          1,775,000       YA
  beban                     605,000            605,000       YA
  laba kotor                775,000            775,000       YA
  laba bersih               170,000            170,000       YA

  Periode OPEN  [2026-10-10 16:04 -> 2026-10-11 16:00]
                                  A                  B    COCOK
  omzet                           0                  0       YA
  modal                           0                  0       YA
  beban                     605,000            605,000       YA   <- fixed
  laba kotor                      0                  0       YA
  laba bersih              -605,000           -605,000       YA

[3] DISTRIBUSI TERSIMPAN vs PREVIEW
  periode 2026-10-08: laba=170.000 karyawan=17.000 kelola=51.000 investor=51.000 aset=51.000
  rasio 10/30/30/30 konsisten: True
```

Distribusi yang sudah tersimpan **tidak berubah** — `Distribution` periode
`2026-10-08` masih 17.000/51.000/51.000/51.000, identik dengan bagi hasil
yang dihitung A secara independen.

### 5.3 Verifikasi langsung ke API yang sedang berjalan

`laba_bersih` periode berjalan berubah dari `0` → `-605.000`, dan distribusi
otomatis menolak berbagi hasil pada laba negatif:
```json
{"eligible": false, "alasan": "Laba Bersih tidak positif", "laba_bersih": -605000.0}
```
`GET /api/expenses` kini mengembalikan `"recurring": true` untuk keenam beban.

### 5.4 Smoke test fitur nonkeuangan

OK: `/api/health`, `/api/auth/me`, `/api/orders`, `/api/orders/latest`,
`/api/customers`, `/api/spareparts`, `/api/claims`, `/api/claims/warranty-summary`,
`/api/payments/by-order/{id}`, `/api/inventory/pemakaian/{id}`,
`/api/kas/periods`, `/api/kas/riwayat`, `/api/kas/saldo`,
`/api/kas/aset/riwayat`, `/api/kas/distribusi`, `/api/refunds`,
`/api/beban-hutang`.

### 5.5 18 regression test baru

| Test | Mengunci apa |
|---|---|
| `test_beban_katalog_dipotong_di_setiap_periode` | M1 — burden 605.000 terbawa 3 periode berturut |
| `test_beban_recurring_default_true_dan_not_null` | M1 — default permanen, kolom NOT NULL |
| `test_beban_one_off_hanya_satu_periode` | M1 — `recurring=False` tidak merembet |
| `test_freeze_beban_idempoten_dan_tidak_menggandakan` | SSOT-4 |
| `test_periode_lama_yang_sudah_beku_tidak_berubah` | **proteksi histori** |
| `test_kategori_di_luar_beban_kategori_tidak_dihitung` | hanya gaji + operasional |
| `test_cash_tanpa_lunas_tetap_diakui` | M2 — CASH tanpa LUNAS diakui |
| `test_non_cash_nol_meski_lunas` | M2 — REFUND = 0 meski LUNAS |
| `test_cash_momen_dipakai_bukan_lunas` | M2 — `taken_at` sebagai momen |
| `test_lunas_tanpa_cash_tidak_masuk_omzet` | M2 — hanya CASH |
| `test_final_price_nol_tidak_jatuh_ke_estimate` | M3 |
| `test_omset_konsisten_antara_core_dan_order_profit` | M3 |
| `test_laba_bersih_empat_pengurang` | SSOT-5 + M4 (invariant 4 pengurang + `tambahan`) |
| `test_tambahan_manual_masuk_laba_bersih` | **M4** — kas Masuk menambah laba |
| `test_tambahan_manual_keluar_mengurangi_laba` | **M4** — kas Keluar mengurangi laba |
| `test_tambahan_tidak_ganda_dengan_tiga_suku_lain` | **M4** — hanya `sumber=MANUAL` |
| `test_tambahan_hanya_dalam_periode` | **M4** — periodisasi |
| `test_tambahan_ikut_menaikkan_ambang_milestone` | **M4** — CTS/CTO ikut `tambahan` |

### 5.6 Verifikasi A-1 vs B setelah FIN-MIRROR-4

```
ENTRY KAS MANUAL (padanan transaksi_tambahan A)
  id=16 kategori='Penjualan Service' jenis=Masuk nominal=10000 created_at=2026-10-10 15:25

Periode CLOSED [2026-10-08 16:00 -> 2026-10-10 16:04]  key=2026-10-08
                                A-1                  B   COCOK
  laba servis               775,000            775,000      YA
  tambahan                   10,000             10,000      YA
  beban                     605,000            605,000      YA
  laba kotor                785,000            785,000      YA
  LABA BERSIH               180,000            180,000      YA
```

---

## 6. Proteksi data

- Backup pra-perubahan: **`D:\PRAKTEK MJPRO\backup-preFINMIRROR-20261010-163836.db`**
- Migrasi hanya `ADD COLUMN`; tidak menghapus/mengubah baris `expenses`,
  `expense_periods`, `service_orders`, `payments`, atau `distributions`.
- `expense_periods` setelah perubahan tetap **6 baris untuk periode 2026-10-08**
  — identik dengan sebelum.
- Snapshot periode `CLOSED` tidak tersentuh.

**Insiden yang perlu dilaporkan:** saat verifikasi, skrip sementara sempat
menulis ke DB produksi (2 order `FINMIRROR-*`, 1 payment, 6 baris
`expense_periods` untuk periode `2026-10-10`) karena `SessionLocal` sudah
terikat ke engine produksi sebelum `database.engine` di-reassign. DB produksi
**sudah dipulihkan penuh dari backup** dan diverifikasi identik dengan kondisi
awal (5 order, 6 expense_periods, 1 distribution, 17 kas_entries). Skrip
bertsalah tersebut sudah dihapus.

---

## 7. Risiko & gap yang tersisa

### Risiko

1. **⚠️ Periode CLOSED `2026-10-08` kini menghitung ulang jadi 180.000, bukan
   170.000.** Ada satu entri kas manual +10.000 (`id=16`, dibuat 2026-10-10
   15:25) yang jatuh di dalam jendela periode itu. Sebelum FIN-MIRROR-4 entri
   itu tidak berpengaruh; sesudahnya `laba_bersih` = 775.000 + 10.000 − 605.000
   = **180.000**.

   Yang **tidak** berubah: `Distribution` periode `2026-10-08` tetap
   170.000 (17.000/51.000/51.000/51.000) dan `KasPeriod.snapshot` periode 1
   tetap mencatat 170.000 — angka historis tersimpan utuh.

   Yang berubah: bila Anda memanggil ulang `compute_finance_core` untuk periode
   closed tersebut, hasilnya 180.000 dan tidak lagi cocok dengan snapshot.
   Ini perbedaan semantik, bukan kehilangan data: A sendiri tidak punya
   konsep "hitung ulang periode lalu" karena tabelnya di-`DELETE` setiap tutup
   buku. **Silakan putuskan sendiri** apakah periode closed perlu dibekukan
   penuh (snapshot jadi satu-satunya sumber angka historical).

2. **M2: pengakuan laba bisa lebih besar dari uang yang benar-benar masuk.**
   Order CASH dengan DP saja kini ikut dihitung Omzet. Konsekuensi langsung
   dari keputusan "mirror A: CASH saja". Koreksinya ada di satu tempat:
   `statusflow.order_profit` + `finance.settled_orders`.

3. **M4 menambah satu sumber laba lagi.** Setiap kas manual bertanda `MANUAL`
   sekarang menambah `laba_bersih` **dan** memicu bagi hasil 10/30/30/30 —
   termasuk uang yang bukan hasil penjualan unit (mis. settlers bukan dari
   penjualan). Ini perilaku A-1 secara literal.

4. **Beban jadi dipotong setiap hari.** Kalau katalog beban 605.000 ternyata
   dimaksudkan "per bulan", setiap siklus harian sekarang hampir selalu merugi
   dan distribusi tidak terjadi. Perlu konfirmasi apakah A memperlakukan
   605.000 sebagai biaya bulanan dibagi, atau tetap per siklus. **A
   memperlakukannya per siklus; mirroring mengikuti A.**

5. **Baris `expenses` yang sudah ada sekarang jadi permanen** (default `True`).
   Kalau ada beban yang sebenarnya sekali bayar (mis. servis AC sekali
   seumur), harus di-`PUT` dengan `{"recurring": false}`.

### Gap (tidak diselesaikan, dicatat eksplisit)

1. **Gate LUNAS pada arsip garansi** — lihat §3.3. Butuh keputusan owner.
2. **`INSERT OR REPLACE` pada `beban` A tidak dimirror.** A memakai
   `nama_beban UNIQUE`, jadi menambah beban dengan nama sama **menimpa**
   entri lama (dan mengubah `id`-nya). B mengizinkan duplikat nama. Menambah
   `UNIQUE` berisiko gagal pada data yang sudah ada, jadi tidak dilakukan
   tanpa persetujuan.
3. **Tidak ada ledger double-entry di kedua sistem.** Keduanya single-entry.
   Mirror ini tidak memperbaikinya — di luar cakupan "menyalin aturan A".
4. **Tidak ada tabel persistensi bagi hasil di A.** A menghitung 10/30/30/30
   di memory tiap render lalu membuangnya; B menyimpannya ke `distributions`.
   B lebih baik dan dipertahankan.
5. **`transaksi_tambahan` (A) = entry kas manual B** — SUDAH di-clone sebagai
   FIN-MIRROR-4 (§3.0), bukan lagi gap.
6. **`pembayaran` A** = tabel 0 baris, tanpa transisi status, tidak dibaca
   siapa pun. Tidak ada Financial Logic therein untuk disalin.
7. **`ritual_tutup_buku` A** (`engine/operasional.py:13-30`) adalah dead code —
   diimpor tapi tidak pernah dipanggil, dan tidak menyimpan apa pun. Tidak ada
   aturan financial yang bisa disalin dari sana.
8. **Scheduler 16:00 tidak ada di A.** Tutup buku di A dipicu manual lewat
   tombol dashboard; tidak ada loop/cron. B sudah punya periode 16:00 sendiri.