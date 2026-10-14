# OWNER DECISIONS / BUSINESS RULES — BOSS SF

**STATUS: 🔒 LOCKED — WAJIB DIPATUHI**

Dokumen ini adalah **sumber kebenaran bisnis** BOSS SF. Semua audit,
pengembangan, validasi, pengujian, dan perubahan kode berikutnya WAJIB
mengacu ke sini.

> **Instruksi final: keputusan Owner adalah sumber kebenaran bisnis.
> Implementasi wajib mengikuti keputusan yang terkunci, bukan sebaliknya.**

Keputusan ini **tidak boleh** ditafsirkan ulang, diubah, atau diganti
berdasarkan asumsi teknis. Pelanggaran aturan terkunci hanya boleh dilepas
dengan **keputusan eksplisit Owner**.

---

## Hubungan dengan FR-01 & FR-02

| Item | Status |
|---|---|
| **FR-01** (Financial Rule) | ✅ **DIPERTAHANKAN** — tetap acuan keuangan utama |
| **FR-02** (Financial Rule) | ✅ **DIPERTAHANKAN** — tetap acuan keuangan utama |

FR-01 dan FR-02 yang sudah dikunci **tetap berlaku**. Keputusan OD-LOCK
berikut **memperjelas perilaku operasional** dan tidak otomatis mengganti,
menggantikan, atau melemahkan aturan FR yang sudah berlaku.

Rinciannya dituliskan di bawah, disusun dari aturan yang **sudah terkunci di
dalam repo** sehingga dapat diaudit:

| Aturan | Sumber acuan di repo |
|---|---|
| FR-01 | `backend/finance.py:3-42`, `backend/statusflow.py:197-236`, `README.md:299-361` |
| FR-02 | `backend/closing.py:2-17` & `:186-201`, `README.md:345` |

---

## FR-01 — Payment Ledger & Financial Core (LOCKED)

**Status: LOCKED — tetap berlaku penuh**

### Rumus resmi

```text
OMZET       = penjualan unit CASH + LUNAS pada periode kas berjalan
              (DP BUKAN Omzet)
MODAL       = Modal Part + Modal Jasa + Modal Lain-lain (3 komponen terpisah)
LABA KOTOR  = OMZET - TOTAL MODAL
BEBAN       = Gaji + Operasional (kategori lain bukan Beban)
LABA BERSIH = LABA KOTOR - TOTAL BEBAN
```

### Aturan wajib

1. **Financial Core adalah satu-satunya sumber hitungan.** `backend/finance.py`
   adalah **satu-satunya** tempat Laba Kotor dan Laba Bersih dihitung.
   Modul lain **wajib membaca**, tidak boleh menghitung ulang.
2. **Omzet hanya dari CASH + LUNAS.** Unit yang sudah LUNAS tapi belum CASH
   belum merealisasikan Omzet. Transaksi kas manual **tidak** masuk Omzet,
   Modal, Beban, maupun laba.
3. **Tiga modal tetap terpisah.** Tidak digabung, tidak boleh dihitung dua kali.
4. **Beban hanya Gaji + Operasional.** Kategori lain tidak masuk Beban.
5. **Beban dibebankan SEKALI per periode kas** lewat snapshot beku
   `expense_periods` (idempoten). Menambah atau mengubah `expenses` setelah
   periode dibekukan **tidak** mengubah beban periode itu.
6. **Payment Ledger bersifat append-only.** Tabel `payments` tidak memiliki
   jalur PUT/DELETE baris. Kolom `service_orders.payment` (DP legacy) adalah
   **read-only arsip**; sumber pemasukan servis yang sah adalah `payments`.
7. **DP tidak pernah jadi Omzet maupun Laba**, di mana pun.
8. **Nilai uang selalu Decimal.** Tanpa jalur float sama sekali.

---

## FR-02 — Mekanisme Tutup Kas (LOCKED)

**Status: LOCKED — tetap berlaku penuh**

### Urutan resmi

1. Periode tetap **16:00 → 16:00**.
2. **Laba Bersih** diambil otoritatif dari Financial Core (FR-01).
3. **Distribusi** terbentuk saat Tutup Kas, **idempotent per periode**.
4. **Cash-out 70%** dieksekusi dari Laci sebagai **satu** entri kas (bukan dobel).
5. **Laci disetel ke uang fisik** bila Admin Declare hitungan fisik —
   lewat **penyesuaian entri eksplisit**, **TIDAK** menyuntik saldo awal.
6. **Kas Aset tidak pernah di-reset.**
7. **Satu transaksi.** Tidak ada `commit` di dalam modul; pemanggil yang
   commit/rollback → kegagalan di tengah tidak meninggalkan data setengah jadi.

### Aturan wajib

- **Periode tertutup bersifat FINAL.** Tidak diubah, tidak dibahas lagi.
- **Tutup Kas tidak menghapus apa pun** (Q14). Periode tertutup tetap
  tersimpan dan dibaca lewat filter presentasi / arsip.
- **Tutup Kas tidak mengubah status apa pun** — hanya menutup periode +
  menyimpan snapshot.
- **Hanya tiga hal yang boleh menyeber periode:**
  **UANG DP**, **KAS ASET**, dan **HUTANG BEBAN**.
- **Declisit** (Laba Bersih negatif) ditutup **Kas Aset** sejauh mampu,
  sisanya menjadi **Hutang Beban** (carry forward). Kas Perputaran tidak
  pernah disentuh; hutang tidak pernah menjadi Omzet maupun Laba.
- **Tidak memaksa distribusi** dan **tidak memakai DP titipan** saat defisit.

---

## OD-LOCK-01 — Pengeluaran Modal Part dan Modal Jasa

**Status: LOCKED**

Modal Part dan Modal Jasa **langsung dikeluarkan dari Laci ketika transaksi
menjadi CASH**.

Pengeluaran modal ini merupakan **perilaku bisnis yang disengaja, bukan bug**.

- ❌ Jangan memindahkan pengeluaran tersebut ke proses Tutup Kas.
- ✅ Tutup Kas tetap menjalankan kewajibannya sesuai Financial Rule Book,
  **tanpa menghitung atau mengeluarkan modal yang sama untuk kedua kalinya**.

---

## OD-LOCK-02 — Distribusi Bagi Hasil

**Status: LOCKED**

Distribusi bagi hasil **langsung dieksekusi ketika seluruh syarat distribusi
terpenuhi**, tidak harus menunggu Tutup Kas.

| Porsi | Persentase | Aliran dana |
|-------|------------|--------------|
| Bonus Karyawan | 10% | Keluar dari Laci |
| Pengelola | 30% | Keluar dari Laci |
| Investor | 30% | Keluar dari Laci |
| Kas Aset | 30% | Dipindahkan dari Laci ke Kas Aset |

- Porsi **70%** langsung dikeluarkan dari Laci.
- Porsi **30%** dipindahkan dari Laci ke Kas Aset.

Perilaku ini sama prinsipnya dengan pemotongan modal pada OD-LOCK-01:
**transaksi keuangan dieksekusi ketika kondisi yang ditetapkan terpenuhi.**

- ❌ Tutup Kas **tidak boleh** mengeksekusi ulang pengeluaran atau perpindahan
  dana yang sudah tercatat.
- ✅ Mekanisme distribusi periode yang sama dan top-up tetap mengikuti aturan
  yang sudah ditetapkan.

---

## OD-LOCK-03 — Status CASH Bersifat Final

**Status: LOCKED**

Transaksi dengan status **CASH tidak boleh diubah kembali ke status lain**,
termasuk **CANCEL**, melalui mekanisme perubahan status biasa.

CASH merupakan **status final** untuk alur servis tersebut.

- ❌ Jangan mengaktifkan kembali transisi `CASH → CANCEL`, meskipun disertai
  catatan koreksi.
- Aturan ini **tidak boleh dilanggar** hanya karena mesin transisi status
  secara teknis memungkinkan perubahan tersebut.

---

## OD-LOCK-04 — Validasi Logika Estimasi dan DP

**Status: LOCKED**

Sebelum data servis disimpan, sistem **wajib memvalidasi konsistensi nilai
estimasi biaya dan DP**.

> **DP tidak boleh lebih besar daripada estimasi biaya transaksi.**

Contoh penolakan:

```text
Estimasi biaya : Rp200.000
DP             : Rp250.000
Hasil          : DITOLAK
```

- ✅ Sistem harus **menampilkan pesan validasi yang jelas** dan meminta pengguna
  memperbaiki data **sebelum penyimpanan**.
- ❌ Jangan membiarkan data yang tidak logis tersimpan lalu mengatasinya dengan
  **mempertahankan kelebihan DP sebagai saldo titipan**.

**Lokasi validasi:**

- **Backend** sebagai pengaman utama.
- **UI** untuk memberikan umpan balik kepada pengguna.
- Berlaku **sebelum data disimpan** pada **semua** proses yang menerima atau
  memperbarui nilai estimasi dan DP.
- ❌ Jangan hanya memeriksa pada satu halaman jika ada jalur input lain.

---

## OD-LOCK-05 — Refund Klaim Garansi Dilakukan Manual

**Status: LOCKED**

Klaim garansi yang berujung pada refund ditangani **secara manual oleh pihak
yang berwenang**.

- Pengeluaran refund berasal dari **Kas Aset Besar** sesuai ketentuan bisnis
  yang berlaku.
- ❌ Proses ini **tidak boleh otomatis** mengurangi saldo Kas Aset melalui
  mekanisme klaim garansi.
- ❌ Jangan mengubah proses manual ini menjadi pengurangan saldo otomatis.
- ✅ Catatan transaksi dan riwayat klaim **tetap harus dapat ditelusuri**
  agar tindakan manual bisa diaudit.
- **Pencatatan riwayat tidak boleh disamakan dengan eksekusi pengurangan
  saldo otomatis.**

---

# Ketidaksesuaian Implementasi

> Dicatat sesuai instruksi: **jangan mengubah keputusan bisnis untuk
> menyesuaikan kode.** Yang harus berubah adalah kodenya, mengikuti aturan.

## ✅ KETIDAKS-SUAIAN-01 — OD-LOCK-03 SUDAH DITEGAKKAN

| | |
|---|---|
| **Aturan** | Status CASH final, tidak boleh kembali menjadi status lain |
| **Temuan (sebelum)** | `check_transition` mengembalikan `True` untuk status terminal bila disertai `catatan`, sehingga `CASH` -> `CANCEL` dimungkinkan. |
| **Perbaikan** | `backend/statusflow.py` — `check_transition` menolak **sebarang** perubahan dari `CASH` ke status lain, **walaupun disertai catatan koreksi**. Pesan penolakan mengarah ke alur refund, bukan perubahan status. |
| **Yang sengaja TIDAK diubah** | `FAILED` -> `CANCEL` dengan catatan tetap boleh (dipakai alur "unit diambil pelanggan"). OD-LOCK-03 hanya mengunci CASH. |
| **Pengaman** | `tests/test_od_lock.py` — 6 test, termasuk uji end-to-end lewat HTTP. |

## ✅ KETIDAKS-SUAIAN-02 — OD-LOCK-04 SUDAH DITEGAKKAN

| | |
|---|---|
| **Aturan** | DP tidak boleh melebihi estimasi; validasi backend + UI |
| **Temuan (sebelum)** | Hanya ada validasi `dp < 0`. Tidak ada batas atas DP terhadap estimasi. Kelebihan DP justru ditahan sebagai saldo titipan. |
| **Perbaikan** | `statusflow.cek_dp_vs_estimasi()` sebagai **helper tunggal**, dipasang di **semua** jalur input: `POST /api/orders/receive`, `POST /api/orders`, `PUT /api/orders/{id}` (kenaikan DP), dan `POST /api/payments` (termasuk akumulasi DP bertahap). Validasi UI ditambahkan di form Terima dan form Update Data Servis. |
| **Catatan** | Estimasi yang dibandingkan adalah nilai `order.estimate`. Bila estimasi belum diisi, validasi dilewati karena jalur "Titip Unit" memang tidak mewajibkan estimasi. |
| **Data lama** | Aturan ini berlaku saat **menyimpan**. Data historis yang sudah kelebihan DP **tidak** ikut diubah; jaring pengaman `dp_terpakai` (hanya sebesar kewajiban) tetap dipertahankan untuk data tersebut. |
| **Pengaman** | `tests/test_od_lock.py` — 11 test. |

---

## Status Implementasi

Seluruh keputusan Owner sudah sejalan dengan kode.

| Keputusan | Letak implementasi |
|---|---|
| OD-LOCK-01 | `backend/routers/orders.py` — `cash.catat_modal` saat CASH; `backend/closing.py` hanya mencatat *selisih* modal yang terlewat, bukan mengulang modal yang sudah tercatat |
| OD-LOCK-02 | `backend/routers/orders.py` — `pastikan_otomatis` saat CASH; idempoten per `kas_period_id` (`distribution.py`) sehingga Tutup Kas tidak mengeksekusi ulang |
| OD-LOCK-03 | `backend/statusflow.py` — `check_transition` menolak perubahan dari CASH |
| OD-LOCK-04 | `backend/statusflow.py` — `cek_dp_vs_estimasi`, dipasang di 4 jalur input backend + 2 form UI |
| OD-LOCK-05 | `backend/refunds.py` — `otomatis=False` untuk refund GARANSI; saldo Kas Aset tidak dikurangi otomatis |

---

# Aturan Penggunaan Dokumen Ini

1. ✅ Dokumen ini adalah **acuan tetap** untuk audit, UAT, regresi, dan
   pengembangan berikutnya.
2. ❌ **Jangan mengubah, menghapus, atau melemahkan aturan terkunci** tanpa
   keputusan eksplisit dari Owner.
3. ✅ Jika implementasi kode bertentangan dengan keputusan ini → catat sebagai
   **ketidaksesuaian implementasi** (bagian di atas).
4. ❌ **Jangan mengubah keputusan bisnis untuk menyesuaikan kode.**
5. Setiap perubahan kode baru harus diperiksa terhadap dokumen ini sebelum
   dianggap selesai.
