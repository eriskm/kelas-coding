# BUSINESS RULES - BOSS SF

> **Sumber kanonik aturan bisnis adalah
> [`docs/OWNER_DECISIONS.md`](OWNER_DECISIONS.md).**
>
> Dokumen ini hanya merangkum dan **menautkan** ke kode yang menegakkannya.
> Kalau ada selisih antara dokumen ini dan `OWNER_DECISIONS.md`, yang
> menang adalah `OWNER_DECISIONS.md`.

Aturan di sini **tidak boleh ditulis ulang di tempat lain** — hanya ditautkan,
supaya tidak ada dua versi yang bisa berbeda.

---

## 1. Daftar aturan terkunci

| ID | Judul | Status |
|---|---|---|
| `FR-01` | Payment Ledger & Financial Core | 🔒 LOCKED |
| `FR-02` | Mekanisme Tutup Kas | 🔒 LOCKED |
| `OD-LOCK-01` | Pengeluaran Modal Part dan Modal Jasa | 🔒 |
| `OD-LOCK-02` | Distribusi Bagi Hasil | 🔒 |
| `OD-LOCK-03` | Status CASH Bersifat Final | 🔒 |
| `OD-LOCK-04` | Validasi Estimasi dan DP | 🔒 |
| `OD-LOCK-05` | Refund Klaim Garansi Dilakukan Manual | 🔒 |
| `OD-LOCK-06` | Pembayaran Beban, Kas Aset, Hutang Beban | 🔒 |
| `OD-LOCK-07` | Identitas Periode Kas & Dasar Hutang Beban | 🔒 (digantikan sebagian oleh OD-LOCK-12) |
| `OD-LOCK-08` | Kelola Akun: Nonaktifkan, Bukan Hapus | 🔒 |
| `OD-LOCK-09` | Role Pengelola dan Investor Read-Only | 🔒 |
| `OD-LOCK-10` | Struktur 7 Role BOSS SF | 🔒 |
| `OD-LOCK-11` | Aturan Dasar Uang BOSS SF | 🔒 |
| `OD-LOCK-12` | Hutang Beban: Input Manual oleh Admin | 🔒 (menggantikan OD-LOCK-07) |

Teks lengkap + status hukumnya: [`OWNER_DECISIONS.md`](OWNER_DECISIONS.md).

---

## 2. Pengakuan pendapatan

| Aturan | Ditegakkan di |
|---|---|
| Omzet = unit `CASH` **dan** `LUNAS` | `finance.settled_orders()` |
| DP **bukan** Omzet | penyajian; `PAYMENT` tidak masuk `SUMBER_BUKU_KAS` |
| Modal = Part + Jasa + Lain, terpisah | kolom terpisah + `ref_type` per komponen |
| Laba Kotor = Omzet − Total Modal | `finance.compute_finance_core()` |
| Laba Bersih = Laba Kotor − Total Beban | idem |
| Beban = Gaji + Operasional saja | `finance.BEBAN_KATEGORI` |
| Transaksi `MANUAL` tidak masuk laba | hanya `tambahan_kas` (informasi) |
| Bagi hasil 10/30/30/30 | `distribution.py` |

[TERKUNCI] Angka resmi selalu dari **ledger `payments`**, bukan kolom legacy
`service_orders.payment`.

Detail: [FINANCE_FLOW.md](FINANCE_FLOW.md).

---

## 3. Periode kas

| Aturan | Ditegakkan di |
|---|---|
| Omzet & Beban **khusus per periode** | kohor `settled_orders(start, end)` |
| Hanya **DP**, **Hutang Beban**, **Kas Aset** yang boleh menyeber | `finance.period_key()` |
| Periode tertutup = final | `closing.tutup_periode()` |
| `period_key()` memakai `kas_periods.id`, **bukan** tanggal | `finance.period_key()` |

[TERKUNCI] Larangan mutlak menyambungkan periode. Violasi ini merusak angka
Omzet dan Beban periode berikutnya.

Detail: [FINANCE_FLOW.md](FINANCE_FLOW.md) bagian 8.

---

## 4. Tutup Kas

[TERKUNCI] Urutan resmi ([FR-02](OWNER_DECISIONS.md)):

1. Catat modal terlewat
2. Bayar Beban
3. Pastikan distribusi
4. Pindahkan 30% Hak Kas Aset
5. Declare / rekonsiliasi

[TERKUNCI] **Jangan pernah** memakai DP titipan atau memaksa distribusi.

[TERKUNCI] Kas Aset **tidak pernah** tersentuh otomatis.

[TERKUNCI] Defisit **tidak** membentuk Hutang Beban otomatis
([OD-LOCK-12](OWNER_DECISIONS.md)).

Detail: [FINANCE_FLOW.md](FINANCE_FLOW.md) bagian 10.

---

## 5. DP

| Aturan | Ditegakkan di |
|---|---|
| DP = titipan customer, bukan kas toko | penyajian (`kas_aset_awal_operasional`) |
| DP tidak boleh melebihi estimasi | `statusflow.cek_dp_vs_estimasi()` di 4 jalur |
| DP dianggap terpakai sebesar kewajiban, hanya bila LUNAS | `cash.dp_terpakai()` |

Toleransi: pembulatan 1 sen diperbolehkan sebelum penolakan. Lihat
[AUDIT_FINDINGS.md](AUDIT_FINDINGS.md).

---

## 6. Status & lifecycle

[TERKUNCI] 9 status kanonik. `CASH` **final** ([OD-LOCK-03](OWNER_DECISIONS.md)).

Status **bayar** (`LUNAS`/`BELUM LUNAS`) bersifat diturunkan — tidak disimpan.

Detail: [SERVICE_LIFECYCLE.md](SERVICE_LIFECYCLE.md).

---

## 7. Kelola akun

| Aturan | Ditegakkan di |
|---|---|
| Nonaktifkan, bukan hapus | `routers/auth.py` |
| Anti-eskalasi: Admin tidak bisa membuat Super Admin | `_tolak_bila_bikin_superadmin()` |
| Setiap perubahan akun masuk journal, nilai sebelum & sesudah | `_catat_jurnal_akun()` |
| Ganti passcode mencabut semua token | `change_passcode` |

Detail: [PERMISSION_MATRIX.md](PERMISSION_MATRIX.md) bagian 5.

---

## 8. Role read-only

[TERKUNCI] [OD-LOCK-09](OWNER_DECISIONS.md): `PENGELOLA` dan `INVESTOR` tidak
boleh menulis apa pun.

Ditegakkan blanket di `authority.can()`, **sebelum** dicek ke matriks. Jangan
mendaftarkan role ini di matriks untuk aksi tulis.

Detail: [PERMISSION_MATRIX.md](PERMISSION_MATRIX.md) bagian 4.

---

## 9. Source of truth per domain

| Domain | Sumber tunggal | Larangan |
|---|---|---|
| Omzet / Modal / Laba | `backend/finance.py` | Jangan hitung ulang di router/laporan |
| Kewajiban & status bayar | `backend/statusflow.py` | Jangan karang ulang |
| Pembayaran Beban | `backend/beban_bayar.py` | **Jangan tambah jalur bayar kedua** |
| Wewenang | `backend/authority.py` | Jangan bikin daftar role terpisah |
| Aturan bisnis | `docs/OWNER_DECISIONS.md` | Jangan tulis ulang di tempat lain |

Mengindahkan sumber ke modul lain **hanya dengan tautan**, jangan dengan
penyalinan teks.

---

## 10. Konflik yang belum selesai

[FAKTA] Ada beberapa tempat di mana kode dan dokumentasi lama berbeda, dan
satu alur Owner yang belum jelas. Rinciannya di
[AUDIT_FINDINGS.md](AUDIT_FINDINGS.md).

[Ringkasan] Yang perlu keputusan Owner:

- Alur "catat Hutang Beban saat Tutup Kas" secara harfiah tidak mungkin
 (endpoint menolak periode tertutup, sementara Tutup Kas sudah menutup periode).
- Apakah lompatan status besar bersertai catatan itu sah.
- Apakah `POST /api/beban-hutang/proses` harus dihapus.

**Jangan memperbaiki sendiri.** Tunggu keputusan Owner.