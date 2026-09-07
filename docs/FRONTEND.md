# BOSS SF — FRONTEND

> Peta frontend AKTUAL BOSS SF agar Agent tidak perlu membaca seluruh `script.js` setiap kali.
> Source code frontend tetap sumber kebenaran behavior dan tampilan.

## 1. FRONTEND OVERVIEW

* **Teknologi aktual:** Vanilla HTML + CSS + JavaScript. Tanpa framework (tanpa React/Vue/Svelte), tanpa bundler, tanpa build system.
* **File utama:** `frontend/index.html` (struktur, ~984 baris), `frontend/script.js` (behavior, ~1570 baris), `frontend/style.css` (styling, ~1771 baris, header masih bertuliskan `ServisKu v3`).
* **Library/CDN yang benar-benar ditemukan di `index.html:8-12`:** `https://cdn.tailwindcss.com` (dengan `tailwind.config` inline: `darkMode: 'class'`, font `Inter`, warna `brand` merah), `https://cdn.jsdelivr.net/npm/apexcharts` (chart dashboard + donut keuangan), `https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css` (ikon), Google Fonts `Inter:wght@400;500;600;700;800`. CSS lokal `/static/style.css?v=10`.
* **Cara komunikasi dengan backend:** `fetch()` ke `API_BASE = '/api'` (`script.js:5`). Helper `apiGet(path)` (GET + Bearer otomatis, lempar `AuthError` saat 401) dan `apiPost(path, body)` (POST JSON + Bearer). Auth memakai `fetch` manual ke `/auth/login`, `/auth/me`, `/auth/logout`.
* **Tanpa build system:** file diserve langsung oleh FastAPI (`/` → `index.html`, `/static/*` → folder `frontend/`). Versi cache-busting manual via query `?v=10` pada `style.css`.
* **SPA / monolithic page:** Ya. Satu `index.html` memuat semua halaman sebagai `<div>/<section>` yang ditukar via class `hidden` (`pageDashboard/pageTransaksi/pagePelanggan/pageGaransi/pageSparepart/pageKeuangan/pageAkun`) + 2 modal floating (`pageReceive` Servis Baru, `pageFormAkun` Form Akun) + 1 overlay login (`loginScreen`).

## 2. FRONTEND STRUCTURE

```text
frontend/
├── index.html   # satu-satunya halaman: login overlay + app-window (title-bar, sidebar, topbar, content, status-bar, mobile nav) + 2 modal
├── script.js    # seluruh behavior: auth, navigasi, API helper, render per halaman, chart, form, state
├── style.css    # sistem styling: app-window, sidebar, panel, star-card, tx-table, float-window, qa-card, kpi-*, login-screen, dark mode, responsive
└── assets/
    ├── logo.png            # logo toko + favicon (/favicon.ico)
    ├── aksi-reference.png  # mockup desain, tidak dipakai logika
    ├── cekdeh.png          # mockup desain
    ├── jarak-reference.png # mockup desain
    ├── konten.png          # mockup desain
    ├── login-reference.png # mockup desain
    └── warna-reference.png # acuan warna KPI (hijau/biru/amber/dinamis/target)
```

Fungsi masing-masing: `index.html` = kerangka + ID; `script.js` = otak; `style.css` = kulit; `assets/logo.png` = identitas; `*-reference.png` = referensi desain saja.

## 3. PAGE / MENU INVENTORY

Terverifikasi dari nav sidebar (`index.html:129-168`), mobile nav (`:953-973`), section ID, dan fungsi `show*` di `script.js:117-123`.

| Menu/Halaman | Fungsi | Status | Data Source |
| ------------ | ------ | ------ | ----------- |
| Login (`loginScreen`) | Overlay login username+passcode | REAL | `POST /api/auth/login`, `GET /api/auth/me` |
| Dashboard (`pageDashboard`) | KPI, aksi cepat, insight, chart status + tren kerusakan | PARTIALLY REAL | `GET /overview` (hitung REAL + finansial MOCK), `GET /statistics/status|damage` (MOCK) |
| Servis Baru (`pageReceive` modal) | Form terima unit baru + History Cerdas | REAL | `POST /orders/receive`, `GET /orders/history/{phone}`, `GET /orders/technicians` |
| Transaksi (`pageTransaksi`) | Tabel seluruh order + pagination | REAL | `GET /orders?page&limit` |
| Pelanggan (`pagePelanggan`) | Master + ringkasan servis terakhir | REAL | `GET /customers/summary?page&limit` |
| Garansi (`pageGaransi`) | Tabel garansi + pagination lokal | MOCK / STATIC | `GR_MOCK` lokal di `script.js`, tanpa fetch |
| Sparepart (`pageSparepart`) | Tabel stok + search lokal | MOCK / STATIC | `SP_MOCK` lokal, tanpa fetch |
| Keuangan (`pageKeuangan`) | Buku kas + alokasi + riwayat + donut | MOCK / STATIC | `KU_KAS/KU_ALLOC/KU_RIWAYAT` in-memory, tanpa fetch |
| Kelola Akun (`pageAkun` + `pageFormAkun` modal) | Tabel akun hardcode + form tanpa backend | MOCK / STATIC | Hardcode di `index.html`, tanpa fetch |

Catatan inventory: sidebar desktop memuat 8 `data-page` (`dashboard, servisbaru, transaksi, pelanggan, garansi, sparepart, keuangan, akun`); mobile bottom nav hanya 6 (`dashboard, transaksi, pelanggan, sparepart, keuangan, akun` — tanpa Servis Baru dan Garansi); `VALID_PAGES` di JS hanya 6 (`dashboard, transaksi, pelanggan, garansi, sparepart, keuangan` — tanpa `servisbaru` dan `akun`). Ketiganya tidak konsisten — didokumentasikan apa adanya.

## 4. LOGIN / SESSION UI

Alur aktual:

```text
Login Form (#loginForm: #loginUsername + #loginPasscode + #rememberMe + #pwToggle + #forgotLink)
↓
username + passcode (validasi kosong di JS)
↓
POST /api/auth/login (handleLogin, loading Memeriksa... + spinner)
↓
token + user
↓
token disimpan (setToken: localStorage bsf_token jika remember else sessionStorage; setRemember; setSavedUsername/clearSavedUsername)
↓
masuk aplikasi (setAdminUI + hideLogin + showPage dashboard + loadDashboard)
↓
GET /api/auth/me (checkSession saat DOMContentLoaded / refresh)
```

Detail:
* **Form login:** `loginScreen` overlay dengan `#loginForm (novalidate, autocomplete off)`, `#loginError/#loginErrorText` untuk pesan, `#loginBtn/#loginBtnText/#loginBtnIcon` dengan state loading.
* **Remember Me:** checkbox `#rememberMe` (default checked). `getRemember/setRemember` via `localStorage bsf_remember`. Menentukan `localStorage` vs `sessionStorage` untuk token + simpan/hapus username.
* **Penyimpanan session/token:** `getToken()` baca `localStorage bsf_token || sessionStorage bsf_token`; `setToken(t, remember)`; `clearToken()` hapus keduanya; `bsf_username`, `bsf_remember`, `bsf_page` di `localStorage`.
* **Session check:** `checkSession()` saat boot: jika ada token → `fetch /auth/me` → sukses return user else `clearToken()` + return null. Boot: jika user → `setAdminUI + hideLogin + loadDashboard + navigateTo(hash/saved)` else `showLogin()`.
* **Logout:** `handleLogout` (klik `#logoutLink`): `POST /auth/logout` diabaikan errornya → `clearToken + remove bsf_page + history.replaceState + location.reload()`.
* **Redirect saat session invalid:** `apiGet/apiPost` lempar `AuthError` saat 401; pemanggil dashboard/transaksi/pelanggan tidak menangani khusus selain log — sesi invalid efektif memaksa login ulang via `checkSession` berikutnya / reload. `showLogin/hideLogin` toggle overlay vs app.
* **User information:** `setAdminUI(user)` mengisi `#adminName` + sapaan topbar (default teks `Admin`). Tidak ada avatar/role dinamis selain itu.
* **Lupa Password:** `#forgotLink` hanya tampilkan error `Hubungi administrator untuk mereset passcode.` (mock, tanpa API).
* **Caps-lock warning:** `#capsWarn` muncul saat Caps Lock aktif di field passcode (`getModifierState`, sembunyi saat blur).
* **Status server + versi:** pill `#serverStatus` di bawah tombol Login (`HEAD /` timeout 5 dtk via `checkServer()` saat init — hijau terhubung / merah tidak terjangkau); footer `v1.0.0`.
* Credential aktual tidak ditulis di sini.

## 5. DASHBOARD UI

Struktur `pageDashboard`: grid `#starCards` (5 kartu), grid `#quickActions` + `#insightCards`, grid chart status (`#statusRange` select periode + `#chartStatusTransaksi` + `#statusMiniGrid` 10 kartu + `#insightStatus` AI) dan tren kerusakan (`#damageRank` + `#damageHighlight` + `#insightDamage` + tombol Detail → `showTransaksi()`).

Hubungan:

```text
Dashboard UI (#starCards, #insightCards, chart, #damageRank)
↓
loadDashboard → renderStarCards + renderQuickActions + renderInsights + initCharts → renderStatusMini + renderDamageSection
↓
GET /overview (dipanggil 3x: starCards, insights, statusMini), GET /statistics/status, GET /statistics/damage
↓
response (hitung REAL + finansial/chart MOCK)
↓
render UI (innerHTML kartu + ApexCharts line/bar + mini grid + banner)
```

* **KPI/star cards:** `renderStarCards()` baca `data.star_cards[5]`, styling via `STAR_META` (emoji+tint, acuan `warna-reference.png`), format `kpiRupiah` (`Rp en-US`), kartu ke-5 (Target Gaji) hitung `kurang = target - bersih` lokal.
* **Insight:** `renderInsights()` baca `data.insight[4]` (Unit Masuk/Selesai/Cash/Pending).
* **Chart:** `initCharts()` (Statistik Status Transaksi: ApexCharts smooth area 10 status dummy `STATUS_TX_DUMMY` + marker diskrit per status + data label angka, tanpa fetch — ref `statistic-reference.png`), `renderDamageSection()` (horizontal bar gradasi dari `/statistics/damage`; bar + kartu highlight bisa diklik → Transaksi terfilter damage via `goDamageFilter()`), `renderStatusMini()` (10 kartu `STATUS_TX_DUMMY`, total 21, persen dari total + banner Insight AI), `updateChartTheme()` + `getChartHeight/getCommonOpts/chartGridColor/isDark` untuk dark mode.
* **Status mini:** 10 kartu status (Analisa 3, Konfirmasi 1, Wait Part 3, Repair 6, Done 6, Failed 1, Garansi 1, Refund/Cancel/Cash 0) + Insight AI (status dominan). Grid 4 kolom desktop / 2 kolom mobile.
* **Data API vs dummy:** hitung order (`total/done/active/pending/ready`, `omset`, insight) REAL dari `service_orders`; `laba_kotor/total_beban/bersih/target_gaji`, seluruh series status dan damage MOCK hardcode backend.
* **Fungsi terkait:** `loadDashboard, renderStarCards, renderQuickActions, renderInsights, initCharts, renderStatusMini, renderDamageSection, damageIcon, updateChartTheme, formatRupiah/kpiRupiah, isDark/chartGridColor`.

## 6. TRANSAKSI UI

* **Tabel transaksi:** `pageTransaksi` → `txBody` dengan kolom aktual No, Tanggal, Device, User/WA, Status, Kerusakan, Perbaikan, Teknisi, Laba (kanan), Aksi (tengah). Badge via `txStatusBadge(status)`, tanggal via `txDate(d)`, laba via `txLaba(o)` + `plRupiah`-sejenis.
* **Kolom yang ditampilkan:** sesuai header `index.html:293-303`. `Perbaikan` berasal dari `repair_plan`, `Laba` turunan estimate/payment (bukan tabel payments).
* **Pagination:** backend-side. `TX_PER_PAGE = 10`, state `_txPage/_txTotal/_txTotalPages/_txReq` (guard race). `renderTransaksi()` → `loadTxPage(1)`; `loadTxPage(page)` → `apiGet('/orders?page&limit')` → render baris + `txInfo` (`Halaman p start - end (dari N transaksi)`) + tombol `txPageBtns` (← Sebelumnya, nomor, Berikutnya →). `txPagination` disembunyikan jika total ≤ 10. `txLoading/txEmpty` untuk loading/kosong/gagal (`Gagal memuat data.`).
* **Search/filter:** ADA frontend-only. `#txSearch` (teks, debounce 300ms) + `#txDateFilter` (label Tanggal terlihat). Saat filter aktif → `loadTxFiltered()` ambil `/orders/latest?limit=500` lalu saring lokal; bar info pagination ditampilkan (`N hasil filter`, tanpa tombol halaman). Tanpa filter → `loadTxPage()` paged backend normal. Tanpa perubahan backend.
* **Action button:** kolom Aksi per baris (tombol view) memanggil `txDetail(id)`; header kanan sebaris `.tx-toolbar`: search + date + tombol Servis Baru → `showServisBaru()`.
* **Detail/edit/delete:** BELUM ADA sebagai fitur. `txDetail(id)` hanya `alert('Detail transaksi #' + id + ' (belum diimplementasikan)')`.
* **API yang dipanggil:** hanya `GET /orders?page&limit`.
* **Fungsi terkait:** `showTransaksi, renderTransaksi, loadTxPage, txStatusBadge, txDate, txLaba, txDetail`.

Yang berjalan vs placeholder: list + pagination REAL; search, detail, edit, hapus masih placeholder/mock.

## 7. PELANGGAN UI (tahap UI: dummy data)

* **Tabel pelanggan:** `pagePelanggan` → `plBody` kolom No (urut, bukan ID), Nama Konsumen, No. WhatsApp, Device Terakhir, Tindakan Terakhir, Harga Terakhir (kanan), Total Servis (tengah, `N×`), Terakhir Servis (tanggal), Aksi (tengah, tombol Lihat Histori). Sumber `PL_DUMMY` 12 pelanggan di `script.js` — 1 record per pelanggan, backend (`GET /customers/summary`) diintegrasikan tahap berikutnya.
* **Pagination:** lokal, `PL_PER_PAGE = 10` (12 data → 2 halaman), info `Halaman p start - end (dari N pelanggan)`, tombol Sebelumnya/nomor/Berikutnya. Styling/pagination sama seperti sebelumnya.
* **Lihat Histori:** tombol per baris → `plHist(idx)` buka modal `pageHistory` (draggable, bisa tutup): ringkasan kartu `renderCustSummary` + tabel riwayat `plHistBody` (No, No. Servis, Tanggal, Device, Tindakan, Harga, Status). `closePlHist()` menutup. Index mengikuti hasil filter (`_plView`).
* **Search:** ADA lokal (`#plSearch`, debounce 300ms): cocokkan Nama / WA (+ device/tindakan). Filter tanggal `#plDateFilter` cocokkan Terakhir Servis (`c.last`). Pagination + histori mengikuti hasil filter. **Summary vs history:** tabel = ringkasan per customer; modal = seluruh riwayat transaksi customer tersebut (dari `c.hist` dummy).

## 8. SERVIS BARU UI

Alur aktual:

```text
Buka Servis Baru (openServisBaru/showServisBaru: tampilkan modal #pageReceive + init dropdown teknisi)
↓
Input customer (#rcName required, #rcPhone opsional → picu History Cerdas)
↓
Input device (#rcDevice required, #rcPassword opsional)
↓
Input kerusakan (#rcDamage textarea) + rencana perbaikan (#rcPlan textarea)
↓
Input estimasi / DP (#rcEstimate/#rcDp number ≥0) + pilih teknisi (#rcTechnician) + status awal (#rcStatus)
↓
Submit (#receiveForm → #receiveSubmitBtn, teks Menyimpan...)
↓
POST /api/orders/receive (apiPost)
↓
Transaksi diperbarui (feedback sukses + reset form; user buka Transaksi manual untuk melihat)
```

* **Field form (sesuai `index.html`, tanpa karangan):** `rcName*` (text), `rcPhone*` (text, `inputmode tel` — terima format WA bebas, normalisasi di tahap backend), `rcDevice*` (text), `rcPassword` (type password + eye toggle `rcPwToggle`, default tersembunyi), `rcImei` (opsional, UI-only, belum dikirim ke API), `rcDamage*` (textarea rows 2, full-width), `rcPlan` (textarea rows 2, full-width, label Rencana Tindakan Perbaikan), `rcEstimate` (number Rp), `rcDp` (number Rp), `rcTechnician` (select, opsi diisi JS + default `— Pilih Teknisi —`), `rcStatus` (select 8 opsi aktual — catat berbeda dengan status backend; didokumentasikan apa adanya), checklist UI-only `rcCheckLcd/Frame/Camera/Button/Charging/Kit` (belum tersimpan ke DB).
* **Progress stepper:** `#rcSteps` 4 step (Data Konsumen → Diagnostik → Estimasi & Penugasan → Siap Eksekusi), status aktif (merah brand + pulse) / done (hijau ✓) / pending via `updateReceiveSteps()` dari kelengkapan field. Step 4 ikut done (hijau) sesaat setelah simpan sukses. Label tampil juga di layar kecil (scroll horizontal).
* **Tombol utama:** `.rc-submit` sticky di bawah modal (tetap terlihat saat scroll) + teks responsif via `receiveSubmitText`/`receiveFeedback`.
* **Shortcut:** `initReceiveShortcuts()` aktif saat modal terbuka — Enter pindah kolom, F2 focus Nama, F4 focus Device, F8/Ctrl+S submit (baris F8 di-highlight `is-primary`).
* **Layout:** `#pageReceive` lebar max 1100px, grid `.rc-layout` (main + side 300px Histori/Shortcut), stack <900px.
* **Validasi frontend (syarat simpan):** `required` HTML pada Nama + WA + Device + Analisa Kerusakan, `type=number min=0` pada nominal, trim + `parseFloat(...)||0` di JS. Stepper ikut syarat yang sama. Backend masih opsional untuk WA/damagetype — pengetatan backend tahap berikutnya. Tidak ada validasi pola WA, maks panjang, atau DP ≤ estimasi.
* **API:** `POST /orders/receive` via `apiPost` dengan payload `{customer_name, customer_phone, device, device_password, damagetype, repair_plan, estimate, dp, technician, status}` (`script.js:1512-1523`).
* **Response:** `ServiceOrderOut` (`res.no_servis` ditampilkan).
* **UI setelah berhasil:** `#receiveFeedback.success` (`Unit berhasil didaftarkan! No. Servis: <b>...`), `form.reset()`, sembunyikan `smartHistory`. Modal tetap terbuka (tidak auto-close/redirect).
* **Error handling:** `#receiveFeedback.error` tampilkan `err.message` (dari `detail` backend atau HTTP status). Tombol dikembalikan ke teks semula via `finally`.
* **Fungsi:** `openServisBaru, showServisBaru, closeServisBaru, initReceivePage, loadSmartHistory`.

## 9. HISTORY CERDAS

* **Tujuan:** tampilkan riwayat servis konsumen sebelumnya saat mengetik WA di Servis Baru (panel `#smartHistory` + `#smartHistoryList`, subjudul `Nomor WhatsApp dipakai untuk History Cerdas`).
* **Input pencarian:** `#rcPhone` (pemicu: `change` + `keyup` ≥4 char) dan `#rcName` (hanya tampilkan hint bila WA kosong, tanpa query). Panel `#smartHistory` selalu tampil di kolom samping dengan badge `#smartHistoryState` (Kosong/Mencari/Ditemukan N/Baru/Gagal).
* **API yang dipanggil:** `GET /api/orders/history/{phone}` via `apiGet` dengan `encodeURIComponent(phone)` (`loadSmartHistory`, ada guard hasil basi). Integrasi real yang sudah ada dipertahankan — tahap ini tidak menambah/mengubah backend.
* **Response:** list order (bisa `[]`). `no_servis, status, device, model, created_at, estimate` dipakai render.
* **Data yang ditampilkan (Customer Found):** kartu ringkasan `renderCustSummary` (Nama, WA, Total Servis, Device Terakhir, Perbaikan Terakhir, Harga Terakhir) + maksimal 3 baris `history-item` via `historyItemsHtml`. Sumber: API real bila ada baris (ringkasan dihitung dari `rows[0]`), else `HISTORY_DUMMY` 2 entri (cocok by normalisasi WA), else New Customer. Kosong → hint; gagal → pesan error. Badge `#smartHistoryState`.
* **Fungsi JS:** `loadSmartHistory` (dipanggil dari `initReceivePage`).

## 10. SPAREPART UI

```text
UI EXIST
API BELUM ADA
DATABASE BELUM ADA
DATA MOCK/LOCAL
```

* **List:** `pageSparepart` → `spBody` kolom aktual No, Tgl Masuk, Kategori, Merek, Jenis Barang, Device, Qty (tengah), Beli (kanan), Jual (kanan), Aksi (tengah). Data `SP_MOCK` 14 item — in-memory (tambah/edit/hapus lokal, hilang setelah refresh), backend tahap berikutnya.
* **KPI:** `#spKpi` 4 kartu (Total Item, Stok Habis, Stok Menipis, Nilai Stok) via `renderSpKpi()`.
* **Search:** `#spSearch` + debounce 300ms (pola sama dengan Transaksi/Pelanggan/Garansi).
* **Tambah/edit/hapus:** tombol Tambah + modal `pageSpare` (`spAdd/closeSpare`, validasi Jenis wajib); `spEdit(i)` prefill modal; `spDel(i)` konfirmasi `confirm()` lalu hapus.
* **Search:** ADA lokal. `#spSearch` (`Cari jenis, merek, device, kategori...`) → state `_spQuery` → `spFiltered()` (match case-insensitive pada 4 field) → `renderSparepart()`. Debounce 300ms; pagination direset ke 1.
* **Stok:** `spQtyCell(qty)`: `0 → Habis` (merah), `≤5 → Menipis` (kuning + angka), `>5 → ok`. Rupiah via `spRupiah` (`id-ID/IDR`).
* **Tambah/edit/hapus:** in-memory via modal (lihat di atas). `txDetail` Transaksi masih `alert`.
* **Pagination lokal:** `SP_PER_PAGE = 10`, `_spPage`, info `Halaman p start - end (dari N sparepart)`, tombol Sebelumnya/nomor/Berikutnya. `spEmpty/spLoading/spPagination/spInfo/spPageBtns` dikelola manual.
* **Fungsi:** `spRupiah, spQtyCell, spEdit, spDel, spFiltered, renderSparepart, initSparepart, showSparepart`.

## 11. GARANSI UI (tahap UI: dummy data)

* **Tabel:** `pageGaransi` → `grBody` kolom No (urut), Nama User, Device, Tgl Mulai, Tgl Akhir, Status (badge + sisa hari), Aksi (Detail + Klaim). Sumber `GR_MOCK` 14 entri kaya (nama, WA, device, tanggal, kerusakan, tindakan, harga, klaim) — backend diintegrasikan tahap berikutnya.
* **Search/filter lokal:** `#grSearch` (Nama/WA/Device, debounce 300ms, compact) + `#grDateFilter` (tampilkan garansi yang berlaku pada tanggal itu) + `#grStatusFilter` (Aktif/Akan Berakhir/Expired/Klaim). Pagination mengikuti hasil filter.
* **KPI:** `#grKpi` 5 kartu (Total slate, Aktif hijau, Akan Berakhir amber, Expired merah, Klaim biru), dihitung dari seluruh data (bukan hasil filter). Grid 5 kolom desktop.
* **Filter:** search + `#grDateFilter` (hint tertulis: menampilkan garansi yang aktif pada tanggal tersebut) + `#grStatusFilter`.
* **Status derivasi:** `grState()` — Klaim bila ada klaim berjalan; else dari tanggal: Expired (<0 hari), Akan Berakhir (≤30 hari), Aktif. Badge `gr-aktif/gr-segera/gr-berakhir/gr-klaim` + teks sisa (`Aktif · N hari lagi`).
* **Detail:** `grDetail()` modal `pageWarranty` (ringkasan + servis sebelumnya: no. servis, tanggal, kerusakan, tindakan, nilai + panel klaim berjalan bila ada).
* **Klaim:** `grClaim()` modal `pageClaim` (identitas readonly + keluhan required + tgl/tindakan/status) → submit simpan in-memory ke entri (`g.klaim`), status jadi Klaim, tabel + KPI refresh. Hilang saat refresh.
* **Fungsi:** `grState, grDaysLeft, grFiltered, initGrToolbar, renderGrKpi, grDetail/closeGrDetail, grClaim/closeGrClaim, initClaimForm, renderGaransi`.

## 12. KEUANGAN UI

```text
UI vs API vs DATABASE: UI lengkap, API BELUM ADA, DATABASE BELUM ADA.
Data hanya di JavaScript/in-memory dan hilang setelah refresh — ditulis eksplisit.
```

* **Kas (Buku Kas):** `kuKasBody` kolom Uraian, Debit (tengah), Kredit (tengah), Saldo (kanan). Sumber `KU_KAS` 4 baris awal + tambah via form (in-memory). Ringkasan `#kuKasSummary` 3 kartu (Total Masuk hijau, Total Keluar merah, Saldo Kas biru) dihitung di `renderBukuKas()`.
* **Form tambah kas:** `#kuKasForm` (`kuKasJenis`, `kuKasKategori` 6 opsi, `kuKasNominal`) push ke `KU_KAS` + refresh tabel + ringkasan. Tanpa validasi saldo minus, tanpa persistensi.
* **Riwayat:** `kuBody` + toolbar (`#kuSearch` debounce 300ms, `#kuJenisFilter`, `#kuDateFilter`) → `kuFiltered()` + pagination mengikuti hasil. Edit via modal `pageKeu` (`kuEdit` prefill, `initKeuForm` simpan), hapus via `confirm` (`kuDel`) — in-memory.
* **Alokasi:** `#kuAllocList` + donut `#kuDonut` — klik potongan donut highlight baris alokasi (`dataPointSelection` → `_kuSelAlloc` → `is-sel`).
* **Form transaksi:** `#kuKasForm` dengan `#kuKasJenis` (`Masuk` default / `Keluar`), `#kuKasKategori` (6 opsi aktual: `Penjualan Service` default, `Modal Part`, `Modal Jasa`, `Beban Gaji`, `Beban Operasional`, `Lainnya`), `#kuKasNominal` (number ≥1 required). Submit `initKuKasForm()` push ke `KU_KAS` (`uraian=kategori, debit/kredit, saldo=last±nominal`) + `renderBukuKas()` + kosongkan nominal. Tanpa validasi saldo minus, tanpa persistensi.
* **Alokasi:** `#kuAllocList` + `#kuTotalProfit` (tetap `6250000`) dari `KU_ALLOC` 4 item aktual (`Bonus Karyawan 10% #f59e0b, Pengelola 30% #dc2626, Investor 30% #2563eb, Kas Aset 30% #16a34a`). Render `renderAlloc()` hitung nominal = total×pct.
* **Riwayat:** `kuBody` kolom No, Tanggal, Jenis, Kategori, Keterangan, Nominal (kanan), Aksi (tengah). Sumber `KU_RIWAYAT` 12 baris + tambah via form kas? Tidak — riwayat dan kas array terpisah (keduanya in-memory). Render `renderRiwayat()` + filter `kuFiltered()`. Edit/hapus fungsional lokal (lihat di atas). Pagination `kuPagination/kuInfo/kuPageBtns`, `KU_PER_PAGE = 10`.
* **Chart:** `#kuDonut` ApexCharts donut (`initProfitChart`, tinggi 200, tanpa legend, label %, dark/light aware, instance `_profitChart` di-update temanya saja).
* **Fungsi:** `showKeuangan, renderKeuangan, renderBukuKas, renderAlloc, initProfitChart, initKuKasForm, renderRiwayat, kuRupiah, kuEdit`.

## 13. KELOLA AKUN UI (tahap UI: dummy in-memory, backend tahap berikutnya)

* **Daftar akun:** `pageAkun` → `tbody#akBody` dirender dari `AKUN_DUMMY` 5 akun (nama, username, role, status, login terakhir) via `renderAkun()`. Kolom No (urut), Nama, Username, Role (badge), Status (badge), Terakhir Login, Aksi (edit + hapus).
* **Summary:** `#akTotal/akAktif/akAdmin` dihitung otomatis dari data (bukan hardcode).
* **Search/filter fungsional:** `#akSearch` (debounce, Nama/Username) + `#akRoleFilter` + `#akStatusFilter` → `akFiltered()`; info `#akInfo` (`N dari M akun (filter)`).
* **Form:** modal `pageFormAkun` (`akNama*/akUsername*/akPassword/akRole/akStatus`) — tambah (`showFormAkun` reset mode) + edit prefill (`akEdit`, judul jadi Edit Akun) + hapus `confirm` (`akDel`); validasi username unik lokal. Submit tutup modal + refresh tabel. In-memory, hilang setelah refresh. Tidak ada `GET/POST /api/users`.

## 14. FRONTEND STATE

State yang benar-benar ditemukan (tanpa karangan):

* **current page:** `localStorage bsf_page` + `location.hash (#/...)` + `VALID_PAGES`. Helper `pageFromHash/savePage/getSavedPage/navigateTo/showPage/setActiveNav`. `hashchange` listener navigasi jika sudah login.
* **current user:** variabel implisit via `setAdminUI(user)` → DOM `#adminName` + sapaan. Tidak ada store user global selain hasil `checkSession`.
* **token:** `localStorage bsf_token` (remember) atau `sessionStorage bsf_token` + `bsf_remember`, `bsf_username`. Helper `getToken/setToken/clearToken/getSavedUsername/setSavedUsername/clearSavedUsername/getRemember/setRemember`.
* **transaction page:** `_txPage/_txTotal/_txTotalPages/_txReq` + `TX_PER_PAGE=10`.
* **customer page:** `_plPage/_plTotal/_plTotalPages/_plReq` + `PL_PER_PAGE=10`.
* **garansi/sparepart/keuangan page:** `_grPage (+GR_PER_PAGE)`, `_spPage/_spQuery (+SP_PER_PAGE)`, `_kuPage (+KU_PER_PAGE) + _profitChart`.
* **mock data:** `GR_MOCK/SP_MOCK/KU_KAS/KU_ALLOC/KU_RIWAYAT/TECHNICIANS` (backend) sebagai konstanta JS.
* **selected menu:** class `active` pada `.nav-link/.mobile-nav-item` via `setActiveNav`.
* **modal state:** terbuka/tutup via `openServisBaru/closeServisBaru/openFormAkun/closeFormAkun` + draggable `makeFloatDraggable/initFloatDrag` (posisi via DOM, tidak dipersist).
* **filter/search state:** hanya `_spQuery` dari `#spSearch` (sparepart). Transaksi/pelanggan/garansi/keuangan/akun tanpa state filter.
* **theme/clock/sidebar:** `documentElement.classList dark` (`initTheme` + toggle `#toggleTheme`), `updateClock` interval 1 detik → `#currentTime/#currentDate`, `toggleSidebar(open)` → `#appSidebar.open + #sidebarOverlay.show` (mobile).
* **DOM state:** `hidden` pada page/modal/empty/loading/pagination, `innerHTML` tabel/chart/history, `disabled` tombol submit saat loading, `dataset.bound` untuk cegah double-bind form kas.

## 15. FRONTEND API MAP

### API yang digunakan frontend (terverifikasi `script.js`)

| Fungsi Frontend | API | Method | Tujuan |
| --------------- | --- | ------ | ------ |
| renderStarCards | /overview | GET | Kartu KPI |
| renderInsights | /overview | GET | Insight Unit |
| renderStatusMini | /overview | GET | Mini status |
| initCharts (status) | /statistics/status | GET | Line chart 7 hari |
| renderDamageSection | /statistics/damage | GET | Bar kerusakan |
| loadTxPage | /orders?page&limit | GET | Tabel transaksi paged |
| loadPlPage | /customers/summary?page&limit | GET | Tabel pelanggan paged |
| checkSession | /auth/me | GET | Validasi sesi boot |
| handleLogin | /auth/login | POST | Login |
| handleLogout | /auth/logout | POST | Logout |
| loadSmartHistory | /orders/history/{phone} | GET | History Cerdas |
| initReceivePage | /orders/technicians | GET | Dropdown teknisi |
| submit receiveForm | /orders/receive | POST | Daftarkan unit |

### API yang tersedia tetapi belum digunakan frontend (lihat `docs/API.md`)

`GET /orders/latest`, `POST /api/orders`, `GET /api/orders/{id}`, `PUT /api/orders/{id}`, `DELETE /api/orders/{id}`, `GET /api/customers`, `GET /api/customers/{id}`, `POST /api/customers`, `PUT /api/customers/{id}`, `DELETE /api/customers/{id}`. Belum ada pemanggilan di `script.js` saat dokumentasi dibuat.

## 16. JAVASCRIPT FUNCTION MAP

Fokus pada fungsi penting (nama sesuai source):

| Function | Fungsi | Halaman/Modul | API terkait |
| -------- | ------ | ------------- | ----------- |
| getToken/setToken/clearToken/getSavedUsername/setSavedUsername/getRemember/setRemember | Auth storage | Auth | — |
| apiGet/apiPost, AuthError | API helper + 401 handling | Global | Semua /api |
| toggleSidebar, setActiveNav, pageFromHash/savePage/getSavedPage/navigateTo/showPage | Navigasi + hash + persist page | Global | — |
| showDashboard/showTransaksi/showPelanggan/showGaransi/showSparepart/showKeuangan/showAkun/showServisBaru/showFormAkun | Entry per halaman | Nav | — (yang fetch di render) |
| openServisBaru/closeServisBaru/openFormAkun/closeFormAkun/makeFloatDraggable/initFloatDrag | Modal floating + drag | Servis Baru/Akun | — |
| updateClock, initTheme, isDark, toggleTheme (via listener) | Clock + dark mode | Topbar | — |
| formatRupiah/kpiRupiah/plRupiah/spRupiah/kuRupiah, escapeHtml, txDate | Format + sanitasi | Global | — |
| renderStarCards, renderQuickActions, renderInsights | KPI + aksi + insight | Dashboard | /overview |
| getChartHeight/getCommonOpts/chartGridColor/initCharts/updateChartTheme/renderStatusMini | Chart status | Dashboard | /overview, /statistics/status |
| renderDamageSection/damageIcon | Tren kerusakan | Dashboard | /statistics/damage |
| initNav, showLogin/hideLogin/setLoginError/clearLoginError/setAdminUI | Nav + login UI | Auth/UI | — |
| checkSession/handleLogin/handleLogout/initLogin | Session + login/logout | Auth | /auth/me, /auth/login, /auth/logout |
| loadDashboard | Orkestrasi dashboard | Dashboard | (di atas) |
| txStatusBadge/txLaba/renderTransaksi/loadTxPage/txDetail | Tabel + pagination transaksi | Transaksi | /orders |
| grStatusBadge/renderGaransi | Tabel garansi mock | Garansi | — |
| loadPlPage/renderPelanggan | Tabel pelanggan paged | Pelanggan | /customers/summary |
| spQtyCell/spFiltered/renderSparepart/initSparepart/spEdit/spDel | Stok + search mock | Sparepart | — |
| renderKeuangan/renderBukuKas/renderAlloc/initProfitChart/initKuKasForm/renderRiwayat/kuEdit | Kas + alokasi + riwayat mock | Keuangan | — |
| loadSmartHistory/initReceivePage | History + submit servis baru | Servis Baru | /orders/history/{phone}, /orders/technicians, /orders/receive |

Fungsi kecil lain (clock, emoji meta, dsb.) tidak dipetakan agar dokumen tetap menjadi peta, bukan salinan file.

## 17. CSS / UI SYSTEM

* **`style.css`:** ~1771 baris, sistem custom: `app-window` (mode desktop rounded + shadow di `sm/md`, dark `#111118`), `title-bar` (desktop only), `sidebar` + `sidebar-overlay` (mobile drawer), `topbar`, `panel`, `star-card/kpi-*` (solid + target), `qa-card`, `metric-row`, `tx-table` (+ varian `pl/sp/gr/cash-table`), `tx-status/gr-aktif/gr-segera/gr-berakhir/qty-*`, `float-window` (titlebar/body/receive-panel/history), `login-screen` (blob + card + field + btn + social disabled), `mobile-nav`, `status-bar`, scrollbar custom, dark mode via `.dark`.
* **Tailwind CDN:** dipakai untuk layout/spacing/typography responsif (`sm:/md:/lg:` grid, `hidden`, flex). Config inline tambah `brand` merah (`500 #dc2626` dominan) + `darkMode: 'class'`.
* **Font:** `Inter` (400–800) sebagai `font-sans` global.
* **Icon library:** Font Awesome 6.5.1 (`fa-solid/fa-regular/fa-brands`).
* **Chart library:** ApexCharts (line area status + bar kerusakan + donut alokasi profit; height adaptif; theme dark/light manual).
* **CSS custom:** melengkapi Tailwind untuk komponen khas (kartu KPI, tabel, modal, login) + state (`active/disabled/hidden/success/error`).
* **Responsive behavior:** mobile-first. HP: fullscreen, hamburger + overlay sidebar, bottom nav, topbar ringkas (tanggal/cuaca disembunyikan), status-bar + title-bar disembunyikan. `sm+`: app-window mengambang rounded, sidebar permanen, topbar penuh. `lg`: grid 5 kolom star cards, 2 kolom dashboard/keuangan.

## 18. REAL VS MOCK MAP

Terverifikasi dari `index.html` + `script.js` + `docs/API.md` (bukan asumsi):

| Modul | UI | API | Database | Status |
| ----- | -- | --- | -------- | ------ |
| Login | ✓ | ✓ | ✓ | REAL |
| Dashboard | ✓ | ✓ (campur) | sebagian | PARTIAL (hitung REAL, finansial/chart MOCK) |
| Servis Baru | ✓ | ✓ | ✓ | REAL |
| Transaksi | ✓ | ✓ | ✓ | REAL (list; detail/edit/delete placeholder) |
| Pelanggan | ✓ | ✓ | ✓ | REAL (summary read-only) |
| History Cerdas | ✓ | ✓ | ✓ | REAL (bagian Servis Baru) |
| Garansi | ✓ | ✗ | ✗ | MOCK |
| Sparepart | ✓ | ✗ | ✗ | MOCK |
| Keuangan | ✓ | ✗ | ✗ | MOCK (in-memory, hilang saat refresh) |
| Kelola Akun | ✓ | ✗ | ✗ | MOCK (hardcode HTML) |

## 19. FRONTEND LIMITATIONS / TECHNICAL DEBT

Temuan terverifikasi, tanpa perbaikan:

* `script.js` monolit ~1570 baris tanpa modul/build/test; `index.html` ~984 baris satu file; pencarian fungsi mengandalkan peta section 16.
* Banyak mock data: `GR_MOCK/SP_MOCK/KU_KAS/KU_ALLOC/KU_RIWAYAT` + finansial/chart dashboard + tabel akun + status-bar (`Servis aktif: 48, Teknisi: 4`) + badge notifikasi (`3`) + cuaca (`32°C`) hardcode.
* Tombol belum implementasi: `txDetail`, `spEdit/spDel`, `kuEdit` hanya `alert`; tombol sosial login `disabled`; Quick Actions selain Servis Baru tanpa aksi; filter akun tanpa handler; pagination akun hardcode.
* API tersedia tetapi belum dipanggil UI: 10 endpoint (lihat section 15) — risiko fitur setengah jalan (CRUD generik, latest, detail/update/delete).
* State masih in-memory/DOM: keuangan hilang saat refresh; posisi modal tidak persist; tidak ada store global.
* Tanpa component framework: duplikasi pola tabel/pagination per halaman (`tx/pl/gr/sp/ku` masing-masing punya handler sendiri).
* Inkonsistensi aktual: `VALID_PAGES` vs sidebar vs mobile nav (lihat section 3); opsi `rcStatus` (ANALISA/KONFIRMASI/WAIT PART/REPAIR/DONE/CASH/FILED/CANCEL) vs status backend (RECEIVED/ANALISA/DIAGNOSIS/REPAIR/QC/WAITING_PART/WAITING_APPROVAL/READY/COMPLETED); `receive` tidak isi `brand/model` sehingga kolom tabel bisa kosong; list transaksi hilangkan `device_password/repair_plan` (backend, berdampak UI).
* Aksesibilitas/UX: `maximum-scale=1.0, user-scalable=no` mengunci zoom HP; `overflow: hidden` pada body mengandalkan scroll area dalam.

## 20. FRONTEND DEVELOPMENT WORKFLOW

```text
BEFORE FRONTEND CHANGE

→ baca AI_CONTEXT.md
→ baca ARCHITECTURE.md
→ baca DATABASE.md
→ baca API.md
→ baca FRONTEND.md
→ identifikasi halaman
→ identifikasi fungsi JS
→ identifikasi API
→ identifikasi state
→ identifikasi database/API impact
→ baru rencanakan perubahan
```

```text
AFTER FRONTEND CHANGE

→ test halaman
→ test interaction
→ test API integration
→ test responsive behavior jika relevan
→ update FRONTEND.md
→ update CHANGELOG.md
→ git commit
```

## 21. SOURCE OF TRUTH

1. `frontend/index.html` = sumber kebenaran struktur UI
2. `frontend/script.js` = sumber kebenaran behavior/state/API integration
3. `frontend/style.css` = sumber kebenaran styling
4. `API.md` = peta API
5. `FRONTEND.md` = dokumentasi pemahaman frontend

Jika dokumentasi berbeda dengan source code:
→ verifikasi source code
→ jangan menebak
→ update dokumentasi.

## 22. LAST VERIFIED

* Tanggal dokumentasi: 2026-09-07 (UTC).
* Konteks dibaca: `docs/AI_CONTEXT.md`, `docs/ARCHITECTURE.md`, `docs/DATABASE.md`, `docs/API.md`.
* Source diperiksa: `frontend/index.html` (head/CDN, login, nav sidebar/mobile, semua section page + modal Servis Baru/Akun, status-bar), `frontend/script.js` (auth storage, navigasi, API helper, semua render/function map, state, login/session, receive + history, boot `DOMContentLoaded`), `frontend/style.css` (header + sistem class + responsive, selektif), `frontend/assets` (daftar file).
* Source code tidak diubah. Database tidak diubah. Fitur baru tidak dibuat. Credential/token/password/secret tidak ditulis.
