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

## OD-LOCK-06 — Pembayaran Beban, Kas Aset, dan Hutang Beban

**Status: LOCKED**

Ketika Beban Gaji dan Operasional harus dibayar:

1. Bayarkan menggunakan **saldo Laci yang tersedia**.
2. Jika Laci tidak mencukupi, **keputusan untuk menutup dari Kas Aset diambil
   MANUAL oleh user** — sistem tidak menutupinya sendiri.
3. **Sisa yang belum tertutup dicatat sebagai Hutang Beban**, lengkap dengan
   rincian dan **periode asalnya**, sambil menampilkan berapa yang *bisa*
   ditutup manual.
4. Penutupan Kas Aset dicatat sendiri oleh user melalui
   `POST /api/kas/aset/keluar`.
5. Hutang Beban **terakumulasi** dan tidak boleh hilang otomatis ketika periode
   berganti.

> ⚠️ **Poin 2 dan 3 pernah tertulis "otomatis" dan telah DIREVISI oleh Owner.**
> Naskah pertama menyatakan sistem otomatis memakai Kas Aset dan benar-benar
> mengurangi saldonya. Owner memutuskan sebaliknya: yang manual adalah
> **keputusannya**, sehingga **saldo Kas Aset tidak boleh pernah berkurang
> sebagai akibat otomatis pembayaran Beban**.

Ketentuan tambahan:

- Pembayaran dilakukan **langsung**, tidak menunggu Tutup Kas.
- **Tutup Kas tidak boleh membayar ulang** Beban yang sudah diselesaikan.
- Transaksi **atomik dan idempoten**; saldo tidak boleh terpotong dua kali.
- Setiap pembayaran memiliki **jejak audit dan referensi periode**.
- ❌ Jangan membuat saldo Laci negatif hanya untuk memaksakan pembayaran.
- ❌ Jangan mengurangi saldo Kas Aset secara otomatis.
- ❌ Jangan menganggap Hutang Beban sebagai uang yang sudah dibayar.
- ✅ **Beban tetap dibekukan SEKALI per periode kas** (FR-01 / OD-001). Poin ini
  tidak melonggarkan aturan beku; yang dijamin adalah kewajiban yang sudah
  tercatat tidak hilang dari sisi pembayaran.
- ✅ **OD-LOCK-05 tidak berubah.** Jalur ini khusus Beban Gaji & Operasional;
  refund klaim garansi tetap manual dari Kas Aset.

### Contoh pengujian (wajib jadi test)

Penjualan Rp600.000 · Modal Rp325.000 · Sisa Laci Rp275.000 · Beban Rp605.000
· Kekurangan Rp330.000.

Kas Aset **tidak boleh bergerak** berapa pun jumlahnya — keputusan menutup
manual. Hutang Beban tetap Rp330.000 dan menunggu tindakan user.

| Skenario | Laci bayar | Kas Aset berubah | Sisa Kas Aset | Hutang Beban |
|---|---|---|---|---|
| **A** — Kas Aset Rp500.000 | 275.000 | ❌ tidak | 500.000 | **Rp330.000** |
| **B** — Kas Aset Rp200.000 | 275.000 | ❌ tidak | 200.000 | **Rp330.000** |
| **C** — Kas Aset Rp0 | 275.000 | ❌ tidak | Rp0 | **Rp330.000** |

---

## OD-LOCK-08 — Kelola Akun: Nonaktifkan, Bukan Hapus

**Status: LOCKED**

Owner: *"Nonaktifkan, bukan hapus."* Kelola Akun **tidak boleh** punya aksi
hapus permanen.

Aturan Operasional:

1. **Nonaktifkan adalah satu-satunya cara** mencabut akses. Datanya tetap dan
   bisa diaktifkan lagi.
2. **Teknisi nonaktif tidak bisa login** dan **tidak bisa menerima penugasan
   baru**.
3. **Histori servis, garansi, laporan kinerja, dan audit transaksi lama tidak
   boleh ikut terhapus** — tidak ada aksi yang menyentuh data historis.
4. **Koreksi data teknisi harus tercatat.** Perubahan nama, role, status, atau
   passcode masuk journal sebagai `AKUN_DIBUAT` / `AKUN_DIUBAH`, lengkap dengan
   nilai **sebelum** dan **sesudah** beserta pelaku (`actor`).
5. **Penghapusan permanen hanya boleh dipertimbangkan** bila tidak melanggar
   audit, retensi data, dan aturan yang berlaku. Selama belum ada keputusan
   Owner bahwa suatu kelas data boleh dihapus, **aksinya tidak ada sama sekali**
   di backend maupun frontend.

### Catatan penting soal role

`SUPERADMIN` adalah **alias** dari `ADMIN` (`authority.ROLE_ALIASES`). Di DB
tidak ada akun ber-role literal `SUPERADMIN`, jadi penjaga tidak boleh memakai
string polos — kalau begitu **tidak ada yang bisa managing akun sama sekali**.

### Contoh pengujian (wajib jadi test)

```
Nonaktifkan -> akun tidak bisa login, unit lama tetap utuh, bisa diaktifkan lagi
Teknisi nonaktif -> tidak muncul di /api/orders/technicians,
                    penugasan baru ditolak 400, unit lama tidak ikut berubah
Koreksi akun    -> AKUN_DIUBAH tercatat di journal, actor + nilai sebelum/sesudah
Hapus akun      -> tidak ada DELETE /api/auth/users/{id}, tidak ada tombol hapus
```

## OD-LOCK-09 - Role Pengelola dan Investor Read-Only

**Status: LOCKED**

Owner: *"Role pengelola hanya bisa melihat keseluruhan program = tidak ada
wewenang untuk mengubah apapun."*

- **PENGELOLA** (dan alias `PEMILIK`) **tidak boleh mengubah apa pun** - bukan
  hanya di halaman kas, tapi di seluruh aplikasi.
- **INVESTOR** sama: boleh melihat angka, tidak boleh menulis.
- Satu-satunya jalan untuk mencabut akses adalah **Nonaktifkan** (OD-LOCK-08).
- Lihat OD-LOCK-10 untuk pembagian peran monitoring yang lebih rinci
  (`REPORT_FULL` dan `REPORT_INVESTOR` adalah hak BACA, bukan tulis).

### Aturan ini ditegakkan di dua lapis

1. **Matriks `AUTHORITY_MATRIX`** - role read-oriented hanya boleh muncul di
   aksi baca laporan.
2. **Blanket di `authority.can()`** - role read-oriented (`MONITORING_ROLES`)
   ditolak **sebelum** matriks dibaca, kecuali untuk `MONITORING_READ_ACTIONS`.

Lapis kedua bukan sekadar formalitas: ia yang membuat Admin salah tulis satu
baris matriks tidak langsung membuka seluruh program untuk role read-only.
Tanpa lapisan itu, PENGELOLA aman hanya karena kebetulan tidak tercatat di
matriks - bukan karena ada penjaganya.

### Kebocoran yang ditemukan dan ditutup

`backend/routers/customers.py` **tidak punya penjaga role sama sekali** - nol
`require_authority`, nol `require_admin`. Terbukti lewat HTTP: **PENGELOLA,
INVESTOR, KASIR, dan TEKNISI** semuanya bisa menambah, mengubah, bahkan
**MENGHAPUS data pelanggan**.

Pembagian yang ditetapkan:

| Aksi | Boleh |
|---|---|
| Melihat daftar / detail pelanggan | semua yang sudah login |
| Tambah / Ubah pelanggan | Admin, Kasir |
| Hapus pelanggan | Admin |

KASIR tetap boleh menambah dan mengubah pelanggan - itu bagian pekerjaannya.
Hanya **hapus** yang dikhususkan ke Admin.

---


## OD-LOCK-10 - Struktur 7 Role BOSS SF

**Status: LOCKED**

Struktur role resmi. Tujuh role, tidak boleh ada duplikat.

| # | Role | Peran | Boleh | Dilarang |
|---|---|---|---|---|
| 1 | **SUPER ADMIN** | Akun Developer | Kelola akun, role, permission, konfigurasi, audit log. Akses administratif seluruh sistem. | - |
| 2 | **ADMIN** | Manager Toko | Operasional, supervise tim, Tutup Kas, catat beban, Kelola Akun. | Konfigurasi teknis / permission Super Admin |
| 3 | **PENGELOLA** | Pemilik | Monitoring: dashboard, laporan keuangan (omzet, modal part/jasa, laba kotor, beban, laba bersih, CTS), laporan operasional & kinerja teknisi, riwayat Tutup Kas, Kas Aset, Hutang Beban, bagi hasil 30%. Filter & unduh laporan. | Semua operasi tulis. Tutup Kas. Konfigurasi. |
| 4 | **INVESTOR** | Monitoring Investasi | Monitoring: omzet, laba, tren, laporan periode, dasar bagi hasil 30% + riwayat pembayarannya, ringkasan Kas Aset & Hutang Beban. Filter & unduh. | Semua operasi tulis. Data pribadi pelanggan. |
| 5 | **KASIR / CS** | Admisi & penagihan | Terima unit, ubah harga/estimasi, pembayaran & pelunasan, nota, ambil unit, refund DP, tambah/ubah pelanggan. | Modal, rumus laba, bagi hasil, catat beban, konfigurasi keuangan, hapus transaksi, Tutup Kas. |
| 6 | **TEKNISI** | Perbaikan unit | Daftar kerja yang ditugaskan, info perangkat & keluhan, progres, diagnosis, tindakan perbaikan, catatan teknis, serah-terima. | Pembayaran, modal, laba, bagi hasil, Tutup Kas, data keuangan sensitif. |
| 7 | **ADMIN SPAREPART** | Kelola barang | Data barang, stok, pencatatan keluar-masuk, permintaan sparepart, riwayat pergerakan, laporan persediaan, melihat kebutuhan sparepart untuk servis. | Transaksi servis, pembayaran pelanggan, laba, bagi hasil, Tutup Kas, modal. |

### 10.1 SUPER ADMIN dipisahkan dari ADMIN

Sebelumnya `SUPERADMIN` adalah **alias** `ADMIN`, jadi keduanya identik dan
"jangan berikan role ini otomatis kepada Admin toko" mustahil ditegakkan.
Kini `ROLE_SUPERADMIN != ROLE_ADMIN`, dan `ROLE_CONFIG` (ubah role, permission,
konfigurasi, audit log) hanya dimiliki SUPER ADMIN.

### 10.2 Akses monitoring dibedakan

Owner memberi keduanya hak **baca laporan**, jadi ada `REPORT_FULL`
(Pengelola: laporan detail) dan `REPORT_INVESTOR` (Investor: laporan investasi
dan dasar bagi hasil). Keduanya tetap **nol operasi tulis** - dibuktikan oleh
blanket `can()` yang menolak role read-oriented sebelum membaca matriks.

### 10.3 Modal dipisah dari harga

Untuk menegakkan "Kasir boleh ubah harga, tidak boleh ubah modal",
`FINANCE_FIELDS` dipecah jadi `MODAL_FIELDS` (part_cost, modal_jasa,
modal_lainnya, tanpa_modal) dan sisanya. `MODAL_FIELDS` dijaga
`ORDER_UPDATE_MODAL` yang hanya milik ADMIN + SUPER ADMIN.

### 10.4 Fail-CLOSED di tampilan

- `bssfCaps()` tidak boleh fallback ke admin -> `custom`
- `canViewAset()` fallback `custom`, bukan `admin`
- `showAkun()` menolak apa pun yang bukan `true` (termasuk `undefined`)
- `navigateTo()` memanggil penjaga halaman; menu yang disembunyikan saja tidak
  cukup karena halaman bisa dibuka lewat hash URL

Menyembunyikan tombol **BUKAN** proteksi keamanan. Proteksi ada di backend;
lapisan tampilan hanya agar tidak menyesatkan.

### 10.5 Kasus yang perlu keputusan Owner

Belum dikerjakan karena tidak boleh ditebak:

1. **Akun `superadmin` di DB punya role `ADMIN`.** Setelah SUPER ADMIN
   dipisah, akun itu jadi Manager Toko dan tidak punya `ROLE_CONFIG`. Data
   tidak diubah (Owner: jangan ubah akun yang ada). Perlu keputusan apakah
   akun itu dinaikkan ke SUPER ADMIN, atau dibuat akun baru.
2. **Teknisi boleh `ORDER_CREATE`?** Spec hanya menyebut "melihat daftar
   pekerjaan yang ditugaskan". Secara bawaan lama Teknisi bisa menerima unit;
   itu dipertahankan karena bisa dipakai alur nyata.
3. **Teknisi/Admin boleh `CLAIM_WRITE` (garansi)?** Spec tidak menyebut garansi
   untuk Teknisi. Pertahankan status quo (hanya Admin).
4. **Investor tidak boleh melihat Kas Aset penuh** (`_boleh_lihat_aset` =
   Super Admin, Admin, Pengelola), tapi spec minta "ringkasan Kas Aset". Endpoint
   ringkasan untuk Investor belum dibuat.
5. **Unduh laporan** untuk Pengelola/Investor belum ada endpoint khusus.

### Contoh pengujian (wajib jadi test)

```
Super Admin        -> punya semua aksi, termasuk ROLE_CONFIG
Admin              -> boleh KAS_CLOSE, TIDAK boleh ROLE_CONFIG
Kasir              -> boleh harga, TIDAK boleh modal/beban/Tutup Kas
Teknisi            -> TIDAK boleh satu pun aksi uang
Admin Sparepart    -> hanya SPAREPART_WRITE
Pengelola/Investor -> nol operasi tulis, hanya REPORT_*
PENGELOLA dipaksa masuk matriks KAS_CLOSE -> can() tetap menolak
```

---


## OD-LOCK-07 — Identitas Periode Kas & Dasar Hutang Beban

**Status: LOCKED**

Aturan ini datang dari satu keputusan Owner dan berlaku sebagai satu kesatuan.

### 7.1 Periode kas diidentifikasi per periode, bukan per tanggal

Owner: *"pakai periode, karena selama pengujian dalam satu hari bisa berkali-kali
tutup kas."*

- Kunci periode kas memakai **`kas_periods.id`**, bukan tanggal.
- ❌ Kunci berbasis tanggal **dilarang**, karena Tutup Kas bisa diulang beberapa
  kali dalam satu hari sehingga menghasilkan kunci yang bentrok.
- Dampak kunci yang bentrok: `ref_id` penanda idempotensi Beban dipakai bersama,
  sehingga periode kedua terlihat "sudah membayar" dan **Beban-nya tidak pernah
  keluar dari Laci**.
- Data beku versi lama (kunci tanggal) **tetap boleh dibaca** supaya periode
  tertutup tidak dibekukan dua kali.

### 7.2 Hutang Beban dihitung dari Laba Kotor

Owner: *"dalam setiap periode jika Laba Kotor tidak dapat menutup Beban maka
akan menjadi Hutang Beban"* dan *"kalau Laba Kotor cukup untuk menutup beban,
sama dengan Target CTO tercapai."*

```
Hutang Beban periode = max(0, Total Beban - Laba Kotor)
```

- **Laba Kotor ≥ Beban** → target CTO tercapai → **tidak ada** Hutang Beban.
- **Laba Kotor < Beban** → selisihnya menjadi Hutang Beban.
- Penentu hutang adalah **Laba Kotor**, bukan "berapa yang tidak kebayar dari
  Laci". Kalau Laci fisik tidak cukup padahal Laba Kotor menutup Beban, sisanya
  **bukan** Hutang Beban; shortfall-nya dilaporkan lewat `kekurangan` dan
  `bisa_ditutup_manual` untuk diputuskan manual oleh user.
- Pembayaran dari Laci tetap mengikuti OD-LOCK-06 (seadanya, tidak pernah
  negatif).
- Hutang yang sudah tercatat **dibiarkan**; kalau periode berikutnya masih
  minus, hutang **terus nambah** — tidak direset, tidak saling menggantikan.

### 7.3 Yang boleh menyeber antar periode

Owner: *"Payment masuk, Modal keluar, Beban keluar dll hanya dihitung per
periode. Jika ganti periode, data itu dianggap sampah jangan baca lagi."*

Hanya **tiga hal** ini yang boleh relating ke periode berikutnya:

| Boleh menyeber | Keterangan |
|---|---|
| 💰 Uang DP selama belum lunas | Titipan customer, bukan Omzet |
| 📋 Beban Hutang | Terakumulasi sampai ditutup manual oleh user |
| 🏦 Kas Aset | Saldo Kas Aset Besar / Pengelola |

Seluruh mutasi Kas lainnya (**Payment masuk, Modal keluar, Beban keluar**)
hanya dibaca untuk **periode miliknya sendiri**.

### Contoh pengujian (wajib jadi test)

Periode dengan Laba Kotor Rp275.000 dan Beban Rp605.000:

```
Hutang Beban = 605.000 - 275.000 = Rp330.000
```

Dua periode berturutan tanpa penjualan: `500.000 + 500.000 = Rp1.000.000` hutang.

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

## ✅ KETIDAKS-SUAIAN-03 — Beban DIBAYAR DUA KALI (OD-LOCK-06)

| | |
|---|---|
| **Aturan** | Beban dibayar sekali: Laci → Kas Aset → Hutang Beban |
| **Temuan (sebelum)** | **Dua jalur pembayaran dengan penanda idempotensi BERBEDA.** `backend/routers/expenses.py` memanggil `cash.catat_began` per-baris (`ref_type='expense'`), sedangkan `closing.selesaikan_periode` membayar seluruh Total Beban periode (`ref_type='beban_periode'`). Terbukti dijalankan: Beban Rp300.000 mengurangi Saldo Laci **Rp600.000**.Selain itu `closing.catat_began` memakai `check_saldo=False`, sehingga Laci bisa menjadi **negatif**. |
| **Perbaikan** | `backend/beban_bayar.py` (baru) — satu mesin pembayaran tunggal `bayar_beban_periode()`, idempoten lewat `ref_type='beban_periode'` + `ref_id=<periode>`. Dipanggil dari `finance.beban_frozen` saat periode dibekukan, dan dari `closing.selesaikan_periode` untuk membayar **sisa saja**. Panggilan per-baris di `routers/expenses.py` dihapus. |
| **Kas Aset** | **Otomatis DIHAPUS atas perintah Owner** (revisi OD-LOCK-06 poin 2–3). Naskah pertama sempat mewajibkan `cash.transfer(KAS_ASET → LACI)` saat menutup kekurangan; Owner menetapkan bahwa keputusan menutup dari Kas Aset itu **manual oleh user**. Sekarang sistem hanya melaporkan `bisa_ditutup_manual` dan `cara_cover`; uang Kas Aset berpindah lewat `POST /api/kas/aset/keluar`. |
| **Hutang Beban** | Dicatat sebagai baris `expense_debt_periods` lengkap dengan periode asal, nilai beban, cover Kas Aset, dan sisa kewajiban. Pembayaran lanjutan **memperbarui** baris yang sama (`periode` UNIQUE), bukan menambah baris baru. |
| **Yang sengaja TIDAK diubah** | Beban tetap beku sekali per periode (FR-01). Distribusi (OD-LOCK-02), Modal saat CASH (OD-LOCK-01), dan refund garansi manual (OD-LOCK-05) tidak tersentuh. |
| **Pengaman** | `tests/test_od_lock_06_beban.py` — 11 test, termasuk ketiga skenario tabel di atas (Kas Aset tidak boleh tersentuh otomatis), request berulang, dan akumulasi hutang. |

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
| OD-LOCK-06 | `backend/beban_bayar.py` — satu mesin `bayar_beban_periode()` (Laci → Kas Aset → Hutang Beban), dipicu dari `finance.beban_frozen` dan `closing.selesaikan_periode` |
| OD-LOCK-07.1 | `finance.period_key(db, start, end)` — kunci dari `kas_periods.id`, bukan tanggal; `legacy_period_key()` hanya untuk membaca data beku lama |
| OD-LOCK-07.2 | `beban_bayar.bayar_beban_periode(..., laba_kotor=...)` — hutang = `max(0, Beban - Laba Kotor)` |
| OD-LOCK-07.3 | `cash.saldo_titipan_dp` (DP), `expense_debt.saldo_hutang` (Hutang Beban), `cash.saldo_kas_aset` (Kas Aset) |

| OD-LOCK-08 | `routers/auth.py` - tidak ada endpoint hapus; `create_user`/`update_user` menulis journal `AKUN_DIBUAT`/`AKUN_DIUBAH` |
| OD-LOCK-08 | `routers/orders.py::_pastikan_teknisi_aktif` - penugasan baru ke teknisi nonaktif ditolak |
| OD-LOCK-09 | `authority.MONITORING_ROLES` + blanket di `authority.can()` - role monitoring ditolak sebelum matriks dibaca, kecuali `MONITORING_READ_ACTIONS` |
| OD-LOCK-09 | `routers/customers.py` - create/update butuh `CUSTOMER_WRITE` (Admin, Kasir), delete butuh `CUSTOMER_DELETE` (Admin) |
| OD-LOCK-10 | `authority.ROLE_SUPERADMIN` terpisah dari `ROLE_ADMIN`; `ROLE_CONFIG` hanya Super Admin |
| OD-LOCK-10 | `authority.MODAL_FIELDS` + `Action.ORDER_UPDATE_MODAL` - Kasir boleh harga, tidak boleh modal |
| OD-LOCK-10 | `frontend/script.js` - `BSSF_CAPS` 7 role, `PAGE_CAP` penjaga halaman, `bssfCaps()`/`canViewAset()`/`showAkun()` fail-closed |
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
