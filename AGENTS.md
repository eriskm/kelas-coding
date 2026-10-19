# AGENTS.md — Pedoman Kerja AI Agent BOSS SF

Dokumen ini **wajib** dibaca sebelum mengubah apa pun di repo ini.

Semua aturan bisnis berasal dari
[`docs/OWNER_DECISIONS.md`](docs/OWNER_DECISIONS.md) — dokumen itu kanonik.
Pedoman ini mengatur **cara kerja**, bukan aturan bisnisnya.

---

## A. PROSEDUR AWAL

### A1. Baca dulu, ubah kemudian

Sebelum menyentuh kode:

1. Baca `AGENTS.md` ini.
2. Baca `docs/OWNER_DECISIONS.md` bila menyangkut uang, permission, atau status.
3. Baca dokumen detail yang relevan (`docs/`).
4. Baca **implementasi aktual** — bukan hanya komentar dan bukan hanya dokumentasi.

### A2. Audit sebelum menyimpulkan

Jangan menyimpulkan sebuah fitur aktif karena ada file, route, tabel, atau
tombolnya. Telusuri implementasinya sampai ketemu fungsi yang benar-benar
memanggilnya.

> Contoh nyata: `Action.AUDIT_READ` ada di matriks wewenang, tapi **tidak ada**
> endpoint yang memakainya. Ada action ≠ ada fitur.

Kalau dokumen dan kode berbeda: **kode adalah fakta.** Selisihnya catat sebagai
temuan — jangan diperbaiki sepihak dan jangan didiamkan.

### A3. Petakan ruang lingkup sebelum eksekusi

Sebelum menulis perubahan, tentukan dan sebutkan:

- File mana yang terdampak.
- Dependensi apa yang ikut berubah.
- Risiko terhadap bisnis, permission, database, dan API.
- Test mana yang membuktikan perubahan ini benar.

### A4. Bukti harus bisa ditelusuri

Setiap angka atau klaim wajib punya sumber: `file:line`, atau output perintah
yang benar-benar dijalankan. Kalau tidak bisa ditelusuri, itu asumsi — tulis
sebagai asumsi, bukan fakta.

---

## B. PERLINDUNGAN ATURAN BISNIS

### B1. Aturan terkunci tidak bisa diubah sendiri

🔒 Aturan `OD-LOCK-*` dan `FR-*` di `docs/OWNER_DECISIONS.md` bersifat **TERKUNCI**.

- ❌ Jangan mengubah, melemahkan, atau menginterpretasi ulang aturan terkunci.
- ❌ Jangan mengubah **kode** supaya cocok dengan interpretasi rulesmu.
- ✅ Kalau kode bertentangan dengan aturan → **perbaiki kodenya**.
- ✅ Kalau kamu ragu → catat sebagai temuan, tunggu keputusan Owner.

### B2. Jangan menebak angka

Gunakan **fungsi aplikasi** untuk menghitung, bukan SQL karangan.

Query mentah bisa meleset karena ada kolom legacy yang sengaja disimpan
(arsip UI) dan yang harus dikecualikan dari hitungan resmi. Contoh: DP tercatat
ganda di `service_orders.payment` (arsip) **dan** di tabel `payments`
(ledger). Angka resmi selalu dari ledger.

### B3. Source of truth per domain

| Domain | Sumber tunggal | Larangan |
|---|---|---|
| Omzet / Modal / Laba | `backend/finance.py` | Jangan hitung ulang di router/laporan |
| Kewajiban & status bayar | `backend/statusflow.py` | Jangan karang ulang |
| Pembayaran Beban | `backend/beban_bayar.py` | **Jangan tambah jalur bayar kedua** |
| Wewenang | `backend/authority.py` | Jangan bikin daftar role terpisah |
| Aturan bisnis | `docs/OWNER_DECISIONS.md` | Jangan tulis ulang di tempat lain |

Kecilkan sumber di modul lain **hanya dengan tautan**, jangan dengan
penyalinan teks — supaya tidak ada dua versi yang bisa berbeda.

### B4. Jangan perluas scope

Jangan menambah baris, kolom, endpoint, atau tombol UI karena "kira-kira akan
membantu". Kalau kamu punya ide bagus, tulis sebagai usulan — **lalu tunggu**.

### B5. Jangan samarkan asumsi

Setiap laporan wajib membedakan:

| Penanda | Arti |
|---|---|
| `[FAKTA]` | Terverifikasi dari kode / test / output |
| `[TERKUNCI]` | Keputusan Owner di `OWNER_DECISIONS.md` |
| `[TEMUAN]` | Hasil audit — belum tentu bug |
| `[BELUM DIPUTUSKAN]` | Tidak ada keputusan; jangan diasumsikan |

---

## C. KEAMANAN DAN PERMISSION

### C1. Satu mekanisme saja

Semua penjaga role **wajib** membaca `AUTHORITY_MATRIX` lewat
`require_authority(Action.X)`.

❌ Jangan menambah pemeriksaan role ad hoc seperti:

```python
if user.role.upper() in ("ADMIN", "SUPERADMIN", "MANAGER"):   # JANGAN
```

✅ Yang benar:

```python
def create_user(..., admin=Depends(require_authority(Action.USER_MANAGE))):
```

`require_admin` pernah ada dan **sudah dihapus** karena ia bypass matriks dan
tidak mengenali alias. Jangan menghidupkannya kembali.

### C2. Lindungi pemisahan SUPERADMIN / ADMIN

`SUPERADMIN` **bukan** alias `ADMIN`.

- Super Admin = Developer aplikasi (role, permission, konfigurasi, audit).
- Admin = Manager toko (operasional + Tutup Kas).
- Alias sah: `DEV`, `DEVELOPER`, `SUPER_ADMIN`, `SUPER ADMIN` → `SUPERADMIN`.

### C3. Lindungi anti-eskalasi

Admin **tidak boleh** membuat atau menaikkan akun menjadi Super Admin.
Penjaganya `_tolak_bila_bikin_superadmin()` di `backend/routers/auth.py`.
Jangan mengubahnya, dan jangan mengalahkannya dengan penyesuaian lain.

Setiap perubahan akun (nama / role / status / passcode) **wajib** masuk journal
lewat `_catat_jurnal_akun`, lengkap nilai sebelum & sesudah. Koreksi diam-diam
dilarang.

### C4. Role read-only

`PENGELOLA` (alias `PEMILIK`) dan `INVESTOR` **read-only blanketsatu**.
Jangan mendaftarkan mereka di `AUTHORITY_MATRIX` untuk aksi tulis —
`authority.can()` sudah menolaknya secara blanket.

### C5. Jangan mengorbankan keamanan demi test hijau

Assertion yang gagal karena suatu guard **adalah informasi**, bukan hambatan.
Yang benar: perbaiki implementasi atau laporkan sebagai temuan.
Yang salah: melonggarkan assertion.

Pengecekan wajib dilakukan terhadap **endpoint aktual**, bukan hanya keberadaan
guard di kode.

> ⚠️ Kalau sebuah endpoint mengembalikan `404` padahal seharusnya `403`,
> kemungkinan besar **path-nya salah** dan guard tidak pernah dievaluasi.
> `404` bukan bukti penolakan akses.

### C6. Verifikasi laporan yang menyangkut security

Dibilang "selesai" hanya kalau:

- Grep/scan benar-benar dijalankan dan hasilnya dilaporkan.
- Test dieksekusi dan output-nya dip pasting.
- Tidak ada asumsi yang tersisa.

---

## D. DATABASE DAN DATA

### D1. Identifikasi database aktif dulu

| Situasi | DB yang dipakai |
|---|---|
| Runtime lokal | `servisku.db` di root — **ini produksi** |
| Test | Salinan di direktori temp (`tests/conftest.py`) |
| Server Ubuntu | Salinan di server — **tidak selalu sama dengan lokal** |

`deploy-ubuntu.ps1` **tidak** mengirim DB kecuali dipanggil `-WithDb`.

Jangan menganggap DB development = DB produksi. Kalau tidak yakin, cek.

### D2. Lindungi data produksi

❌ Dilarang tanpa otorisasi eksplisit:

- Menghapus / mereset / mengimpor ulang data produksi.
- Menjalankan migrasi data terhadap DB yang tidak diminta.
- Menjalankan `tools/reset_keuangan_nol.py` (menghapus operasional + auth tokens).

### D3. Jangan bocorkan data sensitif

- Jangan masukkan password, token, passcode, atau hash ke dalam kode,
  komentar, log, atau dokumentasi.
- Jangan masukkan data pelanggan asli ke dokumentasi atau test.
- Dokumentasi hanya boleh memuat **nama field dan struktur**, bukan isi.

> ⚠️ `setup-online.bat` memuat kredensial Cloudflare Tunnel dalam bentuk
> base64 dan file itu **ter-track di git**. Ini sudah tercatat di
> `docs/AUDIT_FINDINGS.md`. **Jangan pernah menyalin nilai secret itu** ke
> dokumen mana pun. Penyelesaiannya rotasi kredensial + purge history —
> keputusan Owner.

### D4. Migrasi

- **Tidak ada Alembic.** Migrasi = script kustom di `on_startup` + `create_all`.
- Semua skrip migrasi **wajib idempotent** (aman dijalankan berulang).
- Menambah kolom baru → buat skrip migrasi idempotent, **jangan** andalkan
  `create_all` saja (tabel sudah ada tidak akan di-update).
- Bungkus migrasi baru dengan `try/except` supaya kegagalan tidak mematikan
  start aplikasi.

### D5. Jangan ubah skema tanpa kebutuhan

Perubahan skema berdampak ke data produksi. Kalau memang diperlukan: buat
backup, buat migrasi idempotent, jalankan test migrasi, laporkan.

---

## E. ALUR KERJA PERUBAHAN

Ikuti urutan ini:

```
Audit → Rencana singkat → Test relevan → Implementasi → Validasi → Laporan
```

### E1. Test pengaman dulu untuk perubahan berisiko

Untuk perbaikan bug, tulis **test yang gagal dulu** (TDD), buktikan ia merah,
lalu perbaiki sampai hijau. Ini memastikan test-nya benar-benar mengukur
perilaku yang dimaksud — bukan selalu hijau tanpa ada artinya.

Test yang selalu hijau tanpa bukti negatif belum tentu berguna.

### E2. Jangan longgarkan assertion

Kalau test gagal, **cari akar masalahnya**. Jangan:
- Melonggarkan `assert` supaya hijau.
- Menghapus test.
- Menambah `skip` tanpa alasan yang jelas dan tercatat.

Satu-satunya jalan yang benar: perbaiki kode atau laporkan sebagai temuan.

### E3. Pertahankan kompatibilitas

Perubahan tidak boleh merusak perilaku bisnis yang sudah benar. Bila ada
konflik antara permintaan baru dan aturan terkunci — **dokumentasikan
konflik itu, jangan dipaksakan.**

### E4. Jangan nyatakan berhasil sebelum selesai

"Lolos", "selesai", "aman" hanya sah kalau:

- Perintahnya benar-benar dijalankan.
- Test-nya benar-benar dijalankan, dan hasilnya dip pasting.
- Validasi (compile, lint, syntax) sudah dijalankan.

Kalau ada bagian yang gagal, katakan gagal. Jangan menutupinya.

---

## F. BATAS OTONOMI

### F1. Agent boleh bekerja sampai tuntas untuk hal yang secara teknis sudah jelas

Tidak perlu izin berulang untuk:

- Membaca kode, menjalankan test, menjalankan validasi.
- Memperbaiki bug yang jelas dan sudah tercakup aturan.
- Menulis test, dokumentasi, refactor internal tanpa mengubah perilaku.
- Menambah endpoint/field yang **sudah diminta** secara eksplisit.

### F2. Agent WAJIB berhenti dan melapor bila:

| Situasi | Tindakan |
|---|---|
| Butuh keputusan bisnis baru | Tulis opsi + rekomendasi, **tunggu** |
| Mengubah hak akses / role | Tunggu keputusan Owner |
| Tindakan destruktif pada data | Tunggu otorisasi eksplisit |
| Perubahan di luar otorisasi | Tunggu |
| Menemukan konflik kode ↔ aturan terkunci | Laporkan, jangan perbaiki sepihak |
|- Secret bocor / risiko keamanan | Laporkan segera, jangan diam |

Usulan harus menyebut: **apa yang berubah**, **risikonya**, dan **apakah itu
memang diminta Owner atau inisiatif sendiri**.

### F3. Jangan tinggalkan perubahan setengah jalan

Kalau berhenti di tengah, pastikan working tree jelas: apa yang sudah jadi,
apa yang belum, dan apa langkah berikutnya.

---

## G. LAPORAN AKHIR

Setiap pekerjaan wajib melaporkan:

```markdown
## Ringkasan
<apa yang terjadi, 1-3 kalimat>

## Perubahan
- <perubahan konkret>

## File
- <file> — <apa yang berubah>

## Test
- Perintah: <command>
- Hasil: <output nyata>

## Dampak
- Bisnis: <...>
- Permission: <...>
- Database: <...>
- API: <...>

## Risiko / Belum Selesai
- <...>
```

Kalau ada bagian yang tidak dijalankan atau gagal, tulis **"tidak
dijalankan"** atau **"gagal"** beserta alasannya. Jangan menuliskan hasil
yang tidak benar-benar diperoleh.

---

## PETA TEKNIS

| File | Isi |
|---|---|
| `backend/main.py` | Entry point, startup, mount router |
| `backend/authority.py` | **MATRIKS WEWENANG** — sumber kebenaran |
| `backend/models.py` | 21 model / tabel |
| `backend/statusflow.py` | `kewajiban()`, `payment_summary()`, transisi |
| `backend/finance.py` | **CORE** — Omzet / Modal / Laba |
| `backend/cash.py` | Ledger kas 2 layer, Declare |
| `backend/closing.py` | Tutup Kas |
| `backend/beban_bayar.py` | **SATU-SATUNYA** jalur bayar Beban |
| `backend/distribution.py` | Bagi hasil 10/30/30/30 |
| `backend/journal.py` | Audit append-only |
| `backend/routers/auth.py` | Auth, token, anti-eskalasi |
| `frontend/script.js` | `renderKondisiKas()`, `renderKuTitipan()` |
| `docs/OWNER_DECISIONS.md` | **KANONIK** aturan bisnis |

---

## CEK CEPAT

```powershell
python -m pytest tests -q                  # harus semua hijau (tidak boleh ada failure)
python -m compileall -q backend            # kompilasi Python
node --check frontend\script.js           # sintaks JS
git status --short
Select-String -Path backend\**\*.py -Pattern 'require_admin'  # harus kosong
```

---

## ATURAN BISNIS INTI (ringkas — kanonik ada di docs/OWNER_DECISIONS.md)

**Pengakuan pendapatan**
- Omzet = unit `CASH` **dan** `LUNAS`. DP bukan Omzet.
- Modal = Part + Jasa + Lain, tiga komponen **terpisah**.
- Laba Kotor = Omzet − Total Modal. Laba Bersih = Laba Kotor − Total Beban.
- Beban = Gaji + Operasional saja.
- Transaksi `MANUAL` tidak masuk laba di mana pun.
- Bagi hasil 10% / 30% / 30% / 30%.

**Periode kas**
- Omzet dan Beban **khusus per periode** — dilarang menghubungkan periode.
- Hanya **tiga** yang boleh menyeber: **DP**, **Hutang Beban**, **Kas Aset**.
- Periode yang sudah ditutup = final.
- `CASH` = final, tidak bisa diubah.

**Tutup Kas**
- Menyelesaikan kewajiban kas periode: catat modal terlewat → bayar Beban →
  pastikan distribusi → pindahkan 30% Hak Kas Aset → Declare.
- **Jangan pernah** memakai DP titipan atau memaksa distribusi.
- Kas Aset **tidak pernah** tersentuh otomatis.
- `finance.period_key()` memakai `kas_periods.id`, **bukan** tanggal.

**DP**
- DP = titipan customer, bukan kas toko.
- DP tidak boleh melebihi estimasi.
- DP hanya dianggap terpakai sebesar kewajiban unit, dan hanya bila LUNAS.

Lihat `docs/OWNER_DECISIONS.md` untuk teks lengkap dan status hukumnya.

---

## YANG INI SENGAJA TIDAK DIPERBAIKI

- `frontend/script.js` punya `txdRefundDP` dan `txdFailedCancel` yang
  terdefinisi tapi tidak terpakai (dead code).
- Notifikasi adalah **outbox saja** — tidak ada pengiriman ke Telegram/WA.
- `Action.ROLE_CONFIG` dan `Action.AUDIT_READ` ada di matriks tapi belum ada
  endpoint yang memakainya.
- `app.py` di root adalah proyek Flask lama, tidak dijalankan.

Daftar lengkap: `docs/AUDIT_FINDINGS.md`.