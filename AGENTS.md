# Aturan Kerja — BOSS SF Servis

Dokumen ini adalah pengingat yang WAJIB dibaca sebelum melakukan apa pun di repo ini.

---

## 0. ATURAN BISNIS TERKUNCI — WAJIB DIBACA DAHULU

> ### 🔒 `docs/OWNER_DECISIONS.md` adalah **sumber kebenaran bisnis** BOSS SF.
>
> Sebelum melakukan audit, pengembangan, validasi, pengujian, atau perubahan kode,
> **WAJIB** membaca dokumen itu lebih dulu.

Isinya:

| ID | Isi | Status |
|---|---|---|
| **FR-01** | Payment Ledger & Financial Core | 🔒 LOCKED |
| **FR-02** | Mekanisme Tutup Kas | 🔒 LOCKED |
| **OD-LOCK-01** | Modal Part & Jasa keluar dari Laci saat CASH | 🔒 LOCKED |
| **OD-LOCK-02** | Distribusi Bagi Hasil 10/30/30/30 | 🔒 LOCKED |
| **OD-LOCK-03** | Status CASH bersifat FINAL | 🔒 LOCKED |
| **OD-LOCK-04** | DP tidak boleh melebihi estimasi | 🔒 LOCKED |
| **OD-LOCK-05** | Refund klaim garansi dilakukan MANUAL | 🔒 LOCKED |
| **OD-LOCK-06** | Pembayaran Beban: Laci → Kas Aset → Hutang Beban | 🔒 LOCKED |

Yang WAJIB dipatuhi:

- ❌ **Jangan mengubah, menghapus, atau melemahkan aturan terkunci** tanpa
  keputusan eksplisit dari Owner.
- ❌ **Jangan mengubah keputusan bisnis untuk menyesuaikan kode.** Kalau kode
  bertentangan, perbaiki **kodenya**.
- ❌ **Jangan menafsirkan ulang** aturan terkunci berdasarkan asumsi teknis.
- ✅ Catat ketidaksesuaian sebagai temuan, lalu tunggu keputusan Owner.
- ✅ Keputusan Owner adalah acuan; **implementasi wajib mengikuti keputusan
  yang terkunci, bukan sebaliknya.**

Dokumen `OWNER_DECISIONS.md` juga punya bagian **Ketidaksesuaian Implementasi**
yang mencatat aturan mana yang belum berjalan di kode. Itu daftar pekerjaan
yang menunggu perintah Owner — **bukan** daftar untuk dikerjakan sendiri.

---

## 1. KONFIRMASI DULU — TANPA KECUALI

**Jangan pernah melakukan sesuatu berdasarkan asumsi sendiri.**

Sebelum melakukan TINDAKAN APA SAJA, konfirmasi dulu ke Owner:

| Jenis tindakan | Wajib konfirmasi |
|---|---|
| Mengubah kode atau tampilan | Ya |
| Mengubah perhitungan / rumus | Ya |
| Mengubah data atau DB | Ya |
| Commit / push | Ya |
| Menjalankan migrasi | Ya |
| Membuat file baru | Ya |
| Memberi angka / laporan | Ya, kalau belum pasti |

Kalau tidak yakin, **berhenti dan tanya**. Jangan conducting sendiri.

Yang TIDAK boleh dilakukan tanpa izin:
- Menambahkan baris, kolom, atau bagian di UI karena "kiranya akan membantu"
- Mengubah label supaya "lebih jelas" tanpa diminta
- Memberi usul perubahan lalu langsung mengerjakannya
- Menyatakan sesuatu "sudah diperbaiki" tanpa bukti

Kalau memberi usul, sebutkan lengkap:
1. Apa persis yang akan berubah
2. Apa risikonya
3. Apakah itu benar yang diminta Owner atau inisiatif sendiri

Lalu **tunggu**. Jangan eksekusi sebelum Owner bilang ya.

---

## 2. CARA BEKERJA

- **Angka dulu, baru kesimpulan.** Setiap angka yang dilaporkan harus bisa
  ditelusuri ke sumbernya (file:line, atau query yang dijalankan).
- **Bukti negatif.** Setelah mengubahsomething, uji dulu: kalau dikembalikan
  ke kondisi buruk, apakah test benar-benar menjadi merah? Test yang selalu
  hijau tanpa uji negatif belum tentu berguna.
- **Jangan menebak angka.** Gunakan fungsi aplikasi, bukan SQL karangan.
  Kolom legacy bisa membuat hitungan karangan meleset.
- **Cek dulu sebelum-usul.** Jangan mengusulkan perubahan yang secara
  matematis tidak mungkin dilakukan.
- **Koreksi diri.** Kalau salah, akui langsung di depan Owner.

---

## 3. KESALAHAN YANG SUDAH TERJADI — JANGAN DIULANG

1. **Menyajikan angka lintas periode seolah-olah angka periode berjalan.**
   Aggregat beberapa periode tidak boleh muncul sebagai angka satu periode.
2. **Mengusulkan "pengersingan" fungsi yang tidak mungkin digengersingkan.**
   Posisi kas harus punya saldo awal. Memaksa nol merusak Declare.
3. **Menambah baris / mengganti label UI tanpa diminta.**
   Owner hanya menjelaskan, bukan meminta perubahan. Jangan langsung eksekusi.
4. **Salah membaca penjelasan Owner sebagai permintaan perubahan.**
5. **Menghitung dengan SQL mentah** sehingga mengabaikan kolom legacy dan
   melaporkan angka yang salah.

---

## 4. ATURAN BISNIS OWNER (sumber kebenaran)

### Pengakuan pendapatan
- **Omzet** = unit **CASH + LUNAS** saja. DP **bukan** Omzet.
- **Modal** = Modal Part + Modal Jasa + Modal Lain — tiga komponen **terpisah**,
  tidak digabung, tidak boleh dihitung dua kali.
- **Laba Kotor** = Omzet − Total Modal
- **Laba Bersih** = Laba Kotor − Total Beban
- **Transaksi kas manual (jurnal `sumber=MANUAL`) tidak masuk laba**, di mana pun.
  Bukan Omzet, bukan Modal, bukan Beban. Cuma pergerakan uang di laci.
- **Beban** = Gaji + Operasional saja. Kategori lain bukan Beban.
- **Distribusi Laba** = 100% dibagi 10% Karyawan / 30% Pengelola /
  30% Investor / 30% Kas Aset.

### Periode kas
- **Omzet dan Beban itu KHUSUS per periode.** Dilarang keras menghubungkan
  hitungan periode sekarang ke periode berikutnya.
- Hanya **tiga hal** yang boleh menyeber periode: **UANG DP, KAS ASET, dan
  HUTANG BEBAN**.
- Periode yang **sudah ditutup lewat Tutup Kas itu final** — tidak diubah,
  tidak dibahas lagi.

### Uang DP / Titipan
- DP adalah **titipan customer**, bukan kas toko.
- **DP tidak boleh muncul di Kondisi Kas Operasional.** Satu-satunya tempat DP
  dilacak adalah **Laporan Titipan DP**.
- **Declare saat Tutup Kas memakai angka FISIK penuh** (DP ikut dihitung),
  karena uang DP benar-benar ada di dalam laci.
- DP hanya dianggap terpakai **sebesar kewajiban unit**. Kelebihan bayar tetap
  ditahan sampai dikembalikan — jangan diserap habis-habisnya.

### Tutup Kas
- Tutup Kas = **menyelesaikan kewajiban kas periode**, bukan sekadar potong buku.
- Urutan: catat modal terlewat → bayar Beban periode → pastikan distribusi.
- Setelah itu Laci kembali ke titik awal secara matematis.
- **Jangan pernah** memakai DP titipan, memaksa distribusi, atau membuat saldo
  nol artifisial. Defisit ditutup Kas Aset + Hutang Beban.

### Pembayaran Beban (OD-LOCK-06)
- Pembayaran **langsung** saat periode dibekukan — **tidak** menunggu Tutup Kas.
- Urutan dana: **Laci → Kas Aset → Hutang Beban**.
- Kas Aset **benar-benar berpindah** (transfer tercatat di jurnal), bukan
  sekadar mencatat angka cover.
- **Jangan pernah** membuat Laci negatif, dan **jangan** memakai Hutang Beban
  seumpama uang yang sudah dibayar.
- Satu-satunya pencatatatan pembayaran adalah
  `beban_bayar.bayar_beban_periode()`. **Jangan** menambah jalur pembayaran
  baru di tempat lain — dua jalur dengan penanda idempotensi berbeda adalah
  penyebab Beban dibayar dua kali (lihat `KETIDAKS-SUAIAN-03`).
- `ref_type` untuk Beban periode selalu `"beban_periode"` dengan
  `ref_id = <periode>`. Penanda inilah yang membuat Tutup Kas tidak membayar
  ulang.
- Beban tetap **beku sekali per periode** (FR-01).

---

## 5. PETA TEKNIS

- **Backend** : FastAPI + SQLAlchemy, di `backend/`
- **Frontend** : HTML + JS vanilla, di `frontend/`
- **Test** : pytest, di `tests/` — jalankan `python -m pytest tests -q`
- **DB produksi** : `servisku.db` di root project
- **Backup otomatis** : `backup-servisku-*.db`, dipangkas 10 terbaru per start

### Titik penting
| File | Isi |
|---|---|
| `backend/finance.py` | **SATU-SATUNYA tempat** Laba Kotor & Laba Bersih dihitung |
| `backend/beban_bayar.py` | **SATU-SATUNYA tempat** pembayaran Beban (OD-LOCK-06) |
| `backend/routers/dashboard.py` |.endpoint `/api/overview`; **membaca** laba dari core, jangan hitung ulang |
| `backend/closing.py` | Tutup Kas |
| `backend/cash.py` | Ledger kas, `saldo_laci`, Declare/rekonsiliasi |
| `backend/statusflow.py` | `kewajiban()` dan `payment_summary()` — pakai ini, jangan karang ulang |
| `frontend/script.js` | `renderKondisiKas()` dan `renderKuTitipan()` |

### Cara cek cepat
```
python -m pytest tests -q
node --check frontend/script.js
git status --short
```

---

## 6. YANG INI BELUM PERLU DIPERBAIKI

- `script.js` punya fungsi `txdRefundDP` dan `txdFailedCancel` yang **terdefinisi
  tapi tidak terpakai** dari HTML mana pun (dead code).
- Commit masih **belum di-push** ke remote.
- `saldo_laci()` sengaja menjumlah seluruh entri (opening + semua mutasi) —
  itu memang benar untuk Declare. Yang menjaga agar tidak menumpuk adalah
  **Tutup Kas yang selalu menyelesaikan periode**, bukan bentuk fungsinya.