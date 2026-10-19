# AUDIT FINDINGS - BOSS SF

Hasil audit kode, 2026-10-17. Read-only - tidak ada file yang diubah.

| Penanda | Arti |
|---|---|
| `[FAKTA]` | Terverifikasi dari kode, test, atau isi DB |
| `[TEMUAN]` | Hasil audit; belum tentu bug, belum tentu disengaja |
| `[BELUM DIPUTUSKAN]` | Tidak ada keputusan Owner; jangan diasumsikan |

Semua temuan di sini **tidak** diperbaiki. Perbaikannya butuh keputusan Owner.

---

## A. Keamanan

### A1. Kredensial Cloudflare Tunnel ter-commit ke git - **TINGGI**

[FAKTA] `setup-online.bat` memuat `TunnelSecret` dan `AccountTag` dalam bentuk
base64, dan file itu **ter-track di git** (`git ls-files setup-online.bat`).
`.gitignore` tidak menutup pola `.bat`.

Dampak: siapa pun yang bisa membaca repo bisa mengambil alih tunnel.

Penyelesaian (keputusan Owner): rotasi kredensial di dashboard Cloudflare,
lalu purge dari git history.

> Nilai secret **tidak** dicantumkan di dokumen ini, sengaja.

### A2. Tidak ada rate limiting di login - **TINGGI untuk mode online**

[FAKTA] `grep` untuk `slowapi`, `rate_limit`, `limiter` di seluruh `backend/`
= **0 hasil**. `POST /api/auth/login` tidak punya throttle, lockout, maupun
backoff.

Passcode minimum 4 karakter, PBKDF2 200.000 iterasi memperlambat per
percobaan, tapi **tidak membatasi jumlah** percobaan.

Mitigasi sementara: pasang reverse proxy dengan rate limit.

### A3. CORS `allow_origins=["*"]` - **SEDANG**

[FAKTA] `backend/main.py` mengizinkan semua origin dengan
`allow_credentials=True`. Token lewat header (bukan cookie), jadilangsung
eksploitasi kecil - tapi ini broadest-possible dan bertentangan dengan
komentarnya sendiri yang menyebut "untuk development".

### A4. `GET /api/health` membocorkan versi - **RENDAH**

[FAKTA] Endpoint publik mengembalikan `APP_VERSION` dan daftar path
`/api/auth/*`.

### A5. Token tidak pernah di-GC - **RENDAH**

[FAKTA] Baris `auth_tokens` yang kedaluwarsa hanya dihapus saat token itu
dipakai. Tidak ada job pembersihan.

---

## B. Kontradiksi komentar vs kode — kontradiksi komentar vs kode

### B1. Komentar kas tentang DP tidak sesuai kode

[FAKTA] Komentar di `backend/cash.py` menyatakan DP "tidak membuat entri kas
sama sekali". Faktanya DP **tetap** menulis entri Laci Masuk
(`cash.catat_penerimaan`). Fungsi yang disebut di komentar itu **tidak ada**
di repo.

Yang benar secara bisnis: DP memang menambah Laci; pemisahan "bukan Omzet"
dibuat di **penyajian**, bukan dengan menahan pencatatan. Kodenya sudah benar -
komentarnya yang usang.

### B2. Komentar "CASH hanya dari DONE" tidak sesuai kode

[FAKTA] Komentar di router order menyatakan `CASH` wajib hanya dari `DONE`.
Faktanya `check_transition()` mengizinkan `FAILED`/`CANCEL` ke `CASH` selama
disertai `status_note`.

OD-LOCK-03 sendiri tetap terpenuhi (dari `CASH` dikunci).

[BELUM DIPUTUSKAN] Apakah lompatan status besar bersertai catatan memang
diizinkan. Tidak ada dokumen Owner yang menyatakannya.

### B3. Docstring handover usang

[FAKTA] Docstring menyebut `DONE` bisa di-handover. Kode hanya menerima
`CASH`, `FAILED`, `CANCEL`.

### B4. Komentar distribusi usang

[FAKTA] Komentar di `backend/distribution.py` masih menyatakan 30% Kas Aset
dipindah saat distribusi terbentuk, dan Tutup Kas tidak membentuk distribusi.

Kode sekarang mengikuti [OD-LOCK-11.5](OWNER_DECISIONS.md) dan
[OD-LOCK-12](OWNER_DECISIONS.md): 30% dipindah saat **Tutup Kas**, dan Tutup
Kas memang memanggil `pastikan_otomatis`.

**Komentar yang usang, bukan kode.**

### B5. Path endpoint salah di komentar

[FAKTA] `closing.py` dan `beban_bayar.py` mengiklankan endpoint
`/api/kas/hutang-beban/catat`. Endpoint sebenarnya
`/api/beban-hutang/catat`.

### B6. AGENTS.md lama menyebut SUPERADMIN alias ADMIN

[FAKTA] Sudah dipisah di kode, sesuai [OD-LOCK-10.1](OWNER_DECISIONS.md).
Dokumen lama yang salah — sudah dikoreksi di `AGENTS.md` versi sekarang.

---

## C. Jalur yang bisa melanggar aturan terkunci

### C1. `POST /api/beban-hutang/proses` masih menulis Hutang Beban otomatis

[FAKTA] Endpoint ini memanggil `expense_debt.proses_defisit()` yang menulis
`ExpenseDebtPeriod`/`Entry` dengan `hutang = beban - laba_kotor`.

[TERKUNCI] [OD-LOCK-12](OWNER_DECISIONS.md) menyatakan Hutang Beban **tidak
pernah** terbentuk otomatis; diinput manual oleh Admin.

Otoritasnya Admin, jadi bukan kebocoran role - tapi jalur tulis otomatis masih
aktif.

[BELUM DIPUTUSKAN] Apakah endpoint ini harus dihapus, atau dibiarkan sebagai
alat bantu?

### C2. `POST /api/orders` tidak memvalidasi matriks transisi

[FAKTA] Endpoint ini hanya mengecek keanggotaan status, tidak memanggil
`check_transition()`. Bandingkan `POST /api/orders/receive` yang memvalidasi.

Dampak: order bisa lahir dengan status sah apa pun tanpa melalui matriks
transisi.

### C3. Pengecekan teknisi aktif tidak dipanggil di jalur utama

[FAKTA] Penjaga teknisi aktif hanya dipanggil saat status masuk `REPAIR`. Tidak
dipanggil di `receive_unit`, `POST /api/orders`, atau `receive_claim`.

[BELUM DIPUTUSKAN] Apakah penugasan teknisi nonaktif lewat jalur utama harus
ditolak?

---

## D. Bug terverifikasi

### D1. Idempotency tidak pernah selesai - **TERBUKTI DARI DATA**

[FAKTA] `idempotency.jalankan()` tidak melakukan `commit()`. Tapi 5 dari 6
endpoint pemanggil melakukan `commit()` **di dalam** aksi. Akibatnya baris
idempotency ter-commit sebagai `IN_PROGRESS`, dan update ke `COMPLETED` hilang
saat session ditutup.

Bukti di DB produksi: `idempotency_keys` berisi **2 baris `IN_PROGRESS`** untuk
`scope='kas.close'`, padahal kedua periode **berhasil CLOSED**.

Dampak: retry dengan key sama menghasilkan **409 selamanya**, bukan replay.
Proteksi dobel-tutup-kas tidak bekerja lewat jalur itu.

Yang benar: `payments.py` - commit dilakukan setelah `jalankan` selesai.

### D2. `saldo_setelah` selalu null pada refund garansi

[FAKTA] Di router refunds, fungsi `_saldo_layer()` memanggil
`cash.saldo_layer(...))` tapi modul **tidak meng-import `cash`**. `NameError`
ditangkap `except Exception`, jadi `saldo_setelah` selalu `null`.

Refund garansi adalah jalur non-otomatis, jadi tidak menutup saldo, tapi
respons API-nya salah.

### D3. Filter periode riwayat Kas Aset tidak jalan

[FAKTA] Blok filter pada `GET /api/kas/aset/riwayat` ditulis dengan kondisi
`if False`, jadi filter **tidak pernah** dievaluasi. Endpoint selalu
mengembalikan seluruh histori.

### D4. Migrasi ke PostgreSQL tidak bisa dijalankan - **TERBLOKIR**

[FAKTA] `migrate_sqlite_to_postgres.py` punya `TABLE_ORDER` dengan **11
tabel**, sedangkan ada 21. Guard akan `sys.exit` sebelum transfer.

10 tabel tidak terdaftar: `journal_entries`, `expense_periods`,
`distributions`, `refunds`, `expense_debt_periods`, `expense_debt_entries`,
`stock_moves`, `service_order_parts`, `notifications`, `idempotency_keys`.

---

## E. Kode mati

[FAKTA] Ditemukan lewat pencarian repo.

| Item | Lokasi | Catatan |
|---|---|---|
| `app.py` di root | `app.py:1-225` | Proyek **Flask** terpisah, port 5000, DB `keuangan_praktek.db`. Tidak dijalankan apa pun. |
| `WORK_DONE_STATUSES` | `statusflow.py` | Tidak direferensikan |
| `STATUS_LABELS` | `statusflow.py` | Tidak direferensikan |
| `CLOSING_ONLY_STATUSES` | `statusflow.py` | Tidak dipakai; otoritas pakai `CLOSING_STATUSES` sendiri |
| `SUMBER_REFUND_GARANSI`, `SUMBER_PENYESUAIAN`, `SUMBER_HUTANG_BEBAN` | `cash.py` | Dideklarasikan, tidak pernah menulis entri |
| `catat_beban()` | `cash.py` | Mati di produksi; hanya dipanggil test |
| `sisa_kewajiban_beban()` | `beban_bayar.py` | Tidak dipakai di luar modul |
| `txdRefundDP`, `txdFailedCancel` | `frontend/script.js` | Dead code di frontend |
| `_ROLE_SUPERADMIN_CANON` | `routers/auth.py` | Konstanta mati |
| `require_finance` | `routers/auth.py` | Tidak dipakai router mana pun |
| `getattr(customer,"no_wa",...)` | `notifications.py` | Kolom `no_wa` tidak ada di model, selalu jatuh ke `phone` |
| `tools/run_tunnel.bat` | `tools/` | Path drive tidak ada, rusak |

[FAKTA] `app.py` **tidak** boleh dihapus tanpa keputusan Owner — meski tidak
dipakai, itu proyek lama dengan aturan bisnisnya sendiri.

---

## F. Duplikasi sumber wewenang

### F1. `can_edit_finance` masih hidup

[FAKTA] `AUTHORITY_MATRIX[ORDER_UPDATE_FINANCE]` mengizinkan KASIR. Tapi
`routers/auth.py` punya daftar role manual `FINANCE_ROLES` yang **tidak**
memuat KASIR, dan dipakai saat terima unit.

Artinya ada dua sumber wewenang yang berbeda jawaban untuk pertanyaan yang
sama.

[FAKTA] `require_finance` (factory lama) sudah tidak dipakai. Yang masih aktif
adalah `can_edit_finance` di `routers/auth.py`.

### F2. `ROLE_CONFIG` dan `AUDIT_READ` tidak terpakai

[FAKTA] Keduanya ada di matriks, tapi **tidak ada endpoint** yang memakainya.
Belum ada halaman konfigurasi permission, dan belum ada halaman baca audit log.

---

## G. Operasional

| # | Temuan |
|---|---|
| G1 | `migrations_money.py` menjalankan `UPDATE ... ROUND()` pada 14 kolom untuk semua baris **setiap start**. Idempotent tapi O(rows) per boot. |
| G2 | Root repo berisi 20 file `.db`.Backup `backup-pre*`/`checkpoint-*`/`archive-*` tidak pernah di-prune. |
| G3 | Ada file `_tmp_copy_from_A.db-shm` / `-wal` di root - sisa proses SQLite yang tidak ditutup bersih. |
| G4 | Log runtime (`backend/srv.log`, `backend/srv_err.log`, `tools/*.log`) tersimpan di dalam repo. |
| G5 | `tools/reset_keuangan_nol.py` menghapus operasional + auth tokens, dan default-nya menunjuk DB produksi. Ada `--dry-run`. |
| G6 | `idempotency_keys` tidak punya UNIQUE constraint pada `(scope, key)` - masih mungkin menggandakan `IN_PROGRESS` saat concurrent. |

---

## H. Yang belum diputuskan Owner

| # | Pertanyaan |
|---|---|
| H1 | Apakah lompatan status besar bersertai `status_note` itu sah? |
| H2 | Apakah `POST /api/beban-hutang/proses` harus dihapus? |
| H3 | Alur "catat Hutang Beban saat Tutup Kas" secara harfiah tidak mungkin - endpoint menolak periode tertutup, sementara Tutup Kas sudah menutup periode. Alur yang dimaksud Owner yang mana? |
| H4 | Apakah penugasan teknisi nonaktif lewat jalur utama harus ditolak? |
| H5 | Kapan kredensial tunnel dirotasi dan history di-purge? |
| H6 | Apakah rate limiting akan dipasang, dan di layer mana? |
| H7 | Apakah role `INVESTOR` dan `ADMIN_SPAREPART` akan dipakai di produksi? |
| H8 | Apakah `app.py` (Flask lama) boleh dihapus? |

---

## I. Kontrak HTTP yang perlu diwaspadai

[FAKTA] Role tanpa otoritas `ORDER_UPDATE_FINANCE` **tidak** mendapat 403 -
nilainya dipertahankan yang lama dan field kiriman diabaikan. Ini disengaja.

[FAKTA] `POST /api/beban-hutang/catat` dijaga `Action.KAS_CLOSE`, sementara
`/proses` dan `/lunas` dijaga `EXPENSE_DEBT_WRITE`. Semantik "tutup kas"
untuk "catat hutang" tidak dijelaskan di dokumen mana pun.