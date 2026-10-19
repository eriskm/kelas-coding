# API REFERENCE - BOSS SF

89 endpoint. Daftar di bawah **dihasilkan dari aplikasi yang benar-benar
berjalan**, bukan dari dokumentasi.

Semua path relatif terhadap host, port default **8000**.

---

## 1. Autentikasi

[TERKUNCI] Semua endpoint wajib `Authorization: Bearer <token>` kecuali yang
disebut sebagai publik.

```http
POST /api/auth/login
Content-Type: application/json

{"username": "..." , "passcode": "..."}
```

Response berisi token opaque (64 hex char, `secrets.token_hex(32)`), TTL **7
hari**.

Semua request berikutnya:

```http
Authorization: Bearer <token>
```

Token kedaluwarsa dihapus saat dipakai dan menghasilkan 401.

### Endpoint publik (tanpa auth)

| Method | Path | Catatan |
|---|---|---|
| POST | `/api/auth/login` | Wajib |
| GET | `/api/health` | Membocorkan versi aplikasi - lihat [AUDIT_FINDINGS.md](AUDIT_FINDINGS.md) |
| GET | `/` | `frontend/index.html` |
| GET | `/static/*` | Aset frontend |
| GET | `/favicon.ico` | - |

### Endpoint auth

| Method | Path | Otoritas |
|---|---|---|
| POST | `/api/auth/login` | publik |
| POST | `/api/auth/logout` | token valid |
| GET | `/api/auth/me` | token valid |
| POST | `/api/auth/change-passcode` | token valid + passcode lama |
| GET | `/api/auth/roles` | `USER_MANAGE` |
| GET | `/api/auth/users` | `USER_MANAGE` |
| POST | `/api/auth/users` | `USER_MANAGE` + anti-eskalasi |
| PUT | `/api/auth/users/{user_id}` | `USER_MANAGE` + anti-eskalasi |

Ganti passcode **mencabut semua token** user tersebut, termasuk yang sedang
dipakai - wajib login ulang.

[TERKUNCI] Akun **dinonaktifkan, bukan dihapus**
([OD-LOCK-08](OWNER_DECISIONS.md)).

---

## 2. Order / Unit

| Method | Path | Otoritas |
|---|---|---|
| GET | `/api/orders` | token |
| POST | `/api/orders` | `ORDER_CREATE` |
| POST | `/api/orders/receive` | `ORDER_CREATE` |
| GET | `/api/orders/{order_id}` | token |
| PUT | `/api/orders/{order_id}` | `ORDER_UPDATE` |
| DELETE | `/api/orders/{order_id}` | `ORDER_DELETE` |
| POST | `/api/orders/{order_id}/handover` | `ORDER_HANDOVER` |
| GET | `/api/orders/{order_id}/history` | token |
| GET | `/api/orders/latest` | token |
| GET | `/api/orders/history/{phone}` | token |
| GET | `/api/orders/technicians` | token |

[FAKTA] `POST /api/orders` **tidak** memvalidasi matriks transisi status,
berbeda dengan `POST /api/orders/receive`.

[TERKUNCI] Status `CASH` bersifat final - tidak bisa diubah.

---

## 3. Pembayaran

| Method | Path | Otoritas |
|---|---|---|
| POST | `/api/payments` | `PAYMENT_CREATE` |
| GET | `/api/payments/by-order/{order_id}` | token |

[TERKUNCI] DP tidak boleh melebihi estimasi. Pelunasan otomatis terjadi saat
status `CASH`.

Endpoint ini mengirim header `Idempotency-Key`.

---

## 4. Refund

| Method | Path | Otoritas |
|---|---|---|
| POST | `/api/refunds/dp` | `REFUND_DP` |
| POST | `/api/refunds/garansi` | `REFUND_GARANSI` |
| POST | `/api/refunds/failed-cancel` | `FAILED_CANCEL` |
| GET | `/api/refunds` | token |
| GET | `/api/refunds/{refund_id}` | token |
| GET | `/api/refunds/precheck/dp/{service_order_id}` | token |
| GET | `/api/refunds/precheck/garansi/{warranty_claim_id}` | token |

[TERKUNCI] Refund garansi **tidak** otomatis mengeluarkan uang
([OD-LOCK-05](OWNER_DECISIONS.md)) - harus dicatat manual ke Kas Aset.

---

## 5. Garansi / Klaim

| Method | Path | Otoritas |
|---|---|---|
| GET | `/api/claims` | token |
| GET | `/api/claims/{claim_id}` | token |
| PUT | `/api/claims/{claim_id}` | `CLAIM_WRITE` |
| DELETE | `/api/claims/{claim_id}` | `CLAIM_WRITE` |
| POST | `/api/claims/receive` | `ORDER_UPDATE` |
| GET | `/api/claims/by-service/{service_id}` | token |
| GET | `/api/claims/lookup` | token |
| GET | `/api/claims/warranty-summary` | token |
| GET | `/api/claims/warranty/detail/{service_id}` | token |

[FAKTA] Membuat klaim butuh unit asal **LUNAS** dan `warranty_months != 0`.

---

## 6. Kas

| Method | Path | Otoritas |
|---|---|---|
| GET | `/api/kas/saldo` | token |
| GET | `/api/kas/entries` | token |
| POST | `/api/kas/entries` | `KAS_ENTRY_WRITE` |
| PUT | `/api/kas/entries/{entry_id}` | `KAS_ENTRY_WRITE` |
| DELETE | `/api/kas/entries/{entry_id}` | `KAS_ENTRY_WRITE` |
| GET | `/api/kas/periods` | token |
| POST | `/api/kas/close` | `KAS_CLOSE` |
| GET | `/api/kas/rekonsiliasi` | token |
| GET | `/api/kas/modal-kosong` | token |
| GET | `/api/kas/riwayat` | token |
| GET | `/api/kas/distribusi` | token |
| POST | `/api/kas/distribusi/jalankan` | `KAS_CLOSE` |

### Kas Aset

| Method | Path | Otoritas |
|---|---|---|
| POST | `/api/kas/aset/masuk` | `KAS_ASET_INJEKSI` |
| POST | `/api/kas/aset/keluar` | `KAS_ENTRY_WRITE` |
| POST | `/api/kas/aset/transfer` | `KAS_ENTRY_WRITE` |
| GET | `/api/kas/aset/riwayat` | token |
| GET | `/api/kas/aset/cukup` | token |

[TERKUNCI] Kas Aset **tidak pernah** tersentuh otomatis oleh pembayaran
Beban. Satu-satunya perpindahan otomatis adalah 30% Hak Kas Aset saat Tutup Kas
([OD-LOCK-11.5](OWNER_DECISIONS.md)).

---

## 7. Beban & Hutang Beban

| Method | Path | Otoritas |
|---|---|---|
| GET | `/api/expenses` | token |
| POST | `/api/expenses` | `EXPENSE_WRITE` |
| PUT | `/api/expenses/{expense_id}` | `EXPENSE_WRITE` |
| DELETE | `/api/expenses/{expense_id}` | `EXPENSE_WRITE` |
| GET | `/api/beban-hutang` | token |
| POST | `/api/beban-hutang/catat` | `KAS_CLOSE` |
| POST | `/api/beban-hutang/lunas` | `EXPENSE_DEBT_WRITE` |
| POST | `/api/beban-hutang/proses` | `EXPENSE_DEBT_WRITE` |
| GET | `/api/beban-hutang/precheck` | token |
| GET | `/api/beban-hutang/defisit/{kas_period_id}` | token |

[TERKUNCI] Hutang Beban diinput **manual** oleh Admin
([OD-LOCK-12](OWNER_DECISIONS.md)). `POST /beban-hutang/proses` masih menulis
hutang secara otomatis - lihat [AUDIT_FINDINGS.md](AUDIT_FINDINGS.md).

---

## 8. Sparepart & Stok

| Method | Path | Otoritas |
|---|---|---|
| GET | `/api/spareparts` | token |
| POST | `/api/spareparts` | `SPAREPART_WRITE` |
| PUT | `/api/spareparts/{sparepart_id}` | `SPAREPART_WRITE` |
| DELETE | `/api/spareparts/{sparepart_id}` | `SPAREPART_DELETE` |
| POST | `/api/inventory/masuk` | `KAS_ENTRY_WRITE` |
| POST | `/api/inventory/pakai` | `ORDER_UPDATE` |
| POST | `/api/inventory/pakai/{service_order_part_id}/batal` | `ORDER_UPDATE` |
| GET | `/api/inventory/moves` | token |
| GET | `/api/inventory/pemakaian/{service_order_id}` | token |

[TERKUNCI] `ADMIN_SPAREPART` boleh tulis sparepart tetapi **tidak boleh**
menghapus.

[FAKTA] Prefix route adalah `/api/spareparts` (dengan huruf **e**). Path
`/api/sparparts` tidak terdaftar dan akan mengembalikan 404.

---

## 9. Customer

| Method | Path | Otoritas |
|---|---|---|
| GET | `/api/customers` | token |
| POST | `/api/customers` | `CUSTOMER_WRITE` |
| GET | `/api/customers/{customer_id}` | token |
| PUT | `/api/customers/{customer_id}` | `CUSTOMER_WRITE` |
| DELETE | `/api/customers/{customer_id}` | `CUSTOMER_DELETE` |
| GET | `/api/customers/summary` | token |
| GET | `/api/customers/{customer_id}/detail` | token |

---

## 10. Dashboard, Periode, Laporan

| Method | Path | Otoritas |
|---|---|---|
| GET | `/api/overview` | token |
| GET | `/api/period` | token |
| GET | `/api/statistics/status` | token |
| GET | `/api/statistics/damage` | token |
| GET | `/api/laporan/bisnis` | `REPORT_FULL` |
| GET | `/api/laporan/investasi` | `REPORT_INVESTOR` |
| GET | `/api/laporan/export` | `REPORT_FULL` |

[FAKTA] `PENGELOLA` dan `INVESTOR` hanya boleh sampai sini - aksi tulis
ditolak blanket oleh `authority.can()`.

---

## 11. Notifikasi

| Method | Path | Otoritas |
|---|---|---|
| GET | `/api/notifications` | token |
| GET | `/api/notifications/events` | token |

[FAKTA] **Read-only.** Tidak ada endpoint kirim manual.

[FAKTA] Notifikasi adalah **outbox saja** - tidak ada kode pengiriman ke
Telegram atau WhatsApp di seluruh repo.

---

## 12. Header khusus

| Header | Dipakai di |
|---|---|
| `Authorization: Bearer` | Semua endpoint privat |
| `Idempotency-Key` | payments, kas transfer, kas close, refunds, inventory, expense_debt |

---

## 13. Kontrak error

| Kode | Arti |
|---|---|
| 401 | Token hilang, kedaluwarsa, atau akun nonaktif |
| 403 | Role tidak punya otoritas untuk action tersebut |
| 404 | Resource tidak ada **atau path salah** |
| 409 | Konflik - mis. periode sudah ditutup, key idempotency bentrok, klaim tidak memenuhi syarat |
| 422 | Validasi body gagal |

[TERKUNCI] Role tanpa otoritas **`ORDER_UPDATE_FINANCE`** tidak mendapat 403 -
nilainya **dipertahankan yang lama** dan field kiriman diabaikan.

> ⚠️ 403 berarti guard dievaluasi dan menolak. **404 tidak membuktikan
> penolakan akses** - kemungkinan besar path-nya salah sehingga guard tidak
> pernah dijalankan. Lihat [AGENTS.md](../AGENTS.md) bagian C5.

---

## 14. Verify sendiri

```powershell
# daftar route dari aplikasi nyata
cd backend
python -c "from main import app;[print(sorted(r.methods),r.path) for r in app.routes]"
```
