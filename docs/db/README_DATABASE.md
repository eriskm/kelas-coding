# Panduan Struktur & Skema Database Sukabumi Flasher (Untuk AI Agent / Developer)

Dokumen ini dibuat khusus agar **AI Agent** atau developer di projek baru dapat langsung memahami isi, skema, tipe data, dan aturan *query* dari seluruh file database yang ada di folder ini tanpa perlu menebak-nebak.

---

## 1. Daftar File di Folder Ini & Fungsinya

| Nama File | Jenis Database | Ukuran / Isi | Kapan Harus Digunakan? |
| :--- | :--- | :--- | :--- |
| **`sukabumi_flasher_full_12_tabel.db`** | SQLite 3 (Binary) | **12 Tabel Lengkap** (Gabungan SQLite + 4 tabel MySQL) | **(DIREKOMENDASIKAN UNTUK SQLITE)** Gunakan file ini jika projek baru hanya ingin memakai **1 file SQLite saja** untuk seluruh 12 tabel (termasuk stok sparepart & garansi). |
| **`db_ais_systems_full_terbaru.sql`** | MySQL / MariaDB Dump | **12 Tabel Lengkap** (Gabungan MySQL + sinkronisasi terbaru dari SQLite) | **(DIREKOMENDASIKAN UNTUK MYSQL)** Gunakan file ini jika projek baru menggunakan **MySQL / MariaDB / PostgreSQL**, karena seluruh data terbaru dari SQLite sudah digabungkan ke sini. |
| **`sukabumi_flasher.db`** | SQLite 3 (Binary) | 8 Tabel Utama (Murni dari SQLite `SF_WEB`) | Gunakan jika projek baru tetap memakai arsitektur *Hybrid* (SQLite + MySQL terpisah) seperti `SF_WEB`. |
| **`db_ais_systems.sql`** | MySQL / MariaDB Dump | 12 Tabel (Kondisi asli MySQL sebelum sinkronisasi tabel SQLite) | Hanya sebagai *backup* kondisi awal MySQL. |
| **`sukabumi_flasher_sqlite.sql`** | SQLite SQL Dump | `CREATE TABLE` & `INSERT INTO` sintaks SQLite | Gunakan jika ingin membaca isi data SQLite secara langsung lewat teks atau konversi ke DB lain. |

---

## 2. Arsitektur Asal Database (Penting untuk Agent)

Pada projek asal (`SF_WEB`), sistem menggunakan arsitektur *Hybrid Database*:
1. **SQLite (`sukabumi_flasher.db`)** digunakan untuk transaksi harian cepat:
   - `servis` (39 baris — antrean servis aktif)
   - `arsip_servis` (394 baris — riwayat servis selesai/diambil beserta rincian modal & laba)
   - `kas_utama` (190 baris — rekap saldo harian & laba bersih)
   - `beban` (6 baris — daftar beban operasional tetap/variabel)
   - `transaksi_tambahan` (1 baris — kas masuk/keluar di luar servis)
   - `users` (6 baris — akun login admin/teknisi & *hashed password*)
   - `milestone_logs` (75 baris — log pencapaian target harian)
   - `pembayaran` (0 baris — bukti pembayaran transfer/QRIS)
2. **MySQL (`db_ais_systems`)** digunakan untuk gudang & arsip jangka panjang:
   - `data_sparepart` (92 baris — stok sparepart, harga beli, harga jual)
   - `arsip_pelanggan` (553 baris — database riwayat pelanggan & status final)
   - `arsip_garansi` (182 baris — masa aktif garansi servis pelanggan)
   - `master_kas` (1 baris — posisi kas kecil laci & kas aset pengelola)

> **Catatan Penting:** Di dalam file **`db_ais_systems_full_terbaru.sql`**, ke-8 tabel dari SQLite sudah dimigrasikan dan disinkronkan sepenuhnya ke dalam MySQL sehingga terdapat total **12 tabel lengkap** dalam satu database.

---

## 3. Detail Skema Tabel (SQLite vs MySQL)

### ⚠️ PERINGATAN KRITIS UNTUK AI AGENT SAAT QUERY TABEL `servis`:
- **Jika menggunakan SQLite (`sukabumi_flasher.db`):**
  1. Nama kolom di tabel `servis` menggunakan **Huruf Kapital & Spasi** (contoh: `"Tanggal Masuk"`, `"Nama User"`, `"No. WA"`, `"Harga Jual"`). **WAJIB** menggunakan tanda kutip ganda (`"..."`) saat melakukan query SQL.
  2. Kolom `No` bertipe `REAL` dan bukan *auto-increment primary key* yang ketat. Untuk mengambil ID unik per baris di SQLite, selalu gunakan **`SELECT rowid AS id, * FROM servis`**.
- **Jika menggunakan MySQL (`db_ais_systems_full_terbaru.sql`):**
  1. Seluruh nama kolom sudah dinormalisasi menjadi **`snake_case`** tanpa spasi (contoh: `tanggal_masuk`, `nama_user`, `no_wa`, `harga_jual`).
  2. Sudah memiliki Primary Key standar **`id INT AUTO_INCREMENT PRIMARY KEY`** (yang diambil dari `rowid` SQLite).

---

### A. Tabel `servis` (Data Antrean & Transaksi Servis Aktif — 39 Baris)

| Kolom di SQLite (`sukabumi_flasher.db`) | Kolom di MySQL (`db_ais_systems_full_terbaru.sql`) | Tipe Data | Keterangan |
| :--- | :--- | :--- | :--- |
| `rowid` *(implisit)* / `No` | `id` | INT (PK) | ID unik servis (di SQLite gunakan `rowid`) |
| `"Tanggal Masuk"` | `tanggal_masuk` | VARCHAR/TEXT | Format tanggal masuk (misal `2026-10-29` atau `DD/MM/YYYY`) |
| `"Device"` | `device` | VARCHAR(100) | Tipe HP / perangkat yang diservis |
| `"Nama User"` | `nama_user` | VARCHAR(100) | Nama pelanggan |
| `"PassWord"` | `password` | VARCHAR(100) | PIN / Pola / Sandi layar perangkat pelanggan |
| `"No. WA"` | `no_wa` | VARCHAR(50) | Nomor WhatsApp pelanggan |
| `"Deadline"` | `deadline` | DOUBLE/REAL | Target waktu pengerjaan |
| `"Analisa Kerusakan"` | `analisa_kerusakan` | TEXT | Keluhan / analisa kerusakan awal |
| `"Estimasi Biaya"` | `estimasi_biaya` | INT | Perkiraan biaya servis (Rupiah) |
| `"DP"` | `dp` | VARCHAR(50) | Uang muka / Down Payment |
| `"Status"` | `status` | VARCHAR(50) | Status pengerjaan (`Antri`, `Proses`, `Selesai`, `Diambil`, `Cancel`, `Pending`) |
| `"Part"` | `part` | DOUBLE/REAL | Indikator penggunaan sparepart |
| `"Tindakan"` | `tindakan` | TEXT | Tindakan perbaikan yang dilakukan |
| `"Harga Jual"` | `harga_jual` | INT | Total biaya servis yang dibayar pelanggan (Rupiah) |
| `"Modal Part"` | `modal_part` | INT | Harga modal sparepart yang dipakai (Rupiah) |
| `"Modal Jasa"` | `modal_jasa` | INT | Biaya/komisi jasa teknisi (Rupiah) |
| `"Laba Kotor"` | `laba_kotor` | INT | `Harga Jual - Modal Part - Modal Jasa - Lain-lain` |
| `"Teknisi"` | `teknisi` | VARCHAR(100) | Nama teknisi yang menangani |
| `"Tindakan Perbaikan"` | `tindakan_perbaikan` | TEXT | Catatan detail teknisi |
| `"Lain-lain"` | `lain_lain` | INT | Biaya tambahan lainnya |
| `masa_garansi` | `masa_garansi` | VARCHAR(50) | Durasi garansi (misal `7 Hari`, `1 Bulan`, `Non Garansi`) |
| `updated_at` | `updated_at` | DATETIME | Waktu terakhir status diperbarui |
| `flag_kritis` | `flag_kritis` | INT | Flag prioritas/kritis (`0` atau `1`) |
| `kelengkapan` | `kelengkapan` | TEXT | Kelengkapan unit saat diterima (HP saja, dus, SIM tray, dll.) |
| `kondisi_fisik` | `kondisi_fisik` | TEXT | Kondisi fisik unit saat diterima (lecet, retak, mati total, dll.) |

---

### B. Tabel `arsip_servis` (Riwayat Servis Selesai & Keuangan — 394 Baris)
*(Nama kolom **sama** di SQLite maupun MySQL)*
- `id` (INT Primary Key)
- `tanggal_masuk` (VARCHAR/TEXT)
- `tanggal_keluar` (VARCHAR/TEXT)
- `nama_user` (VARCHAR/TEXT)
- `wa` (VARCHAR/TEXT)
- `device` (VARCHAR/TEXT)
- `kerusakan` (TEXT)
- `tindakan` (TEXT)
- `modal_part` (INT)
- `modal_jasa` (INT)
- `harga_jual` (INT)
- `laba_kotor` (INT)
- `teknisi` (VARCHAR/TEXT)
- `kelengkapan` (TEXT)
- `kondisi_fisik` (TEXT)

---

### C. Tabel `data_sparepart` (Stok Inventaris Sparepart — 92 Baris, Khusus di MySQL)
- `id_sparepart` (INT Primary Key, Auto Increment)
- `kategori` (VARCHAR(50)) — Kategori komponen (misal: `LCD`, `Baterai`, `IC`, `Flexible`)
- `merek` (VARCHAR(50)) — Brand HP (misal: `Samsung`, `Xiaomi`, `iPhone`, `Oppo`, `Vivo`, `Infinix`)
- `jenis_barang` (VARCHAR(100)) — Nama/jenis sparepart
- `jenis_device` (VARCHAR(100)) — Tipe HP yang kompatibel
- `qty` (INT) — Jumlah stok tersedia
- `tanggal_masuk` (VARCHAR(20)) — Tanggal restock/masuk
- `harga_beli` (INT) — Harga modal beli (Rupiah)
- `harga_jual` (INT) — Harga jual rekomendasi (Rupiah)

---

### D. Tabel `arsip_pelanggan` (Database Master Pelanggan — 553 Baris, Khusus di MySQL)
- `id_arsip` (INT Primary Key, Auto Increment)
- `nama_user` (VARCHAR(100)) — Nama pelanggan
- `no_wa` (VARCHAR(20)) — Nomor WhatsApp
- `device` (VARCHAR(100)) — Perangkat pelanggan
- `tindakan` (TEXT) — Riwayat perbaikan
- `harga_jual` (INT) — Nominal transaksi
- `status_final` (VARCHAR(50)) — Status akhir (`Done`/`Diambil`/`Cancel`)

---

### E. Tabel `arsip_garansi` (Data Garansi Pelanggan — 182 Baris, Khusus di MySQL)
- `id_garansi` (INT Primary Key, Auto Increment)
- `id_arsip` (INT) — Referensi ke `arsip_pelanggan.id_arsip` / ID servis
- `nama_user` (VARCHAR(100))
- `device` (VARCHAR(100))
- `tgl_mulai` (DATE) — Tanggal mulai garansi (`YYYY-MM-DD`)
- `tgl_akhir` (DATE) — Tanggal berakhir garansi (`YYYY-MM-DD`)

---

### F. Tabel Keuangan & Kas (`kas_utama`, `master_kas`, `beban`, `transaksi_tambahan`, `pembayaran`)

1. **`kas_utama`** (190 Baris — Rekap Kas Harian di SQLite & MySQL)
   - `id` (INT PK), `tanggal` (VARCHAR/TEXT), `saldo_awal` (INT), `saldo_akhir` (INT), `total_laba_bersih` (INT)
2. **`master_kas`** (1 Baris — Saldo Kas Master di MySQL)
   - `id_kas` (INT PK), `kas_kecil_laci` (INT), `kas_aset_pengelola` (INT)
3. **`beban`** (6 Baris — Beban Operasional Toko di SQLite & MySQL)
   - `id` (INT PK), `kategori` (VARCHAR/TEXT), `nama_beban` (VARCHAR/TEXT), `nilai` (INT)
4. **`transaksi_tambahan`** (1 Baris — Arus Kas Tambahan di SQLite & MySQL)
   - `id` (INT PK), `tanggal` (VARCHAR/TEXT), `uraian` (TEXT), `jenis` (`'Masuk'` atau `'Keluar'`), `nominal` (INT)
5. **`pembayaran`** (0 Baris — Log Pembayaran Servis di SQLite & MySQL)
   - `id` (INT PK), `servis_id` (INT), `metode` (VARCHAR/TEXT), `nominal` (INT), `status` (VARCHAR/TEXT), `bukti_bayar` (TEXT), `tanggal` (VARCHAR/TEXT)

---

### G. Tabel Sistem & User (`users`, `milestone_logs`)

1. **`users`** (6 Baris — Akun Pengguna Sistem di SQLite & MySQL)
   - `id` (INT PK)
   - `username` (VARCHAR/TEXT)
   - `password` (VARCHAR/TEXT — *Hashed* menggunakan `werkzeug.security.generate_password_hash`)
   - `role` (VARCHAR/TEXT — misal `'admin'`, `'teknisi'`, `'cs'`)
   - `permissions` (TEXT — JSON string hak akses menu)
   - `foto_profil` (VARCHAR/TEXT)
   - `nama_lengkap` (VARCHAR/TEXT)
   - `status` (VARCHAR/TEXT — `'aktif'` / `'nonaktif'`)
   - `last_login` (VARCHAR/TEXT)
2. **`milestone_logs`** (75 Baris — Log Notifikasi Pencapaian Target)
   - `id` (INT PK di MySQL), `tanggal` (VARCHAR/TEXT), `jenis` (VARCHAR/TEXT)

---

## 4. Instruksi Cepat untuk AI Agent di Projek Baru

1. **Jika Projek Baru Memakai SQLite:**
   - Copy `sukabumi_flasher.db` ke folder projek baru.
   - Jika butuh semua tabel MySQL (`data_sparepart`, `arsip_pelanggan`, `arsip_garansi`, `master_kas`) di dalam SQLite juga, Agent dapat membaca `db_ais_systems_full_terbaru.sql` dan mengimpor ke-4 tabel tersebut ke dalam `sukabumi_flasher.db`.
2. **Jika Projek Baru Memakai MySQL / MariaDB:**
   - Cukup import **1 file saja**, yaitu **`db_ais_systems_full_terbaru.sql`**:
     ```bash
     mysql -u root < "db_ais_systems_full_terbaru.sql"
     ```
   - File tersebut otomatis membuat database `db_ais_systems` beserta seluruh **12 tabel** (baik data SQLite maupun MySQL) dengan isi paling mutakhir.
3. **Jika Projek Baru Memakai PostgreSQL / Prisma / Drizzle / Laravel / Next.js:**
   - Agent dapat membaca struktur dari `db_ais_systems_full_terbaru.sql` karena seluruh nama kolomnya sudah bersih (`snake_case`) dan memiliki tipe data SQL standar.
