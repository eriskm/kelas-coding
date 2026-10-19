# BOSS SF — MODULES

> INDEX / PETA MODUL. Hemat token: tentukan modul → baca docs + source yang ditunjuk saja.
> Bukan dokumentasi teknis panjang. Source code tetap sumber kebenaran.

## 1. MODULE MAP

| Modul | Status | Frontend | Backend | Database | API Doc | Catatan |
| ----- | ------ | -------- | ------- | -------- | ------- | ------- |
| Authentication | REAL | Login overlay + session | `routers/auth.py` | `users`, `auth_tokens` | `API.md §3,§6` | Bearer 7 hari, tanpa role guard |
| Dashboard | PARTIAL | `pageDashboard` + chart | `routers/dashboard.py` | `service_orders` (hitung) | `API.md §7` | Hitung REAL, finansial/chart MOCK |
| Servis Baru | REAL | Modal `pageReceive` | `routers/orders.py` receive | `customers`, `service_orders` | `API.md §8` | Reuse customer by phone |
| History Cerdas | REAL | `#smartHistory` di Servis Baru | `routers/orders.py` history | `customers`, `service_orders` | `API.md §8` | `GET history/{phone}` |
| Transaksi | REAL | `pageTransaksi` paged | `routers/orders.py` list | `service_orders` (+join customer) | `API.md §8` | Detail/edit/delete belum dipakai UI |
| Pelanggan | REAL | `pagePelanggan` summary | `routers/customers.py` summary | `customers`, `service_orders` | `API.md §9` | Read-only summary |
| Sparepart | MOCK | `pageSparepart` + search lokal | BELUM ADA | BELUM ADA | `API.md §13` | `SP_MOCK` lokal |
| Garansi | MOCK | `pageGaransi` paged lokal | BELUM ADA | BELUM ADA | `API.md §13` | `GR_MOCK` lokal |
| Keuangan | MOCK | `pageKeuangan` in-memory | BELUM ADA | BELUM ADA | `API.md §13` | `KU_*`, hilang saat refresh |
| Kelola Akun | MOCK | `pageAkun` hardcode + modal | BELUM ADA | BELUM ADA (`users` ada tapi tak terhubung UI) | `API.md §13` | 5 baris hardcode |

## 2. MODULE → FILE MAP

### Authentication
```text
Docs: AI_CONTEXT.md §4,§6 / ARCHITECTURE.md §4 / DATABASE.md §4,§5 / API.md §3,§6 / FRONTEND.md §4
Frontend: frontend/index.html (loginScreen) + frontend/script.js (getToken/setToken/clearToken, apiGet/apiPost, checkSession, handleLogin/handleLogout/initLogin, showLogin/hideLogin/setAdminUI)
Backend: backend/routers/auth.py (login/logout/me, hash/verify, create_token) + backend/dependencies.py + backend/schemas.py (tidak ada schema auth di sini; LoginRequest/UserOut di auth.py)
Database: users + auth_tokens
```

### Dashboard
```text
Docs: API.md §7 / DATABASE.md §7,§8 / FRONTEND.md §5
Frontend: frontend/index.html (pageDashboard: starCards, quickActions, insightCards, chartStatusTransaksi, damageRank) + frontend/script.js (loadDashboard, renderStarCards, renderQuickActions, renderInsights, initCharts, renderStatusMini, renderDamageSection)
Backend: backend/routers/dashboard.py (get_overview, get_status_stats, get_damage_stats)
Database: service_orders (hitung status/payment/estimate)
```

### Servis Baru + History Cerdas
```text
Docs: API.md §8 / DATABASE.md §6,§7 / FRONTEND.md §8,§9
Frontend: frontend/index.html (pageReceive: rcName/rcPhone/rcDevice/rcPassword/rcDamage/rcPlan/rcEstimate/rcDp/rcTechnician/rcStatus, smartHistory) + frontend/script.js (openServisBaru/closeServisBaru, initReceivePage, loadSmartHistory)
Backend: backend/routers/orders.py (receive_unit, order_history, list_technicians) + backend/schemas.py (ServiceReceiveIn, ServiceOrderOut)
Database: customers + service_orders
```

### Transaksi
```text
Docs: API.md §8 / DATABASE.md §7,§8 / FRONTEND.md §6
Frontend: frontend/index.html (pageTransaksi: txBody/txEmpty/txLoading/txPagination) + frontend/script.js (renderTransaksi, loadTxPage, txStatusBadge/txDate/txLaba, txDetail=alert)
Backend: backend/routers/orders.py (list_orders, get_order, create_order, update_order, delete_order, latest_orders) + backend/schemas.py (ServiceOrderList/Page, ServiceOrderCreate/Update/Out)
Database: service_orders (+ customers via join)
```

### Pelanggan
```text
Docs: API.md §9 / DATABASE.md §6 / FRONTEND.md §7
Frontend: frontend/index.html (pagePelanggan: plBody/plEmpty/plLoading/plPagination) + frontend/script.js (renderPelanggan, loadPlPage, plRupiah)
Backend: backend/routers/customers.py (customer_summary, list/get/create/update/delete_customer) + backend/schemas.py (CustomerSummary/Page, CustomerOut/Create/Update)
Database: customers + service_orders (agregat)
```

### Sparepart (MOCK)
```text
Docs: FRONTEND.md §10 / API.md §13
Frontend: frontend/index.html (pageSparepart: spSearch/spBody) + frontend/script.js (SP_MOCK, spFiltered, renderSparepart, initSparepart, spEdit/spDel=alert)
Backend: BELUM ADA — jangan cari router sparepart
Database: BELUM ADA
```

### Garansi (MOCK)
```text
Docs: FRONTEND.md §11 / API.md §13
Frontend: frontend/index.html (pageGaransi: grBody) + frontend/script.js (GR_MOCK, renderGaransi, grStatusBadge)
Backend: BELUM ADA
Database: BELUM ADA
```

### Keuangan (MOCK)
```text
Docs: FRONTEND.md §12 / API.md §13
Frontend: frontend/index.html (pageKeuangan: kuKasBody/kuKasForm/kuDonut/kuAllocList/kuBody) + frontend/script.js (KU_KAS/KU_ALLOC/KU_RIWAYAT, renderKeuangan/renderBukuKas/renderAlloc/initProfitChart/initKuKasForm/renderRiwayat, kuEdit=alert)
Backend: BELUM ADA
Database: BELUM ADA
```

### Kelola Akun (MOCK)
```text
Docs: FRONTEND.md §13 / DATABASE.md §4 (users ada, tapi UI tak terhubung)
Frontend: frontend/index.html (pageAkun hardcode 5 baris + pageFormAkun modal) + frontend/script.js (showAkun/showFormAkun/openFormAkun/closeFormAkun)
Backend: BELUM ADA endpoint users
Database: users (tidak dibaca UI ini)
```

## 3. MODUL TRANSAKSI

```text
Transaksi
↓
FRONTEND.md §6 (kolom, pagination 10, txDetail=alert)
↓
API.md §8 → GET /api/orders (paged), GET/PUT/DELETE /{id} (belum dipakai UI)
↓
DATABASE.md §7,§8 → service_orders (+ customers join; status/estimate/payment)
↓
frontend/script.js → renderTransaksi, loadTxPage (+ txStatusBadge/txDate/txLaba)
↓
backend/routers/orders.py → list_orders (+ get/create/update/delete/latest)
↓
backend/schemas.py → ServiceOrderList/Page, ServiceOrderCreate/Update/Out
↓
backend/models.py → ServiceOrder (+ Customer relasi)
```

## 4. MODUL PELANGGAN

```text
Pelanggan
↓
FRONTEND.md §7 (summary read-only, paged 10)
↓
API.md §9 → GET /api/customers/summary (dipakai) + CRUD generik (belum dipakai)
↓
DATABASE.md §6 → customers + service_orders (count/max/terakhir)
↓
frontend/script.js → renderPelanggan, loadPlPage
↓
backend/routers/customers.py → customer_summary (+ list/get/create/update/delete)
↓
backend/schemas.py → CustomerSummary/Page, CustomerOut/Create/Update
↓
backend/models.py → Customer (+ ServiceOrder relasi)
```

## 5. MODUL SERVIS BARU

```text
Servis Baru (+ History Cerdas)
↓
FRONTEND.md §8,§9 (field rc*, status select 8 opsi, feedback no_servis)
↓
API.md §8 → POST /api/orders/receive + GET /api/orders/history/{phone} + GET /api/orders/technicians
↓
DATABASE.md §6,§7 → customers (reuse by phone) + service_orders (insert)
↓
frontend/script.js → initReceivePage, loadSmartHistory (change + keyup ≥4)
↓
backend/routers/orders.py → receive_unit, order_history, list_technicians
↓
backend/schemas.py → ServiceReceiveIn (+ ServiceOrderOut)
↓
backend/models.py → Customer + ServiceOrder
```

## 6. MODUL DASHBOARD

```text
Dashboard (PARTIAL: hitung REAL, finansial/chart MOCK)
↓
FRONTEND.md §5 (starCards/insight/chart/damageRank)
↓
API.md §7 → GET /overview (campur) + GET /statistics/status|damage (hardcode)
↓
DATABASE.md §7 → service_orders (total/done/active/pending/ready, sum payment)
↓
frontend/script.js → loadDashboard, renderStarCards, renderInsights, initCharts, renderStatusMini, renderDamageSection
↓
backend/routers/dashboard.py → get_overview, get_status_stats, get_damage_stats
```

## 7. MODUL MOCK

```text
Sparepart → frontend only (pageSparepart, SP_MOCK 14 + search lokal) → API BELUM ADA → database BELUM ADA
Garansi → frontend only (pageGaransi, GR_MOCK 14, paged lokal) → API BELUM ADA → database BELUM ADA
Keuangan → frontend only (KU_KAS 4 + KU_ALLOC 4 + KU_RIWAYAT 12, in-memory hilang saat refresh) → API BELUM ADA → database BELUM ADA
Kelola Akun → frontend only (5 baris hardcode + summary hardcode + form tanpa submit) → API BELUM ADA (users ada tapi tak dipakai UI ini)
```

Jangan desain DB/API baru di tahap mapping. Jika diminta fitur mock → baca `FRONTEND.md` section modul + verifikasi `routers/` + `models.py` bahwa memang BELUM ADA.

## 8. CROSS-MODULE DEPENDENCY

```text
Authentication (users/auth_tokens)
    ↓ gate semua API protected
Servis Baru (receive: cari/buat Customer → insert ServiceOrder)
    ↓
Customer (master) ←→ Service Order (transaksi, FK customer_id)
    ↓
Transaksi (list/join customer) → Pelanggan summary (agregat per customer)
    ↓
Dashboard (agregat service_orders: status/estimate/payment)
    ↓
Payments (anak ServiceOrder, cascade delete; ditulis via seed, tanpa UI/API mandiri)
```

Mock (Sparepart/Garansi/Keuangan/Akun) tidak punya dependency ke modul real — perubahan di sana tidak berdampak DB/API real, dan sebaliknya.

Dampak penting: ubah `service_orders` (kolom/status) → Transaksi + Pelanggan summary + Dashboard + Servis Baru + History ikut terdampak. Ubah `customers.phone` → receive + history + summary ikut terdampak. Ubah auth → semua modul protected ikut terdampak.

## 9. CHANGE IMPACT GUIDE

| Jika mengubah | Minimal cek |
| ------------ | ----------- |
| UI Transaksi | FRONTEND.md §6 + API.md §8 + `orders.py` + `schemas.py` (ServiceOrderList/Page) |
| Customer | FRONTEND.md §7 + API.md §9 + `customers.py` + `models.py` (Customer relasi) |
| Status Servis | FRONTEND.md §5,§6,§8 + API.md §7,§8 + DATABASE.md §8 + `orders.py` + `dashboard.py` |
| Database order | DATABASE.md §7,§10 + `models.py` + `schemas.py` + `orders.py` + FRONTEND.md §5-§8 |
| Login | API.md §3,§6 + `auth.py` + `dependencies.py` + FRONTEND.md §4 (auth storage) |
| Dashboard | FRONTEND.md §5 + API.md §7 + `dashboard.py` + DATABASE.md §7 |
| Servis Baru | FRONTEND.md §8,§9 + API.md §8 + `orders.py` receive/history + `schemas.py` ServiceReceiveIn |
| Modul mock | FRONTEND.md section modul saja + verifikasi `routers/`+`models.py` BELUM ADA (jangan baca DB/API real) |

## 10. TOKEN-EFFICIENT WORKFLOW

```text
USER REQUEST
↓
IDENTIFY MODULE (lihat §1)
↓
OPEN MODULES.md (§2-§9 untuk file + §11 untuk routing docs)
↓
FIND RELEVANT FILES
↓
READ ONLY RELEVANT DOCUMENTATION SECTION (bukan seluruh file docs)
↓
READ ONLY RELEVANT SOURCE CODE (fungsi/router/schema/tabel yang ditunjuk)
↓
UNDERSTAND DEPENDENCY (lihat §8-§9)
↓
CODE
↓
TEST
↓
UPDATE DOCUMENTATION IF STRUCTURE CHANGED
↓
GIT COMMIT
```

```text
JANGAN membaca seluruh project jika pekerjaan hanya menyentuh satu modul.
JANGAN membaca seluruh script.js jika hanya satu fungsi yang diperlukan.
JANGAN membaca seluruh backend jika hanya satu router yang relevan.
```

Contoh: request `ubah kolom tabel Transaksi` → MODULES §1 baris Transaksi → §3 → baca `FRONTEND.md §6` + `API.md §8` + `orders.py:list_orders` + `schemas.py:ServiceOrderList` saja.

## 11. DOCUMENTATION ROUTING RULE

### Jika masalahnya tentang:

**UI / tampilan** → FRONTEND.md

**API / request / response** → API.md

**Database / tabel / relasi** → DATABASE.md

**Hubungan sistem** → ARCHITECTURE.md

**Lokasi file/modul** → MODULES.md (file ini)

**Gambaran umum project** → AI_CONTEXT.md

## 12. SOURCE OF TRUTH

```text
MODULES.md = peta navigasi. Bukan sumber kebenaran implementasi.
```

Sumber kebenaran: `frontend/index.html` (UI), `frontend/script.js` (behavior), `backend/routers/*` (endpoint), `backend/schemas.py` (kontrak), `backend/models.py` + `servisku.db` (data).

Jika mapping di MODULES.md salah:
→ verifikasi source
→ update MODULES.md

## 13. LAST VERIFIED

* Tanggal: 2026-09-07 (UTC).
* Dokumentasi diperiksa: `AI_CONTEXT.md`, `ARCHITECTURE.md`, `DATABASE.md`, `API.md`, `FRONTEND.md` (header + section relevan).
* Source diverifikasi selektif: `frontend/script.js` (12 fungsi modul), `backend/routers/` (decorator + nama handler auth/dashboard/orders/customers), `docs/` inventory.
* Tidak ada source code yang diubah. Tidak ada database yang diubah. Tidak ada endpoint/fitur baru.
