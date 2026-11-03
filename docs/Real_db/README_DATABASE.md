# Backup 3 Tabel Database Sukabumi Flasher (Servis Saat Ini, Pelanggan, Garansi)
**Waktu Backup:** `2026-11-01 14:58:37`

Sesuai instruksi, backup ini **HANYA berisi 3 tabel terbaru** (tanpa tabel `data_sparepart` karena sudah di-copy sebelumnya):
1. **`servis`** — Data Servisan Saat Ini (**39 baris**, hingga ID #413)
2. **`arsip_pelanggan`** — Data Pelanggan (**558 baris**, hingga ID #564)
3. **`arsip_garansi`** — Data Garansi (**179 baris**, hingga ID #503)

---

## Daftar File di Folder Ini

| Nama File | Format | Kegunaan |
| :--- | :--- | :--- |
| **`sukabumi_flasher_3_tabel.db`** | SQLite 3 (`.db`) | File database SQLite murni yang berisi tepat 3 tabel (`servis`, `arsip_pelanggan`, `arsip_garansi`). Siap di-copy atau di-*attach* ke SQLite projek baru. |
| **`backup_3_tabel_mysql.sql`** | MySQL / MariaDB Dump (`.sql`) | Berisi `CREATE TABLE` & `INSERT INTO` khusus 3 tabel (`servis`, `arsip_pelanggan`, `arsip_garansi`) dengan nama kolom `snake_case`. Aman di-import tanpa menyentuh tabel `data_sparepart`. |
| **`backup_3_tabel_sqlite.sql`** | SQLite Dump (`.sql`) | Sintaks SQLite untuk ke-3 tabel tersebut jika ingin di-import ke file `.db` yang sudah ada. |

---

## Ringkasan Skema 3 Tabel

### 1. Tabel `servis` (39 Baris)
- **Di SQLite (`sukabumi_flasher_3_tabel.db`):** Gunakan `SELECT rowid AS id, * FROM servis`. Nama kolom memakai huruf besar/spasi (`"Tanggal Masuk"`, `"Device"`, `"Nama User"`, `"PassWord"`, `"No. WA"`, `"Deadline"`, `"Analisa Kerusakan"`, `"Estimasi Biaya"`, `"DP"`, `"Status"`, `"Part"`, `"Tindakan"`, `"Harga Jual"`, `"Modal Part"`, `"Modal Jasa"`, `"Laba Kotor"`, `"Teknisi"`, `"Tindakan Perbaikan"`, `"Lain-lain"`, `masa_garansi`, `updated_at`, `flag_kritis`, `kelengkapan`, `kondisi_fisik`).
- **Di MySQL (`backup_3_tabel_mysql.sql`):** Seluruh kolom sudah `snake_case` (`id`, `tanggal_masuk`, `device`, `nama_user`, `password`, `no_wa`, `deadline`, `analisa_kerusakan`, `estimasi_biaya`, `dp`, `status`, `part`, `tindakan`, `harga_jual`, `modal_part`, `modal_jasa`, `laba_kotor`, `teknisi`, `tindakan_perbaikan`, `lain_lain`, `masa_garansi`, `updated_at`, `flag_kritis`, `kelengkapan`, `kondisi_fisik`).

### 2. Tabel `arsip_pelanggan` (558 Baris)
- Kolom (sama di SQLite & MySQL): `id_arsip` (PK), `nama_user`, `no_wa`, `device`, `tindakan`, `harga_jual`, `status_final`.

### 3. Tabel `arsip_garansi` (179 Baris)
- Kolom (sama di SQLite & MySQL): `id_garansi` (PK), `id_arsip`, `nama_user`, `device`, `tgl_mulai` (`YYYY-MM-DD`), `tgl_akhir` (`YYYY-MM-DD`).
