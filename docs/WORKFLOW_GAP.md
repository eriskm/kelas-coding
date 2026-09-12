# GAP ANALYSIS — Master Business Workflow vs Implementasi Existing

Tanggal: 2026-09-10
Acuan: MASTER BUSINESS WORKFLOW Sukabumi Flasher (27 pasal)
Status: ANALISA SAJA — belum ada perubahan kode dari dokumen ini.

## Ringkasan

Fondasi sudah sejalan (penerimaan 2 jalur, claim sebagai record baru,
histori tidak ditimpa, 3 nota warna, pemisahan status). Ditemukan 8 gap.

## Sudah sesuai

| Pasal dokumen | Kondisi existing |
|---|---|
| §1 Penerimaan 2 jalur | Servis Baru + Klaim Garansi terpisah, nota sendiri-sendiri |
| §13–17 Claim | Claim = record `CLM-` baru, servis asal tak tersentuh, VALID≠auto-diterima, tolak wajib alasan |
| §9, §11 CANCEL≠FAILED (konsep) | Dipahami di level data; histori tidak dihapus |
| §23–24 histori & 3 nota warna | `SV-`/`CLM-` tetap, PS/PG/NG jadi label + warna |
| §25 pemisahan status | Garansi, hasil claim, status proses di kolom terpisah |

## Gap

### 1. Status FAILED tidak ada di operasional (§2, §4, §6, §8) — BESAR
- Dokumen: 8 status termasuk FAILED (KONFIRMASI tidak setuju / REPAIR gagal).
- Kode: `usStatus`, `usQuickStatus`, `rcStatus` (index.html) tidak punya opsi
  FAILED. Kata "Failed" hanya ada di dummy chart dashboard.
- Dampak: teknisi tidak bisa mencatat pekerjaan gagal; satu-satunya opsi
  adalah CANCEL yang artinya berbeda (§9: FAILED≠CANCEL).

### 2. Status FILED tidak ada di dokumen
- Kode: opsi FILED ("Arsip") ada di 3 dropdown
  (frontend/index.html:1513,1693,1810).
- Dokumen tidak mengenal FILED — arsip menurut §12 lewat Tutup Kas,
  bukan status. Putuskan: hapus FILED atau definisikan di dokumen.

### 3. Tutup Kas & Pindah Arsip cuma seremoni (§12)
- Kode: tombol ada (index.html:1072) tetapi frontend/script.js:2518
  menegaskan "konfirmasi lokal — data & perhitungan tidak diubah".
  CASH/CANCEL tetap tampil di Transaksi.
- Dokumen mewajibkan keduanya keluar dari tampilan operasional aktif
  (tanpa DELETE database).

### 4. Nota Transaksi belum ada (§13, §24)
- Ada 3 nota (PS/PG/NG). Nota/kwitansi pembayaran saat CASH belum ada,
  padahal §10 CASH = transaksi keuangan.

### 5. Resolusi claim REPAIR/REPLACE/REFUND belum ada (§18–21)
- Claim hanya DITERIMA/DITOLAK. Tidak ada field resolusi, tidak ada data
  refund (nilai, metode, approval), tidak ada arus kas keluar refund
  di Keuangan.

### 6. CASH belum masuk Keuangan (§10)
- Panel finance di Update masih hitungan lokal ("belum masuk KAS").
  CASH tercatat tetapi tidak memposting pendapatan ke mana pun.
  CANCEL juga tidak ada penegakan "bukan transaksi".

### 7. QC tidak tercatat (§7)
- Alur DONE→CASH langsung. QC hanya disebut di grouping dashboard backend
  (backend/routers/dashboard.py:20) tetapi tidak bisa diisi dari UI.
- Saran ringan: checklist QC di Update, bukan status baru (dokumen juga
  menulisnya sebagai tahap, bukan status).

### 8. Beda nama kecil
- Nomor: kode `SV-` vs contoh dokumen `SF-` (§14).
- Status garansi: kode `VALID` vs contoh dokumen `ACTIVE` (§25).
- Status legacy backend (RECEIVED/READY/COMPLETED/QC/DIAGNOSIS) masih dipakai
  dashboard tetapi tak bisa diisi dari UI — inkonsisten dengan 8 status dokumen.

## Rekomendasi urutan eksekusi

1. Tambah status FAILED + validasi + aturan CANCEL-hanya-dari-FAILED.
2. Keputusan soal FILED (hapus vs definisikan).
3. Tutup Kas benar-benar memfilter tampilan (flag `is_archived`, bukan delete).
4. Nota Transaksi saat CASH.
5. Resolusi + Refund (satu-satunya yang menyentuh skema klaim).
6. Posting CASH → Keuangan, QC checklist, harmonisasi nama/SV-vs-SF.
