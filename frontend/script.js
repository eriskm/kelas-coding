/* ============================================
   SUKABUMI FLASHER — Dashboard Logic (fetch dari FastAPI)
   ============================================ */

const API_BASE = '/api';

// Auth helpers
function getToken() { return localStorage.getItem('bsf_token') || sessionStorage.getItem('bsf_token'); }
function setToken(t, remember) {
    if (remember === false) {
        localStorage.removeItem('bsf_token');
        sessionStorage.setItem('bsf_token', t);
    } else {
        sessionStorage.removeItem('bsf_token');
        localStorage.setItem('bsf_token', t);
    }
}
function clearToken() { localStorage.removeItem('bsf_token'); sessionStorage.removeItem('bsf_token'); }
function getSavedUsername() { return localStorage.getItem('bsf_username') || ''; }
function setSavedUsername(u) { localStorage.setItem('bsf_username', u); }
function clearSavedUsername() { localStorage.removeItem('bsf_username'); }
// Default MATI. Ware ini dipakai bersama di toko: kalau "Ingat Saya" nyala
// dari awal, siapa pun yang membuka aplikasi di komputer kasir langsung masuk
// tanpa passcode selama token masih hidup (TTL 7 hari). Jadi remembered harus
// jadi pilihan sadar, bukan default.
function getRemember() { return localStorage.getItem('bsf_remember') === '1'; }
function setRemember(v) { localStorage.setItem('bsf_remember', v ? '1' : '0'); }

// ─────────────────────────────────────────────
// SIDEBAR TOGGLE (mobile)
// ─────────────────────────────────────────────

function toggleSidebar(open) {
    const sidebar = document.getElementById('appSidebar');
    const overlay = document.getElementById('sidebarOverlay');
    if (open) {
        sidebar.classList.add('open');
        overlay.classList.add('show');
    } else {
        sidebar.classList.remove('open');
        overlay.classList.remove('show');
    }
}

// ─────────────────────────────────────────────
// PAGE NAVIGATION (dashboard <-> servis baru)
// ─────────────────────────────────────────────

function setActiveNav(active, items) {
    items.forEach(l => l.classList.toggle('active', l.dataset.page === active));
}

// ─────────────────────────────────────────────
// ROUTE PERSISTENCE (tahan refresh + URL hash)
// ─────────────────────────────────────────────

const VALID_PAGES = ['dashboard', 'transaksi', 'pelanggan', 'garansi', 'sparepart', 'keuangan', 'akun'];

// Servis Baru adalah floating overlay di atas halaman utama, jadi status bukanya
// disimpan terpisah agar tahan refresh (bsf_page tetap menyimpan halaman dasar).
const RECEIVE_OPEN_KEY = 'bsf_receive_open';
const RECEIVE_DRAFT_KEY = 'bsf_receive_draft';

function pageFromHash() {
    const m = (location.hash || '').match(/^#\/([a-z]+)/);
    return (m && VALID_PAGES.includes(m[1])) ? m[1] : null;
}

function isReceiveHash() {
    return /^#\/(servisbaru|receive)\/?$/.test(location.hash || '');
}

function isReceiveOpen() {
    try { return localStorage.getItem(RECEIVE_OPEN_KEY) === '1'; } catch (_) { return false; }
}

function setReceiveHash() {
    const h = '#/servisbaru';
    if (location.hash !== h) location.hash = h;
}

// ─────────────────────────────────────────────
// SERVIS BARU — draft autosave (tahan refresh)
// ─────────────────────────────────────────────
const RECEIVE_DRAFT_FIELDS = ['rcName', 'rcPhone', 'rcDevice', 'rcPassword', 'rcImei', 'rcDamage', 'rcPlan', 'rcEstimate', 'rcDp', 'rcFinal', 'rcTechnician', 'rcStatus', 'rcPath'];
let _rcDraftTimer = null;

// Initial path Servis Baru (FINAL, bukan status bebas).
// Path → initial status: TITIP→DITERIMA, PERBAIKAN→PERBAIKAN,
// SPAREPART→WAIT PART, TUNGGU→DONE.
const RC_PATH_TARGET = {
    TITIP: 'DITERIMA',
    PERBAIKAN: 'REPAIR',
    SPAREPART: 'WAIT PART',
    TUNGGU: 'DONE',
};

function rcGetPath() {
    try {
        const c = document.querySelector('input[name="rcPath"]:checked');
        const v = c ? c.value : 'TITIP';
        return RC_PATH_TARGET[v] ? v : 'TITIP';
    } catch (_) { return 'TITIP'; }
}

// Smart detect posisi servis dari data yang diisi (FINAL: Posisi Servis).
// SPAREPART tidak pernah terdeteksi otomatis (butuh keputusan eksplisit).
// Deteksi berhenti begitu user klik card manual (_rcPathManual).
let _rcPathManual = false;

function rcAutoPath() {
    try {
        if (_rcPathManual) return;
        const filled = id => ((document.getElementById(id) || {}).value || '').trim() !== '';
        const numFilled = id => (parseFloat((document.getElementById(id) || {}).value) || 0) > 0;
        let want = 'TITIP';
        if (filled('rcFinal') && filled('rcPlan') && filled('rcTechnician')) want = 'TUNGGU';
        else if (filled('rcPlan') && numFilled('rcEstimate') && filled('rcTechnician')) want = 'REPAIR';
        if (want !== rcGetPath()) {
            const r = document.querySelector('input[name="rcPath"][value="' + want + '"]');
            if (r) { r.checked = true; rcApplyPath(); try { rcPosAnimate(want, true); } catch (_) {} }
        }
    } catch (_) {}
}

function rcApplyPath() {
    const path = rcGetPath();
    const hid = document.getElementById('rcStatus');
    if (hid) hid.value = RC_PATH_TARGET[path];
    const fw = document.getElementById('rcFinalWrap');
    if (fw) fw.classList.toggle('hidden', path !== 'TUNGGU');
    const badge = document.getElementById('rcPathBadge');
    if (badge) {
        const manual = !!_rcPathManual;
        badge.textContent = manual ? 'MANUAL' : 'AUTO';
        badge.classList.toggle('is-manual', manual);
        badge.title = manual ? 'Pilihan manual — deteksi otomatis berhenti'
            : 'Terdeteksi otomatis dari data — klik icon untuk ubah';
    }
    try { rcMarkReq(); } catch (_) {}
    try { updateReceiveSteps(); } catch (_) {}
    try { scheduleReceiveDraft(); } catch (_) {}
}

// Micro-animation Posisi Servis (presentasi saja — tidak mengubah workflow/status/payload).
// - Pop 200ms saat active state berpindah (via CSS .is-live).
// - Ping sekali saat smart-detection otomatis (via .rc-flash).
// - Badge fade/slide ringan saat teks AUTO<->MANUAL berubah (via .rc-badge-in).
function rcPosAnimate(path, isAuto) {
    try {
        if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
        const bar = document.querySelector('.rc-posbar');
        if (bar) {
            const input = document.querySelector('input[name="rcPath"][value="' + path + '"]');
            const label = input ? input.closest('.rc-pos') : null;
            if (label && isAuto) {
                label.classList.remove('rc-flash');
                void label.offsetWidth;
                label.classList.add('rc-flash');
                setTimeout(() => { try { label.classList.remove('rc-flash'); } catch (_) {} }, 380);
            }
            const badge = document.getElementById('rcPathBadge');
            if (badge) {
                badge.classList.remove('rc-badge-in');
                void badge.offsetWidth;
                badge.classList.add('rc-badge-in');
                setTimeout(() => { try { badge.classList.remove('rc-badge-in'); } catch (_) {} }, 260);
            }
        }
    } catch (_) {}
}
try {
    requestAnimationFrame(() => requestAnimationFrame(() => {
        try { document.querySelector('.rc-posbar')?.classList.add('is-live'); } catch (_) {}
    }));
} catch (_) {}

function collectReceiveDraft() {
    const d = {};
    RECEIVE_DRAFT_FIELDS.forEach(id => {
        if (id === 'rcPath') { d.rcPath = rcGetPath(); return; }
        const el = document.getElementById(id);
        if (el) d[id] = el.value;
    });
    try {
        if (typeof collectChecklist === 'function') d._checklist = collectChecklist('rc');
    } catch (_) {}
    return d;
}

function saveReceiveDraft() {
    try {
        const d = collectReceiveDraft();
        const hasValue = Object.keys(d).some(k => {
            if (k === '_checklist') {
                const c = d._checklist || {};
                return (c.fisik || []).length > 0 || ((c.len || []).filter(x => x !== 'unit_saja').length > 0);
            }
            return String(d[k] || '').trim() !== '' && d[k] !== 'ANALISA';
        });
        if (hasValue) localStorage.setItem(RECEIVE_DRAFT_KEY, JSON.stringify(d));
        else localStorage.removeItem(RECEIVE_DRAFT_KEY);
    } catch (_) {}
}

function scheduleReceiveDraft() {
    clearTimeout(_rcDraftTimer);
    _rcDraftTimer = setTimeout(saveReceiveDraft, 300);
}

function restoreReceiveDraft() {
    let d = null;
    try { d = JSON.parse(localStorage.getItem(RECEIVE_DRAFT_KEY) || 'null'); } catch (_) { d = null; }
    if (!d) { _rcPathManual = false; try { rcMarkReq(); } catch (_) {} return false; }
    RECEIVE_DRAFT_FIELDS.forEach(id => {
        if (id === 'rcPath') {
            if (d.rcPath && RC_PATH_TARGET[d.rcPath]) {
                const r = document.querySelector('input[name="rcPath"][value="' + d.rcPath + '"]');
                if (r) r.checked = true;
                // Draft non-TITIP = pilihan eksplisit → kunci dari auto-detect.
                _rcPathManual = (d.rcPath !== 'TITIP');
            } else {
                _rcPathManual = false;
            }
            return;
        }
        const el = document.getElementById(id);
        if (!el || d[id] === undefined) return;
        // Jangan timpa pilihan teknisi bila option-nya belum ada (daftar async).
        if (id === 'rcTechnician' && d[id] && !Array.from(el.options).some(o => o.value === d[id])) return;
        el.value = d[id];
    });
    try { rcApplyPath(); } catch (_) {}
    try {
        if (d._checklist && typeof applyChecklist === 'function') applyChecklist('rc', d._checklist);
    } catch (_) {}
    try { updateReceiveSteps(); } catch (_) {}
    try { rcMarkReq(); } catch (_) {}
    return true;
}

function clearReceiveDraft() {
    try { localStorage.removeItem(RECEIVE_DRAFT_KEY); } catch (_) {}
}

// Tandai field wajib (* merah) mengikuti initial path Servis Baru:
// PERBAIKAN/SPAREPART = Rencana + Estimasi + Teknisi;
// TUNGGU = Rencana + Teknisi + Harga Final; TITIP = tanpa tanda.
// Global agar tahan refresh: dipanggil setiap restoreReceiveDraft().
function rcMarkReq() {
    try {
        const path = rcGetPath();
        const need = (fid) => (path === 'REPAIR' || path === 'WAIT PART')
            ? (fid === 'rcPlan' || fid === 'rcEstimate' || fid === 'rcTechnician')
            : (path === 'TUNGGU'
                ? (fid === 'rcPlan' || fid === 'rcTechnician' || fid === 'rcFinal')
                : false);
        const mark = (labelId, base, fid) => {
            const el = document.getElementById(labelId);
            if (!el) return;
            el.innerHTML = base + (need(fid) ? ' <b class="text-red-500">*</b>' : '');
        };
        mark('rcPlanLabel', 'Rencana Perbaikan', 'rcPlan');
        mark('rcEstimateLabel', 'Estimasi Biaya', 'rcEstimate');
        mark('rcTechnicianLabel', 'Teknisi Penanggung Jawab', 'rcTechnician');
        mark('rcFinalLabel', 'Harga Final', 'rcFinal');
    } catch (_) {}
}

function savePage(key) {
    if (!VALID_PAGES.includes(key)) return;
    localStorage.setItem('bsf_page', key);
    const h = '#/' + key;
    if (location.hash !== h) location.hash = h;
}

function getSavedPage() {
    const p = localStorage.getItem('bsf_page');
    return VALID_PAGES.includes(p) ? p : 'dashboard';
}

//: Halaman -> kapabilitas yang boleh membukanya. Ini PEMBANTU tampilan saja;
//: proteksi sebenarnya ada di backend. Tujuannya role tidak melihat halaman
//: yang memang bukan tugasnya, dan supaya "sembunyikan tombol"
//: tidak dianggap satu-satunya lapis.
const PAGE_CAP = {
    'servisbaru': ['ORDER_CREATE'],
    'transaksi': ['ORDER_CREATE', 'ORDER_UPDATE'],
    'garansi': ['CLAIM_WRITE', 'REPORT_FULL'],
    'sparepart': ['SPAREPART_WRITE'],
    'keuangan': ['KAS_CLOSE', 'EXPENSE_WRITE', 'KAS_ENTRY_WRITE', 'REPORT_FULL',
        'REPORT_INVESTOR'],
    'akun': ['USER_MANAGE'],
};

function bolehBukaHalaman(key) {
    const butuh = PAGE_CAP[key];
    if (!butuh) return true;                 // dashboard / pelanggan: semua login
    return butuh.some(a => can(a));
}

function navigateTo(key) {
    // Penjaga halaman. `navigateTo` bisa dipanggil dari hash URL, jadi menu yang
    // disembunyikan saja TIDAK cukup untuk menutup akses halaman.
    if (!bolehBukaHalaman(key)) {
        toast('Halaman ini di luar kewenangan role Anda.');
        showPage('dashboard');
        return;
    }
    if (key === 'transaksi') showTransaksi();
    else if (key === 'pelanggan') showPelanggan();
    else if (key === 'garansi') showGaransi();
    else if (key === 'sparepart') showSparepart();
    else if (key === 'keuangan') showKeuangan();
    else if (key === 'akun') showAkun();
    else if (key === 'servisbaru' || key === 'receive') openServisBaru();
    else showPage('dashboard');
}

function showPage(name) {
    // Penanda halaman aktif: hashchange yang dipicu savePage() di bawah
    // tidak boleh menavigasi ulang (mencegah render ganda).
    window._activePage = name;
    const isDash = name === 'dashboard';
    const isTransaksi = name === 'transaksi';
    const isPelanggan = name === 'pelanggan';
    const isGaransi = name === 'garansi';
    const isSparepart = name === 'sparepart';
    const isKeuangan = name === 'keuangan';
    const isAkun = name === 'akun';
    if (name === 'receive' || name === 'servisbaru') { openServisBaru(); return; }
    if (name === 'formAkun') { openFormAkun(); return; }
    savePage(name);
    try { localStorage.removeItem(RECEIVE_OPEN_KEY); } catch (_) {}
    // Pindah halaman menutup semua menu titik-3 + popup sementara.
    try { closeRowMenus(); } catch (_) {}
    try { closeReceiveSuccessPopup(false); } catch (_) {}
    try { doneWaClose(); } catch (_) {}

    document.getElementById('pageReceive').classList.remove('open');
    const _pgNota = document.getElementById('pageNota');
    if (_pgNota) _pgNota.classList.remove('open');
    const _pgUpd = document.getElementById('pageUpdateServis');
    if (_pgUpd) _pgUpd.classList.remove('open');
    if (document.getElementById('pageFormAkun')) {
        document.getElementById('pageFormAkun').classList.remove('open');
    }
    
    document.getElementById('pageDashboard').classList.toggle('hidden', !isDash);
    document.getElementById('pageTransaksi').classList.toggle('hidden', !isTransaksi);
    document.getElementById('pagePelanggan').classList.toggle('hidden', !isPelanggan);
    document.getElementById('pageGaransi').classList.toggle('hidden', !isGaransi);
    document.getElementById('pageSparepart').classList.toggle('hidden', !isSparepart);
    document.getElementById('pageKeuangan').classList.toggle('hidden', !isKeuangan);
    if (document.getElementById('pageAkun')) {
        document.getElementById('pageAkun').classList.toggle('hidden', !isAkun);
    }
    
    const navs = document.querySelectorAll('.nav-link');
    const mobiles = document.querySelectorAll('.mobile-nav-item');
    const target = isDash ? 'dashboard' : isTransaksi ? 'transaksi' : isPelanggan ? 'pelanggan' : isGaransi ? 'garansi' : isSparepart ? 'sparepart' : isKeuangan ? 'keuangan' : isAkun ? 'akun' : 'dashboard';
    setActiveNav(target, navs);
    setActiveNav(target, mobiles);
    if (window.innerWidth < 640) toggleSidebar(false);
}

function showDashboard() { showPage('dashboard'); }
function showTransaksi() { showPage('transaksi'); renderTransaksi(); }
function showPelanggan() { showPage('pelanggan'); renderPelanggan(); }
function showGaransi() { showPage('garansi'); renderGaransi(); }
function showSparepart() { _spPage = 1; showPage('sparepart'); renderSparepart(); }
function showKeuangan() { showPage('keuangan'); renderKeuangan(); }

// ─────────────────────────────────────────────
// KELOLA AKUN (data real backend — GET/POST/PUT /api/auth/users)
// Hapus = nonaktifkan (active=0), bukan delete, agar histori login aman.
// ─────────────────────────────────────────────
let _akQuery = '';
let _akRole = '';
let _akStatus = '';
let _akEditId = -1;
let _akReq = 0;
// State real dari backend. AKUN_DUMMY dipensiunkan.
let _akView = [];

function akNorm(r) {
    const active = Number(r.active) === 1;
    let login = 'Belum pernah login';
    if (r.last_login) {
        try {
            const d = new Date(r.last_login);
            login = d.toLocaleDateString('id-ID', { day: 'numeric', month: 'short', year: 'numeric' })
                + ', ' + d.toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit' });
        } catch (_) { login = String(r.last_login).slice(0, 16).replace('T', ' '); }
    }
    return {
        id: r.id,
        nama: r.display_name || '-',
        username: r.username || '-',
        role: r.role || 'Teknisi',
        status: active ? 'Aktif' : 'Nonaktif',
        login: login,
    };
}

function akRoleBadge(role) {
    const admin = role === 'Admin';
    return `<span class="px-2 py-0.5 rounded text-[10px] font-bold ${admin ? 'bg-brand-100 text-brand-700 dark:bg-brand-900/30 dark:text-brand-400' : 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400'}">${escapeHtml(role)}</span>`;
}

function akStatusBadge(status) {
    const on = status === 'Aktif';
    return `<span class="px-2 py-0.5 rounded text-[10px] font-bold ${on ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400' : 'bg-gray-100 text-gray-600 dark:bg-white/10 dark:text-gray-400'}">${escapeHtml(status)}</span>`;
}

function akFiltered() {
    const q = _akQuery.trim().toLowerCase();
    return (_akView || []).filter(a => {
        if (_akRole && a.role !== _akRole) return false;
        if (_akStatus && a.status !== _akStatus) return false;
        if (!q) return true;
        return [a.nama, a.username].some(f => (f || '').toLowerCase().includes(q));
    });
}

// Ringkasan hak akses tiap role, ditampilkan di bawah dropdown Role.
// Disumber dari BACKEND (AUTHORITY_MATRIX) lewat /auth/roles supaya tidak ada
// dua daftar hak akses yang bisa berbeda sendiri di frontend.
let _akRoleHints = null;
async function muatRoleHints() {
    try {
        const d = await apiGet('/auth/roles');
        _akRoleHints = d && d.ringkasan;
    } catch (_) { _akRoleHints = null; }
    tampilkanRoleHint();
}
function tampilkanRoleHint() {
    const el = document.getElementById('akRoleHint');
    const sel = document.getElementById('akRole');
    if (!el || !sel) return;
    const v = String(sel.value || '').trim();
    const info = _akRoleHints && _akRoleHints[v];
    if (!info) { el.textContent = ''; return; }
    el.innerHTML = '<b>' + escapeHtml(v) + '</b> &mdash; ' + escapeHtml(info.ringkas)
        + (info.monitoring ? ' <span class="text-gray-400">(hanya lihat, tidak bisa mengubah data)</span>' : '');
}

function initAkToolbar() {
    const s = document.getElementById('akSearch');
    const r = document.getElementById('akRoleFilter');
    const t = document.getElementById('akStatusFilter');
    if (s && !s.dataset.bound) {
        s.dataset.bound = '1';
        let timer = null;
        s.addEventListener('input', () => {
            clearTimeout(timer);
            timer = setTimeout(() => { _akQuery = s.value; renderAkun(); }, 300);
        });
    }
    if (r && !r.dataset.bound) {
        r.dataset.bound = '1';
        r.addEventListener('change', () => { _akRole = r.value; renderAkun(); });
    }
    if (t && !t.dataset.bound) {
        t.dataset.bound = '1';
        t.addEventListener('change', () => { _akStatus = t.value; renderAkun(); });
    }
}

async function renderAkun() {
    initAkToolbar();
    initAkunForm();
    muatRoleHints();
    const selRole = document.getElementById('akRole');
    if (selRole && !selRole.dataset.bound) {
        selRole.dataset.bound = '1';
        selRole.addEventListener('change', tampilkanRoleHint);
    }
    const my = ++_akReq;
    const body = document.getElementById('akBody');
    if (!body) return;
    try {
        const rows = await apiGet('/auth/users');
        if (my !== _akReq) return; // respons basi — ada request lebih baru
        _akView = (rows || []).map(akNorm);
    } catch (err) {
        if (my !== _akReq) return;
        body.innerHTML = `<tr><td colspan="7"><div class="text-center text-sm text-gray-400 py-6">${escapeHtml(err.message || 'Gagal memuat akun.')}</div></td></tr>`;
        return;
    }
    const total = _akView.length;
    const aktif = _akView.filter(a => a.status === 'Aktif').length;
    const admin = _akView.filter(a => a.role === 'Admin').length;
    const setNum = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
    setNum('akTotal', total);
    setNum('akAktif', aktif);
    setNum('akAdmin', admin);
    const data = akFiltered();
    body.innerHTML = data.map((a) => {
        return `
        <tr class="tx-row">
            <td class="text-center text-gray-500">${_akView.indexOf(a) + 1}</td>
            <td class="font-semibold ${a.status === 'Aktif'
                ? 'text-gray-800 dark:text-gray-200'
                : 'text-red-600 dark:text-red-400 line-through'}">${escapeHtml(a.nama)}</td>
            <td class="text-gray-500">${escapeHtml(a.username)}</td>
            <td class="text-center">${akRoleBadge(a.role)}</td>
            <td class="text-center">${akStatusBadge(a.status)}</td>
            <td class="text-gray-500 text-[11px]">${escapeHtml(a.login)}</td>
            <td class="text-center">
                <button class="w-7 h-7 rounded bg-gray-100 dark:bg-white/5 hover:bg-brand-50 dark:hover:bg-brand-500/10 text-gray-500 hover:text-brand-500 transition-colors" title="Edit Akun" onclick="akEdit(${a.id})"><i class="fa-solid fa-pen-to-square"></i></button>
                ${a.status === 'Aktif'
                    ? `<button class="tx-view-btn tx-del-btn" title="Nonaktifkan Akun (tidak bisa login, bisa diaktifkan lagi)" onclick="akDeactivate(${a.id}, '${escapeHtml(a.username).replace(/'/g, "\\'")}')"><i class="fa-solid fa-user-slash"></i></button>`
                    : `<button class="tx-view-btn tx-edit-btn" title="Aktifkan Lagi" onclick="akReactivate(${a.id})"><i class="fa-solid fa-rotate-left"></i></button>`}
            </td>
        </tr>`;
    }).join('');
    const info = document.getElementById('akInfo');
    if (info) info.textContent = data.length === total
        ? 'Menampilkan 1-' + total + ' dari ' + total + ' akun'
        : 'Menampilkan ' + data.length + ' dari ' + total + ' akun (filter)';
}

function akEdit(id) {
    const a = (_akView || []).find(x => x && x.id === id);
    if (!a) return;
    _akEditId = id;
    document.getElementById('akFormTitle').textContent = 'Edit Akun';
    document.getElementById('akNama').value = a.nama === '-' ? '' : a.nama;
    document.getElementById('akUsername').value = a.username || '';
    document.getElementById('akUsername').disabled = true;
    document.getElementById('akPassword').value = '';
    document.getElementById('akPassword').placeholder = 'Kosongkan bila tidak diganti';
    document.getElementById('akRole').value = a.role || 'Teknisi';
    document.getElementById('akStatus').value = a.status || 'Aktif';
    tampilkanRoleHint();
    openFormAkun();
}

async function akDeactivate(id, username) {
    if (!confirm('Nonaktifkan akun "' + username + '"? Akun tidak bisa login sampai diaktifkan lagi.')) return;
    try {
        await apiPut('/auth/users/' + id, { active: 0 });
        renderAkun();
    } catch (err) {
        toast(err.message || 'Gagal menonaktifkan akun.');
    }
}

async function akReactivate(id) {
    try {
        await apiPut('/auth/users/' + id, { active: 1 });
        renderAkun();
    } catch (err) {
        toast(err.message || 'Gagal mengaktifkan akun.');
    }
}

function initAkunForm() {
    const form = document.getElementById('akunForm');
    if (!form || form.dataset.bound) return;
    form.dataset.bound = '1';
    form.addEventListener('submit', async function (e) {
        e.preventDefault();
        const nama = document.getElementById('akNama').value.trim();
        const username = document.getElementById('akUsername').value.trim();
        const passcode = document.getElementById('akPassword').value;
        if (!nama || !username) return;
        try {
            if (_akEditId >= 0) {
                const payload = {
                    display_name: nama,
                    role: document.getElementById('akRole').value,
                    active: document.getElementById('akStatus').value === 'Aktif' ? 1 : 0,
                };
                if (passcode) payload.passcode = passcode;
                await apiPut('/auth/users/' + _akEditId, payload);
                _akEditId = -1;
            } else {
                if (!passcode || passcode.length < 4) {
                    toast('Passcode minimal 4 karakter.');
                    return;
                }
                await apiPost('/auth/users', {
                    username: username,
                    display_name: nama,
                    role: document.getElementById('akRole').value,
                    passcode: passcode,
                    active: document.getElementById('akStatus').value === 'Aktif' ? 1 : 0,
                });
            }
            renderAkun();
            closeFormAkun();
        } catch (err) {
            toast(err.message || 'Gagal menyimpan akun.');
        }
    });
}

function openServisBaru() {
    document.getElementById('pageReceive').classList.add('open');
    try { localStorage.setItem(RECEIVE_OPEN_KEY, '1'); } catch (_) {}
    closeReceiveSuccessPopup(false);
    restoreReceiveDraft();
    loadReceiveTechnicians();
    setReceiveHash();
    const _nb = document.getElementById('receiveNotaBtn');
    if (_nb) _nb.classList.add('hidden');
    const _st = document.getElementById('receiveSubmitText');
    if (_st) _st.textContent = 'Terima & Daftarkan Servis';
    updateReceiveSteps();
    loadSmartHistory();
    setActiveNav('servisbaru', document.querySelectorAll('.nav-link'));
    setActiveNav(null, document.querySelectorAll('.mobile-nav-item'));
    const first = document.getElementById('rcName');
    if (first) setTimeout(() => first.focus({ preventScroll: true }), 80);
    if (window.innerWidth < 640) toggleSidebar(false);
}
function showServisBaru() { openServisBaru(); }
// Popup sukses Servis Baru: notif No. Servis + tombol Cetak Nota.
function showReceiveSuccessPopup(noServis) {
    const noEl = document.getElementById('rspNoServis');
    if (noEl) noEl.textContent = noServis || '-';
    const ov = document.getElementById('receiveSuccessPopup');
    if (ov) ov.classList.remove('hidden');
}
function closeReceiveSuccessPopup(focusAgain) {
    const ov = document.getElementById('receiveSuccessPopup');
    if (ov) ov.classList.add('hidden');
    if (focusAgain) {
        const f = document.getElementById('rcName');
        if (f) setTimeout(() => f.focus({ preventScroll: true }), 60);
    }
}
function receiveSuccessPrint() {
    closeReceiveSuccessPopup(false);
    openNota();
}
function closeServisBaru() {
    try { localStorage.removeItem(RECEIVE_OPEN_KEY); } catch (_) {}
    closeReceiveSuccessPopup(false);
    document.getElementById('pageReceive').classList.remove('open');
    const isTx = !document.getElementById('pageTransaksi').classList.contains('hidden');
    const isPl = !document.getElementById('pagePelanggan').classList.contains('hidden');
    const isGr = !document.getElementById('pageGaransi').classList.contains('hidden');
    const isSp = !document.getElementById('pageSparepart').classList.contains('hidden');
    const isKu = !document.getElementById('pageKeuangan').classList.contains('hidden');
    const isAk = document.getElementById('pageAkun') && !document.getElementById('pageAkun').classList.contains('hidden');
    const target = isTx ? 'transaksi' : isPl ? 'pelanggan' : isGr ? 'garansi' : isSp ? 'sparepart' : isKu ? 'keuangan' : isAk ? 'akun' : 'dashboard';
    setActiveNav(target, document.querySelectorAll('.nav-link'));
    setActiveNav(target, document.querySelectorAll('.mobile-nav-item'));
    savePage(target);
}

function openFormAkun() {
    const pageFormAkun = document.getElementById('pageFormAkun');
    if (pageFormAkun) pageFormAkun.classList.add('open');
    setActiveNav('akun', document.querySelectorAll('.nav-link'));
    setActiveNav(null, document.querySelectorAll('.mobile-nav-item'));
    const first = document.getElementById('akNama');
    if (first) setTimeout(() => first.focus({ preventScroll: true }), 80);
    if (window.innerWidth < 640) toggleSidebar(false);
}
function showFormAkun() {
    _akEditId = -1;
    document.getElementById('akFormTitle').textContent = 'Tambah Akun';
    document.getElementById('akunForm').reset();
    document.getElementById('akUsername').disabled = false;
    document.getElementById('akPassword').placeholder = 'Minimal 4 karakter';
    openFormAkun();
}
function closeFormAkun() {
    const pageFormAkun = document.getElementById('pageFormAkun');
    if (pageFormAkun) pageFormAkun.classList.remove('open');
    setActiveNav('akun', document.querySelectorAll('.nav-link'));
    setActiveNav('akun', document.querySelectorAll('.mobile-nav-item'));
    savePage('akun');
}

// ─────────────────────────────────────────────
// FLOATING WINDOW: drag via title bar (mouse + touch)
// ─────────────────────────────────────────────

function makeFloatDraggable(winId, barId, closeFunc) {
    const win = document.getElementById(winId);
    const bar = document.getElementById(barId);
    if (!win || !bar) return;
    document.body.appendChild(win);

    const clampPos = (x, y) => {
        const w = win.offsetWidth || 480;
        return {
            x: Math.min(Math.max(x, -(w - 90)), window.innerWidth - 90),
            y: Math.min(Math.max(y, 0), window.innerHeight - 48),
        };
    };
    const begin = (cx, cy) => {
        const r = win.getBoundingClientRect();
        const ox = r.left, oy = r.top;
        win.style.left = ox + 'px';
        win.style.top = oy + 'px';
        // WAJIB: lepaskan anchor sisi yang berlawanan dengan yang kita tulis.
        // Kalau `right`/`bottom` masih aktif dari CSS sementara `left`/`top`
        // mulai diisi, elemen `position:fixed` jadi terkunci di antara keduanya
        // dan browser meregangkan `height` (auto) — card CTO tumbuh jadi
        // beberapa kali lipat begitu digeser ke atas.
        win.style.right = 'auto';
        win.style.bottom = 'auto';
        win.style.transform = 'none';
        win.classList.add('dragging');
        return (mx, my) => {
            const p = clampPos(ox + mx - cx, oy + my - cy);
            win.style.left = p.x + 'px';
            win.style.top = p.y + 'px';
        };
    };
    const finish = () => win.classList.remove('dragging');

    bar.addEventListener('mousedown', (e) => {
        if (e.button !== 0 || e.target.closest('.float-close')) return;
        e.preventDefault();
        const move = begin(e.clientX, e.clientY);
        const onMove = (ev) => move(ev.clientX, ev.clientY);
        const onUp = () => {
            finish();
            document.removeEventListener('mousemove', onMove);
            document.removeEventListener('mouseup', onUp);
        };
        document.addEventListener('mousemove', onMove);
        document.addEventListener('mouseup', onUp);
    });
    bar.addEventListener('touchstart', (e) => {
        if (e.target.closest('.float-close')) return;
        const t = e.touches[0];
        const move = begin(t.clientX, t.clientY);
        const onMove = (ev) => { move(ev.touches[0].clientX, ev.touches[0].clientY); ev.preventDefault(); };
        const onEnd = () => {
            finish();
            bar.removeEventListener('touchmove', onMove);
            bar.removeEventListener('touchend', onEnd);
            bar.removeEventListener('touchcancel', onEnd);
        };
        bar.addEventListener('touchmove', onMove, { passive: false });
        bar.addEventListener('touchend', onEnd);
        bar.addEventListener('touchcancel', onEnd);
    }, { passive: true });

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && win.classList.contains('open')) closeFunc();
    });
    window.addEventListener('resize', () => {
        if (!win.classList.contains('open')) return;
        const r = win.getBoundingClientRect();
        const p = clampPos(r.left, r.top);
        win.style.left = p.x + 'px';
        win.style.top = p.y + 'px';
        win.style.right = 'auto';
        win.style.bottom = 'auto';
        win.style.transform = 'none';
    });
}

function initFloatDrag() {
    makeFloatDraggable('pageReceive', 'receiveTitlebar', closeServisBaru);
    makeFloatDraggable('pageFormAkun', 'akunTitlebar', closeFormAkun);
    makeFloatDraggable('pageHistory', 'histTitlebar', closePlHist);
    makeFloatDraggable('pageWarranty', 'warrantyTitlebar', closeGrDetail);
    makeFloatDraggable('pageClaim', 'claimTitlebar', closeGrClaim);
    makeFloatDraggable('pageSpare', 'spareTitlebar', closeSpare);
    makeFloatDraggable('pageKeu', 'keuTitlebar', closeKeu);
    makeFloatDraggable('pageNota', 'notaTitlebar', closeNota);
    makeFloatDraggable('pageUpdateServis', 'updateTitlebar', closeUpdateServis);
    makeFloatDraggable('pageTxDetail', 'txDetailTitlebar', closeTxDetail);
    makeFloatDraggable('pageClaimReceive', 'claimReceiveTitlebar', closeClaimReceive);
    // CTO floating: pakai mekanisme drag existing (clamp viewport); Escape = noop (non-modal).
    makeFloatDraggable('ctoFloat', 'ctoFloatHead', () => {});
}

// ─────────────────────────────────────────────
// LIVE CLOCK & DATE
// ─────────────────────────────────────────────

function updateClock() {
    const now = new Date();
    const timeStr = now.toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    const dateStr = now.toLocaleDateString('id-ID', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });
    document.getElementById('currentTime').textContent = timeStr;
    document.getElementById('currentDate').textContent = dateStr;
}

// ─────────────────────────────────────────────
// DARK MODE
// ─────────────────────────────────────────────

function initTheme() {
    const saved = localStorage.getItem('theme');
    if (saved === 'dark' || (!saved && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
        document.documentElement.classList.add('dark');
    }
    document.getElementById('toggleTheme').addEventListener('click', () => {
        document.documentElement.classList.toggle('dark');
        localStorage.setItem('theme', document.documentElement.classList.contains('dark') ? 'dark' : 'light');
        updateChartTheme();
    });
}

// ─────────────────────────────────────────────
// HELPER
// ─────────────────────────────────────────────

function formatRupiah(val) {
    if (val >= 1000000) return 'Rp ' + (val / 1000000).toFixed(1).replace('.0', '') + 'jt';
    return 'Rp ' + (val || 0).toLocaleString('id-ID');
}

function isDark() {
    return document.documentElement.classList.contains('dark');
}

function chartGridColor() { return isDark() ? 'rgba(255,255,255,0.04)' : '#f1f5f9'; }

// ─────────────────────────────────────────────
// API LAYER
// ─────────────────────────────────────────────

async function apiGet(path) {
    const headers = {};
    const token = getToken();
    if (token) headers['Authorization'] = 'Bearer ' + token;
    const res = await fetch(API_BASE + path, { headers });
    if (res.status === 401) { throw new AuthError('Sesi tidak valid'); }
    if (!res.ok) throw new Error('API error ' + res.status);
    return res.json();
}

class AuthError extends Error {}

async function apiPost(path, body, opts) {
    const headers = { 'Content-Type': 'application/json' };
    const token = getToken();
    if (token) headers['Authorization'] = 'Bearer ' + token;
    // P2-14: Idempotency-Key untuk endpoint money/closing (retry aman).
    if (opts && opts.idempotencyKey) headers['Idempotency-Key'] = opts.idempotencyKey;
    const res = await fetch(API_BASE + path, {
        method: 'POST',
        headers,
        body: JSON.stringify(body || {}),
    });
    if (res.status === 401) { throw new AuthError('Sesi tidak valid'); }
    if (!res.ok) {
        let detail = 'Gagal menyimpan data (HTTP ' + res.status + ')';
        try { const j = await res.json(); if (j.detail) detail = j.detail; } catch (_) {}
        if (res.status === 403) detail = 'Aksi ditolak: ' + detail;
        if (res.status === 409) detail = detail + ' (sudah ada, tidak digandakan)';
        throw new Error(detail);
    }
    return res.json();
}

// Key idempotensi sekali per aksi UI: retry memakai key yang sama.
function newIdemKey() {
    try {
        if (window.crypto && window.crypto.randomUUID) return window.crypto.randomUUID();
    } catch (_) {}
    return 'ui-' + Date.now() + '-' + Math.random().toString(16).slice(2);
}

// ─────────────────────────────────────────────
// P2-15: CAPABILITY (cermin authority matrix B yang sudah LOCKED)
// Tampilan hanya menawarkan aksi yang diizinkan role; backend tetap penjaga utama.
const BSSF_CAPS = {
    superadmin: ['ORDER_CREATE', 'ORDER_UPDATE', 'ORDER_UPDATE_FINANCE', 'ORDER_UPDATE_MODAL',
        'ORDER_STATUS_CLOSING', 'ORDER_HANDOVER', 'ORDER_DELETE', 'PAYMENT_CREATE', 'PAYMENT_CANCEL',
        'EXPENSE_WRITE', 'KAS_ENTRY_WRITE', 'KAS_CLOSE', 'KAS_ASET_INJEKSI', 'REFUND_DP', 'REFUND_GARANSI',
        'FAILED_CANCEL', 'SPAREPART_WRITE', 'CLAIM_WRITE', 'EXPENSE_DEBT_WRITE', 'USER_MANAGE',
        'CUSTOMER_WRITE', 'CUSTOMER_DELETE', 'ROLE_CONFIG', 'AUDIT_READ', 'REPORT_FULL',
        'REPORT_INVESTOR'],
    admin: ['ORDER_CREATE', 'ORDER_UPDATE', 'ORDER_UPDATE_FINANCE', 'ORDER_UPDATE_MODAL',
        'ORDER_STATUS_CLOSING', 'ORDER_HANDOVER', 'ORDER_DELETE', 'PAYMENT_CREATE', 'PAYMENT_CANCEL',
        'EXPENSE_WRITE', 'KAS_ENTRY_WRITE', 'KAS_CLOSE', 'KAS_ASET_INJEKSI', 'REFUND_DP', 'REFUND_GARANSI',
        'FAILED_CANCEL', 'SPAREPART_WRITE', 'CLAIM_WRITE', 'EXPENSE_DEBT_WRITE', 'USER_MANAGE',
        'CUSTOMER_WRITE', 'CUSTOMER_DELETE', 'AUDIT_READ', 'REPORT_FULL', 'REPORT_INVESTOR'],
    kasir: ['ORDER_CREATE', 'ORDER_UPDATE', 'ORDER_UPDATE_FINANCE', 'ORDER_STATUS_CLOSING',
        'ORDER_HANDOVER', 'PAYMENT_CREATE', 'EXPENSE_WRITE', 'REFUND_DP', 'FAILED_CANCEL',
        'SPAREPART_WRITE', 'CLAIM_WRITE'],
    // ORDER_CREATE (penerimaan unit) TIDAK ada: itu tugas Kasir/CS (OD-LOCK-10).
    teknisi: ['ORDER_UPDATE', 'ORDER_HANDOVER', 'CLAIM_WRITE'],
    // Admin Sparepart: hanya area barang/stok. Tidak boleh menyentuh transaksi
    // pelanggan, pembayaran, laba, atau Tutup Kas.
    // Permission sparepart dipisah dari laporan keuangan: Admin Sparepart
    // boleh laporan persediaan, tapi TIDAK laporan bisnis/keuangan.
    adminSparepart: ['SPAREPART_WRITE', 'REPORT_SPAREPART'],
    pengelola: ['REPORT_FULL'], // Q13: monitoring; boleh lihat + unduh laporan
    investor: ['REPORT_INVESTOR'], // monitoring investasi; tanpa data pribadi
    // Role tidak dikenal / kosong = tanpa hak apa pun. Sengaja TIDAK fallback ke
    // admin: kalau ada typo di kolom Role, akun itu harus terlihat "nyaris
    // tidak bisa apa-apa", bukan diam-diam dapat akses penuh di tampilan.
    custom: [],
};
function bssfCaps() {
    // Fail-CLOSED. Dulu fallback-nya `BSSF_CAPS.admin`, padahal komentar di
    // atas blok BSSF_CAPS sudah menyatakan itu TIDAK boleh terjadi: kalau
    // `window._bssfCaps` belum terisi (halaman dimuat ulang, atau sesi belum
    // selesai), seluruh tampilan sempat mendapat hak ADMIN penuh. Backend
    // tetap menolak, tapi tampilannya menyesatkan -- dan ini persis yang
    // dilarang Owner: menyembunyikan/menampilkan tombol BUKAN proteksi.
    try { return (window._bssfCaps || BSSF_CAPS.custom); } catch (_) { return BSSF_CAPS.custom; }
}
function can(action) { return bssfCaps().indexOf(action) !== -1; }
function applyRoleUI(root) {
    const scope = root || document;
    scope.querySelectorAll('[data-cap]').forEach(el => {
        const ok = can(el.getAttribute('data-cap'));
        el.classList.toggle('hidden', !ok);
    });
}
// v4 #11: siapa boleh melihat SALDO ASET + MASTER KAS (data visibility).
// CS/Kasir/Teknisi -> hanya SALDO LACI. Admin/Pengelola -> semuanya.
function canViewAset() {
    // Fail-CLOSED: tanpa sesi yang sudah knows, TIDAK ada hak melihat.
    // Super Admin ikut boleh (dia akun developer, akses penuh).
    const k = (function () { try { return window._bssfRoleKey; } catch (_) { return 'custom'; } })();
    return k === 'superadmin' || k === 'admin' || k === 'pengelola';
}

function setRoleCapabilities(role) {
    const key = String(role || '').trim().toUpperCase();
    const map = {
        SUPERADMIN: 'superadmin', 'SUPER ADMIN': 'superadmin', SUPER_ADMIN: 'superadmin',
        DEV: 'superadmin', DEVELOPER: 'superadmin',
        ADMIN: 'admin', MANAGER: 'admin',
        KASIR: 'kasir', CS: 'kasir',
        TEKNISI: 'teknisi', TEKNIKER: 'teknisi',
        'ADMIN SPAREPART': 'adminSparepart', ADMIN_SPAREPART: 'adminSparepart',
        ADM_SPAREPART: 'adminSparepart', SPAREPART_ADMIN: 'adminSparepart',
        PENGELOLA: 'pengelola', PEMILIK: 'pengelola',
        INVESTOR: 'investor',
    };
    // Fail-CLOSED. Sebelumnya `map[key] || 'admin'`, jadi role yang salah ketik
    // atau kosong otomatis dapat hak admin di tampilan. Backend tetap menolak,
    // tapi tampilannya menyesatkan -- dan `canViewAset()` ikut jadi true.
    const k = map[key] || 'custom';
    try { window._bssfCaps = BSSF_CAPS[k]; window._bssfRoleKey = k; } catch (_) {}
    applyRoleUI(document);
}

async function apiPut(path, body) {
    const headers = { 'Content-Type': 'application/json' };
    const token = getToken();
    if (token) headers['Authorization'] = 'Bearer ' + token;
    const res = await fetch(API_BASE + path, {
        method: 'PUT',
        headers,
        body: JSON.stringify(body || {}),
    });
    if (res.status === 401) { throw new AuthError('Sesi tidak valid'); }
    if (!res.ok) {
        let detail = 'Gagal menyimpan perubahan (HTTP ' + res.status + ')';
        try { const j = await res.json(); if (j.detail) detail = j.detail; } catch (_) {}
        throw new Error(detail);
    }
    return res.json();
}

// Warna semantik KPI (ref: warna-reference.png):
// hijau=pemasukan, biru=finansial utama, amber=beban,
// dinamis=bersih (hijau/merah), target=kartu putih netral + progress bar
const STAR_META = {
    omset: { emoji: '💰', tint: 'kpi-green' },
    laba_kotor: { emoji: '⚡', tint: 'kpi-blue' },
    beban: { emoji: '💸', tint: 'kpi-amber' },
    laba_bersih: { emoji: '🏆', tint: 'kpi-green' },
    cts: { emoji: '🎯' },
    cto: { emoji: '🏭' },
};

const kpiRupiah = v => 'Rp ' + (Number(v) || 0).toLocaleString('en-US');

// Visibility Card Target Operasional (CTO):
// - CTS < 100% (belum tercapai) → HIDDEN
// - CTS tercapai & CTO belum → SHOW
// - CTO tercapai → HIDDEN
// Memakai flag `tercapai` dari API (hasil formula laba vs target yg sudah ada).
function shouldShowCto(byKey) {
    const ctsOk = byKey['cts'] ? !!byKey['cts'].tercapai : true;
    const ctoOk = byKey['cto'] ? !!byKey['cto'].tercapai : false;
    return ctsOk && !ctoOk;
}

function kpiProgressBar(pct, tercapai) {
    const w = Math.max(0, Math.min(100, Number(pct) || 0));
    const cls = tercapai ? 'is-done' : 'is-run';
    const txt = tercapai ? 'TERCAPAI' : String(Number(pct) || 0).replace('.', ',') + '%';
    return `<div class="kpi-progress"><i class="${cls}" style="width:${w}%"></i></div>`
        + `<div class="kpi-caption">${tercapai ? '<i class="fa-solid fa-circle-check"></i> ' : ''}${escapeHtml(txt)}</div>`;
}

// ─────────────────────────────────────────────
// RENDER: STAR CARDS (dari API overview — key-driven)
// ─────────────────────────────────────────────

// Pengingat Tutup Kas. Periode kas berjalan sejak dibuka sampai ditutup —
// jam 16:00 hanya PATOKAN PENGINGAT, bukan batas periode. Kalau periode aktif
// sudah lewat jam 16:00, tampilkan peringatan (bukan sekadar mengubah angka).
function renderPeriodeWarning(per) {
    if (!per) return;
    let box = document.getElementById('kasPeriodWarning');
    if (!box) {
        box = document.createElement('div');
        box.id = 'kasPeriodWarning';
        box.className = 'kas-period-warning';
        const anchor = document.getElementById('starCards');
        if (anchor && anchor.parentNode) anchor.parentNode.insertBefore(box, anchor);
    }
    if (!per.lewat_jam_16) { box.classList.add('hidden'); return; }
    const mulai = (per.start_at || '').replace('T', ' ').slice(0, 16);
    box.classList.remove('hidden');
    box.innerHTML = '<i class="fa-solid fa-bell"></i>'
        + '<span>Periode kas dibuka <b>' + escapeHtml(mulai)
        + '</b> dan belum ditutup — sudah lewat jam 16:00. '
        + 'Semua transaksi tetap tercatat dalam periode ini. '
        + 'Segera tutup kas di menu Keuangan.</span>';
}

async function renderStarCards() {
    const data = await apiGet('/overview');
    const byKey = {};
    (data.star_cards || []).forEach(c => { if (c && c.key) byKey[c.key] = c; });
    // 5 card utama tetap di layout (CTO bukan bagian grid — dirender floating).
    // Sumber data & formula tidak diubah.
    renderPeriodeWarning(data.period);
    const order = ['omset', 'laba_kotor', 'beban', 'laba_bersih', 'cts'];
    const cards = order.map(key => {
        const c = byKey[key];
        if (!c) return '';
        const m = STAR_META[key] || {};
        const cvalue = typeof c.value === 'number' ? kpiRupiah(c.value) : c.value;
        if (key === 'laba_bersih') {
            const tint = Number(c.value) < 0 ? 'kpi-red' : 'kpi-green';
            return `
            <div class="star-card ${tint} kpi-solid">
                <div class="kpi-top"><span class="kpi-label">${escapeHtml(c.label)}</span><span class="kpi-emoji">${m.emoji}</span></div>
                <div class="kpi-value">${cvalue}</div>
                ${c.sub ? `<div class="kpi-caption kpi-caption-light">${escapeHtml(c.sub)}</div>` : ''}
            </div>`;
        }
        if (key === 'cts') {
            return `
            <div class="star-card kpi-target">
                <div class="kpi-top"><span class="kpi-label-dark">${m.emoji} ${escapeHtml(c.label)}</span></div>
                <div class="kpi-value-dark">${cvalue}</div>
                ${kpiProgressBar(c.progress, c.tercapai)}
                ${c.sub ? `<div class="kpi-caption">${escapeHtml(c.sub)}</div>` : ''}
            </div>`;
        }
        return `
            <div class="star-card ${m.tint} kpi-solid">
                <div class="kpi-top"><span class="kpi-label">${escapeHtml(c.label)}</span><span class="kpi-emoji">${m.emoji}</span></div>
                <div class="kpi-value">${cvalue}</div>
                ${c.sub ? `<div class="kpi-caption kpi-caption-light">${escapeHtml(c.sub)}</div>` : ''}
            </div>`;
    }).join('');
    document.getElementById('starCards').innerHTML = cards;
    renderCtoFloat(byKey);
}

// ─────────────────────────────────────────────
// RENDER: CTO FLOATING CARD (non-blocking, draggable)
// Visibility = shouldShowCto (CTS tercapai & CTO belum) — formula tak diubah.
// Posisi drag milik user tidak direset saat re-render (hanya isi yang diganti).
// ─────────────────────────────────────────────
function renderCtoFloat(byKey) {
    const el = document.getElementById('ctoFloat');
    const body = document.getElementById('ctoFloatBody');
    if (!el || !body) return;
    if (!shouldShowCto(byKey) || !byKey['cto']) {
        el.classList.remove('open');
        return;
    }
    const c = byKey['cto'];
    const pct = Math.max(0, Math.min(100, Number(c.progress) || 0));
    const pctTxt = String(Number(c.progress) || 0).replace('.', ',') + '%';
    const cvalue = typeof c.value === 'number' ? kpiRupiah(c.value) : c.value;
    // Card ini sengaja TIDAK memakai `kpiProgressBar` + `c.sub`: keduanya
    // menampilkan persentase yang sama, jadi tampilannya jadi dobel dan
    // card tumbuh ke bawah. Cukup: angka target, badge persen, bar, 1 catatan.
    body.innerHTML = `
        <div class="cto-float-row">
            <div class="cto-float-val">${escapeHtml(cvalue)}</div>
            <span class="cto-pct">${escapeHtml(pctTxt)}</span>
        </div>
        <div class="kpi-progress cto-bar"><i class="is-run" style="width:${pct}%"></i></div>
        <div class="cto-float-note">
            <i class="fa-solid fa-scale-balanced"></i> dari beban gaji + operasional
        </div>`;
    el.classList.add('open');
}

// ─────────────────────────────────────────────
// RENDER: QUICK ACTIONS
// ─────────────────────────────────────────────

function renderQuickActions() {
    const actions = [
        { icon: 'fa-solid fa-plus',                label: 'Servis Baru', desc: 'Buat transaksi service baru', tint: 'qa-red' },
        { icon: 'fa-solid fa-cash-register',       label: 'Input Kas',   desc: 'Catat pemasukan kas harian',  tint: 'qa-green' },
        { icon: 'fa-solid fa-money-check-dollar',  label: 'Input Beban', desc: 'Catat pengeluaran operasional', tint: 'qa-amber' },
        { icon: 'fa-solid fa-microchip',           label: 'Sparepart',   desc: 'Kelola data sparepart',       tint: 'qa-blue' },
    ];

    document.getElementById('quickActions').innerHTML = actions.map((a, i) => {
        const featured = i === 0 ? ' qa-card-featured' : '';
        const go = i === 0 ? ' onclick="openServisBaru()"' : i === 1 ? ' onclick="openAuditKas()"' : i === 2 ? ' onclick="openBeban()"' : i === 3 ? ' onclick="showSparepart()"' : '';
        return `
            <button class="qa-card ${a.tint}${featured}"${go}>
                <span class="qa-card-icon"><i class="${a.icon}"></i></span>
                <span class="qa-card-label">${a.label}</span>
                <span class="qa-card-desc">${a.desc}</span>
            </button>
        `;
    }).join('');
}
// ─────────────────────────────────────────────
// RENDER: INSIGHT CARDS (dari API overview)
// ─────────────────────────────────────────────

async function renderInsights() {
    const data = await apiGet('/overview');
    const items = data.insight;
    const iconMap = {
        'Unit Masuk': 'fa-inbox',
        'Unit Selesai': 'fa-circle-check',
        'Unit Lunas': 'fa-money-bill-wave',
        'Unit Aktif': 'fa-screwdriver-wrench',
    };
    const tintMap = {
        'Unit Masuk': 'in-blue',
        'Unit Selesai': 'in-green',
        'Unit Lunas': 'in-amber',
        'Unit Aktif': 'in-red',
    };
    const colorMap = {
        'Unit Masuk': 'text-blue-600',
        'Unit Selesai': 'text-green-600',
        'Unit Lunas': 'text-amber-600',
        'Unit Aktif': 'text-red-600',
    };
    document.getElementById('insightCards').innerHTML = items.map(it => {
        const tint = tintMap[it.label] || 'in-blue';
        const color = colorMap[it.label] || it.color;
        return `
        <div class="insight-card ${tint}">
            <div class="insight-top ${color}">${it.label}</div>
            <span class="insight-icon ${color}"><i class="fa-solid ${iconMap[it.label] || 'fa-chart-simple'}"></i></span>
            <div class="insight-val">${it.value}</div>
            <div class="insight-label">Unit</div>
        </div>`;
    }).join('');
}

// ─────────────────────────────────────────────
// CHARTS
// ─────────────────────────────────────────────

let statusChart;

function getChartHeight() {
    return window.innerWidth < 640 ? 220 : 215;
}

function getCommonOpts() {
    return {
        chart: { fontFamily: 'Inter, system-ui, sans-serif', toolbar: { show: false } },
        grid: { borderColor: chartGridColor() },
        theme: { mode: isDark() ? 'dark' : 'light' },
    };
}

// ─────────────────────────────────────────────
// STATISTIK STATUS TRANSAKSI (ref: statistic-reference.png)
// Data real dari backend (GET /api/statistics/status → by_status).
// STATUS_META = tampilan (warna/icon) per status form yang sah.
// ─────────────────────────────────────────────
const STATUS_META = [
    { name: 'DITERIMA',    color: '#0ea5e9', cls: 'sm-sky',     icon: 'fa-inbox' },
    { name: 'ANALISA',     color: '#64748b', cls: 'sm-slate',   icon: 'fa-magnifying-glass' },
    { name: 'KONFIRMASI',  color: '#f97316', cls: 'sm-orange',  icon: 'fa-clipboard-check' },
    { name: 'WAIT PART',   color: '#ca8a04', cls: 'sm-gold',    icon: 'fa-hourglass-half' },
    { name: 'REPAIR',      color: '#2563eb', cls: 'sm-blue',    icon: 'fa-screwdriver-wrench' },
    { name: 'DONE',        color: '#16a34a', cls: 'sm-green',   icon: 'fa-circle-check' },
    { name: 'CASH',        color: '#059669', cls: 'sm-emerald', icon: 'fa-circle-dollar-sign' },
    { name: 'CANCEL',      color: '#dc2626', cls: 'sm-red',     icon: 'fa-circle-xmark' },
    { name: 'FAILED',      color: '#dc2626', cls: 'sm-red',     icon: 'fa-triangle-exclamation' },
];

async function statusCounts() {
    try {
        const st = await apiGet('/statistics/status');
        const byName = {};
        ((st && st.by_status) || []).forEach(r => { byName[r.name] = Number(r.value) || 0; });
        return STATUS_META.map(m => ({ ...m, value: byName[m.name] || 0 }));
    } catch (_) {
        return STATUS_META.map(m => ({ ...m, value: 0 }));
    }
}

async function initCharts() {
    const co = getCommonOpts();
    const rows = await statusCounts();
    const data = rows.map(s => s.value);
    const max = Math.max(1, ...data);

    // Statistik Status Transaksi — Smooth Line/Area per status (real)
    const discrete = rows.map((s, i) => ({
        seriesIndex: 0,
        dataPointIndex: i,
        fillColor: s.color,
        strokeColor: isDark() ? '#111118' : '#ffffff',
        size: 5,
    }));
    statusChart = new ApexCharts(document.querySelector('#chartStatusTransaksi'), {
        ...co,
        chart: { ...co.chart, type: 'area', height: getChartHeight(), toolbar: { show: false }, zoom: { enabled: false } },
        series: [{ name: 'Transaksi', data: data }],
        xaxis: {
            categories: rows.map(s => s.name),
            labels: { style: { fontSize: '9px', fontWeight: 600 }, rotate: 0, trim: false },
            axisBorder: { show: false },
            axisTicks: { show: false },
        },
        yaxis: { min: 0, max: max + 1, tickAmount: Math.min(max + 1, 7), labels: { style: { fontSize: '10px' } } },
        grid: { borderColor: chartGridColor(), strokeDashArray: 4, xaxis: { lines: { show: false } }, yaxis: { lines: { show: true } } },
        colors: ['#3b82f6'],
        fill: { type: 'gradient', gradient: { shadeIntensity: 1, opacityFrom: 0.35, opacityTo: 0.02 } },
        stroke: { curve: 'smooth', width: 3 },
        markers: { size: 0, strokeWidth: 2, discrete },
        dataLabels: {
            enabled: true,
            formatter: v => v,
            offsetY: -13,
            style: { fontSize: '10px', fontWeight: '800' },
            background: { enabled: true, foreColor: '#0f172a', background: '#ffffff', borderRadius: 7, padding: 4, opacity: 0.95, dropShadow: { enabled: false } },
        },
        legend: { show: false },
        tooltip: { y: { formatter: v => v + ' unit' } },
        responsive: [{
            breakpoint: 640,
            options: { chart: { height: 220 }, xaxis: { labels: { style: { fontSize: '8px' } } } },
        }],
    });
    statusChart.render();
}

function updateChartTheme() {
    if (statusChart) statusChart.updateOptions({ theme: { mode: isDark() ? 'dark' : 'light' }, grid: { borderColor: chartGridColor() } });
}

// ─────────────────────────────────────────────
// DASHBOARD ANALYTICS (ref: konten.png)
// ─────────────────────────────────────────────

async function renderStatusMini() {
    const grid = document.getElementById('statusMiniGrid');
    const banner = document.getElementById('insightStatus');
    if (!grid) return;
    const rows = await statusCounts();
    const total = rows.reduce((a, b) => a + b.value, 0);
    const pct = v => total > 0 ? (v / total * 100).toFixed(1) + '%' : '0.0%';
    grid.innerHTML = rows.map(c => `
        <div class="sm-card ${c.cls}">
            <div class="sm-top"><i class="fa-solid ${c.icon}"></i>${c.name}</div>
            <div class="sm-bot"><span class="sm-num">${c.value}</span><span class="sm-pct">${pct(c.value)}</span></div>
        </div>
    `).join('');
    if (banner) {
        if (!total) {
            banner.innerHTML = `<span class="insight-ava insight-ava-ai"><i class="fa-solid fa-robot"></i></span>`
                + `<p><b>Insight AI:</b> Belum ada transaksi tercatat.</p>`
                + `<span class="insight-side"><i class="fa-solid fa-chart-line"></i></span>`;
            return;
        }
        const top = rows.slice().sort((a, b) => b.value - a.value)[0];
        banner.innerHTML = `<span class="insight-ava insight-ava-ai"><i class="fa-solid fa-robot"></i></span>`
            + `<p><b>Insight AI:</b> ${top.name} mendominasi <b>${pct(top.value)} (${top.value} unit)</b> dari total transaksi.`
            + ` Teknisi sedang fokus melakukan pengerjaan perbaikan unit.</p>`
            + `<span class="insight-side"><i class="fa-solid fa-chart-line"></i></span>`;
    }
}

function goDamageFilter(name) {
    _txQuery = name || '';
    _txPage = 1;
    const s = document.getElementById('txSearch');
    if (s) s.value = _txQuery;
    showTransaksi();
}

function damageIcon(name) {
    const n = (name || '').toLowerCase();
    if (n.includes('layar') || n.includes('lcd')) return 'fa-mobile-screen-button';
    if (n.includes('baterai') || n.includes('batre')) return 'fa-battery-half';
    if (n.includes('charg') || n.includes('cas ')) return 'fa-plug-circle-bolt';
    if (n.includes('speaker') || n.includes('suara')) return 'fa-volume-high';
    if (n.includes('kamera') || n.includes('camera')) return 'fa-camera';
    if (n.includes('water') || n.includes('air')) return 'fa-droplet';
    if (n.includes('mesin') || n.includes('mati') || n.includes('nyala')) return 'fa-microchip';
    if (n.includes('software') || n.includes('bootloop') || n.includes('sinyal')) return 'fa-code';
    return 'fa-screwdriver-wrench';
}

const DAMAGE_COLORS = ['#dc2626', '#f97316', '#f59e0b', '#22c55e', '#0ea5e9', '#64748b'];

async function renderDamageSection() {
    const rank = document.getElementById('damageRank');
    const hl = document.getElementById('damageHighlight');
    const banner = document.getElementById('insightDamage');
    if (!rank) return;
    try {
        const damageData = await apiGet('/statistics/damage');
        const items = (damageData.categories || []).map((c, i) => ({
            name: c, value: (damageData.data || [])[i] || 0,
        })).sort((a, b) => b.value - a.value);
        const total = items.reduce((a, b) => a + b.value, 0);
        const max = items.length ? items[0].value : 0;
        const pct = v => total > 0 ? Math.round(v / total * 100) + '%' : '0%';
        if (!items.length || total === 0) {
            rank.innerHTML = `<div class="text-center text-sm text-gray-400 py-6">Belum ada data kerusakan minggu ini.</div>`;
            if (hl) hl.innerHTML = '';
            if (banner) banner.innerHTML = `<span class="insight-ava"><i class="fa-solid fa-lightbulb"></i></span><p><b>Insight:</b> Belum ada data kerusakan minggu ini.</p>`;
            return;
        }
        const top5 = items.slice(0, 5);
        rank.innerHTML = top5.map((it, i) => {
            const color = DAMAGE_COLORS[i % DAMAGE_COLORS.length];
            const w = max > 0 ? Math.max(4, Math.round(it.value / max * 100)) : 0;
            return `
            <div class="dr-row" onclick="goDamageFilter('${escapeHtml(it.name).replace(/'/g, "\\'")}')" title="Lihat di Transaksi">
                <span class="dr-rank"><i class="fa-solid ${damageIcon(it.name)}"></i></span>
                <span class="dr-label">${String(i + 1).padStart(2, '0')}. ${escapeHtml(it.name)}</span>
                <div class="dr-track"><div class="dr-fill" style="width:${w}%;background:${color}"></div></div>
                <div class="dr-stat"><div class="dr-unit">${it.value} Unit</div><div class="dr-pct">${pct(it.value)}</div></div>
            </div>`;
        }).join('');
        if (hl) {
            const t3 = items.slice(0, 3);
            const order = t3.length === 3 ? [t3[1], t3[0], t3[2]] : t3;
            hl.innerHTML = order.map(it => {
                const r = items.indexOf(it) + 1;
                const first = r === 1 ? ' hl-first' : '';
                return `
                <div class="hl-card${first}" onclick="goDamageFilter('${escapeHtml(it.name).replace(/'/g, "\\'")}')" title="Lihat di Transaksi">
                    <div class="hl-tag">#${r} ${escapeHtml(it.name)}</div>
                    <div><span class="hl-num">${it.value}</span> <span class="hl-unit">Unit</span></div>
                    <div class="hl-bot"><span class="hl-share">${pct(it.value)} dari total</span></div>
                </div>`;
            }).join('');
        }
        if (banner) {
            const a = items[0], b = items[1];
            const txt = b
                ? `<b>Insight:</b> Kerusakan <b>${escapeHtml(a.name)} (${pct(a.value)})</b> dan <b>${escapeHtml(b.name)} (${pct(b.value)})</b> mendominasi minggu ini.`
                : `<b>Insight:</b> Kerusakan <b>${escapeHtml(a.name)} (${pct(a.value)})</b> mendominasi minggu ini.`;
            banner.innerHTML = `<span class="insight-ava"><i class="fa-solid fa-lightbulb"></i></span><p>${txt}</p><button type="button" class="insight-act" onclick="showTransaksi()">Lihat Rekomendasi <i class="fa-solid fa-arrow-up-right"></i></button>`;
        }
    } catch (err) {
        rank.innerHTML = `<div class="text-center text-sm text-gray-400 py-6">Gagal memuat data kerusakan.</div>`;
    }
}

// ─────────────────────────────────────────────
// SIDEBAR NAV
// ─────────────────────────────────────────────

function initNav() {
    const links = document.querySelectorAll('.nav-link');
    links.forEach(link => {
        link.addEventListener('click', function (e) {
            e.preventDefault();
            const page = this.dataset.page;
            if (page === 'servisbaru') {
                showPage('receive');
            } else if (page === 'dashboard') {
                showPage('dashboard');
            } else if (page === 'transaksi') {
                showTransaksi();
            } else if (page === 'pelanggan') {
                showPelanggan();
            } else if (page === 'garansi') {
                showGaransi();
            } else if (page === 'sparepart') {
                showSparepart();
            } else if (page === 'keuangan') {
                showKeuangan();
            } else if (page === 'akun') {
                showAkun();
            } else {
                showPage('transaksi');
            }
            if (window.innerWidth < 640) toggleSidebar(false);
        });
    });

    const mobileItems = document.querySelectorAll('.mobile-nav-item');
    mobileItems.forEach(item => {
        item.addEventListener('click', function () {
            mobileItems.forEach(i => i.classList.remove('active'));
            this.classList.add('active');
            const page = this.dataset.page;
            if (page === 'transaksi') {
                showTransaksi();
            } else if (page === 'pelanggan') {
                showPelanggan();
            } else if (page === 'garansi') {
                showGaransi();
            } else if (page === 'sparepart') {
                showSparepart();
            } else if (page === 'keuangan') {
                showKeuangan();
            } else if (page === 'akun') {
                showAkun();
            } else if (page === 'servisbaru') {
                showPage('receive');
            } else {
                showPage('dashboard');
            }
        });
    });
}

// ─────────────────────────────────────────────
// LOGIN FLOW
// ─────────────────────────────────────────────

function showLogin() {
    document.getElementById('loginScreen').classList.remove('hidden-login');
    const u = document.getElementById('loginUsername');
    const p = document.getElementById('loginPasscode');
    const rm = document.getElementById('rememberMe');
    if (rm) rm.checked = getRemember();
    if (u) u.value = getRemember() ? getSavedUsername() : '';
    if (p) p.value = '';
    clearLoginError();
    const target = (u && u.value && p) ? p : u;
    if (target) setTimeout(() => target.focus({ preventScroll: true }), 60);
}

function hideLogin() {
    document.getElementById('loginScreen').classList.add('hidden-login');
}

function setLoginError(msg) {
    const box = document.getElementById('loginError');
    document.getElementById('loginErrorText').textContent = msg;
    box.classList.remove('hidden');
    box.classList.remove('shake');
    void box.offsetWidth;
    box.classList.add('shake');
}

function clearLoginError() {
    document.getElementById('loginError').classList.add('hidden');
}

//: Label role yang enak dibaca buat sidebar. Role di DB bisa campur huruf
//: besar-kecil ("ADMIN", "Teknisi", "Kasir") dan ada alias (PEMILIK =
//: PENGELOLA). Super Admin kini role TERPISAH dari Admin, jadi labelnya
//: berbeda -- kalau tidak, akun developer akan tampil sebagai Manager Toko.
const ROLE_LABEL = {
    ADMIN: 'Administrator',
    SUPERADMIN: 'Super Admin',
    'SUPER ADMIN': 'Super Admin',
    SUPER_ADMIN: 'Super Admin',
    ADMIN_SPAREPART: 'Admin Sparepart',
    'ADMIN SPAREPART': 'Admin Sparepart',
    KASIR: 'Kasir',
    TEKNISI: 'Teknisi',
    PENGELOLA: 'Pengelola',
    PEMILIK: 'Pengelola',
    INVESTOR: 'Investor',
};

function labelRole(role) {
    const key = String(role || '').trim().toUpperCase();
    return ROLE_LABEL[key] || (role ? String(role) : 'Tanpa role');
}

function setAdminUI(user) {
    const name = user.display_name || 'Administrator';
    const initial = name.charAt(0).toUpperCase();
    document.getElementById('adminName').textContent = name;
    // Sebelumnya baris role di sidebar tulisan "Administrator" itu HARDCODE di
    // index.html dan tidak pernah berubah -- jadi akun Kasir/Teknisi/Pengelola
    // tetap tampil/admin di situ. Sekarang ikut dari data akun.
    const roleEl = document.getElementById('adminRole');
    if (roleEl) roleEl.textContent = labelRole(user.role);
    const avatar = document.querySelector('#appSidebar .rounded-full.flex');
    if (avatar) avatar.textContent = initial;
    const welcome = document.querySelector('.app-topbar h1 span.text-brand-500');
    if (welcome) welcome.textContent = user.display_name || 'Admin';
    // Menu Kelola Akun hanya untuk Super Admin / Admin (selaras dengan
    // `require_admin` di backend). Alias lain ikut dipastikan supaya role yang
    // ditulis bebas di DB tidak diam-diam kehilangan menu.
    const _rk = String(user.role || '').trim().toUpperCase();
    const isAdmin = ['SUPERADMIN', 'SUPER ADMIN', 'SUPER_ADMIN', 'DEV', 'DEVELOPER',
        'ADMIN', 'MANAGER'].includes(_rk);
    document.querySelectorAll('[data-page="akun"]').forEach(el => {
        el.style.display = isAdmin ? '' : 'none';
    });
    try { window._isAdmin = isAdmin; } catch (_) {}
    // P2-15: capability per role (cermin authority matrix backend).
    setRoleCapabilities(user.role);
}

function showAkun() {
    // Fail-CLOSED: `undefined` (belum ada sesi) diperlakukan sama dengan false.
    // Dulu hanya `=== false` yang diblokir, jadi sebelum `setAdminUI` selesai
    // halamannya tetap bisa dibuka.
    if (window._isAdmin !== true) {
        toast('Hanya Admin/Super Admin yang boleh membuka Kelola Akun.');
        showPage('dashboard');
        return;
    }
    showPage('akun'); renderAkun();
}

async function loadDashboard() {
    await Promise.all([renderStarCards(), renderInsights(), initCharts(), renderStatusMini(), renderDamageSection()]);
}

// ─────────────────────────────────────────────
// HALAMAN TRANSAKSI
// ─────────────────────────────────────────────

const TX_STATUS_LABEL = {
    // Kanonis FINAL LOCK (P2-15: terminology mengikuti Project A).
    DITERIMA: 'Diterima',
    ANALISA: 'Analisa',
    KONFIRMASI: 'Konfirmasi',
    'WAIT PART': 'Wait Part',
    REPAIR: 'Repair',
    DONE: 'Done',
    CASH: 'Cash',
    CANCEL: 'Cancel',
    FAILED: 'Failed',
    // Alias baca legacy / nota (tidak bisa ditulis lagi).
    RECEIVED: 'Diterima',
    DIAGNOSA: 'Analisa',
    DIAGNOSIS: 'Analisa',
    MENUNGGU_SPAREPART: 'Wait Part',
    WAIT_PART: 'Wait Part',
    WAITING_PART: 'Wait Part',
    PERBAIKAN: 'Repair',
    REPARASI: 'Repair',
    SELESAI: 'Done',
    COMPLETED: 'Done',
    READY: 'Done',
    WAITING_APPROVAL: 'Tunggu Konfirmasi',
    QC: 'QC',
    REVIEW: 'Review',
    GAGAL: 'Failed',
    BATAL: 'Cancel',
    CANCELLED: 'Cancel',
    FILED: 'Arsip (legacy)',
};

//: Opsi dropdown status (Project A): label persis seperti A.
const STATUS_OPTIONS = [
    { value: 'DITERIMA', label: 'Diterima' },
    { value: 'ANALISA', label: 'Analisa' },
    { value: 'KONFIRMASI', label: 'Konfirmasi' },
    { value: 'WAIT PART', label: 'Wait Part' },
    { value: 'REPAIR', label: 'Repair' },
    { value: 'DONE', label: 'Done' },
    { value: 'CASH', label: 'Cash' },
    { value: 'CANCEL', label: 'Cancel' },
    { value: 'FAILED', label: 'Failed' },
];

//: Status closing yang hanya boleh diubah oleh role ber-authority closing
//: (Admin/Kasir) — cerminan CLOSING_STATUSES di backend/authority.py.
const CLOSING_STATUS_KEYS = ['CASH', 'CANCEL', 'FAILED'];
//: Cash hanya boleh dari DONE (rule Project A: Kasir hanya Done -> Cash).
const CASH_ONLY_FROM = 'DONE';

//: Opsi status yang boleh ditampilkan untuk role tertentu (rule Project A).
function statusOptionsFor(roleKey, currentStatus) {
    const r = (roleKey || 'admin').toLowerCase();
    const cur = (currentStatus || '').toUpperCase();
    const out = [];
    for (const o of STATUS_OPTIONS) {
        if (r === 'teknisi') {
            // Teknisi tidak boleh menutup proses secara finansial.
            if (CLOSING_STATUS_KEYS.indexOf(o.value) !== -1) continue;
        }
        if (r === 'kasir') {
            // Kasir hanya boleh menutup Cash dari status DONE.
            if (o.value === 'CASH' && cur !== 'DONE' && cur !== 'CASH') continue;
        }
        out.push(o);
    }
    return out;
}

function renderStatusOptions(el, roleKey, currentStatus) {
    if (!el) return;
    const opts = statusOptionsFor(roleKey, currentStatus);
    el.innerHTML = opts
        .map(o => '<option value="' + escapeHtml(o.value) + '"'
            + (o.value === currentStatus ? ' selected' : '') + '>'
            + escapeHtml(o.label) + '</option>')
        .join('');
}

function txStatusBadge(status) {
    const s = (status || '').toUpperCase().replace(/\s+/g, '_');
    const label = TX_STATUS_LABEL[s] || s || 'Diterima';
    return '<span class="tx-status st-' + s + '"><i class="fa-solid fa-circle"></i>' + escapeHtml(label) + '</span>';
}

function txDate(d) {
    if (!d) return '-';
    const date = new Date(d.includes('T') ? d : d + 'T00:00:00');
    if (isNaN(date)) return '-';
    return date.toLocaleDateString('id-ID', { day: '2-digit', month: 'short', year: 'numeric' });
}

const TX_PER_PAGE = 10;
let _txPage = 1;
let _txTotal = 0;
let _txTotalPages = 1;
let _txReq = 0;
let _txQuery = '';
let _txDate = '';

function txLaba(o) {
    const val = Number(o.estimate) || 0;
    return new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', minimumFractionDigits: 0 }).format(val);
}

// Sisa per unit = Harga Final - (Part + Jasa + Lain).
// Backend (finance.order_sisa) sudah menolak unit yang belum CASH atau
// modalnya belum diisi, jadi nilai null di sini berarti "belum boleh
// dihitung" - ditampilkan '-', bukan Rp 0 yang menyesatkan.
function txSisaModal(o) {
    const v = (o && o.sisa_modal);
    if (v === null || v === undefined) return '-';
    return new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', minimumFractionDigits: 0 }).format(Number(v) || 0);
}

async function renderTransaksi() {
    try { txMenuClose(); } catch (_) {}
    initTxToolbar();
    if (_txQuery.trim() || _txDate) await loadTxFiltered();
    else await loadTxPage(1);
}

function initTxToolbar() {
    const s = document.getElementById('txSearch');
    const d = document.getElementById('txDateFilter');
    if (!s || !d || s.dataset.bound) return;
    s.dataset.bound = '1';
    let t = null;
    s.addEventListener('input', () => {
        clearTimeout(t);
        t = setTimeout(() => { _txQuery = s.value; renderTransaksi(); }, 300);
    });
    d.addEventListener('change', () => { _txDate = d.value; renderTransaksi(); });
}

function txRowHtml(o, num) {
    return `<tr>
        <td class="tx-num">${num}</td>
        <td class="tx-cell-muted tx-nowrap" title="${escapeHtml(o.service_date || '')}">${txDate(o.service_date)}</td>
        <td><span class="tx-device tx-ellipsis" title="${escapeHtml(o.device || '-')}">${escapeHtml(o.device || '-')}</span></td>
        <td class="tx-cust">
            <div class="tx-line-main tx-user tx-ellipsis" title="${escapeHtml(o.customer_name || '-')}">${escapeHtml(o.customer_name || '-')}</div>
            <div class="tx-line-sub tx-cell-muted tx-ellipsis" title="${escapeHtml(o.customer_phone || '-')}">${escapeHtml(o.customer_phone || '-')}</div>
        </td>
        <td class="tx-statuscell">${txStatusBadge(o.status)}</td>
        <td class="tx-work">
            <div class="tx-line-main tx-user tx-ellipsis" title="${escapeHtml(o.damagetype || '-')}">${escapeHtml(o.damagetype || '-')}</div>
            <div class="tx-line-sub tx-cell-muted tx-ellipsis" title="${escapeHtml(o.repair_plan || '-')}">${escapeHtml(o.repair_plan || '-')}</div>
        </td>
        <td class="tx-cell-muted tx-nowrap" title="${escapeHtml(o.technician || '-')}">${escapeHtml(o.technician || '-')}</td>
        <td class="tx-laba tx-nowrap">${txLaba(o)}</td>
        <td class="tx-sisa tx-nowrap" title="Harga Final - (Modal Part + Jasa + Lain). Tampil hanya setelah status CASH dan modal diisi.">${txSisaModal(o)}</td>
        <td class="tx-aksi">
            <button type="button" class="tx-view-btn" data-txmenu-btn title="Menu" onclick="txMenuToggle(${o.id}, this)"><i class="fa-solid fa-ellipsis-vertical"></i></button>
        </td>
    </tr>`;
}

async function loadTxFiltered() {
    const body = document.getElementById('txBody');
    const empty = document.getElementById('txEmpty');
    const loading = document.getElementById('txLoading');
    const pagination = document.getElementById('txPagination');
    if (!body) return;

    const myReq = ++_txReq;
    body.innerHTML = '';
    pagination.classList.add('hidden');
    empty.classList.add('hidden');
    loading.classList.remove('hidden');

    try {
        const q = _txQuery.trim().toLowerCase();
        const rows = await apiGet('/orders/latest?limit=500');
        if (myReq !== _txReq) return;
        const hit = (rows || []).filter(o => {
            if (_txDate) {
                const d = String(o.service_date || (o.created_at || '').slice(0, 10) || '').slice(0, 10);
                if (d !== _txDate) return false;
            }
            if (q) {
                const hay = [o.no_servis, o.device, o.brand, o.model, o.customer_name, o.customer_phone, o.status, o.damagetype, o.repair_plan, o.technician]
                    .map(v => (v || '').toLowerCase()).join(' ');
                if (!hay.includes(q)) return false;
            }
            return true;
        });

        loading.classList.add('hidden');
        if (!hit.length) {
            empty.innerHTML = '<i class="fa-solid fa-magnifying-glass text-3xl mb-2 block opacity-40"></i>Tidak ada transaksi yang cocok dengan filter.';
            empty.classList.remove('hidden');
            if (document.getElementById('txInfo')) document.getElementById('txInfo').textContent = '';
            if (document.getElementById('txPageBtns')) document.getElementById('txPageBtns').innerHTML = '';
            return;
        }
        body.innerHTML = hit.map((o, i) => txRowHtml(o, i + 1)).join('');
        pagination.classList.add('hidden');
        if (document.getElementById('txPageBtns')) document.getElementById('txPageBtns').innerHTML = '';
        const info = document.getElementById('txInfo');
        if (info) info.textContent = hit.length + ' hasil filter';
    } catch (err) {
        loading.classList.add('hidden');
        empty.classList.remove('hidden');
        empty.innerHTML = '<i class="fa-solid fa-circle-exclamation text-3xl mb-2 block opacity-40"></i>Gagal memuat data.';
    }
}

async function loadTxPage(page) {
    const body = document.getElementById('txBody');
    const empty = document.getElementById('txEmpty');
    const loading = document.getElementById('txLoading');
    const pagination = document.getElementById('txPagination');
    if (!body) return;

    const myReq = ++_txReq;
    _txPage = page;
    body.innerHTML = '';
    pagination.classList.add('hidden');
    empty.classList.add('hidden');
    loading.classList.remove('hidden');

    try {
        const res = await apiGet('/orders?page=' + _txPage + '&limit=' + TX_PER_PAGE);
        if (myReq !== _txReq) return;
        _txTotal = res.total || 0;
        _txTotalPages = res.total_pages || 1;
        _txPage = res.page || _txPage;
        const rows = res.items || [];

        loading.classList.add('hidden');
        if (_txTotal === 0) {
            empty.innerHTML = '<i class="fa-solid fa-inbox text-3xl mb-2 block opacity-40"></i>Belum ada transaksi.';
            empty.classList.remove('hidden');
            if (pagination) pagination.classList.add('hidden');
            if (document.getElementById('txInfo')) document.getElementById('txInfo').textContent = '';
            if (document.getElementById('txPageBtns')) document.getElementById('txPageBtns').innerHTML = '';
            return;
        }

        const start = (_txPage - 1) * TX_PER_PAGE;
        body.innerHTML = rows.map((o, i) => txRowHtml(o, start + i + 1)).join('');

        const end = start + rows.length;
        if (pagination) {
            if (_txTotal > TX_PER_PAGE) pagination.classList.remove('hidden');
            else pagination.classList.add('hidden');
        }
        const info = document.getElementById('txInfo');
        if (info) info.textContent = 'Halaman ' + _txPage + '  ' + (start + 1) + ' - ' + end + '  (dari ' + _txTotal + ' transaksi)';

        const pageBtns = document.getElementById('txPageBtns');
        if (pageBtns) {
            pageBtns.innerHTML = '';
            const mkBtn = (txt, p, disabled, active, label) => {
                const b = document.createElement('button');
                b.type = 'button';
                b.innerHTML = txt;
                if (label) { b.title = label; b.setAttribute('aria-label', label); }
                b.className = 'tx-page-btn' + (active ? ' active' : '') + (disabled ? ' disabled' : '');
                if (!disabled) b.addEventListener('click', () => loadTxPage(p));
                return b;
            };
            pageBtns.appendChild(mkBtn('<i class="fa-solid fa-chevron-left"></i>', _txPage - 1, _txPage === 1, false, 'Sebelumnya'));
            for (let p = 1; p <= _txTotalPages; p++) {
                pageBtns.appendChild(mkBtn(String(p), p, false, p === _txPage));
            }
            pageBtns.appendChild(mkBtn('<i class="fa-solid fa-chevron-right"></i>', _txPage + 1, _txPage === _txTotalPages, false, 'Berikutnya'));
        }
    } catch (err) {
        loading.classList.add('hidden');
        empty.classList.remove('hidden');
        empty.innerHTML = '<i class="fa-solid fa-circle-exclamation text-3xl mb-2 block opacity-40"></i>Gagal memuat data.';
    }
}

let _txdOrder = null; // order aktif di window Detail Transaksi (read-only)

function txdCheckLabels(keys, master) {
    const map = {};
    (master || []).forEach(x => { map[x.key] = x.label; });
    return (keys || []).map(k => map[k] || k).filter(Boolean);
}

async function txDetail(id) {
    let o;
    try {
        o = await apiGet('/orders/' + id);
    } catch (err) {
        toast(err.message);
        return;
    }
    _txdOrder = o;
    const cust = o.customer || {};
    document.getElementById('txdTitle').textContent = 'TRANSAKSI #' + (o.no_servis || o.id);
    document.getElementById('txdHeadDevice').textContent = o.device || '-';
    document.getElementById('txdHeadCustomer').textContent = cust.name || '-';
    const badge = document.getElementById('txdHeadStatus');
    if (badge) {
        badge.textContent = o.status || '-';
        badge.className = 'tx-status st-' + String(o.status || '').toUpperCase().replace(/\s+/g, '_');
    }
    const row = (k, v) => `<div><span class="block text-[10.5px] font-bold uppercase tracking-wide text-gray-400">${escapeHtml(k)}</span><b class="text-[13px] text-gray-800 dark:text-gray-100">${escapeHtml(v || '-')}</b></div>`;
    document.getElementById('txdCustomer').innerHTML =
        row('No. Servis', o.no_servis) + row('Tanggal Terima', notaTgl((o.service_date || '').slice(0, 10))) +
        row('Nama Pelanggan', cust.name) + row('Nomor WhatsApp', cust.phone) +
        row('Device', o.device) + row('IMEI', o.imei) +
        row('Kunci Layar / Pola', o.device_password ? '••••••' : '-') + row('Teknisi', o.technician);
    document.getElementById('txdWork').innerHTML =
            row('Keluhan', o.damagetype) + row('Rencana Perbaikan', o.repair_plan) +
        row('Status', o.status) + row('Tgl Lunas', o.lunas_date ? notaTgl((o.lunas_date || '').slice(0, 10)) : '-')
        + row('Status Bayar', o.payment_status || '-') + row('Status Unit', (o.unit_status || 'DI TOKO') + (o.taken_at ? ' • ' + notaTgl(String(o.taken_at).slice(0, 10)) : ''));
    const fisik = txdCheckLabels(o.check_fisik, (typeof CHECK_FISIK !== 'undefined' ? CHECK_FISIK : []));
    const len = txdCheckLabels(o.check_len, (typeof CHECK_LEN !== 'undefined' ? CHECK_LEN : []));
    document.getElementById('txdChecklist').innerHTML =
        '<p class="text-[11px] font-bold uppercase tracking-wide text-gray-400 mb-1">Kondisi unit saat diterima</p>'
        + '<div class="text-[12.5px] text-gray-600 dark:text-gray-300">'
        + (fisik.length ? escapeHtml(fisik.join(' · ')) : 'Tidak ada catatan fisik')
        + ' <span class="text-gray-400">| ' + escapeHtml(len.join(' · ') || 'Unit saja') + '</span></div>';
    const rupiah = v => 'Rp ' + (Number(v) || 0).toLocaleString('id-ID');
    const final = (o.final_price !== null && o.final_price !== undefined) ? o.final_price : o.estimate;
    document.getElementById('txdFinance').innerHTML =
        row('Estimasi Biaya', rupiah(o.estimate)) + row('DP (Uang Muka)', rupiah(o.payment)) +
        row('Harga Final', rupiah(final)) + row('Modal Part', rupiah(o.part_cost)) +
        row('Sisa (Final − DP)', rupiah((Number(final) || 0) - (Number(o.payment) || 0)));
    const wbox = document.getElementById('txdWarranty');
    if (o.status === 'CASH' && o.taken_at) {
        const _txdm = (o.warranty_months !== null && o.warranty_months !== undefined) ? o.warranty_months : null;
        const end = warrantyEndFor((o.lunas_date || '').slice(0, 10), _txdm);
        wbox.innerHTML = '<span class="text-[11px] font-bold text-gray-400">GARANSI:</span>' + clrWarrantyBadge(_txdm === 0 ? 'EXPIRED' : 'VALID')
            + '<span class="text-[12px] text-gray-500 dark:text-gray-400">' + escapeHtml(warrantyLabel(_txdm) + (end ? ' s/d ' + notaTgl(end) : '')) + '</span>';
    } else if (o.status === 'CASH') {
        wbox.innerHTML = '<span class="text-[11px] font-bold text-gray-400">GARANSI:</span>' + clrWarrantyBadge('VALID')
            + '<span class="text-[12px] text-gray-500 dark:text-gray-400">30 hari (awal masa menunggu sinkronisasi)</span>';
    } else {
        wbox.innerHTML = '<span class="text-[12px] text-gray-400">Garansi aktif saat status Cash (transaksi terealisasi).</span>';
    }
    const wb = document.getElementById('txdWarrantyBtn');
    if (wb) wb.classList.toggle('hidden', o.status !== 'CASH');
    const cbox = document.getElementById('txdClaims');
    cbox.innerHTML = '<span class="text-[12px] text-gray-400"><i class="fa-solid fa-circle-notch fa-spin"></i> Memuat histori klaim...</span>';
    // P2-15: panel pemakaian part + tombol refund (authority-gated).
    const pbox = document.getElementById('txdParts');
    if (pbox) pbox.innerHTML = '<span class="text-[12px] text-gray-400"><i class="fa-solid fa-circle-notch fa-spin"></i> Memuat pemakaian part...</span>';
    applyRoleUI(document.getElementById('pageTxDetail') || document);
    try { await loadUnitParts(o.id); } catch (_) {}
    document.getElementById('pageTxDetail').classList.add('open');
    try {
        const rows = await apiGet('/claims/by-service/' + o.id);
        cbox.innerHTML = '<p class="text-[11px] font-bold uppercase tracking-wide text-gray-400 mb-1.5">Histori klaim (' + rows.length + ')</p>'
            + (rows.length ? rows.map(c => `
                <div class="clr-result">
                    <div class="flex items-center justify-between gap-2 flex-wrap">
                        <b class="text-[12.5px]">${escapeHtml(c.claim_no)}</b>
                        <span class="flex gap-1.5">${clrStatusBadge(c.claim_status)}${clrStatusBadge(c.decision)}</span>
                    </div>
                    <div class="text-[11px] text-gray-400 mt-0.5">${escapeHtml(c.complaint || '')}</div>
                </div>`).join('')
                : '<div class="text-[12px] text-gray-400">Belum ada claim untuk servis ini.</div>');
    } catch (_) {
        cbox.innerHTML = '<div class="text-[12px] text-gray-400">Histori klaim tidak dapat dimuat.</div>';
    }
}

function closeTxDetail() {
    document.getElementById('pageTxDetail').classList.remove('open');
    _txdOrder = null;
}

function txdGoEdit() {
    const o = _txdOrder;
    closeTxDetail();
    if (o) openUpdateServis(o);
}

function txdPrintNota() {
    const o = _txdOrder;
    if (!o) return;
    const cust = o.customer || {};
    _lastNota = {
        no: o.no_servis || '-',
        tgl: (o.service_date || '').slice(0, 10) || new Date().toISOString().slice(0, 10),
        nama: cust.name || '',
        phone: cust.phone || '',
        device: o.device || '',
        damage: o.damagetype || '',
        plan: o.repair_plan || '',
        estimate: Number(o.estimate) || 0,
        dp: Number(o.payment) || 0,
        technician: o.technician || '',
        status: o.status || '',
        imei: o.imei || '',
        password: o.device_password || '',
    };
    try { _lastNota.checklist = { fisik: o.check_fisik || [], len: o.check_len || ['unit_saja'] }; } catch (_) {}
    closeTxDetail();
    openNota();
}

function txdPrintWarranty() {
    const o = _txdOrder;
    if (!o || o.status !== 'CASH') return;
    const cust = o.customer || {};
    const cash = ((o.lunas_date || '').slice(0, 10)) || new Date().toISOString().slice(0, 10);
    const final = (o.final_price !== null && o.final_price !== undefined) ? o.final_price : (Number(o.estimate) || 0);
    const mths = (o.warranty_months !== null && o.warranty_months !== undefined) ? o.warranty_months : null;
    _lastWarranty = {
        kind: 'WARRANTY',
        no: o.no_servis || '-',
        tgl: cash,
        nama: cust.name || '',
        phone: cust.phone || '',
        device: o.device || '',
        imei: o.imei || '',
        plan: o.repair_plan || '',
        technician: o.technician || '',
        final: Number(final) || 0,
        part: Number(o.part_cost) || 0,
        warranty_months: mths === null ? 1 : mths,
        warranty_label: warrantyLabel(mths),
        warranty_days: WARRANTY_DAYS,
        warranty_end: warrantyEndFor(cash, mths),
        status: 'CASH',
    };
    _notaMode = 'WARRANTY';
    renderWarrantyNotaPreview(_lastWarranty);
    renderWarrantyNotaDigital(_lastWarranty);
    const fb = document.getElementById('notaFeedback');
    if (fb) fb.classList.add('hidden');
    const win = document.getElementById('pageNota');
    try { document.body.appendChild(win); } catch (_) {}
    win.style.zIndex = '9600';
    win.classList.add('open');
}

function txdGoClaim() {
    const keyword = (_txdOrder && _txdOrder.no_servis) || '';
    closeTxDetail();
    openClaimReceive();
    if (keyword) {
        const s = document.getElementById('clrSearch');
        if (s) s.value = keyword;
        claimRSearch();
    }
}

let _txEditId = null;
let _txEditCustomerId = null;

async function txEdit(id) {
    let o;
    try {
        o = await apiGet('/orders/' + id);
    } catch (err) {
        toast(err.message);
        return;
    }
    openUpdateServis(o);
}

async function txDel(id) {
    if (!confirm('Hapus transaksi #' + id + '? Data yang dihapus tidak bisa dikembalikan.')) return;
    try {
        await apiDel('/orders/' + id);
        txMenuClose();
        await renderTransaksi();
    } catch (err) {
        toast(err.message);
    }
}

// Menu titik-3 kolom Aksi Transaksi (Detail / Ubah / Hapus) — pola sama seperti plMenu.
let _txMenuId = null;

function txMenuToggle(id, btn) {
    const menu = document.getElementById('txMenu');
    if (!menu) return;
    if (_txMenuId === id && !menu.classList.contains('hidden')) { txMenuClose(); return; }
    closeRowMenus('txMenu');
    _txMenuId = id;
    menu.dataset.id = id;
    menu.classList.remove('hidden');
    const r = btn.getBoundingClientRect();
    const mw = 200, mh = 160;
    let left = Math.min(r.right - mw, window.innerWidth - mw - 8);
    left = Math.max(8, left);
    let top = r.bottom + 6;
    if (top + mh > window.innerHeight - 8) top = Math.max(8, r.top - mh - 6);
    menu.style.left = left + 'px';
    menu.style.top = top + 'px';
}

function txMenuClose() {
    const menu = document.getElementById('txMenu');
    if (menu) menu.classList.add('hidden');
    _txMenuId = null;
}

if (!window._txMenuBound) {
    window._txMenuBound = true;
    document.addEventListener('click', function (e) {
        const menu = document.getElementById('txMenu');
        if (!menu || menu.classList.contains('hidden')) return;
        if (e.target.closest('#txMenu') || e.target.closest('[data-txmenu-btn]')) return;
        txMenuClose();
    });
    document.addEventListener('keydown', function (e) {
        if (e.key !== 'Escape') return;
        txMenuClose();
    });
    window.addEventListener('resize', txMenuClose);
    document.addEventListener('scroll', function () { txMenuClose(); }, true);
}

function txMenuAct(act) {
    const menu = document.getElementById('txMenu');
    const id = Number((menu || {}).dataset.id);
    txMenuClose();
    if (!id) return;
    if (act === 'detail') txDetail(id);
    else if (act === 'edit') txEdit(id);
    else if (act === 'hapus') txDel(id);
}

// Penutup bersama menu titik-3 semua tabel (kecuali yang sedang dibuka).
// Mencegah dua popup menu tumpuk (z-index sama).
function closeRowMenus(exceptId) {
    try {
        ['txMenu', 'plMenu', 'grMenu', 'spMenu', 'kuMenu'].forEach(mid => {
            if (mid === exceptId) return;
            const m = document.getElementById(mid);
            if (m) m.classList.add('hidden');
        });
        if (exceptId !== 'txMenu') _txMenuId = null;
        if (exceptId !== 'plMenu') _plMenuId = null;
        if (exceptId !== 'grMenu') { _grMenuIdx = null; try { _grMenuSid = null; } catch (_) {} }
        if (exceptId !== 'spMenu') _spMenuId = null;
        if (exceptId !== 'kuMenu') _kuMenuKey = null;
    } catch (_) {}
}

// Menu titik-3 kolom Aksi Garansi (Detail / Klaim) — kunci service_order_id
// (fallback idx bila id tak cocok, mis. data berubah di tengah jalan).
let _grMenuSid = null;
let _grMenuIdx = null;

function grMenuToggle(sid, idx, btn) {
    const menu = document.getElementById('grMenu');
    if (!menu) return;
    if (_grMenuSid === sid && !menu.classList.contains('hidden')) { grMenuClose(); return; }
    closeRowMenus('grMenu');
    _grMenuSid = sid;
    _grMenuIdx = idx;
    menu.dataset.sid = sid;
    menu.dataset.idx = idx;
    menu.classList.remove('hidden');
    const r = btn.getBoundingClientRect();
    const mw = 200, mh = 110;
    let left = Math.min(r.right - mw, window.innerWidth - mw - 8);
    left = Math.max(8, left);
    let top = r.bottom + 6;
    if (top + mh > window.innerHeight - 8) top = Math.max(8, r.top - mh - 6);
    menu.style.left = left + 'px';
    menu.style.top = top + 'px';
}

function grMenuClose() {
    const menu = document.getElementById('grMenu');
    if (menu) menu.classList.add('hidden');
    _grMenuSid = null;
    _grMenuIdx = null;
}

if (!window._grMenuBound) {
    window._grMenuBound = true;
    document.addEventListener('click', function (e) {
        const menu = document.getElementById('grMenu');
        if (!menu || menu.classList.contains('hidden')) return;
        if (e.target.closest('#grMenu') || e.target.closest('[data-grmenu-btn]')) return;
        grMenuClose();
    });
    document.addEventListener('keydown', function (e) {
        if (e.key !== 'Escape') return;
        grMenuClose();
    });
    window.addEventListener('resize', grMenuClose);
    document.addEventListener('scroll', function () { grMenuClose(); }, true);
}

function grMenuAct(act) {
    const menu = document.getElementById('grMenu');
    const sid = (menu || {}).dataset.sid;
    let idx = (_grView || []).findIndex(x => x && String(x.service_order_id) === String(sid));
    if (idx < 0) idx = Number((menu || {}).dataset.idx);
    grMenuClose();
    if (idx === null || idx === undefined || Number.isNaN(idx)) return;
    if (act === 'detail') grDetail(idx);
    else if (act === 'claim') grClaim(idx);
}

// Menu titik-3 kolom Aksi Sparepart (Ubah / Hapus) — id row.
let _spMenuId = null;

function spMenuToggle(id, btn) {
    const menu = document.getElementById('spMenu');
    if (!menu) return;
    if (_spMenuId === id && !menu.classList.contains('hidden')) { spMenuClose(); return; }
    closeRowMenus('spMenu');
    _spMenuId = id;
    menu.dataset.id = id;
    menu.classList.remove('hidden');
    const r = btn.getBoundingClientRect();
    const mw = 200, mh = 110;
    let left = Math.min(r.right - mw, window.innerWidth - mw - 8);
    left = Math.max(8, left);
    let top = r.bottom + 6;
    if (top + mh > window.innerHeight - 8) top = Math.max(8, r.top - mh - 6);
    menu.style.left = left + 'px';
    menu.style.top = top + 'px';
}

function spMenuClose() {
    const menu = document.getElementById('spMenu');
    if (menu) menu.classList.add('hidden');
    _spMenuId = null;
}

if (!window._spMenuBound) {
    window._spMenuBound = true;
    document.addEventListener('click', function (e) {
        const menu = document.getElementById('spMenu');
        if (!menu || menu.classList.contains('hidden')) return;
        if (e.target.closest('#spMenu') || e.target.closest('[data-spmenu-btn]')) return;
        spMenuClose();
    });
    document.addEventListener('keydown', function (e) {
        if (e.key !== 'Escape') return;
        spMenuClose();
    });
    window.addEventListener('resize', spMenuClose);
    document.addEventListener('scroll', function () { spMenuClose(); }, true);
}

function spMenuAct(act) {
    const menu = document.getElementById('spMenu');
    const id = Number((menu || {}).dataset.id);
    spMenuClose();
    if (!id) return;
    if (act === 'edit') spEdit(id);
    else if (act === 'hapus') spDel(id);
}

// Menu titik-3 Riwayat Kas manual (Ubah / Hapus) — baris otomatis tetap gembok.
let _kuMenuKey = null;

function kuMenuToggle(source, refId, btn) {
    const menu = document.getElementById('kuMenu');
    if (!menu) return;
    const key = source + ':' + refId;
    if (_kuMenuKey === key && !menu.classList.contains('hidden')) { kuMenuClose(); return; }
    closeRowMenus('kuMenu');
    _kuMenuKey = key;
    menu.dataset.source = source;
    menu.dataset.ref = refId;
    menu.classList.remove('hidden');
    const r = btn.getBoundingClientRect();
    const mw = 200, mh = 110;
    let left = Math.min(r.right - mw, window.innerWidth - mw - 8);
    left = Math.max(8, left);
    let top = r.bottom + 6;
    if (top + mh > window.innerHeight - 8) top = Math.max(8, r.top - mh - 6);
    menu.style.left = left + 'px';
    menu.style.top = top + 'px';
}

function kuMenuClose() {
    const menu = document.getElementById('kuMenu');
    if (menu) menu.classList.add('hidden');
    _kuMenuKey = null;
}

if (!window._kuMenuBound) {
    window._kuMenuBound = true;
    document.addEventListener('click', function (e) {
        const menu = document.getElementById('kuMenu');
        if (!menu || menu.classList.contains('hidden')) return;
        if (e.target.closest('#kuMenu') || e.target.closest('[data-kumenu-btn]')) return;
        kuMenuClose();
    });
    document.addEventListener('keydown', function (e) {
        if (e.key !== 'Escape') return;
        kuMenuClose();
    });
    window.addEventListener('resize', kuMenuClose);
    document.addEventListener('scroll', function () { kuMenuClose(); }, true);
}

function kuMenuAct(act) {
    const menu = document.getElementById('kuMenu');
    const source = (menu || {}).dataset.source || 'manual';
    const refId = Number((menu || {}).dataset.ref);
    kuMenuClose();
    if (!refId) return;
    const row = (_kuView || []).find(x => x && x.source === source && Number(x.ref_id) === refId);
    const ket = row ? row.ket : '';
    if (act === 'edit') kuEditRow(source, refId);
    else if (act === 'hapus') kuDelRow(source, refId, ket);
}

// Escape menutup popup sementara (sukses Servis Baru, konfirmasi WA DONE).
// plEditPopup sudah ditutup Escape via _plMenuBound; menu row punya handler sendiri.
if (!window._popEscBound) {
    window._popEscBound = true;
    document.addEventListener('keydown', function (e) {
        if (e.key !== 'Escape') return;
        try { closeReceiveSuccessPopup(false); } catch (_) {}
        try { doneWaClose(); } catch (_) {}
    });
}

// ─────────────────────────────────────────────
// UPDATE DATA SERVIS (edit transaksi: kiri data, kanan finance + aksi)
// Finance = hitungan lokal tersimpan via PUT /api/orders (final_price + modal_*).
// ─────────────────────────────────────────────

function usVal(id) { const el = document.getElementById(id); return el ? el.value : ''; }
function usNum(id) { return parseFloat(usVal(id)) || 0; }

let _usNo = '';
let _usTgl = '';
let _usLunasDate = ''; // awal masa garansi (dikunci backend saat pelunasan penuh)
let _usStatusInit = ''; // status saat form dibuka — untuk deteksi transisi ke SELESAI
let _usTechnicianInit = ''; // teknisi dari server — dipasang lagi setelah option teknisi terisi
// Baseline checklist dari server per No. Servis — untuk dirty-guard:
// checklist hanya dikirim saat user benar-benar mengubahnya.
let _usCheckBaseline = '';

function _usServerChecklist(o) {
    const fisik = Array.isArray(o.check_fisik) ? o.check_fisik : [];
    const len = Array.isArray(o.check_len) ? o.check_len : ['unit_saja'];
    return { fisik: fisik, len: len.length ? len : ['unit_saja'] };
}

function openUpdateServis(o) {
    _txEditId = o.id;
    _usNo = o.no_servis || '';
    _usTechnicianInit = o.technician || '';
    _usTgl = (o.service_date || '').slice(0, 10) || new Date().toISOString().slice(0, 10);
    _usLunasDate = (o.cash_date || '').slice(0, 10) || '';
    _txEditCustomerId = o.customer_id || (o.customer || {}).id || null;
    document.getElementById('usTitle').textContent = 'UPDATE DATA SERVIS #' + (o.no_servis || o.id);
    document.getElementById('usHeadDevice').textContent = o.device || '-';
    document.getElementById('usHeadCustomer').textContent = (o.customer || {}).name || o.customer_name || '-';
    document.getElementById('usNama').value = (o.customer || {}).name || o.customer_name || '';
    document.getElementById('usPhone').value = (o.customer || {}).phone || o.customer_phone || '';
    document.getElementById('usDevice').value = o.device || '';
    document.getElementById('usPassword').value = o.device_password || '';
    document.getElementById('usImei').value = o.imei || '';
    document.getElementById('usDamage').value = o.damagetype || '';
    document.getElementById('usPlan').value = o.repair_plan || '';
    document.getElementById('usEstimate').value = (o.estimate !== null && o.estimate !== undefined) ? o.estimate : '';
    document.getElementById('usDp').value = (o.payment !== null && o.payment !== undefined) ? o.payment : '';
    document.getElementById('usTechnician').value = o.technician || '';
    // Finance: nilai awal dari data tersimpan (final/part sudah persisten di server).
    const _usFinalInit = (o.final_price !== null && o.final_price !== undefined) ? o.final_price
        : ((o.estimate !== null && o.estimate !== undefined) ? o.estimate : '');
    document.getElementById('usFinFinal').value = _usFinalInit;
    document.getElementById('usFinPart').value = (o.part_cost !== null && o.part_cost !== undefined) ? o.part_cost : '';
    // Modal jasa/lainnya: dari server bila sudah tersimpan (atribut transaksi),
    // selain itu kosong (mode Manual) agar tidak menimpa data.
    document.getElementById('usFinPartKe').value = 'Toko';
    document.getElementById('usFinJasaMode').value = 'Manual';
    document.getElementById('usFinJasa').value = (o.modal_jasa !== null && o.modal_jasa !== undefined) ? o.modal_jasa : '';
    document.getElementById('usFinJasaKe').value = o.technician || '';
    document.getElementById('usFinLain').value = (o.modal_lainnya !== null && o.modal_lainnya !== undefined) ? o.modal_lainnya : '';
    const _cbTanpaModal = document.getElementById('usTanpaModal');
    if (_cbTanpaModal) _cbTanpaModal.checked = !!(o.tanpa_modal);
    usSyncTanpaModal();
    // Checklist awal: SELALU dari data server per No. Servis (bukan dummy,
    // bukan store lokal). Setelah refresh pun tampil sama persis.
    const _usCheck = _usServerChecklist(o);
    applyChecklist('us', _usCheck);
    _usCheckBaseline = JSON.stringify(_usCheck);
    _checkStore[_usNo] = _usCheck;
    const _wmSel = document.getElementById('usWarrantyMonths');
    if (_wmSel) _wmSel.value = String((o.warranty_months !== null && o.warranty_months !== undefined) ? o.warranty_months : 1);
    _usStatusInit = o.status || 'DITERIMA';
    usSetStatus(o.status || 'DITERIMA');
    usFinUpdate();
    const _noteEl = document.getElementById('usStatusNote');
    if (_noteEl) _noteEl.value = '';
    usUnitRefresh(o.unit_status || 'DI TOKO', o.taken_at || null);
    try { usPaymentsLoad(o.id); } catch (_) {}
    try { usHistoryLoad(o.id); } catch (_) {}
    const fb = document.getElementById('usFeedback');
    if (fb) fb.classList.add('hidden');
    const txt = document.getElementById('usSaveText');
    if (txt) txt.textContent = 'Simpan Perubahan Servis';
    document.getElementById('pageUpdateServis').classList.add('open');
    loadUpdateTechnicians();
    try { usLoadClaimHistory(o.id); } catch (_) {}
}

function closeUpdateServis() {
    document.getElementById('pageUpdateServis').classList.remove('open');
    _txEditId = null;
    _txEditCustomerId = null;
    _usNo = '';
    _usTgl = '';
    _usLunasDate = '';
}

// ── Status Unit (DI TOKO / DIAMBIL) — dimensi terpisah dari status servis ──
let _usUnit = 'DI TOKO';
let _usTakenAt = null;

function usUnitRefresh(unitStatus, takenAt) {
    _usUnit = unitStatus || 'DI TOKO';
    _usTakenAt = takenAt || null;
    usUnitUpdate();
}

function usUnitUpdate() {
    const badge = document.getElementById('usUnitBadge');
    if (badge) {
        const taken = _usUnit === 'DIAMBIL';
        badge.innerHTML = '<i class="fa-solid fa-circle"></i>' + (taken ? 'DIAMBIL' : 'DI TOKO');
        badge.className = 'tx-status ' + (taken ? 'st-SELESAI' : 'st-KONFIRMASI');
    }
    const info = document.getElementById('usUnitTaken');
    if (info) info.textContent = (_usTakenAt ? 'Diambil: ' + txDate(String(_usTakenAt).slice(0, 10)) : '');
    const btn = document.getElementById('usHandoverBtn');
    if (btn) btn.classList.toggle('hidden', _usUnit === 'DIAMBIL');
}

async function usHandover() {
    if (!_txEditId) return;
    if (!confirm('Tandai unit sudah diserahkan ke konsumen (DIAMBIL)?')) return;
    try {
        const o = await apiPost('/orders/' + _txEditId + '/handover', {});
        usUnitRefresh(o.unit_status || 'DIAMBIL', o.taken_at || null);
        const fb = document.getElementById('usFeedback');
        if (fb) {
            fb.classList.remove('hidden');
            fb.classList.add('success');
            fb.innerHTML = '<i class="fa-solid fa-circle-check"></i> Unit tercatat DIAMBIL.';
        }
        renderTransaksi();
    } catch (err) {
        toast(err.message || 'Gagal mencatat serah terima.');
    }
}

// ── Pembayaran (jurnal payments: DP + PELUNASAN) ──
function usPayRupiah(v) {
    return 'Rp ' + (Number(v) || 0).toLocaleString('id-ID');
}

async function usPaymentsLoad(orderId) {
    const list = document.getElementById('usPayList');
    const sum = document.getElementById('usPaySummary');
    if (list) list.innerHTML = 'Memuat...';
    try {
        const d = await apiGet('/payments/by-order/' + orderId);
        if (list) {
            list.innerHTML = (d.items && d.items.length)
                ? d.items.map(p => `<div class="us-row"><span>${escapeHtml(p.kind || 'BAYAR')} • ${escapeHtml(p.method || 'CASH')}</span><b>${usPayRupiah(p.amount)}</b></div>`).join('')
                : '<span class="text-gray-400">Belum ada pembayaran.</span>';
        }
        if (sum) sum.textContent = d.payment_status + ' • Bayar ' + usPayRupiah(d.total_bayar) + ' • Sisa ' + usPayRupiah(d.sisa);
    } catch (_) {
        if (list) list.innerHTML = '<span class="text-gray-400">Gagal memuat pembayaran.</span>';
    }
}

async function usPaymentsSave() {
    if (!_txEditId) return;
    const fb = document.getElementById('usPayFeedback');
    const kind = (document.getElementById('usPayKind') || {}).value || 'PELUNASAN';
    const amount = parseFloat((document.getElementById('usPayAmount') || {}).value) || 0;
    const method = (document.getElementById('usPayMethod') || {}).value || 'CASH';
    if (fb) fb.classList.add('hidden');
    if (!(amount > 0)) {
        if (fb) {
            fb.classList.remove('hidden');
            fb.classList.add('error');
            fb.textContent = 'Nominal pembayaran harus lebih dari 0.';
        }
        return;
    }
    try {
        // P2-14: Idempotency-Key agar retry pembayaran tidak menggandakan efek.
        const d = await apiPost('/payments',
            { service_order_id: _txEditId, kind, amount, method },
            { idempotencyKey: _usPayIdemKey || (_usPayIdemKey = newIdemKey()) });
        _usPayIdemKey = null;
        const amt = document.getElementById('usPayAmount');
        if (amt) amt.value = '';
        await usPaymentsLoad(_txEditId);
        if (d.payment_status === 'LUNAS') {
            _usLunasDate = new Date().toISOString().slice(0, 10);
            try { usWarrantyUpdate(); } catch (_) {}
        }
        renderTransaksi();
        if (fb) {
            fb.classList.remove('hidden');
            fb.classList.add('success');
            fb.innerHTML = '<i class="fa-solid fa-circle-check"></i> Pembayaran tercatat (' + d.payment_status + ').';
        }
    } catch (err) {
        if (fb) {
            fb.classList.remove('hidden');
            fb.classList.add('error');
            fb.textContent = err.message || 'Gagal mencatat pembayaran.';
        }
    }
}

// ── Riwayat status (timeline per order) ──
async function usHistoryLoad(orderId) {
    const el = document.getElementById('usHistoryList');
    if (el) el.innerHTML = 'Memuat...';
    try {
        const rows = await apiGet('/orders/' + orderId + '/history');
        if (el) {
            el.innerHTML = (rows && rows.length)
                ? rows.map(h => {
                    const w = h.waktu ? String(h.waktu).slice(0, 16).replace('T', ' ') : '-';
                    const dari = h.dari_status ? escapeHtml(h.dari_status) + ' → ' : '';
                    return `<div class="us-row"><span>${dari}<b>${escapeHtml(h.ke_status || '-')}</b>${h.catatan ? ' • ' + escapeHtml(h.catatan) : ''}</span><b class="tx-cell-muted">${escapeHtml(w)}${h.oleh ? ' • ' + escapeHtml(h.oleh) : ''}</b></div>`;
                }).join('')
                : '<span class="text-gray-400">Belum ada riwayat.</span>';
        }
    } catch (_) {
        if (el) el.innerHTML = '<span class="text-gray-400">Gagal memuat riwayat.</span>';
    }
}

// ── Konfirmasi WhatsApp saat transisi status Servis ──
//
// Dua kejadian berbeda, jadi dua pesan terpisah:
//
//   DONE -> pekerjaan selesai dikerjakan. Unit siap diambil.
//   CASH -> transaksi terealisasi. Di sinilah garansi berlaku, jadi
//           pesannya pengantar untuk melengkapi Nota Garansi.
//
// Sebelumnya popup ini hanya dipicu saat CASH, padahal komentar di
// kode sama-sama menyebut DONE. DONE tidak pernah memberi konfirmasi.
let _doneWaData = null;
let _doneWaJenis = 'DONE';

function doneWaMessage(d) {
    const L = [];
    L.push('Halo ' + (d.nama || 'Kak') + ' 🙏');
    L.push('Kabar baik! Servis unit Anda sudah selesai dikerjakan ✅');
    L.push('');
    L.push('No. Servis: ' + (d.no || '-'));
    L.push('Device: ' + (d.device || '-'));
    if (d.damage) L.push('Kerusakan: ' + d.damage);
    if (d.plan) L.push('Tindakan: ' + d.plan);
    if (d.final) L.push('Biaya perbaikan: ' + usRupiah(d.final));
    L.push('');
    L.push('Unit siap diambil di SUKABUMI FLASHER.');
    L.push('Terima kasih atas kepercayaan Anda 🙏');
    return L.join('\n');
}

function cashWaMessage(d) {
    const L = [];
    L.push('Halo ' + (d.nama || 'Kak') + ' 🙏');
    L.push('Unit Anda sudah selesai dan telah kami terima.');
    L.push('');
    L.push('No. Servis: ' + (d.no || '-'));
    L.push('Device: ' + (d.device || '-'));
    L.push('Biaya: ' + usRupiah(d.final));
    const _sisaWa = (d.sisa !== undefined && d.sisa !== null) ? Number(d.sisa) || 0
        : Math.max(0, (Number(d.final) || 0) - (Number(d.dp) || 0));
    if ((Number(d.dp) || 0) > 0 || _sisaWa > 0) L.push('DP masuk: ' + usRupiah(d.dp) + ' • Sisa: ' + usRupiah(_sisaWa));
    if (d.garansi) L.push('Garansi: ' + d.garansi);
    L.push('');
    L.push('Berikut ini ringkasan unit dan masa garansinya.');
    L.push('Simpan pesan ini sebagai bukti. Terima kasih 🙏');
    return L.join('\n');
}

function doneWaShow(d, jenis) {
    _doneWaData = d || null;
    _doneWaJenis = (jenis === 'CASH') ? 'CASH' : 'DONE';
    const isCash = _doneWaJenis === 'CASH';
    const judul = document.getElementById('doneWaTitle');
    const sub = document.getElementById('doneWaSub');
    if (judul) judul.textContent = isCash ? 'Lengkapi Nota Garansi 🛡️' : 'Unit Selesai ✅';
    if (sub) sub.textContent = isCash ? 'Kirim pengantar garansi ke pelanggan?' : 'Kirim konfirmasi ke pelanggan?';
    const to = document.getElementById('doneWaTo');
    if (to) to.textContent = 'Ke: ' + ((d && d.nama) || '-') + ' • ' + ((d && d.phone) || '(no. WA kosong)');
    const pv = document.getElementById('doneWaPreview');
    if (pv) pv.textContent = isCash ? cashWaMessage(d || {}) : doneWaMessage(d || {});
    const num = notaWaNumber(d && d.phone);
    const warn = document.getElementById('doneWaWarn');
    if (warn) {
        if (!num) {
            warn.classList.remove('hidden');
            warn.textContent = 'Nomor WhatsApp kosong — isi Nomor WhatsApp lalu simpan ulang untuk mengirim.';
        } else warn.classList.add('hidden');
    }
    const send = document.getElementById('doneWaSendBtn');
    if (send) send.classList.toggle('hidden', !num);
    const ov = document.getElementById('doneWaPopup');
    if (ov) ov.classList.remove('hidden');
}

function cashWaShow(d) {
    doneWaShow(d, 'CASH');
}

function doneWaClose() {
    const ov = document.getElementById('doneWaPopup');
    if (ov) ov.classList.add('hidden');
    _doneWaData = null;
}

function doneWaSend() {
    const d = _doneWaData;
    if (!d) return;
    const isCash = _doneWaJenis === 'CASH';
    const msg = isCash ? cashWaMessage(d) : doneWaMessage(d);
    try {
        if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(msg);
    } catch (_) {}
    const num = notaWaNumber(d.phone);
    if (!num) return;
    window.open('https://wa.me/' + num + '?text=' + encodeURIComponent(msg), '_blank');
    doneWaClose();
    const fb = document.getElementById('usFeedback');
    if (fb) {
        fb.classList.remove('hidden', 'error');
        fb.classList.add('success');
        fb.innerHTML = '<i class="fa-solid fa-circle-check"></i> Membuka WhatsApp pelanggan — tekan kirim di WA untuk menyelesaikan.';
    }
}

// Status servis: SATU sumber tulis (usSetStatus) + SATU sumber baca (usGetStatus).
// Kedua kontrol (usStatus & usQuickStatus) hanya mirror dari state yang sama.
// FINAL LOCK: 9 status Bahasa Indonesia; CASH/FILED/legacy tidak valid lagi.
function usSetStatus(s) {
    const a = document.getElementById('usStatus');
    const b = document.getElementById('usQuickStatus');
    if (a) a.value = s;
    if (b) b.value = s;
    const badge = document.getElementById('usHeadStatus');
    if (badge) {
        badge.textContent = s;
        badge.className = 'tx-status st-' + String(s || '').toUpperCase().replace(/\s+/g, '_');
    }
    // Tombol Cetak Nota Penerimaan hanya relevan di awal
    // (DITERIMA/ANALISA/DIAGNOSA/KONFIRMASI). Lewat dari itu pakai nota garansi / klaim.
    const rp = document.getElementById('usReprintBtn');
    if (rp) rp.classList.toggle('hidden', !(['DITERIMA', 'ANALISA', 'KONFIRMASI'].includes(s)));
    // Panel Masa Garansi + tombol nota garansi tampil saat SELESAI.
    const wb = document.getElementById('usWarrantyBtn');
    if (wb) wb.classList.toggle('hidden', s !== 'CASH');
    const wp = document.getElementById('usWarrantyPanel');
    if (wp) wp.classList.toggle('hidden', s !== 'CASH');
    if (s === 'CASH') { try { usWarrantyUpdate(); } catch (_) {} }
    // SELESAI = pekerjaan sudah dilakukan: label berubah dari Rencana -> realisasi.
    // Tanda * merah mengikuti syarat wajib tiap status:
    // KONFIRMASI = Rencana + Estimasi; PERBAIKAN = Teknisi;
    // SELESAI = Tindakan + Teknisi; GAGAL/BATAL = Catatan.
    try {
        const planBase = (s === 'DONE' || s === 'CASH') ? 'Perbaikan / Tindakan Perbaikan' : 'Rencana Perbaikan';
        const need = (fid) => (s === 'KONFIRMASI' && (fid === 'usPlan' || fid === 'usEstimate'))
            || (s === 'REPAIR' && fid === 'usTechnician')
            || ((s === 'DONE' || s === 'CASH') && (fid === 'usPlan' || fid === 'usTechnician'))
            || ((s === 'FAILED' || s === 'CANCEL') && fid === 'usStatusNote');
        const mark = (labelId, base, fid) => {
            const el = document.getElementById(labelId);
            if (!el) return;
            el.innerHTML = base + (need(fid) ? ' <b class="text-red-500">*</b>' : '');
        };
        mark('usPlanLabel', planBase, 'usPlan');
        mark('usEstimateLabel', 'Estimasi Biaya', 'usEstimate');
        mark('usTechnicianLabel', 'Teknisi Penanggung Jawab', 'usTechnician');
        mark('usFinFinalLabel', 'Harga Final (total pembayaran pelanggan)', 'usFinFinal');
        mark('usStatusNoteLabel', 'Catatan Status (wajib untuk Gagal/Batal)', 'usStatusNote');
    } catch (_) {}
    try { usUnitUpdate(); } catch (_) {}
}

function usGetStatus() {
    const b = document.getElementById('usQuickStatus');
    const a = document.getElementById('usStatus');
    return (b && b.value) || (a && a.value) || 'DITERIMA';
}

function usRupiah(v) {
    return 'Rp ' + (Number(v) || 0).toLocaleString('id-ID');
}

function usFinUpdate() {
    const est = usNum('usEstimate');
    const dp = usNum('usDp');
    const final = usNum('usFinFinal');
    const mode = usVal('usFinJasaMode');
    const jasaEl = document.getElementById('usFinJasa');
    const part = usNum('usFinPart');
    // Modal Jasa persentase dihitung dari laba kotor SETELAH Modal Part:
    // jasa = (Harga Final - Modal Part) x persen
    const brutoJasa = Math.max(0, final - part);
    if (mode === '40' || mode === '50') {
        const auto = Math.round(brutoJasa * Number(mode) / 100);
        if (jasaEl) jasaEl.value = auto;
    }
    const jasa = usNum('usFinJasa');
    const lain = usNum('usFinLain');
    const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = usRupiah(v); };
    set('usSumEstimate', est);
    set('usSumDp', dp);
    set('usSumFinal', final);
    set('usSumPart', part);
    set('usSumJasa', jasa);
    set('usSumLain', lain);
    set('usSumSisa', final - part - jasa - lain);
    const wrap = document.getElementById('usFinLainKeWrap');
    if (wrap) wrap.classList.toggle('hidden', !(lain > 0));
    usSyncTanpaModal();
}

// Samakan tampilan penanda "Tanpa Modal" dengan isi modal yang diketik.
// - Modal sudah terisi -> checkbox dikunci OFF dan keterangannya disembunyikan
//   (backend juga menolak kombinasi itu, jadi formnya lebih cepat).
// - Modal kosong -> checkbox boleh dicentang.
function usSyncTanpaModal() {
    const cb = document.getElementById('usTanpaModal');
    const wrap = document.getElementById('usTanpaModalWrap');
    const hint = document.getElementById('usTanpaModalHint');
    if (!cb || !wrap) return;
    const total = (usNum('usFinPart') || 0) + (usNum('usFinJasa') || 0) + (usNum('usFinLain') || 0);
    const adaModal = total > 0;
    cb.disabled = adaModal;
    if (adaModal) cb.checked = false;
    wrap.classList.remove('hidden');
    if (hint) {
        hint.textContent = adaModal
            ? 'Modal sudah terisi, jadi penanda ini tidak dipakai.'
            : 'Centang HANYA kalau unit ini memang tanpa biaya (mis. hanya software, tanpa ganti part). Tanpa centang, unit CASH-nya tidak dihitung sebagai transaksi.';
        hint.classList.toggle('text-amber-600', !adaModal && !cb.checked);
    }
}

function usReprint() {
    // Cetak ulang nota penerimaan dari data form terkini (live),
    // tapi No. Servis & Tanggal terima tetap pakai data asli server
    // agar nota cetak ulang identik dengan nota awal.
    let _usCheckNow = null;
    try { _usCheckNow = collectChecklist('us'); } catch (_) {}
    _lastNota = {
        no: _usNo || document.getElementById('usTitle').textContent.replace('UPDATE DATA SERVIS #', '') || '-',
        tgl: _usTgl || new Date().toISOString().slice(0, 10),
        nama: usVal('usNama'),
        phone: usVal('usPhone'),
        device: usVal('usDevice'),
        damage: usVal('usDamage'),
        plan: usVal('usPlan'),
        estimate: usNum('usEstimate'),
        dp: usNum('usDp'),
        technician: usVal('usTechnician'),
        status: usGetStatus(),
        imei: usVal('usImei'),
        password: usVal('usPassword'),
    };
    if (_usCheckNow) _lastNota.checklist = _usCheckNow;
    openNota();
}

// Dropdown teknisi di Update Data Servis (unit + penanggung jawab modal jasa).
// Sumber sama dengan Servis Baru; dipanggil ulang tiap overlay dibuka karena
// token belum tersedia saat DOMContentLoaded.
async function loadUpdateTechnicians(fallbackFill) {
    let techs = null;
    try { techs = await apiGet('/orders/technicians'); } catch (_) {
        if (fallbackFill) { fallbackFill('usTechnician'); fallbackFill('usFinJasaKe'); }
        return;
    }
    if (!Array.isArray(techs) || !techs.length) return;
    ['usTechnician', 'usFinJasaKe'].forEach(id => {
        const sel = document.getElementById(id);
        if (!sel || sel.options.length > 1) return;
        const keep = id === 'usTechnician' ? '— Pilih Teknisi —' : '— Nama Teknisi —';
        sel.innerHTML = `<option value="">${keep}</option>` + techs.map(t => `<option value="${t}">${t}</option>`).join('');
    });
    // Option baru saja terisi async: pasang lagi teknisi dari order, kalau ada.
    if (_usTechnicianInit) {
        ['usTechnician', 'usFinJasaKe'].forEach(id => {
            const sel = document.getElementById(id);
            if (sel && Array.from(sel.options).some(o => o.value === _usTechnicianInit)) {
                sel.value = _usTechnicianInit;
            }
        });
    }
}

function initUpdateServis() {
    renderChecklist('us', 'usCheckGroups', 'Catatan kondisi awal — tidak diubah otomatis saat data servis diperbarui.', { fisik: ACTIVE_FISIK_KEYS, len: ACTIVE_LEN_KEYS });
    const techFill = (selId) => {
        const sel = document.getElementById(selId);
        if (!sel || sel.options.length > 1) return;
        const src = document.getElementById('rcTechnician');
        if (src) sel.innerHTML = src.innerHTML;
    };
    loadUpdateTechnicians(techFill);
    ['usEstimate', 'usDp', 'usFinFinal', 'usFinPart', 'usFinJasa', 'usFinLain'].forEach(id => {
        const el = document.getElementById(id);
        if (el && !el.dataset.usBound) {
            el.dataset.usBound = '1';
            el.addEventListener('input', usFinUpdate);
        }
    });
    const jm = document.getElementById('usFinJasaMode');
    if (jm && !jm.dataset.usBound) { jm.dataset.usBound = '1'; jm.addEventListener('change', usFinUpdate); }
    const cbTM = document.getElementById('usTanpaModal');
    if (cbTM && !cbTM.dataset.usBound) {
        cbTM.dataset.usBound = '1';
        cbTM.addEventListener('change', usSyncTanpaModal);
    }
    const wm = document.getElementById('usWarrantyMonths');
    if (wm && !wm.dataset.usBound) { wm.dataset.usBound = '1'; wm.addEventListener('change', usWarrantyUpdate); }
    // P2-15: opsi dropdown dibangun dari STATUS_OPTIONS + gate role (Project A).
    const _rk = (function () { try { return window._bssfRoleKey; } catch (_) { return 'custom'; } })();
    const _sa = document.getElementById('usStatus');
    renderStatusOptions(_sa, _rk, _usStatusInit);
    if (_sa && !_sa.dataset.usBound) { _sa.dataset.usBound = '1'; _sa.addEventListener('change', () => usSetStatus(_sa.value)); }
    const _sb = document.getElementById('usQuickStatus');
    renderStatusOptions(_sb, _rk, _usStatusInit);
    if (_sb && !_sb.dataset.usBound) { _sb.dataset.usBound = '1'; _sb.addEventListener('change', () => usSetStatus(_sb.value)); }
    const form = document.getElementById('updateForm');
    if (form && !form.dataset.usBound) {
        form.dataset.usBound = '1';
        form.addEventListener('submit', async function (e) {
            e.preventDefault();
            if (!_txEditId) return;
            const btn = document.getElementById('usSaveBtn');
            const txt = document.getElementById('usSaveText');
            const fb = document.getElementById('usFeedback');
            if (fb) fb.classList.add('hidden');
            if (btn) btn.disabled = true;
            if (txt) txt.textContent = 'Menyimpan...';
            try {
                const _usCheckNow = collectChecklist('us');
                const _usCheckChanged = JSON.stringify(_usCheckNow) !== _usCheckBaseline;
                const _usSt = usGetStatus();
                const _usNote = (usVal('usStatusNote') || '').trim();
                // Syarat per status (FINAL LOCK, mirror backend):
                // KONFIRMASI = Rencana + Estimasi; PERBAIKAN = Teknisi;
                // SELESAI = Tindakan + Teknisi; GAGAL/BATAL = Catatan wajib.
                const _needFail = (label) => {
                    if (fb) {
                        fb.classList.remove('hidden');
                        fb.classList.add('error');
                        fb.textContent = 'Status ' + _usSt + ' wajib melengkapi: ' + label + '.';
                    }
                };
                const _needFocus = (id) => {
                    const _first = document.getElementById(id);
                    if (_first) _first.focus({ preventScroll: true });
                    if (btn) btn.disabled = false;
                    if (txt) txt.textContent = 'Simpan Perubahan Servis';
                };
                if (_usSt === 'KONFIRMASI') {
                    const _missing = [];
                    if (!usVal('usPlan').trim()) _missing.push(['Rencana Perbaikan', 'usPlan']);
                    if (!(usNum('usEstimate') > 0)) _missing.push(['Estimasi Biaya', 'usEstimate']);
                    if (_missing.length) {
                        _needFail(_missing.map(m => m[0]).join(', '));
                        _needFocus(_missing[0][1]);
                        return;
                    }
                } else if (_usSt === 'REPAIR') {
                    if (!usVal('usTechnician').trim()) {
                        _needFail('Teknisi Penanggung Jawab');
                        _needFocus('usTechnician');
                        return;
                    }
                } else if (_usSt === 'DONE') {
                    // DONE wajib: Perbaikan/Tindakan + Teknisi + Harga Final.
                    // Harga Final = total pembayaran pelanggan; tanpa itu unit
                    // bisa "selesai" tanpa tahu harganya, dan karena
                    // kewajiban() memakai final_price ?? estimate, harga 0 ikut
                    // terhitung sebagai omzet 0 -- unit lenyap dari laporan.
                    const _missing = [];
                    if (!usVal('usPlan').trim()) _missing.push(['Perbaikan / Tindakan Perbaikan', 'usPlan']);
                    if (!usVal('usTechnician').trim()) _missing.push(['Teknisi Penanggung Jawab', 'usTechnician']);
                    if (!(usNum('usFinFinal') > 0)) _missing.push(['Harga Final (total pembayaran pelanggan)', 'usFinFinal']);
                    if (_missing.length) {
                        _needFail(_missing.map(m => m[0]).join(', '));
                        _needFocus(_missing[0][1]);
                        return;
                    }
                } else if (_usSt === 'CASH') {
                    // CASH = event realisasi (Owner Cash Model P2-15): wajib Tindakan + Teknisi.
                    //
// Modal Part & Modal Jasa SENGAJA TIDAK divalidasi di sini.
                    // Dulu ada `usNum('usFinPart') > 0` yang menolak nilai 0,
                    // padahal 0 itu sah (servis tanpa ganti part / hanya jasa).
                    // Guard itu memicu pesan "Status CASH wajib melengkapi: Modal Part"
                    // di layar SEBELUM request dikirim, jadi backend tidak pernah
                    // sempat memprosesnya. Guard backend (router orders.py) yang
                    // jadi satu-satunya penentu.
                    const _missing = [];
                    if (!usVal('usPlan').trim()) _missing.push(['Perbaikan / Tindakan Perbaikan', 'usPlan']);
                    if (!usVal('usTechnician').trim()) _missing.push(['Teknisi Penanggung Jawab', 'usTechnician']);
                    if (_missing.length) {
                        _needFail(_missing.map(m => m[0]).join(', '));
                        _needFocus(_missing[0][1]);
                        return;
                    }
                } else if (_usSt === 'FAILED' || _usSt === 'CANCEL') {
                    if (!_usNote) {
                        _needFail(_usSt === 'FAILED' ? 'Alasan kegagalan (catatan)' : 'Alasan pembatalan (catatan)');
                        _needFocus('usStatusNote');
                        return;
                    }
                }
                // OD-LOCK-04 (Owner, LOCKED): total DP unit tidak boleh melebihi
                // estimasi biaya. Mirror dari backend `statusflow.cek_dp_vs_estimasi`.
                const _usEstNow = usNum('usEstimate');
                const _usDpNow = usNum('usDp');
                if (_usEstNow > 0 && _usDpNow > _usEstNow) {
                    _needFail('DP tidak boleh lebih besar daripada estimasi biaya (estimasi Rp '
                        + Number(_usEstNow).toLocaleString('id-ID') + ', DP Rp '
                        + Number(_usDpNow).toLocaleString('id-ID') + ')');
                    _needFocus('usDp');
                    return;
                }
                const _usPayload = {
                    device: usVal('usDevice').trim(),
                    device_password: usVal('usPassword'),
                    imei: usVal('usImei').trim(),
                    damagetype: usVal('usDamage').trim(),
                    repair_plan: usVal('usPlan').trim(),
                    estimate: usNum('usEstimate'),
                    payment: usNum('usDp'),
                    final_price: usNum('usFinFinal') || 0,
                    // Modal boleh bernilai 0 (servis tanpa ganti part / hanya jasa).
                    // Kolom kosong dianggap 0 — sama seperti "Lain-lain".
                    // PENTING: jangan kirim `null` di sini. Nilai null akan
                    // tersimpan di DB dan membuat unit itu tidak bisa diubah ke
                    // status CASH selamanya, dan perhitungan labanya rusak ketika dibaca lagi.
                    part_cost: usNum('usFinPart') || 0,
                    modal_jasa: usNum('usFinJasa') || 0,
                    modal_lainnya: usNum('usFinLain') || 0,
                    // Penanda "memang tanpa modal" (servis hanya software, tanpa
                    // ganti part). Tanpa ini unit modal-0 tidak akan pernah masuk
                    // Omzet. Backend menolak kalau modalnya ternyata sudah terisi.
                    tanpa_modal: !!(document.getElementById('usTanpaModal') || {}).checked,
                    warranty_months: usWarrantyMonths(),
                    technician: usVal('usTechnician'),
                    status: _usSt,
                    status_note: _usNote || undefined,
                };
                // Checklist hanya dikirim bila user mengubahnya eksplisit.
                // Jika tidak disentuh, field dihilangkan agar data server tidak tertimpa.
                if (_usCheckChanged) {
                    _usPayload.check_fisik = _usCheckNow.fisik;
                    _usPayload.check_len = _usCheckNow.len;
                }
                await apiPut('/orders/' + _txEditId, _usPayload);
                if (_txEditCustomerId) {
                    await apiPut('/customers/' + _txEditCustomerId, {
                        name: usVal('usNama').trim(),
                        phone: usVal('usPhone').trim(),
                    });
                }
                // Segarkan momen lunas + garansi + unit dari server.
                try {
                    const _saved = await apiGet('/orders/' + _txEditId);
                    _usLunasDate = (_saved.lunas_date || '').slice(0, 10) || _usLunasDate;
                    const _wm2 = document.getElementById('usWarrantyMonths');
                    if (_wm2 && _saved.warranty_months !== null && _saved.warranty_months !== undefined) _wm2.value = String(_saved.warranty_months);
                    usUnitRefresh(_saved.unit_status || 'DI TOKO', _saved.taken_at || null);
                    try { usPaymentsLoad(_txEditId); } catch (_) {}
                    try { usHistoryLoad(_txEditId); } catch (_) {}
                } catch (_) {}
                usSetStatus(usGetStatus());
                if (_usCheckChanged) {
                    _usCheckBaseline = JSON.stringify(_usCheckNow);
                    if (_usNo) _checkStore[_usNo] = _usCheckNow;
                }
                if (fb) {
                    fb.classList.remove('hidden');
                    fb.classList.add('success');
                    fb.innerHTML = `<i class="fa-solid fa-circle-check"></i> Data servis tersimpan di server. Rincian kas di panel kanan masih hitungan lokal (belum masuk KAS).`;
                }
                renderTransaksi();
                // DONE = pekerjaan selesai -> konfirmasi ke pelanggan.
                // CASH = transaksi terealisasi -> pengantar lengkapi nota garansi.
                // Dua pesan berbeda; keduanya pakai _usStatusInit sebagai
                // pengaman supaya popup tidak muncul ulang saat status tidak berubah.
                const _sebelumnya = _usStatusInit;
                _usStatusInit = _usSt;
                const _baruKe = (target) => (_usSt === target && _sebelumnya !== target);
                let _sisa = 0;
                if (_baruKe('DONE') || _baruKe('CASH')) {
                    try {
                        const _pay = await apiGet('/payments/by-order/' + _txEditId);
                        _sisa = _pay.sisa || 0;
                    } catch (_) {}
                }
                const _pesanWa = {
                    nama: usVal('usNama').trim(),
                    phone: usVal('usPhone').trim(),
                    device: usVal('usDevice').trim(),
                    no: _usNo,
                    damage: usVal('usDamage').trim(),
                    plan: usVal('usPlan').trim(),
                    final: usNum('usFinFinal'),
                    dp: usNum('usDp'),
                    sisa: _sisa,
                    garansi: usWarrantyText(),
                };
                if (_baruKe('DONE')) {
                    doneWaShow(_pesanWa, 'DONE');
                } else if (_baruKe('CASH')) {
                    cashWaShow(_pesanWa);
                }
            } catch (err) {
                if (fb) {
                    fb.classList.remove('hidden');
                    fb.classList.add('error');
                    fb.textContent = err.message;
                }
            } finally {
                if (btn) btn.disabled = false;
                if (txt) txt.textContent = 'Simpan Perubahan Servis';
            }
        });
    }
    if (document.body.dataset.usKeys !== '1') {
        document.body.dataset.usKeys = '1';
        document.addEventListener('keydown', function (e) {
            const dw = document.getElementById('doneWaPopup');
            if (dw && !dw.classList.contains('hidden') && e.key === 'Escape') { doneWaClose(); return; }
            const win = document.getElementById('pageUpdateServis');
            if (!win || !win.classList.contains('open')) return;
            if (e.key === 'F8' || ((e.ctrlKey || e.metaKey) && String(e.key).toLowerCase() === 's')) {
                e.preventDefault();
                document.getElementById('updateForm').requestSubmit();
            }
        });
    }
}

// ─────────────────────────────────────────────
// HALAMAN GARANSI (data real backend)
// ─────────────────────────────────────────────

const GR_PER_PAGE = 10;
let _grPage = 1;
let _grQuery = '';
let _grDate = '';
let _grStatus = '';
let _grView = [];
let _grClaimOrderId = null;

// `klaim: null` = belum klaim (status diturunkan dari tanggal).
// `klaim: {...}` = sedang/dalam klaim (status Klaim).
// Daftar garansi real dari backend (GET /api/claims/warranty-summary):
// servis SELESAI + LUNAS bergaransi + klaim berjalan. GR_MOCK dipensiunkan.
// Bentuk item identik dengan mock lama: no, nama, phone, device,
// mulai, akhir, damage, plan, price, klaim{tgl,keluhan,tindakan,status}.
let _grAll = [];
let _grReq = 0;

function grDaysLeft(akhir) {
    const a = new Date(akhir + 'T00:00:00');
    const t = new Date();
    t.setHours(0, 0, 0, 0);
    if (isNaN(a)) return null;
    return Math.round((a - t) / 86400000);
}

// Status diturunkan dari tanggal agar badge selalu jujur (tahap UI).
function grState(g) {
    if (g.klaim) return { key: 'klaim', label: 'Klaim', days: grDaysLeft(g.akhir) };
    const d = grDaysLeft(g.akhir);
    if (d === null) return { key: 'aktif', label: 'Aktif', days: null };
    if (d < 0) return { key: 'expired', label: 'Expired', days: d };
    if (d <= 30) return { key: 'segera', label: 'Akan Berakhir', days: d };
    return { key: 'aktif', label: 'Aktif', days: d };
}

function grStatusBadge(g) {
    const st = grState(g);
    const cls = st.key === 'aktif' ? 'gr-aktif' : st.key === 'expired' ? 'gr-berakhir' : st.key === 'klaim' ? 'gr-klaim' : 'gr-segera';
    let extra = '';
    if (st.days !== null && st.days !== undefined) {
        extra = st.days < 0 ? ' · ' + Math.abs(st.days) + ' hari lalu' : ' · ' + st.days + ' hari lagi';
    }
    return '<span class="tx-status ' + cls + '"><i class="fa-solid fa-circle"></i>' + escapeHtml(st.label) + escapeHtml(extra) + '</span>';
}

function grFiltered() {
    const q = _grQuery.trim().toLowerCase();
    return (_grAll || []).filter(g => {
        if (q && ![g.nama, g.phone, g.device].some(f => (f || '').toLowerCase().includes(q))) return false;
        if (_grDate && !(g.mulai <= _grDate && _grDate <= g.akhir)) return false;
        if (_grStatus && grState(g).key !== _grStatus) return false;
        return true;
    });
}

function initGrToolbar() {
    const s = document.getElementById('grSearch');
    const d = document.getElementById('grDateFilter');
    const f = document.getElementById('grStatusFilter');
    if (!s || !d || !f || s.dataset.bound) return;
    s.dataset.bound = '1';
    let t = null;
    s.addEventListener('input', () => {
        clearTimeout(t);
        t = setTimeout(() => { _grQuery = s.value; _grPage = 1; renderGaransi(); }, 300);
    });
    d.addEventListener('change', () => { _grDate = d.value; _grPage = 1; renderGaransi(); });
    f.addEventListener('change', () => { _grStatus = f.value; _grPage = 1; renderGaransi(); });
}

function renderGrKpi() {
    const el = document.getElementById('grKpi');
    if (!el) return;
    const n = { total: (_grAll || []).length, aktif: 0, segera: 0, expired: 0, klaim: 0 };
    (_grAll || []).forEach(g => {
        const k = grState(g).key;
        if (k === 'aktif') n.aktif++;
        else if (k === 'segera') n.segera++;
        else if (k === 'expired') n.expired++;
        else if (k === 'klaim') n.klaim++;
    });
    const cards = [
        { label: 'Total Garansi', value: n.total, icon: 'fa-shield-halved', cls: 'sm-slate' },
        { label: 'Aktif', value: n.aktif, icon: 'fa-circle-check', cls: 'sm-green' },
        { label: 'Akan Berakhir', value: n.segera, icon: 'fa-hourglass-half', cls: 'sm-amber' },
        { label: 'Expired', value: n.expired, icon: 'fa-circle-xmark', cls: 'sm-red' },
        { label: 'Klaim', value: n.klaim, icon: 'fa-file-circle-plus', cls: 'sm-blue' },
    ];
    el.innerHTML = cards.map(c => `
        <div class="sm-card ${c.cls}">
            <div class="sm-top"><i class="fa-solid ${c.icon}"></i>${c.label}</div>
            <div class="sm-bot"><span class="sm-num">${c.value}</span><span class="sm-pct">unit</span></div>
        </div>
    `).join('');
}

function grDetail(idx) {
    const g = _grView[idx];
    if (!g) return;
    const st = grState(g);
    document.getElementById('warrantyTitle').textContent = 'Garansi — ' + g.nama;
    document.getElementById('warrantySub').textContent = g.device + ' • ' + st.label;
    const initial = (g.nama.trim().charAt(0) || '?').toUpperCase();
    document.getElementById('warrantySummary').innerHTML = `<div class="rc-cust" style="margin-bottom:12px">
        <div class="rc-cust-top"><span class="rc-cust-ava">${escapeHtml(initial)}</span>
        <div class="rc-cust-id"><b>${escapeHtml(g.nama)}</b><span>${escapeHtml(g.phone || '-')}</span></div>
        ${grStatusBadge(g)}</div></div>`;
    document.getElementById('warrantyDetail').innerHTML = `
        <div><span>No. Servis</span><b>${escapeHtml(g.no || '-')}</b></div>
        <div><span>Tgl Mulai</span><b>${txDate(g.mulai)}</b></div>
        <div><span>Tgl Akhir</span><b>${txDate(g.akhir)}</b></div>
        <div><span>Kerusakan Sebelumnya</span><b>${escapeHtml(g.damage || '-')}</b></div>
        <div><span>Rencana Perbaikan</span><b>${escapeHtml(g.plan || '-')}</b></div>
        <div><span>Nilai Servis</span><b>${plRupiah(g.price)}</b></div>`;

    // -- (1) Identitas Unit -------------------------------------------------
    // Diambil dari data unit pada servis sebelumnya. Kalau belum diisi di
    // servis itu, ditampilkan jujur sebagai "Belum diisi" -- TIDAK dikarang.
    const kosong = 'Belum diisi';
    document.getElementById('warrantyUnit').innerHTML = `
        <div><span>Merek HP</span><b>${escapeHtml((g.brand || '').trim() || kosong)}</b></div>
        <div><span>Model HP</span><b>${escapeHtml((g.model || '').trim() || kosong)}</b></div>
        <div><span>IMEI</span><b>${escapeHtml((g.imei || '').trim() || kosong)}</b></div>
        <div><span>Device</span><b>${escapeHtml(g.device || '-')}</b></div>`;

    // -- (3) Teknisi yang menangani ----------------------------------------
    document.getElementById('warrantyTeknisi').innerHTML = `
        <div><span>Teknisi Penanggung Jawab</span><b>${escapeHtml((g.teknisi || '').trim() || kosong)}</b></div>`;

    // -- (2) Riwayat Klaim Garansi -----------------------------------------
    // Hanya klaim yang benar-benar tersimpan. Kalau belum pernah ada klaim,
    // tampilkan keterangan yang diminta Owner, bukan baris kosong.
    const riwayat = Array.isArray(g.riwayat_klaim) ? g.riwayat_klaim : [];
    const elRiwayat = document.getElementById('warrantyRiwayat');
    if (!riwayat.length) {
        elRiwayat.innerHTML = `<div class="text-[11.5px] text-gray-500 dark:text-gray-400">Belum ada riwayat klaim garansi.</div>`;
    } else {
        elRiwayat.innerHTML = '<div class="space-y-2.5">' + riwayat.map((r, i) => `
            <div class="panel receive-panel">
                <div class="receive-panel-head">
                    <span class="receive-head-ico"><i class="fa-solid fa-file-circle-check"></i></span>
                    <div>
                        <h3 class="text-sm font-bold text-gray-800 dark:text-white">Klaim ${i + 1}</h3>
                        <span class="text-[10.5px] text-gray-400">${escapeHtml(r.tanggal || 'Tanpa tanggal')}${r.no_klaim ? ' · ' + escapeHtml(r.no_klaim) : ''}${r.status ? ' · ' + escapeHtml(r.status) : ''}</span>
                    </div>
                </div>
                <div class="rc-cust-grid">
                    <div><span>Tanggal Klaim</span><b>${escapeHtml(r.tanggal || kosong)}</b></div>
                    <div><span>Keluhan Pelanggan</span><b>${escapeHtml((r.keluhan || '').trim() || kosong)}</b></div>
                    <div><span>Hasil Pemeriksaan</span><b>${escapeHtml((r.hasil_pemeriksaan || '').trim() || kosong)}</b></div>
                    <div><span>Keputusan Klaim</span><b>${escapeHtml(r.keputusan || kosong)}</b></div>
                    <div><span>Tindakan Perbaikan</span><b>${escapeHtml((r.tindakan || '').trim() || kosong)}</b></div>
                    ${r.catatan_teknisi ? `<div><span>Catatan Teknisi</span><b>${escapeHtml(r.catatan_teknisi)}</b></div>` : ''}
                </div>
            </div>`).join('') + '</div>';
    }
    document.getElementById('warrantyClaim').innerHTML = g.klaim ? `
        <div class="panel receive-panel mt-3">
            <div class="receive-panel-head">
                <span class="receive-head-ico"><i class="fa-solid fa-file-circle-check"></i></span>
                <div><h3 class="text-sm font-bold text-gray-800 dark:text-white">Klaim Berjalan</h3>
                <span class="text-[10.5px] text-gray-400">${escapeHtml(g.klaim.tgl || '')} • ${escapeHtml(g.klaim.status || '')}</span></div>
            </div>
            <div class="rc-cust-grid">
                <div><span>Keluhan</span><b>${escapeHtml(g.klaim.keluhan || '-')}</b></div>
                <div><span>Tindakan</span><b>${escapeHtml(g.klaim.tindakan || '-')}</b></div>
                <div><span>Status</span><b>${escapeHtml(g.klaim.status || '-')}</b></div>
            </div>
        </div>` : '';
    document.getElementById('pageWarranty').classList.add('open');
}

function closeGrDetail() {
    document.getElementById('pageWarranty').classList.remove('open');
}

function grClaim(idx) {
    const g = _grView[idx];
    if (!g) return;
    _grClaimOrderId = g.service_order_id || null;
    document.getElementById('clName').value = g.nama || '';
    document.getElementById('clPhone').value = g.phone || '';
    document.getElementById('clDevice').value = g.device || '';
    document.getElementById('clTgl').value = new Date().toISOString().slice(0, 10);
    document.getElementById('clKeluhan').value = '';
    const fb = document.getElementById('claimFeedback');
    fb.classList.add('hidden');
    fb.classList.remove('success');
    fb.textContent = '';
    document.getElementById('pageClaim').classList.add('open');
}

function closeGrClaim() {
    document.getElementById('pageClaim').classList.remove('open');
    _grClaimOrderId = null;
}

function initClaimForm() {
    const form = document.getElementById('claimForm');
    if (!form || form.dataset.bound) return;
    form.dataset.bound = '1';
    // Klaim real: POST /api/claims/receive (record claim baru, servis lama tak diubah).
    form.addEventListener('submit', async function (e) {
        e.preventDefault();
        if (!_grClaimOrderId) return;
        const btn = document.getElementById('claimSubmitBtn');
        const txt = document.getElementById('claimSubmitText');
        const fb = document.getElementById('claimFeedback');
        const keluhan = document.getElementById('clKeluhan').value.trim();
        if (!keluhan) {
            fb.classList.remove('hidden');
            fb.innerHTML = `<i class="fa-solid fa-triangle-exclamation"></i> Isi dulu keluhan claim.`;
            return;
        }
        btn.disabled = true;
        txt.textContent = 'Menyimpan...';
        try {
            await apiPost('/claims/receive', {
                service_order_id: _grClaimOrderId,
                complaint: keluhan,
                claim_date: document.getElementById('clTgl').value || undefined,
            });
            fb.classList.remove('hidden');
            fb.classList.add('success');
            fb.innerHTML = `<i class="fa-solid fa-circle-check"></i> Klaim tercatat di server. Status garansi: <b>Klaim</b>.`;
            _grClaimOrderId = null;
            renderGaransi();
        } catch (err) {
            fb.classList.remove('hidden');
            fb.innerHTML = `<i class="fa-solid fa-triangle-exclamation"></i> ${escapeHtml(err.message || 'Gagal menyimpan klaim.')}`;
        } finally {
            btn.disabled = false;
            txt.textContent = 'Ajukan Klaim';
        }
    });
}

async function renderGaransi() {
    try { grMenuClose(); } catch (_) {}
    initGrToolbar();
    initClaimForm();
    const my = ++_grReq;
    try {
        const data = await apiGet('/claims/warranty-summary');
        if (my !== _grReq) return; // respons basi — ada request lebih baru
        _grAll = ((data && data.items) || []).map(g => ({
            service_order_id: g.service_order_id,
            no: g.no || '-',
            nama: g.nama || '-',
            phone: g.phone || '-',
            device: g.device || '-',
            mulai: g.mulai,
            akhir: g.akhir,
            damage: g.damage,
            plan: g.plan,
            price: g.price,
            klaim: g.klaim,
            // Identitas unit & teknisi: dari data servis ASAL. Backend hanya
            // pass-through apa yang sudah tersimpan; tidak ada nilai karangan.
            brand: g.brand,
            model: g.model,
            imei: g.imei,
            teknisi: g.teknisi,
            riwayat_klaim: Array.isArray(g.riwayat_klaim) ? g.riwayat_klaim : [],
        }));
    } catch (err) {
        if (my !== _grReq) return;
        _grAll = [];
        const loading = document.getElementById('grLoading');
        if (loading) loading.classList.add('hidden');
        const empty = document.getElementById('grEmpty');
        if (empty) {
            empty.innerHTML = '<i class="fa-solid fa-circle-exclamation text-3xl mb-2 block opacity-40"></i>' + escapeHtml(err.message || 'Gagal memuat data.');
            empty.classList.remove('hidden');
        }
        renderGrKpi();
        return;
    }
    renderGrKpi();
    const body = document.getElementById('grBody');
    const empty = document.getElementById('grEmpty');
    const loading = document.getElementById('grLoading');
    const pagination = document.getElementById('grPagination');
    const info = document.getElementById('grInfo');
    const pageBtns = document.getElementById('grPageBtns');
    if (!body) return;

    body.innerHTML = '';
    loading.classList.add('hidden');
    empty.classList.add('hidden');

    const data = grFiltered();
    _grView = data;
    const total = data.length;
    const totalPages = Math.max(1, Math.ceil(total / GR_PER_PAGE));
    if (_grPage > totalPages) _grPage = totalPages;
    if (_grPage < 1) _grPage = 1;

    if (total === 0) {
        empty.innerHTML = (_grQuery.trim() || _grDate || _grStatus)
            ? '<i class="fa-solid fa-magnifying-glass text-3xl mb-2 block opacity-40"></i>Tidak ada garansi yang cocok dengan filter.'
            : '<i class="fa-solid fa-shield-halved text-3xl mb-2 block opacity-40"></i>Belum ada data garansi.';
        empty.classList.remove('hidden');
        pagination.classList.add('hidden');
        if (info) info.textContent = '';
        if (pageBtns) pageBtns.innerHTML = '';
        return;
    }

    const start = (_grPage - 1) * GR_PER_PAGE;
    const rows = data.slice(start, start + GR_PER_PAGE);
    rows.forEach((g, i) => {
        const idx = start + i;
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td class="tx-num">${idx + 1}</td>
            <td><span class="tx-device tx-ellipsis" title="${escapeHtml(g.nama)}">${escapeHtml(g.nama)}</span></td>
            <td class="tx-cell-muted"><span class="tx-ellipsis" title="${escapeHtml(g.device)}">${escapeHtml(g.device)}</span></td>
            <td class="tx-cell-muted tx-nowrap">${txDate(g.mulai)}</td>
            <td class="tx-cell-muted tx-nowrap">${txDate(g.akhir)}</td>
            <td>${grStatusBadge(g)}</td>
            <td class="tx-aksi">
                <button type="button" class="tx-view-btn" data-grmenu-btn title="Menu" onclick="grMenuToggle(${g.service_order_id}, ${idx}, this)"><i class="fa-solid fa-ellipsis-vertical"></i></button>
            </td>
        `;
        body.appendChild(tr);
    });

    const end = start + rows.length;
    if (total > GR_PER_PAGE) pagination.classList.remove('hidden');
    else pagination.classList.add('hidden');
    if (info) info.textContent = 'Halaman ' + _grPage + '  ' + (start + 1) + ' - ' + end + '  (dari ' + total + ' garansi)';

    if (pageBtns) {
        pageBtns.innerHTML = '';
        const mkBtn = (txt, p, disabled, active, label) => {
            const b = document.createElement('button');
            b.type = 'button';
            b.innerHTML = txt;
            if (label) { b.title = label; b.setAttribute('aria-label', label); }
            b.className = 'tx-page-btn' + (active ? ' active' : '') + (disabled ? ' disabled' : '');
            if (!disabled) b.addEventListener('click', () => { _grPage = p; renderGaransi(); });
            return b;
        };
        pageBtns.appendChild(mkBtn('<i class="fa-solid fa-chevron-left"></i>', _grPage - 1, _grPage === 1, false, 'Sebelumnya'));
        for (let p = 1; p <= totalPages; p++) {
            pageBtns.appendChild(mkBtn(String(p), p, false, p === _grPage));
        }
        pageBtns.appendChild(mkBtn('<i class="fa-solid fa-chevron-right"></i>', _grPage + 1, _grPage === totalPages, false, 'Berikutnya'));
    }
}

// ─────────────────────────────────────────────
// HALAMAN PELANGGAN (master + ringkasan servis)
// ─────────────────────────────────────────────

// ─────────────────────────────────────────────
// HALAMAN PELANGGAN (master + ringkasan servis — data real backend)
// Backend: GET /api/customers/summary + /{id}/detail + PUT + DELETE.
// ─────────────────────────────────────────────

const PL_PER_PAGE = 10;
let _plPage = 1;
let _plReq = 0;
let _plQuery = '';
let _plDate = '';
let _plView = [];

function initPlToolbar() {
    const s = document.getElementById('plSearch');
    const d = document.getElementById('plDateFilter');
    if (s && !s.dataset.bound) {
        s.dataset.bound = '1';
        let t = null;
        s.addEventListener('input', () => {
            clearTimeout(t);
            t = setTimeout(() => { _plQuery = s.value; loadPlPage(1); }, 300);
        });
    }
    if (d && !d.dataset.bound) {
        d.dataset.bound = '1';
        d.addEventListener('change', () => { _plDate = d.value; loadPlPage(1); });
    }
}

// Menu aksi pelanggan — ID-based (bukan index tabel).
let _plMenuId = null;

function plFind(id) {
    return (_plView || []).find(c => c && c.id === id) || null;
}

function plMenuToggle(id, btn) {
    const menu = document.getElementById('plMenu');
    if (!menu) return;
    if (_plMenuId === id && !menu.classList.contains('hidden')) { plMenuClose(); return; }
    closeRowMenus('plMenu');
    _plMenuId = id;
    menu.dataset.id = id;
    menu.classList.remove('hidden');
    const r = btn.getBoundingClientRect();
    const mw = 200, mh = 196;
    let left = Math.min(r.right - mw, window.innerWidth - mw - 8);
    left = Math.max(8, left);
    let top = r.bottom + 6;
    if (top + mh > window.innerHeight - 8) top = Math.max(8, r.top - mh - 6);
    menu.style.left = left + 'px';
    menu.style.top = top + 'px';
}

function plMenuClose() {
    const menu = document.getElementById('plMenu');
    if (menu) menu.classList.add('hidden');
    _plMenuId = null;
}

if (!window._plMenuBound) {
    window._plMenuBound = true;
    document.addEventListener('click', function (e) {
        const menu = document.getElementById('plMenu');
        if (!menu || menu.classList.contains('hidden')) return;
        if (e.target.closest('#plMenu') || e.target.closest('[data-plmenu-btn]')) return;
        plMenuClose();
    });
    document.addEventListener('keydown', function (e) {
        if (e.key !== 'Escape') return;
        plMenuClose();
        const pe = document.getElementById('plEditPopup');
        if (pe && !pe.classList.contains('hidden')) plEditClose();
    });
    window.addEventListener('resize', plMenuClose);
    document.addEventListener('scroll', function () { plMenuClose(); }, true);
}

function plMenuAct(act) {
    const menu = document.getElementById('plMenu');
    const id = Number((menu || {}).dataset.id);
    plMenuClose();
    if (!id) return;
    if (act === 'detail') plDetailOpen(id, false);
    else if (act === 'riwayat') plDetailOpen(id, true);
    else if (act === 'edit') plEditOpen(id);
    else if (act === 'baru') plServisBaru(id);
    else if (act === 'hapus') plDelete(id);
}

// (PL_DUMMY dihapus — tabel memakai data real GET /api/customers/summary.)

function plRupiah(v) {
    if (v === null || v === undefined) return '-';
    return new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', minimumFractionDigits: 0 }).format(Number(v) || 0);
}

async function renderPelanggan() {
    initPlToolbar();
    await loadPlPage(1);
}

// Detail pelanggan (data real by ID) + Riwayat Servis — jendela Histori.
async function plDetailOpen(id, toHistory) {
    const title = document.getElementById('histTitle');
    const sub = document.getElementById('histSub');
    const summary = document.getElementById('histSummary');
    const tbody = document.getElementById('plHistBody');
    if (title) title.textContent = 'Memuat...';
    if (sub) sub.textContent = '';
    if (summary) summary.innerHTML = '<div class="history-empty"><i class="fa-solid fa-circle-notch fa-spin"></i> Memuat data pelanggan...</div>';
    if (tbody) tbody.innerHTML = '';
    document.getElementById('pageHistory').classList.add('open');
    try {
        const d = await apiGet('/customers/' + id + '/detail');
        const c = d.customer || {};
        if (title) title.textContent = 'Detail — ' + (c.name || '-');
        if (sub) sub.textContent = (c.phone || '-') + ' • ' + d.total_servis + '× servis';
        if (summary) {
            const initial = ((c.name || '?').trim().charAt(0) || '?').toUpperCase();
            summary.innerHTML = `<div class="rc-cust">
                <div class="rc-cust-top"><span class="rc-cust-ava">${escapeHtml(initial)}</span>
                <div class="rc-cust-id"><b>${escapeHtml(c.name || '-')}</b><span>${escapeHtml(c.phone || '-')}</span></div>
                <span class="rc-cust-total">${d.total_servis}× servis</span></div>
                <div class="rc-cust-grid pl-agg">
                <div><span>Jumlah Device</span><b>${d.device_count} device</b></div>
                <div><span>Total Servis</span><b>${d.total_servis}×</b></div>
                <div><span>Total Transaksi</span><b>${plRupiah(d.total_nilai)}</b></div>
                <div><span>Terakhir Servis</span><b>${d.last_at ? txDate(d.last_at) : '-'}</b></div>
                </div></div>`;
        }
        if (tbody) {
            const rows = d.orders || [];
            tbody.innerHTML = rows.length ? rows.map((o, i) => {
                const harga = (o.final_price !== null && o.final_price !== undefined) ? o.final_price : o.estimate;
                const tgl = (o.service_date || '') || (o.created_at || '').slice(0, 10);
                return `
                <tr>
                    <td class="tx-num">${i + 1}</td>
                    <td class="tx-cell-muted tx-nowrap" title="${escapeHtml(o.no_servis || '-')}">${escapeHtml(o.no_servis || '-')}</td>
                    <td class="tx-cell-muted tx-nowrap">${txDate(tgl)}</td>
                    <td><span class="tx-device tx-ellipsis" title="${escapeHtml(o.device || '-')}">${escapeHtml(o.device || '-')}</span></td>
                    <td class="tx-cell-muted"><span class="tx-ellipsis" title="${escapeHtml(o.damagetype || '-')}">${escapeHtml(o.damagetype || '-')}</span></td>
                    <td class="tx-cell-muted"><span class="tx-ellipsis" title="${escapeHtml(o.repair_plan || '-')}">${escapeHtml(o.repair_plan || '-')}</span></td>
                    <td class="tx-cell-muted tx-nowrap" title="${escapeHtml(o.technician || '-')}">${escapeHtml(o.technician || '-')}</td>
                    <td class="tx-laba tx-nowrap">${plRupiah(harga)}</td>
                    <td class="tx-statuscell">${txStatusBadge(o.status)}</td>
                </tr>`;
            }).join('') : '<tr><td colspan="9" class="text-center text-gray-400 py-6">Belum ada riwayat servis.</td></tr>';
        }
        if (toHistory && tbody) {
            const panel = tbody.closest('.panel');
            if (panel) {
                const scroller = document.querySelector('#pageHistory .float-body');
                if (scroller) scroller.scrollTop = scroller.scrollHeight;
            }
        }
    } catch (err) {
        if (title) title.textContent = 'Detail Pelanggan';
        if (summary) summary.innerHTML = `<div class="history-empty"><i class="fa-solid fa-circle-exclamation"></i> ${escapeHtml(err.message || 'Gagal memuat.')}</div>`;
    }
}

function closePlHist() {
    document.getElementById('pageHistory').classList.remove('open');
}

// Edit pelanggan (Nama + WA) — data real by ID.
let _plEditId = null;

async function plEditOpen(id) {
    _plEditId = id;
    const fb = document.getElementById('plEditFeedback');
    if (fb) fb.classList.add('hidden');
    try {
        const c = await apiGet('/customers/' + id);
        document.getElementById('plEditName').value = c.name || '';
        document.getElementById('plEditPhone').value = c.phone || '';
    } catch (err) {
        if (fb) {
            fb.classList.remove('hidden', 'success');
            fb.classList.add('error');
            fb.textContent = err.message;
        }
    }
    document.getElementById('plEditPopup').classList.remove('hidden');
    setTimeout(() => { const el = document.getElementById('plEditName'); if (el) el.focus({ preventScroll: true }); }, 60);
}

function plEditClose() {
    const ov = document.getElementById('plEditPopup');
    if (ov) ov.classList.add('hidden');
    _plEditId = null;
}

async function plEditSave() {
    if (!_plEditId) return;
    const name = (document.getElementById('plEditName').value || '').trim();
    const phone = (document.getElementById('plEditPhone').value || '').trim();
    const fb = document.getElementById('plEditFeedback');
    if (!name) {
        if (fb) {
            fb.classList.remove('hidden', 'success');
            fb.classList.add('error');
            fb.textContent = 'Nama pelanggan wajib diisi.';
        }
        return;
    }
    const btn = document.getElementById('plEditSaveBtn');
    if (btn) btn.disabled = true;
    try {
        await apiPut('/customers/' + _plEditId, { name, phone });
        plEditClose();
        await loadPlPage(_plPage);
    } catch (err) {
        if (fb) {
            fb.classList.remove('hidden', 'success');
            fb.classList.add('error');
            fb.textContent = err.message;
        }
    } finally {
        if (btn) btn.disabled = false;
    }
}

// Servis Baru dengan pelanggan terisi otomatis (data real by ID).
async function plServisBaru(id) {
    let c = plFind(id);
    if (!c) {
        try { c = await apiGet('/customers/' + id); } catch (_) { return; }
    }
    openServisBaru();
    const n = document.getElementById('rcName');
    const p = document.getElementById('rcPhone');
    if (n) n.value = c.name || '';
    if (p) p.value = c.phone || '';
    try { loadSmartHistory(); } catch (_) {}
    const d = document.getElementById('rcDevice');
    if (d) setTimeout(() => d.focus({ preventScroll: true }), 120);
}

// Hapus pelanggan — diblokir bila relasi servis/klaim masih aktif.
async function plDelete(id) {
    const c = plFind(id);
    const total = c ? (Number(c.total_servis) || 0) : 0;
    const name = c ? c.name : ('#' + id);
    if (total > 0) {
        toast('"' + name + '" memiliki ' + total + ' data servis — tidak dapat dihapus karena masih memiliki relasi aktif.');
        return;
    }
    if (!confirm('Hapus pelanggan "' + name + '"?')) return;
    try {
        await apiDel('/customers/' + id);
        await loadPlPage(_plPage);
    } catch (err) {
        toast(err.message || 'Gagal menghapus pelanggan.');
    }
}

async function loadPlPage(page) {
    const body = document.getElementById('plBody');
    const empty = document.getElementById('plEmpty');
    const loading = document.getElementById('plLoading');
    const pagination = document.getElementById('plPagination');
    if (!body) return;
    const myReq = ++_plReq;
    plMenuClose();
    body.innerHTML = '';
    empty.classList.add('hidden');
    loading.classList.remove('hidden');
    try {
        const params = new URLSearchParams({ page: String(page || 1), limit: String(PL_PER_PAGE) });
        if (_plQuery.trim()) params.set('q', _plQuery.trim());
        if (_plDate) params.set('date', _plDate);
        const data = await apiGet('/customers/summary?' + params.toString());
        if (myReq !== _plReq) return; // respons basi — ada request lebih baru, abaikan
        const items = (data && data.items) || [];
        _plView = items;
        _plPage = (data && data.page) || 1;
        const total = (data && data.total) || 0;
        const totalPages = (data && data.total_pages) || 1;
        loading.classList.add('hidden');
        if (!items.length) {
            empty.innerHTML = (_plQuery.trim() || _plDate)
                ? '<i class="fa-solid fa-magnifying-glass text-3xl mb-2 block opacity-40"></i>Pelanggan tidak ditemukan.'
                : '<i class="fa-solid fa-users text-3xl mb-2 block opacity-40"></i>Belum ada pelanggan.';
            empty.classList.remove('hidden');
            pagination.classList.add('hidden');
            if (document.getElementById('plInfo')) document.getElementById('plInfo').textContent = '';
            if (document.getElementById('plPageBtns')) document.getElementById('plPageBtns').innerHTML = '';
            return;
        }
        const start = (_plPage - 1) * PL_PER_PAGE;
        items.forEach((c, i) => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
            <td class="tx-num">${start + i + 1}</td>
            <td><span class="tx-device tx-ellipsis" title="${escapeHtml(c.name)}">${escapeHtml(c.name)}</span></td>
            <td class="tx-cell-muted pl-c-phone" title="${escapeHtml(c.phone || '')}">${escapeHtml(c.phone || '-')}</td>
            <td class="tx-cell-muted"><span class="tx-ellipsis" title="${escapeHtml(c.last_device || '')}">${escapeHtml(c.last_device || '-')}</span></td>
            <td class="tx-cell-muted"><span class="tx-ellipsis" title="${escapeHtml(c.last_action || '')}">${escapeHtml(c.last_action || '-')}</span></td>
            <td class="tx-laba">${c.last_price ? plRupiah(c.last_price) : '-'}</td>
            <td class="tx-cell-muted text-center pl-c-total">${c.total_servis} servis</td>
            <td class="tx-cell-muted pl-c-date">${c.last_at ? txDate(c.last_at) : '-'}</td>
            <td class="tx-aksi"><div class="pl-aksi">
                <button type="button" class="tx-view-btn" data-plmenu-btn title="Menu" onclick="plMenuToggle(${c.id}, this)"><i class="fa-solid fa-ellipsis-vertical"></i></button>
            </div></td>
        `;
            body.appendChild(tr);
        });

        const end = start + items.length;
        if (total > PL_PER_PAGE) pagination.classList.remove('hidden');
        else pagination.classList.add('hidden');
        const info = document.getElementById('plInfo');
        if (info) info.textContent = 'Halaman ' + _plPage + '  ' + (start + 1) + ' - ' + end + '  (dari ' + total + ' pelanggan)';

        const pageBtns = document.getElementById('plPageBtns');
        if (pageBtns) {
            pageBtns.innerHTML = '';
            const mkBtn = (txt, p, disabled, active, label) => {
                const b = document.createElement('button');
                b.type = 'button';
                b.innerHTML = txt;
                if (label) { b.title = label; b.setAttribute('aria-label', label); }
                b.className = 'tx-page-btn' + (active ? ' active' : '') + (disabled ? ' disabled' : '');
                if (!disabled) b.addEventListener('click', () => loadPlPage(p));
                return b;
            };
            pageBtns.appendChild(mkBtn('<i class="fa-solid fa-chevron-left"></i>', _plPage - 1, _plPage === 1, false, 'Sebelumnya'));
            for (let p = 1; p <= totalPages; p++) {
                pageBtns.appendChild(mkBtn(String(p), p, false, p === _plPage));
            }
            pageBtns.appendChild(mkBtn('<i class="fa-solid fa-chevron-right"></i>', _plPage + 1, _plPage === totalPages, false, 'Berikutnya'));
        }
    } catch (err) {
        if (myReq !== _plReq) return; // respons basi — ada request lebih baru, abaikan
        loading.classList.add('hidden');
        empty.innerHTML = '<i class="fa-solid fa-circle-exclamation text-3xl mb-2 block opacity-40"></i>' + escapeHtml(err.message || 'Gagal memuat data.');
        empty.classList.remove('hidden');
        pagination.classList.add('hidden');
    }
}

// ─────────────────────────────────────────────
// HALAMAN SPAREPART (data real backend)
// ─────────────────────────────────────────────

const SP_PER_PAGE = 10;
let _spPage = 1;
let _spQuery = '';
let _spReq = 0;
let _spEditId = -1;
// State real dari backend (GET/POST/PUT/DELETE /api/spareparts). SP_MOCK dipensiunkan.
let _spView = [];

function spNorm(r) {
    return {
        id: r.id,
        tgl: r.tanggal || (r.created_at || '').slice(0, 10),
        kategori: r.kategori || '-',
        merek: r.merek || '-',
        jenis: r.jenis || '-',
        device: r.device || '-',
        qty: Number(r.qty) || 0,
        beli: Number(r.harga_beli) || 0,
        jual: Number(r.harga_jual) || 0,
    };
}

function spRupiah(v) {
    return new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', minimumFractionDigits: 0 }).format(Number(v) || 0);
}

function spQtyCell(qty) {
    if (qty <= 0) return '<span class="qty-out">0</span> <span class="qty-flag out">Habis</span>';
    if (qty <= 5) return `<span class="qty-low">${qty}</span> <span class="qty-flag low">Menipis</span>`;
    return `<span class="qty-ok">${qty}</span>`;
}

function spEdit(id) {
    const s = (_spView || []).find(x => x && x.id === id);
    if (!s) return;
    _spEditId = id;
    document.getElementById('spfTitle').textContent = 'Edit Sparepart';
    document.getElementById('spfKategori').value = s.kategori || '';
    document.getElementById('spfMerek').value = s.merek || '';
    document.getElementById('spfJenis').value = s.jenis || '';
    document.getElementById('spfDevice').value = s.device || '';
    document.getElementById('spfQty').value = s.qty ?? 0;
    document.getElementById('spfBeli').value = s.beli || 0;
    document.getElementById('spfJual').value = s.jual || 0;
    const fb = document.getElementById('spfFeedback');
    fb.classList.add('hidden');
    fb.classList.remove('success');
    document.getElementById('pageSpare').classList.add('open');
}

async function spDel(id) {
    const s = (_spView || []).find(x => x && x.id === id);
    if (!s) return;
    if (!confirm('Hapus sparepart "' + s.jenis + '"?')) return;
    try {
        await apiDel('/spareparts/' + id);
        renderSparepart();
    } catch (err) {
        toast(err.message || 'Gagal menghapus.');
    }
}

// ── P2-12: pergerakan stok (barang masuk + riwayat) ──
async function loadSparepartMoves() {
    const body = document.getElementById('spMoveBody');
    const sel = document.getElementById('spMovePart');
    if (!body && !sel) return;
    let moves = [];
    try { const r = await apiGet('/inventory/moves?limit=25'); moves = (r && r.items) || []; } catch (_) {}
    if (sel && !sel.options.length && _sparepartsCache && _sparepartsCache.length) {
        sel.innerHTML = _sparepartsCache.map(p => `<option value="${p.id}">${escapeHtml((p.merek || '') + ' ' + (p.jenis || ''))}</option>`).join('');
    }
    if (body) {
        body.innerHTML = moves.length ? moves.map(m => `<tr>
            <td>${escapeHtml(String(m.waktu || '').replace('T', ' ').slice(0, 16))}</td>
            <td class="tx-ellipsis" title="${escapeHtml(m.sparepart_label || '-')}">${escapeHtml(m.sparepart_label || '-')}</td>
            <td>${escapeHtml(m.aksi || '-')}</td>
            <td class="numeric-r">${m.qty}</td>
            <td class="numeric-r">${m.qty_sesudah}</td></tr>`).join('')
            : `<tr><td colspan="5"><div class="text-center text-sm text-gray-400 py-6">Belum ada pergerakan stok.</div></td></tr>`;
    }
    applyRoleUI(document.getElementById('pageSparepart') || document);
}

async function spMoveSubmit() {
    if (!can('SPAREPART_WRITE')) { toast('Aksi ditolak: role Anda tidak berwenang mengubah stok.'); return; }
    const id = document.getElementById('spMovePart').value;
    const qty = Number(document.getElementById('spMoveQty').value || 0);
    const ket = (document.getElementById('spMoveNote').value || '').trim();
    if (!id || !qty) { _kuFb('spMoveFeedback', 'Part dan qty wajib diisi.', 'error'); return; }
    try {
        const r = await apiPost('/inventory/masuk?sparepart_id=' + id + '&qty=' + qty
            + '&keterangan=' + encodeURIComponent(ket || 'Barang masuk'),
            {}, { idempotencyKey: newIdemKey() });
        _kuFb('spMoveFeedback', 'Barang masuk tercatat. Saldo ' + (r.qty_sesudah) + '.', 'success');
        document.getElementById('spMoveQty').value = '1';
        document.getElementById('spMoveNote').value = '';
        toast('Stok bertambah.', 'success');
        await renderSparepart();
    } catch (err) {
        _kuFb('spMoveFeedback', err.message || 'Gagal mencatat barang masuk.', 'error');
    }
}

// ── P2-12: pemakaian part untuk satu unit (pakai & batal) ──
async function loadUnitParts(orderId) {
    const host = document.getElementById('txdParts');
    if (!host) return;
    let items = [];
    try { const r = await apiGet('/inventory/pemakaian/' + orderId); items = (r && r.items) || []; } catch (_) {}
    let spar = [];
    try { spar = (await apiGet('/spareparts?limit=100')).items || []; } catch (_) { spar = []; }
    const opts = spar.map(p => `<option value="${p.id}">${escapeHtml((p.merek || '') + ' ' + (p.jenis || ''))} (sisa ${p.qty})</option>`).join('');
    host.innerHTML = `
        <div class="flex flex-col sm:flex-row sm:items-end gap-2.5" data-cap="SPAREPART_WRITE">
            <div class="flex-1">
                <label class="field-label" for="txdPartSel">Part</label>
                <select class="receive-input" id="txdPartSel">${opts || '<option value="">Stok kosong</option>'}</select>
            </div>
            <div class="w-full sm:w-28">
                <label class="field-label" for="txdPartQty">Qty</label>
                <input class="receive-input" type="number" id="txdPartQty" min="1" value="1">
            </div>
            <button type="button" onclick="txdPakaiPart(${orderId})" class="receive-submit-btn">
                <i class="fa-solid fa-screwdriver-wrench"></i> Pakai Part
            </button>
        </div>
        <div id="txdPartFeedback" class="hidden receive-feedback mt-2"></div>
        <div class="overflow-x-auto mt-2">
            <table class="tx-table w-full text-sm">
                <thead><tr><th>Part</th><th class="numeric-r">Qty</th><th>Status</th><th class="text-right">Aksi</th></tr></thead>
                <tbody>${items.length ? items.map(u => `<tr>
                    <td class="tx-ellipsis">${escapeHtml(u.label || '-')}</td>
                    <td class="numeric-r">${u.qty}</td>
                    <td>${escapeHtml(u.status || '-')}</td>
                    <td class="text-right">${(u.status === 'DIPAKAI' && can('SPAREPART_WRITE'))
                        ? `<button type="button" onclick="txdBatalPart(${u.id}, ${orderId})" class="receive-back-btn">Batal</button>` : ''}</td>
                </tr>`).join('') : `<tr><td colspan="4"><div class="text-center text-sm text-gray-400 py-4">Belum ada pemakaian part.</div></td></tr>`}</tbody>
            </table>
        </div>`;
    applyRoleUI(host);
}

async function txdPakaiPart(orderId) {
    if (!can('SPAREPART_WRITE')) { toast('Aksi ditolak: role Anda tidak berwenang memakai stok.'); return; }
    const pid = document.getElementById('txdPartSel').value;
    const qty = Number(document.getElementById('txdPartQty').value || 0);
    if (!pid || !qty) { _kuFb('txdPartFeedback', 'Part dan qty wajib diisi.', 'error'); return; }
    try {
        await apiPost('/inventory/pakai?sparepart_id=' + pid + '&qty=' + qty + '&service_order_id=' + orderId,
            {}, { idempotencyKey: newIdemKey() });
        _kuFb('txdPartFeedback', 'Pemakaian part tercatat.', 'success');
        toast('Stok dipotong.', 'success');
        await loadUnitParts(orderId);
    } catch (err) {
        _kuFb('txdPartFeedback', err.message || 'Gagal memakai part (stok kurang?).', 'error');
    }
}

async function txdBatalPart(usageId, orderId) {
    if (!can('SPAREPART_WRITE')) { toast('Aksi ditolak: role Anda tidak berwenang.'); return; }
    if (!confirm('Batalkan pemakaian part ini? Stok akan dikembalikan.')) return;
    try {
        const r = await apiPost('/inventory/pakai/' + usageId + '/batal', {},
                                { idempotencyKey: newIdemKey() });
        _kuFb('txdPartFeedback', r.idempotent
            ? 'Pemakaian sudah dibatalkan sebelumnya (tidak digandakan).'
            : 'Pemakaian dibatalkan; stok dikembalikan ' + (r.pengembalian || 0) + '.', 'success');
        await loadUnitParts(orderId);
    } catch (err) {
        _kuFb('txdPartFeedback', err.message || 'Gagal membatalkan pemakaian.', 'error');
    }
}

// ── P2-10: refund DP & Failed → Cancel (dana Laci) ──
async function txdRefundDP(orderId) {
    if (!can('REFUND_DP')) { toast('Aksi ditolak: hanya Admin/Kasir.'); return; }
    let pre = null;
    try { pre = await apiGet('/refunds/precheck/dp/' + orderId); } catch (_) {}
    if (!pre || !pre.bisa_refund) {
        toast('Tidak ada DP yang belum direfund pada unit ini.');
        return;
    }
    const v = prompt('Nominal refund DP (maks ' + Number(pre.sisa).toLocaleString('id-ID') + ')', String(pre.sisa));
    if (v === null) return;
    const nominal = Number(v);
    if (!nominal || nominal <= 0) { toast('Nominal tidak valid.'); return; }
    try {
        const r = await apiPost('/refunds/dp', { service_order_id: orderId, nominal },
                                { idempotencyKey: newIdemKey() });
        toast('Refund DP ' + kuRupiah(nominal) + ' dari Kas Perputaran. Saldo Laci ' + kuRupiah(r.saldo_setelah) + '.', 'success');
        if (typeof openTxDetail === 'function') await openTxDetail(orderId);
    } catch (err) { toast(err.message || 'Gagal refund DP.'); }
}

async function txdFailedCancel(orderId) {
    if (!can('FAILED_CANCEL')) { toast('Aksi ditolak: hanya Admin/Kasir.'); return; }
    if (!confirm('Failed → Cancel: kembalikan dana ke Kas Perputaran (bukan refund garansi)?')) return;
    try {
        const r = await apiPost('/refunds/failed-cancel', { service_order_id: orderId },
                                { idempotencyKey: newIdemKey() });
        toast('Dana dikembalikan ' + kuRupiah(r.refund.nominal) + ' dari Kas Perputaran.', 'success');
        if (typeof openTxDetail === 'function') await openTxDetail(orderId);
    } catch (err) { toast(err.message || 'Gagal proses Failed → Cancel.'); }
}

function spAdd() {
    _spEditId = -1;
    document.getElementById('spfTitle').textContent = 'Tambah Sparepart';
    document.getElementById('spareForm').reset();
    const fb = document.getElementById('spfFeedback');
    fb.classList.add('hidden');
    fb.classList.remove('success');
    document.getElementById('pageSpare').classList.add('open');
}

function closeSpare() {
    document.getElementById('pageSpare').classList.remove('open');
    _spEditId = -1;
}

function renderSpKpi(src) {
    const el = document.getElementById('spKpi');
    if (!el) return;
    const data = src || _spView || [];
    const total = data.length;
    const habis = data.filter(s => (s.qty || 0) <= 0).length;
    const tipis = data.filter(s => (s.qty || 0) > 0 && (s.qty || 0) <= 5).length;
    const nilai = data.reduce((a, s) => a + (Number(s.qty) || 0) * (Number(s.jual) || 0), 0);
    const cards = [
        { label: 'Total Item', value: total, unit: 'item', icon: 'fa-boxes-stacked', cls: 'sm-slate' },
        { label: 'Stok Habis', value: habis, unit: 'item', icon: 'fa-box-open', cls: 'sm-red' },
        { label: 'Stok Menipis', value: tipis, unit: 'item', icon: 'fa-triangle-exclamation', cls: 'sm-amber' },
        { label: 'Nilai Stok', value: spRupiah(nilai), unit: 'jual', icon: 'fa-sack-dollar', cls: 'sm-green' },
    ];
    el.innerHTML = cards.map(c => `
        <div class="sm-card ${c.cls}">
            <div class="sm-top"><i class="fa-solid ${c.icon}"></i>${c.label}</div>
            <div class="sm-bot"><span class="sm-num">${c.value}</span><span class="sm-pct">${c.unit}</span></div>
        </div>
    `).join('');
}

function spFiltered() {
    const q = _spQuery.trim().toLowerCase();
    // P2-15: cache untuk form pergerakan stok (barang masuk / pemakaian part).
    try { _sparepartsCache = (_spView || []).slice(); } catch (_) {}
    if (!q) return (_spView || []).slice();
    return (_spView || []).filter(s => [s.jenis, s.merek, s.device, s.kategori]
        .some(f => (f || '').toLowerCase().includes(q)));
}

// Ambil SEMUA halaman sparepart (limit backend 100/halaman).
// Mengembalikan array atau null bila respons basi.
async function spFetchAll(q, my) {
    let _all = [];
    let _pg = 1;
    for (;;) {
        const params = new URLSearchParams({ page: String(_pg), limit: '100' });
        if ((q || '').trim()) params.set('q', q.trim());
        const data = await apiGet('/spareparts?' + params.toString());
        if (my !== _spReq) return null; // respons basi — ada request lebih baru
        const items = ((data && data.items) || []).map(spNorm);
        _all = _all.concat(items);
        const total = (data && data.total) || 0;
        if (!_all.length || _all.length >= total || items.length < 100 || _pg >= 50) break;
        _pg += 1;
    }
    return _all;
}

async function renderSparepart() {
    try { spMenuClose(); } catch (_) {}
    const my = ++_spReq;
    try {
        // Tabel memakai filter q; KPI selalu dari SELURUH stok (tanpa q)
        // agar tidak ikut menyusut saat mencari.
        _spView = await spFetchAll(_spQuery, my);
        if (_spView === null) return;
        if (_spQuery.trim()) {
            const _allKpi = await spFetchAll('', my);
            if (_allKpi === null) return;
            renderSpKpi(_allKpi);
        } else {
            renderSpKpi(_spView);
        }
    } catch (err) {
        if (my !== _spReq) return;
        _spView = [];
        const loading = document.getElementById('spLoading');
        if (loading) loading.classList.add('hidden');
        const empty = document.getElementById('spEmpty');
        if (empty) {
            empty.innerHTML = '<i class="fa-solid fa-circle-exclamation text-3xl mb-2 block opacity-40"></i>' + escapeHtml(err.message || 'Gagal memuat data.');
            empty.classList.remove('hidden');
        }
        renderSpKpi();
        return;
    }
    renderSpKpi();
    const body = document.getElementById('spBody');
    const empty = document.getElementById('spEmpty');
    const loading = document.getElementById('spLoading');
    const pagination = document.getElementById('spPagination');
    const info = document.getElementById('spInfo');
    const pageBtns = document.getElementById('spPageBtns');
    if (!body) return;

    body.innerHTML = '';
    loading.classList.add('hidden');
    empty.classList.add('hidden');

    const data = spFiltered();
    const total = data.length;
    const totalPages = Math.max(1, Math.ceil(total / SP_PER_PAGE));
    if (_spPage > totalPages) _spPage = totalPages;
    if (_spPage < 1) _spPage = 1;

    if (total === 0) {
        empty.classList.remove('hidden');
        empty.innerHTML = _spQuery.trim()
            ? '<i class="fa-solid fa-magnifying-glass text-3xl mb-2 block opacity-40"></i>Sparepart tidak ditemukan.'
            : '<i class="fa-solid fa-box-open text-3xl mb-2 block opacity-40"></i>Belum ada data sparepart.';
        pagination.classList.add('hidden');
        if (info) info.textContent = '';
        if (pageBtns) pageBtns.innerHTML = '';
        return;
    }

    const start = (_spPage - 1) * SP_PER_PAGE;
    const rows = data.slice(start, start + SP_PER_PAGE);
    rows.forEach((s, i) => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td class="tx-num">${start + i + 1}</td>
            <td class="tx-cell-muted tx-nowrap" title="${escapeHtml(s.tgl || '')}">${txDate(s.tgl)}</td>
            <td class="tx-cell-muted"><span class="tx-ellipsis" title="${escapeHtml(s.kategori)}">${escapeHtml(s.kategori)}</span></td>
            <td class="tx-cell-muted"><span class="tx-ellipsis" title="${escapeHtml(s.merek)}">${escapeHtml(s.merek)}</span></td>
            <td><span class="tx-device tx-ellipsis" title="${escapeHtml(s.jenis)}">${escapeHtml(s.jenis)}</span></td>
            <td class="tx-cell-muted"><span class="tx-ellipsis" title="${escapeHtml(s.device)}">${escapeHtml(s.device)}</span></td>
            <td class="text-center tx-nowrap">${spQtyCell(s.qty)}</td>
            <td class="tx-laba-muted tx-nowrap">${spRupiah(s.beli)}</td>
            <td class="tx-laba tx-nowrap">${spRupiah(s.jual)}</td>
            <td class="tx-aksi">
                <button type="button" class="tx-view-btn" data-spmenu-btn title="Menu" onclick="spMenuToggle(${s.id}, this)"><i class="fa-solid fa-ellipsis-vertical"></i></button>
            </td>
        `;
        body.appendChild(tr);
    });

    const end = start + rows.length;
    if (total > SP_PER_PAGE) pagination.classList.remove('hidden');
    else pagination.classList.add('hidden');
    if (info) info.textContent = 'Halaman ' + _spPage + '  ' + (start + 1) + ' - ' + end + '  (dari ' + total + ' sparepart)';

    if (pageBtns) {
        pageBtns.innerHTML = '';
        const mkBtn = (txt, p, disabled, active, label) => {
            const b = document.createElement('button');
            b.type = 'button';
            b.innerHTML = txt;
            if (label) { b.title = label; b.setAttribute('aria-label', label); }
            b.className = 'tx-page-btn' + (active ? ' active' : '') + (disabled ? ' disabled' : '');
            if (!disabled) b.addEventListener('click', () => { _spPage = p; renderSparepart(); });
            return b;
        };
        pageBtns.appendChild(mkBtn('<i class="fa-solid fa-chevron-left"></i>', _spPage - 1, _spPage === 1, false, 'Sebelumnya'));
        for (let p = 1; p <= totalPages; p++) {
            pageBtns.appendChild(mkBtn(String(p), p, false, p === _spPage));
        }
        pageBtns.appendChild(mkBtn('<i class="fa-solid fa-chevron-right"></i>', _spPage + 1, _spPage === totalPages, false, 'Berikutnya'));
    }
}

function initSparepart() {
    const input = document.getElementById('spSearch');
    if (input && !input.dataset.bound) {
        input.dataset.bound = '1';
        let t = null;
        input.addEventListener('input', () => {
            clearTimeout(t);
            t = setTimeout(() => { _spQuery = input.value; _spPage = 1; renderSparepart(); }, 300);
        });
    }
    const form = document.getElementById('spareForm');
    if (form && !form.dataset.bound) {
        form.dataset.bound = '1';
        form.addEventListener('submit', async function (e) {
            e.preventDefault();
            const jenis = document.getElementById('spfJenis').value.trim();
            if (!jenis) return;
            const payload = {
                kategori: document.getElementById('spfKategori').value.trim() || null,
                merek: document.getElementById('spfMerek').value.trim() || null,
                jenis: jenis,
                device: document.getElementById('spfDevice').value.trim() || null,
                qty: Math.max(0, parseInt(document.getElementById('spfQty').value, 10) || 0),
                harga_beli: Math.max(0, Number(document.getElementById('spfBeli').value) || 0),
                harga_jual: Math.max(0, Number(document.getElementById('spfJual').value) || 0),
            };
            const fb = document.getElementById('spfFeedback');
            try {
                if (_spEditId >= 0) {
                    await apiPut('/spareparts/' + _spEditId, payload);
                    _spEditId = -1;
                } else {
                    await apiPost('/spareparts', payload);
                    _spPage = 1;
                }
                renderSparepart();
                fb.classList.remove('hidden');
                fb.classList.add('success');
                fb.innerHTML = `<i class="fa-solid fa-circle-check"></i> Tersimpan di stok.`;
            } catch (err) {
                fb.classList.remove('hidden');
                fb.innerHTML = `<i class="fa-solid fa-triangle-exclamation"></i> ${escapeHtml(err.message || 'Gagal menyimpan.')}`;
            }
        });
    }
}

// ─────────────────────────────────────────────
// HALAMAN KEUANGAN (data real backend)
// ─────────────────────────────────────────────

const KU_PER_PAGE = 10;
let _kuPage = 1;
let _kuReq = 0;
let _kuRiwReq = 0;
let _profitChart = null;
// State real dari backend — tidak ada lagi array lokal (KU_* dipensiunkan).
// Buku Kas = turunan jurnal payments + expenses + jurnal manual, scope periode kas aktif.
let _kuFin = null;
let _kuSaldoLapisan = null; // P2-06 / SSOT-7: saldo Laci & Kas Aset terpisah
let _kuKasRows = [];
let _kuAllocView = [];
let _kuSelAlloc = -1;

function kuRupiah(v) {
    return new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', minimumFractionDigits: 0 }).format(Number(v) || 0);
}

async function renderKeuangan() {
    kuShowMain(true);
    initKuKasForm();
    await loadKuFinance();
    renderRiwayat();
}

// Satu-satunya sumber angka Buku Kas: backend (overview + riwayat periode aktif).
async function loadKuFinance() {
    const my = ++_kuReq;
    const body = document.getElementById('kuKasBody');
    try {
        const [ov, sl] = await Promise.all([
            apiGet('/overview'),
            apiGet('/kas/saldo').catch(() => null), // P2-06: saldo Kas Aset (opsional)
        ]);
        if (my !== _kuReq) return; // respons basi — ada request lebih baru
        _kuFin = (ov && ov.finance) || null;
        _kuSaldoLapisan = sl || null;
        // Saldo awal Mutasi Kas sekarang datang dari `/kas/riwayat.opening`
        // (sumber tunggal yang sama dengan saldo berjalan), bukan dari sini.
        // P2-15: panel turunan lain (tidak kritis bila gagal).
        loadKuAset().catch(() => {});
        loadKuDebt().catch(() => {});
        loadKuNotif().catch(() => {});
            renderKondisiKas();
        renderKuTitipan();
        renderAlloc();
        // Tabel Rincian Arus Kas = detail Kondisi Kas. Karena panelnya disembunyikan
        // di balik tombol "Riwayat Transaksi", jangan render diam-diam: cukup muat
        // ulang saat tombolnya ditekan (kuShowRiwayat).
        _kuPage = 1;
        if (_kuRiwayatVisible()) renderRiwayat();
        renderKuArsip();
    } catch (err) {
        if (my !== _kuReq) return;
        if (body) body.innerHTML = `<tr><td colspan="6"><div class="text-center text-sm text-gray-400 py-6">Gagal memuat kas: ${escapeHtml(err.message || '')}</div></td></tr>`;
    }
}

// ─────────────────────────────────────────────────────────────
// P2-15: PANEL TURUNAN KEUANGAN (semua angka dari backend SSOT)
// ─────────────────────────────────────────────────────────────
function _kuMoney(v) { return 'Rp ' + (Number(v) || 0).toLocaleString('id-ID'); }

// Kas Aset: saldo terpisah + riwayat mutasi (P2-06).
async function loadKuAset() {
    const summary = document.getElementById('kuAsetSummary');
    const body = document.getElementById('kuAsetBody');
    if (!summary && !body) return;
    let saldo = null, items = [];
    try { saldo = await apiGet('/kas/saldo'); } catch (_) {}
    try { const r = await apiGet('/kas/aset/riwayat?period=all&limit=50'); items = (r && r.items) || []; } catch (_) {}
    const laci = _kuSaldoLapisan || {};
    const lihatAset = canViewAset();
    // v4 #11: untuk role tanpa authority, panel Kas Aset ditampilkan mulai dari
    // Kas Kecil/Laci saja. Judul & deskripsi Kas Besar disembunyikan — bukan
    // sekadar angkanya, tapi juga penjelasan posisi yang tidak boleh terlihat.
    const _t = document.getElementById('kuMasterTitle');
    if (_t) {
        _t.innerHTML = lihatAset
            ? '<i class="fa-solid fa-vault"></i> Kas Aset (Master Kas)'
            : '<i class="fa-solid fa-wallet"></i> Kas Kecil (Laci)';
    }
    const _d = document.getElementById('kuMasterDesc');
    if (_d) {
        _d.classList.toggle('hidden', !lihatAset);
        if (lihatAset) _d.textContent = 'Master Kas = Saldo Laci (Kas Aset Kecil) + Saldo Aset (Kas Aset Besar/Pengelola). Perpindahan Laci ↔ Aset tidak mengubah Master Kas. Angka di bawah adalah uang milik toko -- uang titipan DP customer tidak dihitung.';
    }
    if (summary) {
        // Angka FISIK (`laci`/`master_kas`) masih memuat DP karena uangnya benar-benar
        // ada di dalam laci, dan itulah yang dipakai saat Declare Tutup Kas. Yang
        // ditampilkan ke Owner adalah versi setelah DP yang ditahan dikurangi,
        // supaya uang customer tidak terbaca sebagai uang usaha (Owner).
        const cards = [
            { label: 'Kas Aset Kecil (Laci)', value: kuRupiah(laci.laci_milik_toko != null ? laci.laci_milik_toko : (laci.laci || 0)), icon: 'fa-wallet', cls: 'sm-blue' },
        ];
        if (lihatAset) {
            cards.push({ label: 'Kas Aset Besar (Pengelola)', value: kuRupiah(laci.aset || 0), icon: 'fa-vault', cls: 'sm-blue' });
            cards.push({ label: 'Master Kas', value: kuRupiah(laci.master_kas_milik_toko != null ? laci.master_kas_milik_toko : (laci.master_kas || 0)), icon: 'fa-layer-group', cls: 'sm-green' });
        }
        summary.innerHTML = cards.map(c => `
            <div class="sm-card ${c.cls}">
                <div class="sm-top"><i class="fa-solid ${c.icon}"></i>${c.label}</div>
                <div class="sm-bot"><span class="sm-num ku-num">${c.value}</span></div>
            </div>`).join('');
    }
    // Aset detail hanya diambil bila role berhak (v4 #11).
    if (!lihatAset) items = [];
    if (body) {
        body.innerHTML = items.length ? items.slice().reverse().map(it => {
            const masuk = (it.jenis || '') === 'Masuk';
            const sub = [it.kategori || '', it.tgl || ''].filter(Boolean).join(' • ');
            return `<tr>
                <td><span class="tx-device tx-ellipsis" title="${escapeHtml(it.ket || '-')}">${escapeHtml(it.ket || '-')}</span>${sub ? `<br><span class="text-[10.5px] text-gray-400">${escapeHtml(sub)}</span>` : ''}</td>
                <td class="tx-debit numeric-c">${masuk ? kuRupiah(it.nominal) : '<span class="text-green-500">-</span>'}</td>
                <td class="tx-kredit numeric-c">${masuk ? '<span class="text-red-500">-</span>' : kuRupiah(it.nominal)}</td>
                <td class="tx-saldo numeric-r">${kuRupiah(it.saldo)}</td>
            </tr>`;
        }).join('') : `<tr><td colspan="4"><div class="text-center text-sm text-gray-400 py-6">Belum ada mutasi Kas Aset.</div></td></tr>`;
    }
    applyRoleUI(document.getElementById('kuAsetForm') || document);
}

function _kuFb(id, msg, kind) {
    const el = document.getElementById(id);
    if (!el) return;
    el.classList.remove('hidden', 'success', 'error');
    el.textContent = msg;
    if (kind) el.classList.add(kind);
}

async function kuAsetMasuk() {
    if (!can('KAS_ASET_INJEKSI')) { toast('Aksi ditolak: hanya Admin.'); return; }
    const nominal = Number(document.getElementById('kuAsetNominal').value || 0);
    const keterangan = (document.getElementById('kuAsetKeterangan').value || '').trim();
    const posisi = (document.getElementById('kuAsetPosisi') || {}).value || 'LACI';
    if (!nominal || !keterangan) { _kuFb('kuAsetFeedback', 'Nominal dan keterangan wajib diisi.', 'error'); return; }
    const btnKey = newIdemKey();
    try {
        const res = await apiPost('/kas/aset/masuk', { nominal, keterangan, posisi }, { idempotencyKey: btnKey });
        _kuFb('kuAsetFeedback', 'Dana masuk ke ' + (res.label || posisi)
            + '. Saldo ' + _kuMoney(res.saldo_setelah) + ' · Master Kas ' + _kuMoney(res.master_kas_setelah) + '.', 'success');
        document.getElementById('kuAsetNominal').value = '';
        document.getElementById('kuAsetKeterangan').value = '';
        toast('Kas Aset bertambah ' + _kuMoney(nominal) + '.', 'success');
        await loadKuFinance();
    } catch (err) {
        _kuFb('kuAsetFeedback', err.message || 'Gagal menambah Kas Aset.', 'error');
    }
}

async function kuAsetKeluar() {
    if (!can('KAS_ASET_INJEKSI')) { toast('Aksi ditolak: hanya Admin.'); return; }
    const nominal = Number(document.getElementById('kuAsetNominal').value || 0);
    const keterangan = (document.getElementById('kuAsetKeterangan').value || '').trim();
    if (!nominal || !keterangan) { _kuFb('kuAsetFeedback', 'Nominal dan keterangan wajib diisi.', 'error'); return; }
    try {
        const cek = await apiGet('/kas/aset/cukup?nominal=' + nominal);
        if (cek && cek.cukup === false) {
            _kuFb('kuAsetFeedback', 'Saldo Kas Aset tidak cukup (kurang ' + _kuMoney(cek.kurang) + ').', 'error');
            return;
        }
    } catch (_) { /* lanjut: backend tetap memvalidasi */ }
    try {
        const res = await apiPost('/kas/aset/keluar', { nominal, keterangan }, { idempotencyKey: newIdemKey() });
        _kuFb('kuAsetFeedback', 'Dana keluar. Saldo Kas Aset ' + _kuMoney(res.saldo_setelah) + '.', 'success');
        document.getElementById('kuAsetNominal').value = '';
        document.getElementById('kuAsetKeterangan').value = '';
        toast('Kas Aset berkurang ' + _kuMoney(nominal) + '.', 'success');
        await loadKuFinance();
    } catch (err) {
        _kuFb('kuAsetFeedback', err.message || 'Gagal menarik Kas Aset.', 'error');
    }
}

// v4 #5: transfer fisik Laci <-> Aset (Master Kas tetap).
async function kuAsetTransfer() {
    if (!can('KAS_ASET_INJEKSI')) { toast('Aksi ditolak: hanya Admin.'); return; }
    if (!canViewAset()) { toast('Transfer Kas Aset tidak tersedia untuk role Anda.'); return; }
    const nominal = Number(document.getElementById('kuAsetNominal').value || 0);
    const keterangan = (document.getElementById('kuAsetKeterangan').value || '').trim();
    const arah = ((document.getElementById('kuTransferArah') || {}).value || 'LACI->KAS_ASET').split('->');
    if (!nominal || !keterangan) { _kuFb('kuAsetFeedback', 'Nominal dan keterangan wajib diisi.', 'error'); return; }
    const masterSebelum = (_kuSaldoLapisan && _kuSaldoLapisan.master_kas) || 0;
    try {
        const res = await apiPost('/kas/aset/transfer',
            { dari: arah[0], ke: arah[1], nominal, keterangan }, { idempotencyKey: newIdemKey() });
        _kuFb('kuAsetFeedback', 'Transfer selesai. ' + res.label_dari + ' → ' + res.label_ke
            + '. Master Kas ' + _kuMoney(res.master_kas_setelah) + '.', 'success');
        document.getElementById('kuAsetNominal').value = '';
        document.getElementById('kuAsetKeterangan').value = '';
        toast('Transfer Kas Aset tercatat.', 'success');
        await loadKuFinance();
    } catch (err) {
        _kuFb('kuAsetFeedback', err.message || 'Gagal transfer Kas Aset.', 'error');
    }
}

// Panel "Distribusi Laba" sudah DIHAPUS dari halaman Keuangan.
//
// Fungsinya merender empat baris 10/30/30/30 yang IDENTIK dengan Alokasi
// Profit, tanpa donut, badge CTO, alasan, maupun tombol Jalankan Distribusi.
// Jadi tidak ada informasi yang hilang saat panel ini dibuang; semuanya sudah
// ada (dan lebih lengkap) di panel Alokasi Profit.
//
// Catatan: teks lamanya berbunyi "Terbentuk saat Tutup Kas" -- itu sudah tidak
// benar sejak distribution berubah otomatis (CTO tercapai), bukan Tutup Kas.

// Hutang Beban (P2-11): status, ledger, proses defisit, pelunasan.
async function loadKuDebt() {
    const sum = document.getElementById('kuDebtSummary');
    const body = document.getElementById('kuDebtBody');
    if (!sum && !body) return;
    let d = null;
    try { d = await apiGet('/beban-hutang'); } catch (_) {}
    const hutang = (d && d.saldo_hutang) || 0;
    if (sum) {
        const cards = [
            { label: 'Sisa Hutang Beban', value: kuRupiah(hutang), icon: 'fa-file-circle-exclamation', cls: 'sm-red' },
            { label: 'Saldo Kas Aset', value: kuRupiah((d && d.saldo_kas_aset) || 0), icon: 'fa-vault', cls: 'sm-blue' },
        ];
        sum.innerHTML = cards.map(c => `
            <div class="sm-card ${c.cls}">
                <div class="sm-top"><i class="fa-solid ${c.icon}"></i>${c.label}</div>
                <div class="sm-bot"><span class="sm-num ku-num">${c.value}</span></div>
            </div>`).join('');
    }
    if (body) {
        const per = (d && d.periode) || [];
        body.innerHTML = per.length ? per.map(p => `<tr>
            <td>${escapeHtml(p.periode || '-')}</td>
            <td class="numeric-r">${kuRupiah(p.defisit || 0)}</td>
            <td class="numeric-r">${kuRupiah(p.cover_kas_aset || 0)}</td>
            <td class="numeric-r">${kuRupiah(p.hutang_baru || 0)}</td></tr>`).join('')
            : `<tr><td colspan="4"><div class="text-center text-sm text-gray-400 py-6">Belum ada proses defisit Beban.</div></td></tr>`;
    }
    kuRenderHutangManual();
    applyRoleUI(document.body);
}

// OD-LOCK-12: padanan Conditions Kas Operasional (baris terakhir tabel).
// Dihitung backend di `dashboard._kondisi_kas_akhir` dan dikirim sebagai
// `finance.kondisi_kas_akhir`, jadi angka di sini sama persis dengan yang
// dibaca Admin di tabel - bukan hasil hitung ulang di frontend.
function kuKondisiKasAkhir() {
    const fin = _kuFin || {};
    const v = Number(fin.kondisi_kas_akhir);
    return isFinite(v) ? v : 0;
}

function kuRenderHutangManual() {
    const wrap = document.getElementById('kuHutangManualWrap');
    const input = document.getElementById('kuHutangInput');
    const btn = document.getElementById('kuHutangBtn');
    const hint = document.getElementById('kuHutangHint');
    if (!wrap || !input || !hint) return;
    const boleh = can('EXPENSE_DEBT_WRITE') || can('KAS_CLOSE');
    const akhir = kuKondisiKasAkhir();
    const minus = akhir < 0 ? -akhir : 0;

    if (!boleh) {
        wrap.classList.add('hidden');
        return;
    }
    wrap.classList.remove('hidden');

    if (minus > 0) {
        // Isi otomatis dengan nilai minus; Admin boleh menyesuaikan selama
        // tidak melebihi minus (server juga memeriksanya).
        if (document.activeElement !== input) input.value = Math.round(minus);
        hint.textContent = 'Conditions Kas Operasional berakhir MINUS '
            + kuRupiah(minus) + '. Isi nominal (tidak boleh melebihi angka itu), '
            + 'lalu tekan Catat. Satu periode hanya boleh satu kali.';
        if (btn) btn.disabled = false;
    } else {
        input.value = '';
        hint.textContent = 'Conditions Kas Operasional berakhir PLUS '
            + kuRupiah(akhir) + '. Tidak ada Hutang Beban yang perlu dicatat '
            + 'pada periode ini.';
        if (btn) btn.disabled = true;
    }
}

function kuPeriodeAktifId() {
    // `finance.periode` = `kas_period:<id>` (lihat `finance.period_key`).
    const fin = _kuFin || {};
    const raw = String(fin.periode || '');
    const cocok = raw.match(/(\d+)\s*$/);
    return cocok ? Number(cocok[1]) : null;
}

async function kuHutangCatat() {
    if (!can('EXPENSE_DEBT_WRITE') && !can('KAS_CLOSE')) {
        toast('Aksi ditolak: hanya Admin / Super Admin.');
        return;
    }
    const input = document.getElementById('kuHutangInput');
    const nominal = Number((input && input.value) || 0);
    const minus = -kuKondisiKasAkhir();
    if (!(minus > 0)) {
        _kuFb('kuDebtFeedback', 'Conditions Kas Operasional tidak minus, jadi tidak ada Hutang Beban.', 'error');
        return;
    }
    if (!(nominal > 0)) {
        _kuFb('kuDebtFeedback', 'Isi nominal lebih besar dari nol.', 'error');
        return;
    }
    if (nominal > minus) {
        _kuFb('kuDebtFeedback', 'Nominal ' + kuRupiah(nominal) + ' melebihi nilai minus '
            + kuRupiah(minus) + '.', 'error');
        return;
    }
    const pid = kuPeriodeAktifId();
    if (!pid) {
        _kuFb('kuDebtFeedback', 'Periode kas aktif tidak ditemukan.', 'error');
        return;
    }
    if (!confirm('Catat Hutang Beban ' + kuRupiah(nominal)
        + ' untuk periode ini?\n\nTindakan ini hanya bisa satu kali per periode.')) return;
    try {
        const res = await apiPost('/beban-hutang/catat',
            { kas_period_id: pid, nominal: nominal },
            { idempotencyKey: newIdemKey() });
        _kuFb('kuDebtFeedback', 'Hutang Beban ' + kuRupiah(res.hutang_baru)
            + ' tercatat. Sisa hutang ' + kuRupiah(res.saldo_hutang) + '.', 'success');
        toast('Hutang Beban tercatat.', 'success');
        await loadKuDebt();
    } catch (err) {
        _kuFb('kuDebtFeedback', err.message || 'Gagal mencatat Hutang Beban.', 'error');
    }
}

async function kuDebtLunas() {
    if (!can('EXPENSE_DEBT_WRITE')) { toast('Aksi ditolak: hanya Admin.'); return; }
    try {
        const pre = await apiGet('/beban-hutang/precheck');
        if (!pre || !pre.bisa_lunas) {
            _kuFb('kuDebtFeedback', pre && pre.saldo_hutang === 0
                ? 'Tidak ada Hutang Beban outstanding.'
                : 'Saldo Kas Aset tidak cukup untuk melunasi.', 'error');
            return;
        }
        if (!confirm('Lunasi Hutang Beban ' + _kuMoney(pre.saldo_hutang) + ' dari Kas Aset?')) return;
        const res = await apiPost('/beban-hutang/lunas', {}, { idempotencyKey: newIdemKey() });
        _kuFb('kuDebtFeedback', 'Pelunasan ' + _kuMoney(res.nominal) + '. Sisa hutang '
            + _kuMoney(res.saldo_hutang) + '.', 'success');
        toast('Hutang Beban dilunasi.', 'success');
        await loadKuDebt();
    } catch (err) {
        _kuFb('kuDebtFeedback', err.message || 'Gagal melunasi Hutang Beban.', 'error');
    }
}

// Notifikasi (P2-13): log read-only + status provider.
// Di UI hanya sebuah ICON lonceng (badge jumlah antrean) + popover 10 terbaru.
let _kuNotifData = { items: [], n_diantrekan: 0, provider_aktif: false };

async function kuToggleNotif(ev) {
    if (ev) ev.stopPropagation();
    const pop = document.getElementById('kuNotifPop');
    const btn = document.getElementById('kuNotifBtn');
    if (!pop) return;
    const akanBuka = pop.classList.contains('hidden');
    if (akanBuka) {
        // Muat ulang saat dibuka supaya isinya tidak basi.
        try { await loadKuNotif(); } catch (_) {}
        pop.classList.remove('hidden');
        if (btn) btn.setAttribute('aria-expanded', 'true');
        document.addEventListener('click', kuTutupNotifJikalauDiLuar, true);
    } else {
        kuTutupNotif();
    }
}

function kuTutupNotif() {
    const pop = document.getElementById('kuNotifPop');
    const btn = document.getElementById('kuNotifBtn');
    if (pop) pop.classList.add('hidden');
    if (btn) btn.setAttribute('aria-expanded', 'false');
    document.removeEventListener('click', kuTutupNotifJikalauDiLuar, true);
}

function kuTutupNotifJikalauDiLuar(e) {
    const wrap = document.querySelector('.ku-notif-wrap');
    if (wrap && !wrap.contains(e.target)) kuTutupNotif();
}

// Di-load saat halaman Keuangan dibuka supaya badge langsung terisi.
async function loadKuNotif() {
    const body = document.getElementById('kuNotifBody');
    const prov = document.getElementById('kuNotifProvider');
    const badge = document.getElementById('kuNotifBadge');
    if (!body && !badge) return;
    let d = null;
    try { d = await apiGet('/notifications?limit=10'); } catch (_) {}
    const items = (d && d.items) || [];
    _kuNotifData = {
        items: items,
        n_diantrekan: (d && typeof d.n_diantrekan === 'number') ? d.n_diantrekan : 0,
        provider_aktif: !!(d && d.provider_aktif)
    };
    if (badge) {
        // Badge = antrean yang belum terkirim. Selama provider nonaktif angka ini
        // hanya naik -- itu memang mencerminkan antrean, bukan error.
        const n = _kuNotifData.n_diantrekan;
        badge.textContent = n > 99 ? '99+' : String(n);
        badge.classList.toggle('hidden', n <= 0);
        badge.title = n + ' notifikasi belum terkirim';
    }
    if (prov) {
        prov.textContent = _kuNotifData.provider_aktif
            ? 'provider: aktif'
            : 'provider: nonaktif';
    }
    if (body) {
        body.innerHTML = items.length ? items.map(n => `<tr>
            <td class="whitespace-nowrap">${escapeHtml(String(n.created_at || '').replace('T', ' ').slice(0, 16))}</td>
            <td>${escapeHtml(n.event || '-')}</td>
            <td><span class="ku-notif-chip ku-notif-chip-${escapeHtml(String(n.status || '').toLowerCase())}">${escapeHtml(n.status || '-')}</span></td></tr>`).join('')
            : `<tr><td colspan="3"><div class="text-center text-sm text-gray-400 py-6">Belum ada notifikasi.</div></td></tr>`;
    }
    return _kuNotifData;
}

// ── Keuangan: Rincian Arus Kas dipindah ke "Riwayat Transaksi" ──
// Halaman utama (kuMainView) fokus ke Kondisi Kas Operasional, Alokasi Profit,
// Titipan DP, dan panel turunan. Tabel Rincian Arus Kas beserta arsip periode
// tertutup disembunyikan di balik tombol "Riwayat Transaksi" paling bawah.
function _kuRiwayatVisible() {
    const v = document.getElementById('kuRiwayatView');
    return !!v && !v.classList.contains('hidden');
}

// Buka Riwayat Transaksi: tampilkan panelnya, sembunyikan pembuka, muat ulang
// tabel (penting: dipanggil ulang tiap dibuka supaya data periode segar).
function kuShowRiwayat() {
    const view = document.getElementById('kuRiwayatView');
    const toggle = document.getElementById('kuRiwayatToggleWrap');
    if (view) view.classList.remove('hidden');
    if (toggle) toggle.classList.add('hidden');
    renderRiwayat();
    if (view) view.scrollIntoView({ block: 'start', behavior: 'smooth' });
}

// Kembali ke halaman utama: sembunyikan Riwayat, tampilkan kembali pembuka.
function kuShowMain() {
    const view = document.getElementById('kuRiwayatView');
    const toggle = document.getElementById('kuRiwayatToggleWrap');
    if (view) view.classList.add('hidden');
    if (toggle) toggle.classList.remove('hidden');
    const page = document.getElementById('pageKeuangan');
    if (page) page.scrollIntoView({ block: 'start' });
}

// Tutup Kas real: kunci snapshot periode aktif ke server, buka periode baru.
async function kuTutupKas() {
    let counted = null;
    try {
        const raw = localStorage.getItem('bsf_audit_kas');
        if (raw) counted = JSON.parse(raw).nominal;
    } catch (_) {}

    // PERINGATAN KERAS (bukan pemblokiran). Unit CASH yang Modalnya belum diisi
    // TIDAK masuk Omzet/Transaksi sama sekali -- jadi kalau dibiarkan begitu,
    // Laba maupun CTO jadi tidak benar. Tutup kas tetap boleh diteruskan,
    // tapi harus terasa jelas bahwa ada transaksi yang belum lengkap.
    let warn = '';
    let hard = 0;
    try {
        const mk = await apiGet('/kas/modal-kosong?period=current');
        if (mk && mk.jumlah > 0) {
            hard = mk.jumlah;
            const daftar = mk.items.slice(0, 15);
            warn = '\n\n' + '='.repeat(56)
                 + '\n⚠  PERINGATAN KERAS — TRANSAKSI BELUM DIKASIH MODAL  ⚠'
                 + '\n' + '='.repeat(56)
                 + '\n' + mk.jumlah + ' unit berstatus CASH belum punya Modal'
                   + ' (Part/Jasa/Lain = 0):'
                 + '\n'
                 + daftar.map(x => '   • ' + x.no_servis + '   Rp ' + Number(x.harga).toLocaleString('id-ID')).join('\n')
                 + (mk.items.length > daftar.length
                     ? '\n   • ... dan ' + (mk.items.length - daftar.length) + ' unit lainnya' : '')
                 + '\n'
                 + 'Unit-unit ini BELUM masuk Omzet/Transaksi, karena tanpa'
                 + ' modal tidak ada biaya yang tercatat.'
                 + '\nSebaiknya isi Modal Part & Modal Jasa dulu, lalu tutup kas.'
                 + '\n\nNB: servis yang memang tanpa ganti part (hanya jasa)'
                   + ' bisa modal 0 -- tapi harus dikejar agar tidak ikut disaring.'
                 + '\n' + '='.repeat(56);
        }
    } catch (_) {}

    const msg = counted
        ? 'Proses Tutup Kas & Pindah Arsip? Hitungan laci terakhir: Rp ' + Number(counted).toLocaleString('id-ID') + '. Selisih akan dicatat di arsip.' + warn
        : 'Proses Tutup Kas & Pindah Arsip (jam 16.00)? Pastikan seluruh transaksi kas sudah tercatat.' + warn;
    if (!confirm(msg)) return;
    // Kalau ada modal kosong, minta konfirmasi kedua. Bukan sekadar mengulang
    // dialog yang sama -- tujuannya supaya ini terasa benar-benar "keras" dan
    // tidak lolos dengan tidak sengaja menekan OK.
    if (hard > 0) {
        const lagi = confirm(
            'Yakin? ' + hard + ' transaksi akan ikut masuk ARSIP tanpa Modal\n'
            + 'sehingga TIDAK terhitung di Omzet periode ini.\n\n'
            + 'Klik Cancel untuk membatalkan dan mengisi Modal dulu.');
        if (!lagi) return;
    }
    try {
        const res = await apiPost('/kas/close', { cash_counted: counted },
                                 { idempotencyKey: newIdemKey() });
        try { localStorage.removeItem('bsf_audit_kas'); } catch (_) {}
        const s = (res && res.snapshot) || {};
        const f = s.finance || {};
        const r = v => 'Rp ' + (Number(v) || 0).toLocaleString('id-ID');
        toast('Tutup kas berhasil. Masuk ' + r(f.total_masuk) + ' • Keluar ' + r(f.total_keluar)
            + ' • Saldo ' + r(f.saldo)
            + (s.selisih !== null && s.selisih !== undefined ? ' • Selisih laci ' + r(s.selisih) : '')
            + '. Periode baru dibuka.', 'success');
        try { await loadDashboard(); } catch (_) {}
        await loadKuFinance();
        renderKuArsip();
    } catch (err) {
        toast(err.message || 'Gagal tutup kas.');
    }
}

// Arsip periode yang sudah ditutup (snapshot dari server).
async function renderKuArsip() {
    const el = document.getElementById('kuArsip');
    const block = document.getElementById('kuArsipBlock');
    if (!el) return;
    try {
        const periods = await apiGet('/kas/periods');
        const closed = (periods || []).filter(p => p && p.status === 'CLOSED' && p.snapshot);
        const snaps = closed.map(p => {
            try { return { p, s: JSON.parse(p.snapshot) }; } catch (_) { return null; }
        }).filter(x => x && x.s);
        if (!snaps.length) {
            el.innerHTML = '';
            if (block) block.hidden = true;
            return;
        }
        // Panel-nya sendiri sudah ada di HTML (blok 4 "Arsip Tutup Kas"), jadi di
        // sini cukup baris-barisnya -- tidak perlu membuat `.panel` baru yang
        // membuat blok ini terlihat seperti panel asing di dalam halaman.
        if (block) block.hidden = false;
        const r = v => 'Rp ' + (Number(v) || 0).toLocaleString('id-ID');
        el.innerHTML = snaps.map(({ p, s }) => {
            const f = (s && s.finance) || {};
            const mulai = String(((s || {}).period || {}).start_at || '').slice(0, 16).replace('T', ' ');
            const selesai = String(((s || {}).period || {}).end_at || '').slice(0, 16).replace('T', ' ');
            const punyaSelisih = s.selisih !== null && s.selisih !== undefined;
            const badge = punyaSelisih
                ? (Number(s.selisih) === 0
                    ? '<span class="ku-arsip-chip is-ok">Rekonsiliasi pas</span>'
                    : '<span class="ku-arsip-chip is-warn">Selisih ' + r(s.selisih) + '</span>')
                : '<span class="ku-arsip-chip">Tanpa Declare fisik</span>';
            return `<div class="ku-arsip-row">
                <div class="ku-arsip-main">
                    <div class="ku-arsip-title">
                        <span class="al-dot" style="background:#64748b"></span>
                        Periode ${escapeHtml(mulai)} &ndash; ${escapeHtml(selesai)}
                        ${badge}
                    </div>
                    <div class="ku-arsip-meta">
                        Ditutup ${escapeHtml(String(p.closed_at || '').slice(0, 16).replace('T', ' '))}
                        oleh ${escapeHtml(p.closed_by || '-')}
                    </div>
                </div>
                <div class="ku-arsip-nums">
                    <span>Masuk <b>${r(f.total_masuk)}</b></span>
                    <span>Keluar <b>${r(f.total_keluar)}</b></span>
                    <span>Saldo <b>${r(f.saldo)}</b></span>
                </div>
            </div>`;
        }).join('');
} catch (_) {
        el.innerHTML = '';
        if (block) block.hidden = true;
    }
}

// Panel TITIPAN DP PELANGGAN — terpisah dari Kondisi Kas / Arus Kas.
// 4 ringkasan + daftar mutasi (Tanggal, No Servis, Pelanggan/Unit, Jenis,
// Masuk, Keluar, Saldo). Semuanya dari backend yang menurunkannya dari
// `payments` + `refunds`; tidak ada ledger titipan sendiri, jadi mustahil
// terjadi mutasi ganda walau request diulang atau halaman di-refresh.
function renderKuTitipan() {
    const grid = document.getElementById('kuTitipanGrid');
    const body = document.getElementById('kuTitipanBody');
    if (!grid && !body) return;
    const t = ((_kuFin || {}).titipan_dp) || {};

    // Hanya DP yang MASIH DITAHAN. Unit yang sudah LUNAS atau DP-nya sudah
    // dikembalikan tidak ditampilkan lagi -- begitu tidak ada yang tertahan,
    // panel kosong (Owner: "jika sudah tidak ada Saldo Titipan, sebaiknya data
    // ini dikosongkan saja"). Datanya sendiri tidak dihapus dari database.
    const rows = Array.isArray(t.live) ? t.live : [];
    const kosong = rows.length === 0;
    // Saldo ditahan = seluruh mutasi yang masih tampil (masuk - kembali).
    // Tidak boleh menjumlahkan kolom `saldo`: itu running balance per baris.
    const ditahan = rows.reduce((a, it) =>
        a + (Number(it.masuk) || 0) - (Number(it.keluar) || 0), 0);

    if (grid) {
        const cells = kosong ? [
            { k: 'DP Masih Ditahan', v: 0, c: 'v-saldo' },
        ] : [
            { k: 'DP Masuk', v: ditahan, c: 'v-in' },
            { k: 'Jumlah Unit Bertitipan', v: rows.length, c: '' },
            { k: 'Saldo Titipan Berjalan', v: ditahan, c: 'v-saldo' },
        ];
        grid.innerHTML = cells.map(c => `
            <div class="ku-tp-cell">
                <span class="ku-tp-label">${escapeHtml(c.k)}</span>
                <span class="ku-tp-val ${c.c}">${c.v && Number(c.v).toLocaleString('id-ID') ? kuRupiah(c.v) : c.v}</span>
            </div>`).join('');
    }

    if (!body) return;
    if (kosong) {
        body.innerHTML = '<tr><td colspan="7"><div class="text-center text-xs text-gray-400 py-5">'
            + 'Tidak ada titipan DP yang sedang ditahan. Semua DP sudah menjadi '
            + 'pembayaran transaksi atau dikembalikan.</div></td></tr>';
        return;
    }
    const cls = { 'DP Masuk': 'v-in', 'Dipakai untuk Pelunasan': '', 'Pengembalian DP': 'v-out' };
    body.innerHTML = rows.map(it => `
        <tr>
            <td class="tx-cell-muted tx-nowrap">${escapeHtml(it.tgl || '-')}</td>
            <td class="tx-cell-muted tx-nowrap">${escapeHtml(it.no_servis || '-')}</td>
            <td><span class="tx-ellipsis" title="${escapeHtml(it.pelanggan || '-')} — ${escapeHtml(it.unit || '-')}">${escapeHtml(it.pelanggan || '-')}</span><br><span class="text-[10.5px] text-gray-400">${escapeHtml(it.unit || '-')}</span></td>
            <td class="tx-nowrap"><span class="tx-titipan-tag">${escapeHtml(it.label || it.jenis || '-')}</span></td>
            <td class="numeric-r">${Number(it.masuk) ? kuRupiah(it.masuk) : '<span class="text-green-500">-</span>'}</td>
            <td class="numeric-r">${Number(it.keluar) ? kuRupiah(it.keluar) : '<span class="text-red-500">-</span>'}</td>
            <td class="tx-saldo numeric-r">${kuRupiah(it.saldo)}</td>
        </tr>`).join('');
}

// Kondisi Kas — posisi kas + arus periode OPERASIONAL, URUTAN TETAP:
//   1. Kas Besar        (hanya Admin/Pengelola)
//   2. Kas Kecil/Laci   (Kas Aset Awal periode — bebas dari Titipan DP)
//   3. Total Penjualan  (Omzet — sudah CASH + LUNAS)
//   4. Total Modal     (Part + Jasa + Lain — keluar saat status CASH)
//   5. Total Beban     (Gaji & Operasional)
//   6. Bagi Hasil      (hanya kalau distribusi sudah terbentuk — lihat di bawah)
// Kolom: Uraian / Debit / Kredit / Saldo. Kasir & CS mulai dari baris
// Kas Kecil/Laci — posisi Kas Besar tidak dikirim maupun dirender untuk mereka.
//
// ATURAN OWNER: uang DP TIDAK PERNAH muncul di tabel ini. DP itu titipan
// customer, bukan kas toko, jadi tidak boleh jadi baris Debit/Kredit maupun
// ikut dalam saldo berjalan di sini. Satu-satunya tempat DP dilacak adalah
// panel "Laporan Titipan DP". Jangan menambahkan baris titipan ke tabel ini.
function renderKondisiKas() {
    const body = document.getElementById('kuKondisiBody');
    if (!body) return;
    const fin = _kuFin || {};
    const lihatAset = canViewAset();

    let saldo = 0;
    const rows = [];
    // Tanpa tag di bawah nama: kategori (Kas Aset Awal / Omzet / Modal / Beban)
    // sudah terbaca dari uraian dan kartu ringkasan di atas tabel.
    //
    // Kolom Saldo = SALDO LACI yang berjalan. Baris berstatus `posisi` (hanya
    // "Kas Besar") TIDAK ikut dijumlahkan: itu posisi uang di Kas Aset, bukan
    // arus kas. Kalau ikut dijumlahkan, saldo terakhir tabel jadi Saldo Laci
    // ditambah Kas Aset — jadi tidak sama dengan kartu "Saldo Kas (Laci)".
    const row = (nama, debit, kredit, cls, posisi) => {
        const d = Number(debit) || 0;
        const k = Number(kredit) || 0;
        if (!posisi) {
            saldo += d - k;
        }
        rows.push(
            `<tr class="${cls || ''}">`
            + `<td><span class="tx-device">${escapeHtml(nama)}</span></td>`
            + `<td class="tx-debit numeric-c">${d ? kuRupiah(d) : '<span class="text-green-500">-</span>'}</td>`
            + `<td class="tx-kredit numeric-c">${k ? kuRupiah(k) : '<span class="text-red-500">-</span>'}</td>`
            + `<td class="tx-saldo numeric-r">${kuRupiah(posisi ? d : saldo)}</td>`
            + `</tr>`);
    };

    // 1. Kas Besar — hanya role ber-authority (backend juga tidak mengirimnya).
    //    Baris POSISI: tidak ikut menambah/mengurangi saldo berjalan.
    if (lihatAset && fin.saldo_aset !== undefined) {
        row('Kas Besar (Pengelola)', Number(fin.saldo_aset) || 0, 0, 'is-besar', true);
    }
    // 2. Kas Kecil / Laci — saldo operasional (titipan DP dikurangi).
    row('Kas Kecil / Laci', Number(fin.kas_aset_awal_operasional) || 0, 0, 'is-laci');
    // 3. Total Penjualan Service (Omzet periode).
    row('Total Penjualan Service', Number(fin.omset) || 0, 0);
    // TIDAK ADA baris titipan DP di Kondisi Kas Operasional.
    //
    // Owner (tegas): "uang DP tidak masuk ke Kondisi Kas Operasional. DP hanya
    // masuk Laporan Titipan DP." Baris 'Uang Titipan DP (Belum Jadi Omzet)'
    // pernah ada di sini untuk mengejar kolom Saldo dengan kartu "Saldo Kas
    // (Laci)". Sekarang kartu itu sudah bebas DP (laci_milik_toko), jadi baris
    // itu justru membuat DP muncul di tempat yang Owner larang. Seluruh
    // posisi titipan hanya dilacak di panel "Laporan Titipan DP".
    // 4. Total Modal (Part + Jasa + Lain).
    row('Total Modal (Part+Jasa+Lain)', 0, Number(fin.total_modal) || 0);
    // 5. Total Beban (Gaji & Operasional).
    row('Total Beban (Gaji & OPS)', 0, Number(fin.total_beban) || 0);

    // 6. BAGI HASIL — muncul kalau distribusi sudah benar-benar TERBENTUK,
    //    yaitu uangnya sudah keluar dari Laci (70%) dan 30% Hak Kas Aset sudah
    //    masuk ke Saldo Aset.
    //
    //    Syarat "sudah terbentuk" itu penting: kalau hanya CTO tercapai tapi
    //    distributions belum dijalankan, uangnya masih ada di Laci. Kalau baris
    //    ini ikut digambar dari angka pratinjau, kolom Saldo di tabel akan
    //    berhenti di angka yang SALAH (tidak sama dengan Saldo Kas (Laci)).
    //
    //   Menambah 4 baris Kredit di sini TIDAK merusak saldo berjalan: seluruh
    //    porsi (70% + 30%) memang benar-benar keluar dari Laci, sehingga saldo
    //    terakhir tabel tetap sama dengan Saldo Kas (Laci).
    const al = fin.alokasi || {};
    const formed = !!fin.alokasi_terbentuk && Number(fin.laba_bersih) > 0;
    if (formed) {
        rows.push(
            `<tr class="ku-kd-sep"><td colspan="4">`
            + `<span class="ku-kd-sep-txt"><i class="fa-solid fa-share-from-square"></i> `
            + `Bagi Hasil Laba — sudah dibagikan (CTO tercapai)</span></td></tr>`);
        row('Bagi Hasil: Bonus Karyawan (10%)', 0, Number(al.karyawan) || 0);
        row('Bagi Hasil: Pengelola (30%)', 0, Number(al.pengelola) || 0);
        row('Bagi Hasil: Investor (30%)', 0, Number(al.investor) || 0);
        // Porsi Hak Kas Aset keluar dari Laci lalu masuk ke Kas Aset. Di tabel
        // ini tetap Kredit karena uangnya memang keluar dari Laci.
        row('Setoran Kas Aset (30%)', 0, Number(al.kas_aset) || 0, 'is-total');
    } else if (fin.cto_tercapai) {
        rows.push(
            `<tr class="ku-kd-tunggu"><td colspan="4">`
            + `<span class="ku-kd-tunggu-txt"><i class="fa-solid fa-circle-info"></i> `
            + `CTO tercapai — distribusi belum dijalankan. Tekan `
            + `<b>Jalankan Distribusi</b> di panel Alokasi Profit. `
            + `Baris Bagi Hasil akan muncul setelah uangnya benar-benar dibagikan.`
            + `</span></td></tr>`);
    }

body.innerHTML = rows.join('');
}

// CATATAN (2026-10-17, Owner): kartu ringkasan Kas di panel "Kas Operasional"
// (Kas Kecil / Kas Besar / MASTER KAS) SUDAH DIHAPUS karena isinya mengulang
// tabel "Kondisi Kas Operasional" yang ada tepat di bawahnya. Fungsi
// renderBukuKas() ikut dihapus. Posisi uang sekarang dibaca langsung dari
// tabel itu.

// Distribusi Laba — otomatis begitu CTO tercapai (Laba Kotor >= Total Beban).
// Uangnya LANGSUNG bergerak saat baris distribusi terbentuk, tidak menunggu
// Tutup Kas:
//   10% Karyawan / 30% Pengelola / 30% Investor -> keluar permanen dari Laci
//   30% Hak Kas Aset                          -> keluar Laci, masuk Saldo Aset
// Efeknya Master Kas turun hanya 70% (porsi Hak Kas Aset hanya pindah lokasi).
// Jalankan distribusi sekarang (tombol manual). Memakai gatekeeper yang SAMA
// dengan pemicu otomatis, jadi persis aturan yang berlaku: 70% keluar permanen
// dari Laci, 30% Hak Kas Aset pindah ke Saldo Aset, dan tidak jalan kalau
// Saldo Laci tidak cukup untuk seluruh porsi.
async function kuJalankanDistribusi() {
    if (!confirm('Jalankan Distribusi Laba sekarang?\n\n' +
        '70% (Karyawan + Pengelola + Investor) akan KELUAR permanen dari Laci.\n' +
        '30% Hak Kas Aset akan keluar dari Laci dan MASUK ke Kas Aset.\n\n' +
        'Tindakan ini tidak bisa dibatalkan dari halaman ini.')) return;
    const btn = document.getElementById('kuDistribusiBtn');
    if (btn) { btn.disabled = true; }
    try {
        const res = await apiPost('/kas/distribusi/jalankan', {}, { idempotencyKey: newIdemKey() });
        if (res && res.jalankan) {
            toast('Distribusi dijalankan. Saldo Laci ' + (res.saldo_laci || '0') +
                  ' • Kas Aset ' + (res.saldo_kas_aset || '0') +
                  ' • Master Kas ' + (res.master_kas || '0'), 'success');
        } else {
            toast('Belum bisa distribusi: ' + ((res && res.alasan) || 'tidak diketahui'), 'error');
        }
        await loadKuFinance();
    } catch (err) {
        toast((err && err.message) || 'Gagal menjalankan distribusi.', 'error');
    } finally {
        if (btn) { btn.disabled = false; }
    }
}

function renderAlloc() {
    const list = document.getElementById('kuAllocList');
    const totalEl = document.getElementById('kuTotalProfit');
    const btn = document.getElementById('kuDistribusiBtn');
    const fin = _kuFin || {};
    const total = Number(fin.laba_bersih) || 0;
    const al = fin.alokasi || {};
    const cto = !!fin.cto_tercapai;
    const formed = !!fin.alokasi_terbentuk && total > 0;
    const src = formed ? al : (fin.alokasi_preview || {});
    const badge = document.getElementById('kuAllocBadge');
    const note = document.getElementById('kuAllocNote');
    if (badge) {
        badge.classList.toggle('is-ok', cto);
        badge.textContent = !cto ? 'MENUNGGU CTO'
            : (formed ? 'TERBENTUK' : 'MENUNGGU');
    }
    if (note) {
        const alasan = fin.distribusi_alasan;
        note.textContent = !cto
            ? 'Belum otomatis: Laba Kotor masih di bawah Total Beban (CTO).'
            : (formed
                ? 'Uang sudah dibagikan: 70% keluar dari Laci, 30% Hak Kas Aset masuk ke Kas Aset.'
                : (alasan ? ('Belum terbentuk — ' + alasan + '.')
                          : 'Menunggu perhitungan laba periode.'));
    }
    if (totalEl) totalEl.textContent = kuRupiah(total);
    // Catatan kecil di bawah: KAPAN distribution terbentuk + berapa kali laba
    // sudah ditambahkan lewat top-up. Tanpa ini, kenaikan yang terjadi (laba naik
    // lalu dialokasikan lagi) terlihat seperti angka yang melompat tanpa sebab.
    const catatan = document.getElementById('kuAllocCatatan');
    if (catatan) {
        if (!cto) {
            catatan.innerHTML = 'Alokasi <b>otomatis</b> saat Target Operasional (CTO) tercapai — bukan saat Tutup Kas.';
        } else if (!formed) {
            catatan.innerHTML = 'Begitu CTO tercapai, laba bersih langsung dibagi <b>10% / 30% / 30% / 30%</b> secara otomatis. Kalau ada transaksi baru setelahnya, hanya <b>selisihnya</b> yang ditambah.';
        } else {
            // 1 = baru terbentuk, >1 = ada top-up karena laba naik lagi.
            const n = Number(fin.distribusi_jumlah_alokasi) || 0;
            let t = 'Sudah terbentuk otomatis. 70% keluar dari Laci, 30% Hak Kas Aset masuk ke Kas Aset.';
            if (n > 1) t += ' Terjadi <b>' + (n - 1) + ' kali top-up</b> — tiap kali laba naik, hanya selisihnya yang ditambah.';
            catatan.innerHTML = t;
        }
    }
    // Tombol manual hanya muncul kalau CTO tercapai tapi distributions belum
    // jalan — mis. data sudah terlanjur CASH sebelum aturan otomatis ini aktif.
    if (btn) btn.classList.toggle('hidden', !(cto && !formed));
    _kuAllocView = cto ? [
        { nama: 'Bonus Karyawan', val: src.karyawan || 0, color: '#f59e0b' },
        { nama: 'Pengelola', val: src.pengelola || 0, color: '#dc2626' },
        { nama: 'Investor', val: src.investor || 0, color: '#2563eb' },
        { nama: 'Kas Aset', val: src.kas_aset || 0, color: '#16a34a' },
    ] : [];
    updateProfitChart(_kuAllocView.map(a => (total > 0 ? a.val / total * 100 : 0)), cto);
    if (!list) return;
    if (!cto) {
        list.innerHTML = '';
        return;
    }
    list.innerHTML = _kuAllocView.map((a, i) => {
        const pct = total > 0 ? Math.round(a.val / total * 100) : 0;
        return `
        <div class="al-row${i === _kuSelAlloc ? ' is-sel' : ''}" data-alloc="${i}">
            <span class="al-dot" style="background:${a.color}"></span>
            <span class="al-name">${escapeHtml(a.nama)}</span>
            <span class="al-pct">${pct}%</span>
            <span class="al-nom">${kuRupiah(a.val)}</span>
        </div>`;
    }).join('');
}

function updateProfitChart(series, show) {
    const el = document.querySelector('#kuDonut');
    if (!el || typeof ApexCharts === 'undefined') return;
    const labels = ['Bonus Karyawan', 'Pengelola', 'Investor', 'Kas Aset'];
    const colors = ['#f59e0b', '#dc2626', '#2563eb', '#16a34a'];
    el.style.display = show ? '' : 'none';
    if (!show) return;
    if (_profitChart) {
        _profitChart.updateOptions({ labels, colors, theme: { mode: isDark() ? 'dark' : 'light' } });
        _profitChart.updateSeries(series);
        return;
    }
    _profitChart = new ApexCharts(el, {
        chart: {
            fontFamily: 'Inter, system-ui, sans-serif', type: 'donut', height: 200, toolbar: { show: false },
            events: {
                dataPointSelection: (e, ctx, cfg) => {
                    const i = cfg && cfg.dataPointIndex;
                    _kuSelAlloc = (_kuSelAlloc === i) ? -1 : i;
                    renderAlloc();
                },
            },
        },
        series: series,
        labels: labels,
        colors: colors,
        theme: { mode: isDark() ? 'dark' : 'light' },
        legend: { show: false },
        dataLabels: { enabled: true, formatter: v => Math.round(v) + '%' },
        plotOptions: { pie: { donut: { size: '62%', labels: { show: false } } } },
        stroke: { width: 2 },
        tooltip: { y: { formatter: v => Math.round(v) + '%' } },
    });
    _profitChart.render();
}

function initKuKasForm() {
    const form = document.getElementById('kuKasForm');
    if (!form || form.dataset.bound) return;
    form.dataset.bound = '1';
    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const jenis = document.getElementById('kuKasJenis').value;
        const kategori = document.getElementById('kuKasKategori').value;
        const nominal = Number(document.getElementById('kuKasNominal').value) || 0;
        if (nominal <= 0) return;
        const btn = form.querySelector('button[type="submit"]');
        if (btn) btn.disabled = true;
        try {
            // Beban Gaji/Operasional = expenses (masuk hitungan beban + daftar Beban).
            // Selain itu = jurnal kas manual (pemasukan non-servis / penyesuaian).
            if (jenis === 'Keluar' && (kategori === 'Beban Gaji' || kategori === 'Beban Operasional')) {
                await apiPost('/expenses', {
                    kategori: kategori === 'Beban Gaji' ? 'Gaji' : 'Operasional',
                    uraian: kategori + ' — entri Buku Kas',
                    nilai: nominal,
                });
            } else {
                await apiPost('/kas/entries', {
                    jenis: jenis, kategori: kategori, keterangan: kategori, nominal: nominal,
                });
            }
            document.getElementById('kuKasNominal').value = '';
            await loadKuFinance();
            renderRiwayat();
            try { await loadDashboard(); } catch (_) {}
        } catch (err) {
            toast(err.message || 'Gagal menyimpan entri kas.');
        } finally {
            if (btn) btn.disabled = false;
        }
    });
}

let _kuQuery = '';
let _kuJenis = '';
let _kuDate = '';
let _kuView = [];
let _kuEditId = -1; // id kas_entries yang sedang diedit (-1 = tambah baru)

function initKuToolbar() {
    const s = document.getElementById('kuSearch');
    const j = document.getElementById('kuJenisFilter');
    const d = document.getElementById('kuDateFilter');
    if (s && !s.dataset.bound) {
        s.dataset.bound = '1';
        let t = null;
        s.addEventListener('input', () => {
            clearTimeout(t);
            t = setTimeout(() => { _kuQuery = s.value; _kuPage = 1; renderRiwayat(); }, 300);
        });
    }
    if (j && !j.dataset.bound) {
        j.dataset.bound = '1';
        j.addEventListener('change', () => { _kuJenis = j.value; _kuPage = 1; renderRiwayat(); });
    }
    if (d && !d.dataset.bound) {
        d.dataset.bound = '1';
        d.addEventListener('change', () => { _kuDate = d.value; _kuPage = 1; renderRiwayat(); });
    }
}

function kuEditRow(source, refId) {
    if (source !== 'manual') {
        toast(source === 'order'
            ? 'Data otomatis dari transaksi servis — ubah via Update Data Servis.'
            : 'Data beban — kelola via Input Beban di dashboard.');
        return;
    }
    const r = (_kuView || []).find(x => x && x.source === 'manual' && x.ref_id === refId);
    if (!r) return;
    _kuEditId = refId;
    document.getElementById('keJenis').value = r.jenis || 'Masuk';
    document.getElementById('keKategori').value = r.kategori || 'Lainnya';
    document.getElementById('keKet').value = (r.ket && r.ket !== r.kategori ? r.ket : '') || '';
    document.getElementById('keTgl').value = r.tgl || '';
    document.getElementById('keNominal').value = r.nominal || '';
    const fb = document.getElementById('keuFeedback');
    fb.classList.add('hidden');
    fb.classList.remove('success');
    document.getElementById('pageKeu').classList.add('open');
}

function closeKeu() {
    document.getElementById('pageKeu').classList.remove('open');
    _kuEditId = -1;
}

async function kuDelRow(source, refId, ket) {
    if (source !== 'manual') {
        toast(source === 'order'
            ? 'Data otomatis dari transaksi servis — tidak dapat dihapus di sini.'
            : 'Data beban — hapus via Input Beban di dashboard.');
        return;
    }
    if (!confirm('Hapus "' + (ket || 'transaksi') + '" dari jurnal kas?')) return;
    try {
        await apiDel('/kas/entries/' + refId);
        await loadKuFinance();
        renderRiwayat();
    } catch (err) {
        toast(err.message || 'Gagal menghapus.');
    }
}

function initKeuForm() {
    const form = document.getElementById('keuForm');
    if (!form || form.dataset.bound) return;
    form.dataset.bound = '1';
    // Form riwayat = jurnal kas manual (tersimpan di server).
    form.addEventListener('submit', async function (e) {
        e.preventDefault();
        const ket = document.getElementById('keKet').value.trim();
        if (!ket) return;
        const payload = {
            tgl: document.getElementById('keTgl').value || new Date().toISOString().slice(0, 10),
            jenis: document.getElementById('keJenis').value,
            kategori: document.getElementById('keKategori').value,
            ket: ket,
            nominal: Math.max(1, Number(document.getElementById('keNominal').value) || 0),
        };
        const fb = document.getElementById('keuFeedback');
        try {
            if (_kuEditId >= 0) {
                await apiPut('/kas/entries/' + _kuEditId, {
                    jenis: payload.jenis, kategori: payload.kategori,
                    keterangan: payload.ket, nominal: payload.nominal, tanggal: payload.tgl,
                });
                _kuEditId = -1;
            } else {
                await apiPost('/kas/entries', {
                    jenis: payload.jenis, kategori: payload.kategori,
                    keterangan: payload.ket, nominal: payload.nominal, tanggal: payload.tgl,
                });
                _kuPage = 1;
            }
            await loadKuFinance();
            renderRiwayat();
            fb.classList.remove('hidden');
            fb.classList.add('success');
            fb.innerHTML = `<i class="fa-solid fa-circle-check"></i> Tersimpan di jurnal kas.`;
        } catch (err) {
            fb.classList.remove('hidden');
            fb.innerHTML = `<i class="fa-solid fa-triangle-exclamation"></i> ${escapeHtml(err.message || 'Gagal menyimpan.')}`;
        }
    });
}

// ─────────────────────────────────────────────
// RIWAYAT TRANSAKSI — 3 bagian
//   (1) Ringkasan Kas Laci : Saldo Awal / Total Masuk / Total Keluar / Saldo Akhir
//   (2) Mutasi Kas         : tabel per peristiwa kas + saldo berjalan
//   (3) Rekonsiliasi       : saldo sistem / fisik / selisih / penyesuaian
// Semua angka berasal dari backend; tidak ada yang dihitung ulang di sini.
// ─────────────────────────────────────────────

// Baris pembuka "Saldo Awal" hanya ditampilkan di halaman pertama tanpa filter.
// Kalau difilter, saldo berjalan akan terlihat melompat karena baris sebelumnya
// tidak ikut tampil — jadi lebih baik disembunyikan daripada mengelirukan.
function _kuAwalRow(opening) {
    const tanpaFilter = !_kuQuery.trim() && !_kuJenis && !_kuDate && _kuPage === 1;
    if (!tanpaFilter) return '';
    return `<tr class="ku-row-awal">
            <td class="tx-cell-muted tx-nowrap">&mdash;</td>
            <td><span class="tx-device">SALDO AWAL</span><br><span class="text-[10.5px] text-gray-400">Saldo Laci / Kas Aset Kecil &mdash; awal periode</span></td>
            <td><span class="tx-titipan-tag">Saldo Awal</span></td>
            <td class="numeric-c"><span class="text-green-500">-</span></td>
            <td class="numeric-c"><span class="text-red-500">-</span></td>
            <td class="tx-saldo numeric-r">${kuRupiah(opening)}</td>
            <td class="tx-aksi"></td>
        </tr>`;
}

function _kuSumCard(label, value, icon, cls) {
    return `<div class="sm-card ${cls || ''}">
        <div class="sm-top"><i class="fa-solid ${icon}"></i>${escapeHtml(label)}</div>
        <div class="sm-bot"><span class="sm-num ku-num">${value}</span></div>
    </div>`;
}

// (1) Ringkasan Kas Laci
function renderKuMutasiRingkasan(d) {
    const el = document.getElementById('kuMutasiSummary');
    if (!el) return;
    el.innerHTML = [
        _kuSumCard('Saldo Awal', kuRupiah(d.opening || 0), 'fa-flag', 'sm-blue'),
        _kuSumCard('Total Masuk', kuRupiah(d.total_masuk || 0), 'fa-arrow-trend-up', 'sm-green'),
        _kuSumCard('Total Keluar', kuRupiah(d.total_keluar || 0), 'fa-arrow-trend-down', 'sm-red'),
        _kuSumCard('Saldo Akhir', kuRupiah(d.saldo_akhir || 0), 'fa-wallet', 'sm-blue'),
    ].join('');
}

// (3) Rekonsiliasi Tutup Kas
function renderKuRekonsiliasi(r) {
    const el = document.getElementById('kuRekonsiliasi');
    const note = document.getElementById('kuRekonsiliasiNote');
    if (!el) return;
    const belum = !r || r.saldo_fisik === null || r.saldo_fisik === undefined;
    const nilai = (v) => (v === null || v === undefined) ? '<span class="text-gray-400">Belum dideklarasi</span>' : kuRupiah(v);
    el.innerHTML = [
        _kuSumCard('Saldo Sistem', kuRupiah((r && r.saldo_sistem) || 0), 'fa-scale-balanced', 'sm-blue'),
        _kuSumCard('Saldo Fisik', nilai(r && r.saldo_fisik), 'fa-hand-holding-dollar', belum ? 'sm-blue' : 'sm-green'),
        _kuSumCard('Selisih', belum ? '<span class="text-gray-400">-</span>'
            : kuRupiah(r.selisih), 'fa-scale-unbalanced', belum ? 'sm-blue' : 'sm-red'),
        _kuSumCard('Penyesuaian', (r && r.penyesuaian)
            ? '<span class="text-amber-600">Dicatat</span>' : '<span class="text-gray-400">Tidak ada</span>',
            'fa-pen-to-square', 'sm-blue'),
    ].join('');
    if (note) {
        note.textContent = (r && r.catatan) || '';
        note.classList.toggle('hidden', !note.textContent);
    }
}

async function renderRiwayat() {
    try { kuMenuClose(); } catch (_) {}
    initKuToolbar();
    initKeuForm();
    renderKuArsip();
    const my = ++_kuRiwReq;
    const body = document.getElementById('kuKasBody');
    const empty = document.getElementById('kuEmpty');
    const pagination = document.getElementById('kuPagination');
    const info = document.getElementById('kuInfo');
    const pageBtns = document.getElementById('kuPageBtns');
    if (!body) return;

    body.innerHTML = '';
    empty.classList.add('hidden');
    pagination.classList.add('hidden');

    try {
        // PENTING: period=current. Tanpa itu backend memakai default "all" dan
        // tabelnya menarik SELURUH riwayat, padahal Conditions Kas di atasnya
        // hanya merepresentasikan periode berjalan — saldo barisnya jadi tidak
        // cocok. Periode lama sudah ditangani oleh Arsip Periode Tertutup.
        const params = new URLSearchParams({ period: 'current', page: String(_kuPage), limit: String(KU_PER_PAGE) });
        if (_kuQuery.trim()) params.set('q', _kuQuery.trim());
        if (_kuJenis) params.set('jenis', _kuJenis);
        if (_kuDate) params.set('date', _kuDate);
        const data = await apiGet('/kas/riwayat?' + params.toString());
        if (my !== _kuRiwReq) return; // respons basi — ada request lebih baru

        const items = (data && data.items) || [];
        _kuView = items;
        _kuPage = (data && data.page) || 1;
        const total = (data && data.total) || 0;
        const totalPages = (data && data.total_pages) || 1;

        // (1) & (3) digambar lebih dulu supaya tetap tampil walau tabel kosong.
        renderKuMutasiRingkasan(data || {});
        renderKuRekonsiliasi((data && data.rekonsiliasi) || null);

        if (!items.length) {
            empty.innerHTML = (_kuQuery.trim() || _kuJenis || _kuDate)
                ? '<i class="fa-solid fa-magnifying-glass text-3xl mb-2 block opacity-40"></i>Tidak ada mutasi kas yang cocok dengan filter.'
                : '<i class="fa-solid fa-receipt text-3xl mb-2 block opacity-40"></i>Belum ada mutasi kas periode ini.<br>Pembayaran, DP, beban, dan entri manual akan tercatat otomatis di sini.';
            empty.classList.remove('hidden');
            pagination.classList.add('hidden');
            if (info) info.textContent = '';
            if (pageBtns) pageBtns.innerHTML = '';
            body.innerHTML = _kuAwalRow((data && data.opening) || 0);
            return;
        }

        const start = (_kuPage - 1) * KU_PER_PAGE;
        body.insertAdjacentHTML('beforeend', _kuAwalRow((data && data.opening) || 0));
        items.forEach((r) => {
            const masuk = r.jenis === 'Masuk';
            const manual = r.source === 'manual';
            const isDp = r.source === 'dp';
            const ketJudul = escapeHtml(r.ket || '-');
            const ketSub = escapeHtml(r.kategori || '');
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td class="tx-cell-muted tx-nowrap">${txDate(r.tgl)}</td>
                <td><span class="tx-device tx-ellipsis" title="${ketJudul}">${ketJudul}</span></td>
                <td><span class="tx-ellipsis" title="${ketSub}">${isDp ? '<span class="tx-titipan-tag">Uang Titipan</span>' : ''}${ketSub}</span></td>
                <td class="tx-debit numeric-c">${masuk ? kuRupiah(r.nominal) : '<span class="text-green-500">-</span>'}</td>
                <td class="tx-kredit numeric-c">${masuk ? '<span class="text-red-500">-</span>' : kuRupiah(r.nominal)}</td>
                <td class="tx-saldo numeric-r">${kuRupiah(r.saldo)}</td>
                <td class="tx-aksi">${manual ? `
                    <button type="button" class="tx-view-btn" data-kumenu-btn title="Menu" onclick="kuMenuToggle('${r.source}', ${r.ref_id}, this)"><i class="fa-solid fa-ellipsis-vertical"></i></button>
                ` : `<span class="text-gray-300 dark:text-white/20" title="${isDp ? 'Otomatis dari penerimaan DP' : (r.source === 'order' ? 'Otomatis dari transaksi servis' : 'Otomatis dari beban')}"><i class="fa-solid fa-lock"></i></span>`}
                </td>
            `;
            body.appendChild(tr);
        });

        const end = start + items.length;
        if (total > KU_PER_PAGE) pagination.classList.remove('hidden');
        else pagination.classList.add('hidden');
        if (info) {
            info.textContent = 'Halaman ' + _kuPage + '  ' + (start + 1) + ' - ' + end
                + '  (dari ' + total + ' mutasi)';
        }

        if (pageBtns) {
            pageBtns.innerHTML = '';
            const mkBtn = (txt, p, disabled, active, label) => {
                const b = document.createElement('button');
                b.type = 'button';
                b.innerHTML = txt;
                if (label) { b.title = label; b.setAttribute('aria-label', label); }
                b.className = 'tx-page-btn' + (active ? ' active' : '') + (disabled ? ' disabled' : '');
                if (!disabled) b.addEventListener('click', () => { _kuPage = p; renderRiwayat(); });
                return b;
            };
            pageBtns.appendChild(mkBtn('<i class="fa-solid fa-chevron-left"></i>', _kuPage - 1, _kuPage === 1, false, 'Sebelumnya'));
            for (let p = 1; p <= totalPages; p++) {
                pageBtns.appendChild(mkBtn(String(p), p, false, p === _kuPage));
            }
            pageBtns.appendChild(mkBtn('<i class="fa-solid fa-chevron-right"></i>', _kuPage + 1, _kuPage === totalPages, false, 'Berikutnya'));
        }
    } catch (err) {
        if (my !== _kuRiwReq) return;
        empty.innerHTML = '<i class="fa-solid fa-circle-exclamation text-3xl mb-2 block opacity-40"></i>' + escapeHtml(err.message || 'Gagal memuat data.');
        empty.classList.remove('hidden');
        pagination.classList.add('hidden');
    }
}

function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

// Toast non-blocking pengganti alert() — tumpuk maks 3, hilang otomatis.
function toast(msg, type) {
    try {
        let wrap = document.getElementById('toastWrap');
        if (!wrap) {
            wrap = document.createElement('div');
            wrap.id = 'toastWrap';
            wrap.className = 'toast-wrap';
            wrap.setAttribute('role', 'status');
            document.body.appendChild(wrap);
        }
        const t = document.createElement('div');
        const kind = (type === 'success' || type === 'info') ? type : 'error';
        t.className = 'toast is-' + kind;
        const icon = kind === 'success' ? 'fa-circle-check' : kind === 'info' ? 'fa-circle-info' : 'fa-circle-exclamation';
        const ic = document.createElement('i');
        ic.className = 'fa-solid ' + icon;
        const tx = document.createElement('span');
        tx.textContent = msg;
        t.appendChild(ic);
        t.appendChild(tx);
        wrap.appendChild(t);
        while (wrap.children.length > 3) wrap.removeChild(wrap.firstChild);
        setTimeout(() => { try { t.remove(); } catch (_) {} }, 3800);
    } catch (_) {}
}

async function checkSession() {
    if (!getToken()) return null;
    try {
        const res = await fetch(API_BASE + '/auth/me', { headers: { 'Authorization': 'Bearer ' + getToken() } });
        if (!res.ok) { clearToken(); return null; }
        return res.json();
    } catch (e) {
        clearToken();
        return null;
    }
}

async function handleLogin(e) {
    e.preventDefault();
    clearLoginError();
    const username = document.getElementById('loginUsername').value.trim();
    const passcode = document.getElementById('loginPasscode').value;
    if (!username || !passcode) { setLoginError('Username dan passcode wajib diisi.'); return; }

    const btn = document.getElementById('loginBtn');
    const btnText = document.getElementById('loginBtnText');
    const btnIcon = document.getElementById('loginBtnIcon');
    btn.disabled = true;
    btnText.textContent = 'Memeriksa...';
    btnIcon.classList.remove('fa-arrow-right-to-bracket');
    btnIcon.classList.add('fa-circle-notch', 'fa-spin');

    try {
        const res = await fetch(API_BASE + '/auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, passcode }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            if (res.status === 404) {
                throw new Error('Backend versi lama (tanpa fitur login). Matikan via matikan.bat lalu jalankan ulang jalankan.bat.');
            }
            throw new Error(data.detail || 'Login gagal, coba lagi.');
        }
        const remember = document.getElementById('rememberMe').checked;
        setRemember(remember);
        setToken(data.token, remember);
        if (remember) setSavedUsername(username);
        else clearSavedUsername();
        setAdminUI(data.user);
        hideLogin();
        showPage('dashboard');
        await loadDashboard();
    } catch (err) {
        setLoginError(err.message);
    } finally {
        btn.disabled = false;
        btnText.textContent = 'Login';
        btnIcon.classList.add('fa-arrow-right-to-bracket');
        btnIcon.classList.remove('fa-circle-notch', 'fa-spin');
    }
}

async function handleLogout(e) {
    e.preventDefault();
    if (getToken()) {
        try {
            await fetch(API_BASE + '/auth/logout', { method: 'POST', headers: { 'Authorization': 'Bearer ' + getToken() } });
        } catch (_) { /* abaikan */ }
    }
    clearToken();
    localStorage.removeItem('bsf_page');
    try { localStorage.removeItem(RECEIVE_OPEN_KEY); localStorage.removeItem(RECEIVE_DRAFT_KEY); } catch (_) {}
    history.replaceState(null, '', location.pathname + location.search);
    location.reload();
}

function initLogin() {
    const form = document.getElementById('loginForm');
    const pwToggle = document.getElementById('pwToggle');
    const pwInput = document.getElementById('loginPasscode');
    const userInput = document.getElementById('loginUsername');
    const logoutLink = document.getElementById('logoutLink');

    form.addEventListener('submit', handleLogin);
    logoutLink.addEventListener('click', handleLogout);

    const forgotLink = document.getElementById('forgotLink');
    if (forgotLink) {
        forgotLink.addEventListener('click', () => {
            setLoginError('Hubungi administrator untuk mereset passcode.');
        });
    }

    [userInput, pwInput].forEach(el => {
        el.addEventListener('input', clearLoginError);
    });

    pwToggle.addEventListener('click', () => {
        const show = pwInput.type === 'password';
        pwInput.type = show ? 'text' : 'password';
        pwToggle.innerHTML = `<i class="fa-solid ${show ? 'fa-eye-slash' : 'fa-eye'}"></i>`;
        pwToggle.setAttribute('aria-label', show ? 'Sembunyikan passcode' : 'Tampilkan passcode');
    });

    const capsWarn = document.getElementById('capsWarn');
    if (pwInput && capsWarn) {
        const checkCaps = e => {
            const on = e && e.getModifierState && e.getModifierState('CapsLock');
            capsWarn.classList.toggle('hidden', !on);
        };
        pwInput.addEventListener('keyup', checkCaps);
        pwInput.addEventListener('click', checkCaps);
        pwInput.addEventListener('blur', () => capsWarn.classList.add('hidden'));
    }

    checkServer();
}

// ── Ubah passcode milik sendiri (Kelola Akun) ────────────────────────────────
// Endpoint membatalkan SEMUA token user ini, jadi setelah sukses kita paksa
// logout: kalau tidak, passcode baru yang salah ketik tidak akanketahuan
// sampai token lama sendiri kadaluarsa (7 hari).
const MIN_PASSCODE = 4;
function _pcFb(msg, isErr) {
    const fb = document.getElementById('pcFeedback');
    if (!fb) return;
    fb.classList.remove('hidden', 'success', 'error');
    fb.classList.add(isErr ? 'error' : 'success');
    fb.innerHTML = `<i class="fa-solid ${isErr ? 'fa-triangle-exclamation' : 'fa-circle-check'}"></i> ${escapeHtml(msg)}`;
}

function initPasscodeForm() {
    const form = document.getElementById('passcodeForm');
    if (!form) return;
    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const oldEl = document.getElementById('pcOld');
        const newEl = document.getElementById('pcNew');
        const new2El = document.getElementById('pcNew2');
        const btn = document.getElementById('pcBtn');
        const lama = oldEl ? oldEl.value : '';
        const baru = newEl ? newEl.value.trim() : '';
        const baru2 = new2El ? new2El.value.trim() : '';
        if (!lama) return _pcFb('Isi passcode lama dulu.', true);
        if (baru.length < MIN_PASSCODE) return _pcFb('Passcode baru minimal ' + MIN_PASSCODE + ' karakter.', true);
        if (baru !== baru2) return _pcFb('Ulangi passcode baru tidak sama.', true);
        if (baru === lama) return _pcFb('Passcode baru harus berbeda dari yang lama.', true);
        if (btn) btn.disabled = true;
        try {
            const res = await apiPost('/auth/change-passcode',
                                     { current_passcode: lama, new_passcode: baru });
            _pcFb((res && res.pesan) || 'Passcode diubah.', false);
            form.reset();
            // Semua token dicabut backend -- logout agar user langsung login ulang.
            setTimeout(() => {
                clearToken();
                try { localStorage.removeItem('bsf_page'); } catch (_) {}
                location.reload();
            }, 1200);
        } catch (err) {
            _pcFb(err.message || 'Gagal mengubah passcode.', true);
            if (btn) btn.disabled = false;
        }
    });
}

async function checkServer() {
    const box = document.getElementById('serverStatus');
    const txt = document.getElementById('serverStatusText');
    if (!box || !txt) return false;
    const set = (mode, label) => {
        box.dataset.mode = mode;
        txt.textContent = label;
    };
    set('checking', 'Memeriksa server...');
    try {
        const ctl = new AbortController();
        const timer = setTimeout(() => ctl.abort(), 5000);
        const res = await fetch('/', { method: 'HEAD', signal: ctl.signal, cache: 'no-store' });
        clearTimeout(timer);
        if (!res.ok) throw new Error('bad status');
        set('online', 'Server terhubung');
        return true;
    } catch (_) {
        set('offline', 'Server tidak terjangkau');
        return false;
    }
}

// ─────────────────────────────────────────────
// INIT
// ─────────────────────────────────────────────

// ─────────────────────────────────────────────
// SERVIS BARU — stepper, shortcut, histori states (UI-only, tanpa ubah payload/API)
// ─────────────────────────────────────────────

function updateReceiveSteps() {
    const steps = document.querySelectorAll('#rcSteps .rc-step');
    if (!steps.length) return;
    const val = id => { const el = document.getElementById(id); return el ? (el.value || '') : ''; };
    const s1 = val('rcName').trim() !== '' && val('rcPhone').trim() !== '';
    const s2 = s1 && val('rcDevice').trim() !== '' && val('rcDamage').trim() !== '';
    const s3 = s1 && s2 && ((parseFloat(val('rcEstimate')) || 0) > 0 || (parseFloat(val('rcDp')) || 0) > 0 || val('rcTechnician').trim() !== '');
    const done = [s1, s2, s3];
    steps.forEach((li, idx) => {
        const n = idx + 1;
        li.classList.remove('is-active', 'is-done');
        if (n <= 3) {
            if (done[idx]) li.classList.add('is-done');
            else if (n === 1 || done[idx - 1]) li.classList.add('is-active');
        } else {
            if (done[0] && done[1] && done[2]) li.classList.add('is-active');
        }
    });
}

function rcShortcutToggle() {
    const pop = document.getElementById('rcShortcutPop');
    if (pop) pop.classList.toggle('open');
}

// Klik area luar menutup popover (sekali ikat, tanpa mengganggu form/shortcut).
if (!window._rcShortcutBound) {
    window._rcShortcutBound = true;
    document.addEventListener('click', function (e) {
        const pop = document.getElementById('rcShortcutPop');
        if (!pop || !pop.classList.contains('open')) return;
        if (e.target.closest('#rcShortcutPop, #rcShortcutFab')) return;
        pop.classList.remove('open');
    });
}

function initReceiveShortcuts() {
    if (document.body.dataset.rcKeys === '1') return;
    document.body.dataset.rcKeys = '1';
    document.addEventListener('keydown', function (e) {
        const win = document.getElementById('pageReceive');
        if (!win || !win.classList.contains('open')) return;
        if (e.key === 'F2') {
            e.preventDefault();
            document.getElementById('rcName').focus();
        } else if (e.key === 'F4') {
            e.preventDefault();
            document.getElementById('rcDevice').focus();
        } else if (e.key === 'F8' || ((e.ctrlKey || e.metaKey) && String(e.key).toLowerCase() === 's')) {
            e.preventDefault();
            document.getElementById('receiveForm').requestSubmit();
        } else if (e.key === 'Enter') {
            const t = e.target;
            if (t && t.tagName === 'INPUT' && t.type !== 'submit' && t.type !== 'checkbox' && win.contains(t)) {
                e.preventDefault();
                const fields = Array.from(win.querySelectorAll('input, select, textarea'))
                    .filter(el => !el.disabled && el.type !== 'hidden' && el.offsetParent !== null);
                const i = fields.indexOf(t);
                if (i > -1 && i < fields.length - 1) fields[i + 1].focus();
            }
        }
    });
}

function renderCustSummary(o) {
    const initial = ((o.name || '?').trim().charAt(0) || '?').toUpperCase();
    return `<div class="rc-cust">
        <div class="rc-cust-top"><span class="rc-cust-ava">${escapeHtml(initial)}</span>`
        + `<div class="rc-cust-id"><b>${escapeHtml(o.name)}</b><span>${escapeHtml(o.phone)}</span></div>`
        + `<span class="rc-cust-total">${o.total}× servis</span></div>`
        + `<div class="rc-cust-grid">`
        + `<div><span>Device Terakhir</span><b>${escapeHtml(o.device || '-')}</b></div>`
        + `<div><span>Perbaikan Terakhir</span><b>${escapeHtml(o.plan || '-')}</b></div>`
        + `<div><span>Harga Terakhir</span><b>${o.price != null ? formatRupiah(o.price) : '-'}</b></div>`
        + `</div></div>`;
}

function historyItemsHtml(rows) {
    return rows.map(o => `
        <div class="history-item">
            <div class="history-top">
                <span class="history-no">${o.no_servis}</span>
                <span class="history-status st-${(o.status || '').toLowerCase().replace(/ /g, '')}">${o.status}</span>
            </div>
            <div class="history-dev"><i class="fa-solid fa-mobile-screen-button"></i> ${o.device}${o.model ? ' - ' + o.model : ''}</div>
            <div class="history-meta">
                <span><i class="fa-regular fa-calendar"></i> ${o.created_at ? new Date(o.created_at).toLocaleDateString('id-ID') : ''}</span>
                <span><i class="fa-solid fa-tags"></i> ${formatRupiah(o.estimate)}</span>
            </div>
        </div>
    `).join('');
}

async function loadSmartHistory() {
    const phoneEl = document.getElementById('rcPhone');
    const nameEl = document.getElementById('rcName');
    const list = document.getElementById('smartHistoryList');
    const badge = document.getElementById('smartHistoryState');
    if (!phoneEl || !list) return;
    const setBadge = (txt, mode) => { if (badge) { badge.textContent = txt; badge.dataset.mode = mode || ''; } };
    const phone = phoneEl.value.trim();
    if (!phone) {
        const hint = (nameEl && nameEl.value.trim())
            ? 'Ketik Nomor WhatsApp untuk Histori Cerdas.'
            : 'Ketik Nama / Nomor WhatsApp untuk cek histori pelanggan.';
        list.innerHTML = `<div class="history-empty"><i class="fa-solid fa-user-magnifying-glass"></i> ${hint}</div>`;
        setBadge('Kosong', 'empty');
        return;
    }
    list.innerHTML = `<div class="history-empty rc-searching"><i class="fa-solid fa-circle-notch fa-spin"></i> Mencari histori...</div>`;
    setBadge('Mencari...', 'search');
    try {
        const rows = await apiGet('/orders/history/' + encodeURIComponent(phone));
        if (phoneEl.value.trim() !== phone) return; // hasil basi, abaikan
        if (!rows.length) {
            list.innerHTML = `<div class="history-empty"><i class="fa-solid fa-user-plus"></i> Pelanggan baru — belum memiliki histori servis.</div>`;
            setBadge('Baru', 'new');
            return;
        }
        setBadge('Ditemukan ' + rows.length, 'found');
        const first = rows[0];
        const cust = {
            name: (nameEl && nameEl.value.trim()) || 'Pelanggan',
            phone: phone,
            total: rows.length,
            device: first.device,
            plan: first.repair_plan || first.damagetype,
            price: first.estimate,
        };
        list.innerHTML = renderCustSummary(cust) + historyItemsHtml(rows.slice(0, 3));
    } catch (e) {
        list.innerHTML = `<div class="history-empty"><i class="fa-solid fa-triangle-exclamation"></i> Gagal memuat riwayat</div>`;
        setBadge('Gagal', 'error');
    }
}

// ─────────────────────────────────────────────
// CHECKLIST UNIT — sumber tunggal (Servis Baru & Update konsisten)
// Definisi master; nilai tersimpan permanen per No. Servis (check_fisik/check_len).
// ─────────────────────────────────────────────

const CHECK_FISIK = [
    { key: 'lcd_pecah', label: 'LCD Pecah' },
    { key: 'lcd_terbuka', label: 'LCD Terbuka' },
    { key: 'frame_bengkok', label: 'Frame/Case Bengkok' },
    { key: 'frame_gompal', label: 'Frame/Case Gompal' },
    { key: 'tombol_tidak_ada', label: 'Tombol Tidak Ada' },
    { key: 'bekas_air', label: 'Bekas Air' }
];

const CHECK_LEN = [
    { key: 'unit_saja', label: 'Unit Saja' },
    { key: 'case', label: 'Case' },
    { key: 'sim_card', label: 'SIM Card' },
    { key: 'memory_card', label: 'Memory Card' },
    { key: 'box', label: 'Box' },
    { key: 'charger', label: 'Charger' }
];

// Subset aktif Kondisi & Kelengkapan — dipakai Servis Baru (rc) & Update (us).
// Master CHECK_* tetap utuh sebagai kamus label histori/nota; Klaim memakai daftar penuh.
const ACTIVE_FISIK_KEYS = ['frame_bengkok', 'tombol_tidak_ada', 'bekas_air'];
const ACTIVE_LEN_KEYS = ['unit_saja', 'case', 'sim_card', 'memory_card'];

const _checkStore = {};

function renderChecklist(prefix, containerId, note, only) {
    const box = document.getElementById(containerId);
    if (!box) return;
    const pick = (list, keys) => (keys ? list.filter(it => keys.includes(it.key)) : list);
    const group = (title, icon, list) => `
        <div class="rc-check-group">
            <p class="rc-check-group-head"><span class="rc-check-group-ico"><i class="fa-solid ${icon}"></i></span>${title}</p>
            <div class="rc-check-grid">
                ${list.map(it => `<label class="rc-check"><input type="checkbox" id="${prefix}-ck-${it.key}"><span>${it.label}</span></label>`).join('')}
            </div>
        </div>`;
    box.innerHTML =
            group('Kondisi Fisik Saat Diterima', 'fa-mobile-screen-button', pick(CHECK_FISIK, only && only.fisik))
        + group('Kelengkapan Saat Diterima', 'fa-box-open', pick(CHECK_LEN, only && only.len))
        + (note ? `<p class="field-hint">${note}</p>` : '');
}

function collectChecklist(prefix) {
    const get = (list) => list
        .filter(it => { const el = document.getElementById(prefix + '-ck-' + it.key); return el && el.checked; })
        .map(it => it.key);
    return { fisik: get(CHECK_FISIK), len: get(CHECK_LEN) };
}

function applyChecklist(prefix, data) {
    data = data || { fisik: [], len: [] };
    const set = (list, keys) => list.forEach(it => {
        const el = document.getElementById(prefix + '-ck-' + it.key);
        if (el) el.checked = (keys || []).includes(it.key);
    });
    set(CHECK_FISIK, data.fisik);
    set(CHECK_LEN, data.len);
}

// Daftar teknisi dari server: nama unik di service_orders + user aktif
// ber-role TEKNISI/ADMIN/SUPERADMIN (backend/routers/orders.py).
// WAJIB dipanggil ulang tiap overlay dibuka: pada DOMContentLoaded token belum
// ada, sehingga fetch pertama 401 dan dropdown tetap kosong sampai page reload.
async function loadReceiveTechnicians() {
    const sel = document.getElementById('rcTechnician');
    if (!sel) return [];
    let techs = null;
    try { techs = await apiGet('/orders/technicians'); } catch (_) { return []; }
    if (!Array.isArray(techs) || !techs.length) return [];
    const cur = sel.value || '';
    sel.innerHTML = '<option value="">— Pilih Teknisi —</option>'
        + techs.map(t => `<option value="${t}">${t}</option>`).join('');
    // Kembalikan pilihan teknisi dari draft setelah option async tersedia.
    try {
        const d = JSON.parse(localStorage.getItem(RECEIVE_DRAFT_KEY) || 'null');
        const want = (d && d.rcTechnician) || cur;
        if (want && Array.from(sel.options).some(o => o.value === want)) sel.value = want;
    } catch (_) { if (cur) sel.value = cur; }
    return techs;
}

async function initReceivePage() {
    // Guard anti double-binding: listener submit/input dipasang sekali saja.
    // Pemanggilan ulang hanya me-restore draft (tanpa dobel POST/history).
    if (window._initReceiveBound) { restoreReceiveDraft(); loadReceiveTechnicians(); return; }
    window._initReceiveBound = true;
    renderChecklist('rc', 'rcCheckGroups', null, { fisik: ACTIVE_FISIK_KEYS, len: ACTIVE_LEN_KEYS });
    applyChecklist('rc', { fisik: [], len: ['unit_saja'] });
    restoreReceiveDraft();
    await loadReceiveTechnicians();

    const phoneEl = document.getElementById('rcPhone');
    phoneEl.addEventListener('change', loadSmartHistory);
    phoneEl.addEventListener('keyup', function () { if (this.value.trim().length >= 4) loadSmartHistory(); });
    const nameEl = document.getElementById('rcName');
    if (nameEl) nameEl.addEventListener('input', function () { if (!phoneEl.value.trim()) loadSmartHistory(); });
    const pwToggle = document.getElementById('rcPwToggle');
    const pwInput = document.getElementById('rcPassword');
    if (pwToggle && pwInput) pwToggle.addEventListener('click', () => {
        const show = pwInput.type === 'password';
        pwInput.type = show ? 'text' : 'password';
        pwToggle.innerHTML = `<i class="fa-solid ${show ? 'fa-eye-slash' : 'fa-eye'}"></i>`;
        pwToggle.setAttribute('aria-label', show ? 'Sembunyikan password' : 'Tampilkan password');
    });

    const form = document.getElementById('receiveForm');
    form.addEventListener('input', () => { rcAutoPath(); updateReceiveSteps(); scheduleReceiveDraft(); });
    form.addEventListener('change', () => { rcAutoPath(); updateReceiveSteps(); scheduleReceiveDraft(); });
    // Initial path Servis Baru: radio Posisi Servis (klik manual = kunci pilihan).
    document.querySelectorAll('input[name="rcPath"]').forEach(r => {
        if (!r.dataset.pathBound) {
            r.dataset.pathBound = '1';
            r.addEventListener('change', () => { _rcPathManual = true; rcApplyPath(); try { rcPosAnimate(r.value, false); } catch (_) {} });
        }
    });
    rcApplyPath();
    initReceiveShortcuts();
    updateReceiveSteps();

    document.getElementById('receiveForm').addEventListener('submit', async function (e) {
        e.preventDefault();
        const btn = document.getElementById('receiveSubmitBtn');
        const txt = document.getElementById('receiveSubmitText');
        const fb = document.getElementById('receiveFeedback');
        fb.classList.add('hidden');
        btn.disabled = true;
        txt.textContent = 'Menyimpan...';
        try {
            // Guard initial path (mirror backend check_initial_path).
            const _rcPath = rcGetPath();
            const _rcTarget = RC_PATH_TARGET[_rcPath];
            const _rcVal = id => ((document.getElementById(id) || {}).value || '').trim();
            const _rcMissing = [];
            if (_rcPath === 'REPAIR' || _rcPath === 'WAIT PART') {
                if (!_rcVal('rcPlan')) _rcMissing.push(['Rencana Perbaikan', 'rcPlan']);
                if (!((parseFloat((document.getElementById('rcEstimate') || {}).value) || 0) > 0)) _rcMissing.push(['Estimasi Biaya', 'rcEstimate']);
                if (!_rcVal('rcTechnician')) _rcMissing.push(['Teknisi Penanggung Jawab', 'rcTechnician']);
            } else if (_rcPath === 'TUNGGU') {
                if (!_rcVal('rcPlan')) _rcMissing.push(['Rencana/Tindakan Perbaikan', 'rcPlan']);
                if (!_rcVal('rcTechnician')) _rcMissing.push(['Teknisi Penanggung Jawab', 'rcTechnician']);
                if (((document.getElementById('rcFinal') || {}).value || '').trim() === '') _rcMissing.push(['Harga Final (wajib terdefinisi, boleh 0)', 'rcFinal']);
            }
            if (_rcMissing.length) {
                fb.classList.remove('hidden');
                fb.classList.add('error');
                fb.textContent = 'Path ' + _rcPath + ' wajib melengkapi: ' + _rcMissing.map(m => m[0]).join(', ') + '.';
                const _first = document.getElementById(_rcMissing[0][1]);
                if (_first) _first.focus({ preventScroll: true });
                btn.disabled = false;
                txt.textContent = 'Terima & Daftarkan Servis';
                return;
            }
            // OD-LOCK-04 (Owner, LOCKED): DP tidak boleh lebih besar daripada
            // estimasi biaya. Divalidasi di sini agar user dapat umpan balik
            // SEBELUM disimpan; backend tetap menjadi pengaman utama.
            const _rcEst = parseFloat((document.getElementById('rcEstimate') || {}).value) || 0;
            const _rcDp = parseFloat((document.getElementById('rcDp') || {}).value) || 0;
            if (_rcEst > 0 && _rcDp > _rcEst) {
                fb.classList.remove('hidden');
                fb.classList.add('error');
                fb.textContent = 'DP tidak boleh lebih besar daripada estimasi biaya '
                    + '(estimasi Rp ' + _rcEst.toLocaleString('id-ID')
                    + ', DP Rp ' + _rcDp.toLocaleString('id-ID') + ').';
                const _dpEl = document.getElementById('rcDp');
                if (_dpEl) _dpEl.focus({ preventScroll: true });
                btn.disabled = false;
                txt.textContent = 'Terima & Daftarkan Servis';
                return;
            }
            const _rcFinalRaw = ((document.getElementById('rcFinal') || {}).value || '').trim();
            const _rcCheck = collectChecklist('rc');
            const res = await apiPost('/orders/receive', {
                customer_name: document.getElementById('rcName').value.trim(),
                customer_phone: phoneEl.value.trim(),
                device: document.getElementById('rcDevice').value.trim(),
                device_password: document.getElementById('rcPassword').value.trim(),
                imei: (document.getElementById('rcImei') || {}).value.trim(),
                check_fisik: _rcCheck.fisik,
                check_len: _rcCheck.len,
                damagetype: document.getElementById('rcDamage').value.trim(),
                repair_plan: document.getElementById('rcPlan').value.trim(),
                estimate: parseFloat(document.getElementById('rcEstimate').value) || 0,
                dp: parseFloat(document.getElementById('rcDp').value) || 0,
                final_price: _rcFinalRaw === '' ? null : (parseFloat(_rcFinalRaw) || 0),
                technician: document.getElementById('rcTechnician').value,
                status: _rcTarget,
                initial_path: _rcPath,
            });
            fb.classList.remove('hidden');
            fb.classList.add('success');
            fb.innerHTML = `<i class="fa-solid fa-circle-check"></i> Unit berhasil didaftarkan! No. Servis: <b>${res.no_servis}</b>`;
            _lastNota = {
                no: res.no_servis,
                tgl: new Date().toISOString().slice(0, 10),
                nama: document.getElementById('rcName').value.trim(),
                phone: phoneEl.value.trim(),
                device: document.getElementById('rcDevice').value.trim(),
                damage: document.getElementById('rcDamage').value.trim(),
                plan: document.getElementById('rcPlan').value.trim(),
                estimate: parseFloat(document.getElementById('rcEstimate').value) || 0,
                dp: parseFloat(document.getElementById('rcDp').value) || 0,
                technician: document.getElementById('rcTechnician').value || '',
                status: document.getElementById('rcStatus').value,
                imei: (document.getElementById('rcImei') || {}).value || '',
                password: (document.getElementById('rcPassword') || {}).value || '',
            };
            _lastNota.checklist = _rcCheck;
            _checkStore[res.no_servis] = _rcCheck;
            const _nb2 = document.getElementById('receiveNotaBtn');
            if (_nb2) _nb2.classList.remove('hidden');
            this.reset();
            clearReceiveDraft();
            _rcPathManual = false;
            try { rcApplyPath(); } catch (_) {}
            applyChecklist('rc', { fisik: [], len: ['unit_saja'] });
            document.querySelectorAll('#rcSteps .rc-step').forEach(li => { li.classList.remove('is-active'); li.classList.add('is-done'); });
            loadSmartHistory();
            showReceiveSuccessPopup(res.no_servis);
        } catch (err) {
            fb.classList.remove('hidden');
            fb.classList.add('error');
            fb.textContent = err.message;
        } finally {
            btn.disabled = false;
            txt.textContent = 'Terima & Daftarkan Servis';
        }
    });
}

// ─────────────────────────────────────────────
// NOTA PENERIMAAN SERVICE (data real dari transaksi terakhir)
// ─────────────────────────────────────────────

let _lastNota = null;
let _notaMode = 'SERVICE'; // SERVICE | CLAIM | WARRANTY — menentukan template & teks nota
let _lastClaim = null; // claim garansi terakhir (untuk nota claim & workflow)
let _lastWarranty = null; // nota garansi terakhir (terbit saat SELESAI + LUNAS)

// Placeholder pilihan teknisi tidak boleh bocor ke nota customer.
function notaTechnician(v) {
    const t = String(v || '').trim();
    if (!t || t === '— Pilih Teknisi —' || t === '— Nama Teknisi —') return '-';
    return t;
}

function notaData() { return _lastNota; }

function notaRupiah(v) {
    return 'Rp ' + (Number(v) || 0).toLocaleString('id-ID');
}

function notaTgl(t) {
    const p = String(t || '').split('-');
    return (p.length === 3) ? p[2] + '-' + p[1] + '-' + p[0] : String(t || '-');
}

function openNota() {
    const d = notaData();
    if (!d) {
        notaFlash('Belum ada data nota — buat Servis Baru dulu.', true);
        return;
    }
    renderNotaPreview(d);
    renderNotaDigital(d);
    const fb = document.getElementById('notaFeedback');
    if (fb) fb.classList.add('hidden');
    const win = document.getElementById('pageNota');
    // Nota harus selalu di depan (mis. saat dibuka dari Update Data Servis
    // yang juga float-window). appendChild menaikkan urutan tumpuk,
    // zIndex memastikan menang dari #pageUpdateServis.
    try { document.body.appendChild(win); } catch (_) {}
    win.style.zIndex = '9600';
    win.classList.add('open');
    _notaMode = 'SERVICE';
    try { notaDigitalFit(); } catch (_) {}
}

function closeNota() {
    document.getElementById('pageNota').classList.remove('open');
}

function renderNotaPreview(d) {
    const el = document.getElementById('notaPreview');
    if (!el) return;
    const row = (k, v) => `<div class="nt-row"><span>${escapeHtml(k)}</span><b>${escapeHtml(v || '-')}</b></div>`;
    el.innerHTML = `
        <div class="nt-head">
            <div class="nt-brand">SUKABUMI FLASHER</div>
            <div class="nt-sub">BUSINESS OPERATING SYSTEM</div>
            <div class="nt-title">NOTA PENERIMAAN SERVICE</div>
        </div>
        <div class="nt-sep"></div>
        ${row('No. Servis', d.no)}
        ${row('Tanggal', notaTgl(d.tgl))}
        <div class="nt-sep"></div>
        ${row('Pelanggan', d.nama)}
        ${row('Nomor WhatsApp', d.phone)}
        ${row('Device', d.device)}
        <div class="nt-sep"></div>
        <div class="nt-label">Kerusakan:</div>
        <div class="nt-val">${escapeHtml(d.damage)}</div>
        <div class="nt-label">Tindakan:</div>
        <div class="nt-val">${escapeHtml(d.plan)}</div>
        <div class="nt-sep"></div>
        ${row('Estimasi', notaRupiah(d.estimate))}
        ${row('DP', notaRupiah(d.dp))}
        ${row('Teknisi', notaTechnician(d.technician))}
        ${row('Status', d.status)}
        <div class="nt-sep"></div>
        <div class="nt-foot">Simpan nota ini sebagai<br>bukti pengambilan unit.<br>Terima kasih!</div>`;
}

function notaWrap(text, w) {
    const words = String(text || '-').split(/\s+/);
    const lines = [];
    let cur = '';
    words.forEach(wd => {
        if ((cur + ' ' + wd).trim().length > w) { if (cur) lines.push(cur); cur = wd; }
        else cur = (cur + ' ' + wd).trim();
    });
    if (cur) lines.push(cur);
    return lines.length ? lines : ['-'];
}

function notaText(d) {
    const L = [];
    const sep = '--------------------------------';
    const kv = (k, v) => {
        const s = k + ' : ' + (v || '-');
        notaWrap(s, 32).forEach(x => L.push(x));
    };
    L.push('        SUKABUMI FLASHER');
    L.push('   BUSINESS OPERATING SYSTEM');
    L.push('   NOTA PENERIMAAN SERVICE');
    L.push(sep);
    kv('No', d.no);
    kv('Tgl', notaTgl(d.tgl));
    L.push(sep);
    kv('Pelanggan', d.nama);
    kv('WA', d.phone);
    kv('Device', d.device);
    L.push(sep);
    L.push('Kerusakan:');
    notaWrap(d.damage, 32).forEach(x => L.push(x));
    L.push('Tindakan:');
    notaWrap(d.plan, 32).forEach(x => L.push(x));
    L.push(sep);
    kv('Estimasi', notaRupiah(d.estimate));
    kv('DP', notaRupiah(d.dp));
    kv('Teknisi', notaTechnician(d.technician));
    kv('Status', d.status);
    L.push(sep);
    L.push('Simpan nota ini sebagai');
    L.push('bukti pengambilan unit.');
    L.push('Terima kasih!');
    return L.join('\n');
}

function notaPrintCSS() {
    return 'body{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12px;color:#000;margin:0;padding:8px;}' +
        '.nota{width:72mm;margin:0 auto;white-space:pre-wrap;word-break:break-word;}' +
        '@media print{@page{size:auto;margin:5mm;}body{padding:0;}}';
}

function notaPrint() {
    const isClaim = (_notaMode === 'CLAIM' && _lastClaim);
    const isWarranty = (_notaMode === 'WARRANTY' && _lastWarranty);
    const d = isClaim ? _lastClaim : isWarranty ? _lastWarranty : notaData();
    if (!d) { notaFlash('Belum ada data nota.', true); return; }
    const text = isClaim ? claimNotaText(d) : isWarranty ? warrantyNotaText(d) : notaText(d);
    const w = window.open('', '_blank', 'width=360,height=640');
    if (!w) {
        notaFlash('Popup diblokir browser — izinkan popup untuk mencetak.', true);
        return;
    }
    w.document.write('<!DOCTYPE html><html><head><meta charset="utf-8"><title>Nota ' +
        escapeHtml(d.no || d.claim_no) + '</title><style>' + notaPrintCSS() + '</style></head><body>' +
        '<div class="nota">' + escapeHtml(text) + '</div>' +
        '<script>window.onload=function(){window.print();};<' + '/script></body></html>');
    w.document.close();
}

function notaWaNumber(phone) {
    let p = String(phone || '').replace(/\D/g, '');
    if (!p) return '';
    if (p.charAt(0) === '0') p = '62' + p.slice(1);
    return p;
}

function notaFlash(msg, isErr) {
    const fb = document.getElementById('notaFeedback');
    if (!fb) return;
    fb.classList.remove('hidden', 'success', 'error');
    fb.classList.add(isErr ? 'error' : 'success');
    fb.innerHTML = `<i class="fa-solid ${isErr ? 'fa-triangle-exclamation' : 'fa-circle-check'}"></i> ${escapeHtml(msg)}`;
}

function notaShareWA() {
    const isClaim = (_notaMode === 'CLAIM' && _lastClaim);
    const isWarranty = (_notaMode === 'WARRANTY' && _lastWarranty);
    const d = isClaim ? _lastClaim : isWarranty ? _lastWarranty : notaData();
    if (!d) { notaFlash('Belum ada data nota.', true); return; }
    const msg = isClaim
        ? 'Halo ' + (d.nama || 'Kak') + ', unit Anda sudah kami terima sebagai klaim garansi di SUKABUMI FLASHER.\n\n' + claimNotaText(d)
        : isWarranty
        ? 'Halo ' + (d.nama || 'Kak') + ', servis Anda sudah selesai dan bergaransi 30 hari di SUKABUMI FLASHER.\n\n' + warrantyNotaText(d)
        : 'Halo ' + (d.nama || 'Kak') + ', unit Anda sudah terdaftar di SUKABUMI FLASHER.\n\n' + notaText(d);
    try {
        if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(msg);
    } catch (_) {}
    const num = notaWaNumber(d.phone);
    if (!num) { notaFlash('Nomor WhatsApp kosong — teks nota sudah disalin.', true); return; }
    notaFlash('Teks nota disalin — membuka WhatsApp customer...');
    window.open('https://wa.me/' + num + '?text=' + encodeURIComponent(msg), '_blank');
}

function notaSaveImage() {
    const isClaim = (_notaMode === 'CLAIM' && _lastClaim);
    const isWarranty = (_notaMode === 'WARRANTY' && _lastWarranty);
    const d = isClaim ? _lastClaim : isWarranty ? _lastWarranty : notaData();
    if (!d) { notaFlash('Belum ada data nota.', true); return; }
    const lines = (isClaim ? claimNotaText(d) : isWarranty ? warrantyNotaText(d) : notaText(d)).split('\n');
    const fs = 22, lh = 29, pad = 24, W = 560;
    const H = lines.length * lh + pad * 2;
    const cv = document.createElement('canvas');
    cv.width = W; cv.height = H;
    const ctx = cv.getContext('2d');
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, W, H);
    ctx.fillStyle = '#111111';
    ctx.font = fs + 'px ui-monospace, Menlo, Consolas, monospace';
    ctx.textBaseline = 'top';
    lines.forEach((ln, i) => {
        const tw = ctx.measureText(ln).width;
        const centered = /SUKABUMI FLASHER|BUSINESS OPERATING SYSTEM|NOTA PENERIMAAN|Terima kasih|bukti pengambilan|Simpan nota|^---/.test(ln);
        ctx.fillText(ln, centered ? Math.max(pad, (W - tw) / 2) : pad, pad + i * lh);
    });
    const a = document.createElement('a');
    a.href = cv.toDataURL('image/png');
    a.download = 'nota-' + String(d.no || 'servis').replace(/[^A-Za-z0-9-]/g, '') + '.png';
    document.body.appendChild(a);
    a.click();
    a.remove();
    notaFlash('Gambar nota tersimpan ke device.');
}

// ── Nota Digital: modern, visual, untuk smartphone/WA (data real transaksi) ──

function notaSwitch(tab) {
    const t = document.getElementById('notaThermalWrap');
    const dg = document.getElementById('notaDigitalWrap');
    const tt = document.getElementById('notaTabThermal');
    const td = document.getElementById('notaTabDigital');
    const isD = tab === 'digital';
    if (t) t.classList.toggle('hidden', isD);
    if (dg) dg.classList.toggle('hidden', !isD);
    if (tt) tt.classList.toggle('is-active', !isD);
    if (td) td.classList.toggle('is-active', isD);
    const win = document.getElementById('pageNota');
    if (win) win.classList.toggle('nota-wide', isD);
    if (isD) { const dd = notaData(); if (dd) { renderNotaDigital(dd); notaDigitalFit(); } }
}

// Kanvas Nota Digital fix 1066px: preview diskala agar muat, export selalu 1:1.
function notaDigitalFit() {
    try {
        const wrap = document.getElementById('notaDigital');
        const win = document.getElementById('pageNota');
        if (!wrap || !win || !win.classList.contains('open')) return;
        const sheet = wrap.querySelector('.nps-sheet');
        if (!sheet) return;
        const avail = wrap.clientWidth || 0;
        const s = avail > 0 ? Math.min(1, avail / 1066) : 1;
        if (s < 1) {
            sheet.style.transform = 'scale(' + s + ')';
            sheet.style.transformOrigin = 'top left';
            wrap.style.height = Math.ceil(sheet.offsetHeight * s) + 'px';
            wrap.style.overflow = 'hidden';
        } else {
            sheet.style.transform = '';
            sheet.style.transformOrigin = '';
            wrap.style.height = '';
            wrap.style.overflow = '';
        }
    } catch (_) {}
}

if (!window._npsFitBound) {
    window._npsFitBound = true;
    window.addEventListener('resize', function () { try { notaDigitalFit(); } catch (_) {} });
}

function notaJam() {
    const n = new Date();
    const p = x => String(x).padStart(2, '0');
    return p(n.getHours()) + ':' + p(n.getMinutes());
}

function notaTglSlash(t) {
    const p = String(t || '').split('-');
    return (p.length === 3) ? p[2] + '/' + p[1] + '/' + p[0] : String(t || '-');
}

function notaStatusClass(s) {
    const v = String(s || '').toUpperCase();
    if (v === 'CASH') return 'nd-green';
    if (v === 'SELESAI' || v === 'DONE' || v === 'COMPLETED') return 'nd-green';
    if (v === 'BATAL' || v === 'CANCEL' || v === 'GAGAL' || v === 'FAILED') return 'nd-red';
    if (v === 'DITERIMA' || v === 'ANALISA' || v === 'KONFIRMASI'
        || v === 'WAIT PART') return 'nd-amber';
    if (v === 'REPAIR') return 'nd-blue';
    return 'nd-blue';
}

function notaEstimasiSelesai(d) {
    if (d.estimasi_selesai) return d.estimasi_selesai;
    const m = String(d.tgl || '').match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (!m) return '-';
    const dt = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]) + 3);
    const p = n => String(n).padStart(2, '0');
    return dt.getFullYear() + '-' + p(dt.getMonth() + 1) + '-' + p(dt.getDate());
}

// Nomor WhatsApp TOKO — satu-satunya sumber (tampil di Nota Digital).
// Nomor WA customer tetap dari data servis (d.phone). Jangan dicampur.
const SHOP_WA = '628111737030';
function shopWaDisplay() {
    const p = String(SHOP_WA || '').replace(/\D/g, '').replace(/^62/, '');
    if (p.length === 10) return '+62 ' + p.slice(0, 3) + '-' + p.slice(3, 7) + '-' + p.slice(7);
    return '+' + String(SHOP_WA || '').replace(/\D/g, '');
}

// Snapshot KONDISI SERVIS pada Nota Penerimaan (bukan histori/timeline).
// Lifecycle resmi (P2-15 / FINAL LOCK): DITERIMA → ANALISA → KONFIRMASI → WAIT PART
// → REPAIR → DONE → CASH (+ cabang CANCEL/FAILED).
function notaSnapshotStatus(status) {
    const s = String(status || '').toUpperCase().replace(/\s+/g, '_');
    const map = {
        DITERIMA:   { label: 'DITERIMA',   cls: 'nps-red',     stage: 0, sub: 'Unit baru diterima — belum masuk analisa.' },
        RECEIVED:   { label: 'DITERIMA',   cls: 'nps-red',     stage: 0, sub: 'Unit baru diterima — belum masuk analisa.' },
        ANALISA:    { label: 'ANALISA',    cls: 'nps-amber',   stage: 1, sub: 'Unit dalam pemeriksaan teknisi.' },
        DIAGNOSA:   { label: 'ANALISA',    cls: 'nps-amber',   stage: 1, sub: 'Unit dalam pemeriksaan teknisi.' },
        DIAGNOSIS:  { label: 'ANALISA',    cls: 'nps-amber',   stage: 1, sub: 'Unit dalam pemeriksaan teknisi.' },
        KONFIRMASI: { label: 'KONFIRMASI', cls: 'nps-amber',   stage: 2, sub: 'Menunggu persetujuan pelanggan.' },
        'WAIT PART':{ label: 'WAIT PART',  cls: 'nps-amber',   stage: 3, sub: 'Menunggu sparepart datang.' },
        WAIT_PART:  { label: 'WAIT PART',  cls: 'nps-amber',   stage: 3, sub: 'Menunggu sparepart datang.' },
        REPAIR:     { label: 'REPAIR',     cls: 'nps-blue',    stage: 4, sub: 'Unit sedang dikerjakan teknisi.' },
        PERBAIKAN:  { label: 'REPAIR',     cls: 'nps-blue',    stage: 4, sub: 'Unit sedang dikerjakan teknisi.' },
        DONE:       { label: 'DONE',       cls: 'nps-green',   stage: 5, sub: 'Pekerjaan selesai — unit dapat diambil.' },
        SELESAI:    { label: 'DONE',       cls: 'nps-green',   stage: 5, sub: 'Pekerjaan selesai — unit dapat diambil.' },
        COMPLETED:  { label: 'DONE',       cls: 'nps-green',   stage: 5, sub: 'Pekerjaan selesai — unit dapat diambil.' },
        CASH:       { label: 'CASH',       cls: 'nps-emerald', stage: 6, sub: 'Transaksi terealisasi — unit sudah diambil & dibayar.' },
        FAILED:     { label: 'FAILED',     cls: 'nps-red',     stage: -1, sub: 'Perbaikan tidak berhasil.' },
        GAGAL:      { label: 'FAILED',     cls: 'nps-red',     stage: -1, sub: 'Perbaikan tidak berhasil.' },
        CANCEL:     { label: 'CANCEL',     cls: 'nps-red',     stage: -1, sub: 'Perbaikan dibatalkan.' },
        BATAL:      { label: 'CANCEL',     cls: 'nps-red',     stage: -1, sub: 'Perbaikan dibatalkan.' },
    };
    if (map[s]) return map[s];
    return { label: String(status || '-'), cls: 'nps-neutral', stage: -1, sub: 'Kondisi unit saat nota dibuat.' };
}

const NPS_STAGES = ['DITERIMA', 'ANALISA', 'KONFIRMASI', 'WAIT PART', 'REPAIR', 'DONE', 'CASH'];

// Label checklist nota (fisik/len) dari master yang sudah ada.
function notaChecklistText(list, master) {
    try {
        const arr = Array.isArray(list) ? list : [];
        if (!arr.length) return '-';
        const labels = txdCheckLabels(arr, master);
        return (labels && labels.length ? labels.join(' • ') : '-');
    } catch (_) { return '-'; }
}

function renderNotaDigital(d) {
    const el = document.getElementById('notaDigital');
    if (!el) return;
    const teknisi = notaTechnician(d.technician);
    const tgl = notaTglSlash(d.tgl);
    const jam = notaJam();
    const imei = (d.imei || '').trim() || '-';
    const qrUrl = 'https://api.qrserver.com/v1/create-qr-code/?size=132x132&margin=6&data='
        + encodeURIComponent('SUKABUMI FLASHER ' + (d.no || ''));
    const stCls = notaStatusClass(d.status).replace('nd-', '');
    // Snapshot kondisi servis saat nota dibuat (bukan histori/timeline).
    const st = notaSnapshotStatus(d.status);
    const waShop = shopWaDisplay();
    const sisa = (Number(d.estimate) || 0) - (Number(d.dp) || 0);
    const imeiTxt = (d.imei || '').trim() || '-';
    const fisikTxt = notaChecklistText(d.checklist && d.checklist.fisik, CHECK_FISIK);
    const lenTxt = notaChecklistText(d.checklist && d.checklist.len, CHECK_LEN);
    el.innerHTML = `
    <div class="nps-sheet">
        <div class="nps-head">
            <div class="nps-brand">
                <span class="nps-logo"><img src="/static/assets/logo.png" alt="SUKABUMI FLASHER" onerror="this.style.display='none'"><i class="fa-solid fa-bolt"></i></span>
                <div><b>SUKABUMI FLASHER</b><span>SMARTPHONE SERVICE LAB</span></div>
            </div>
            <div class="nps-contact">
                <div><i class="fa-brands fa-whatsapp"></i>${escapeHtml(waShop)}</div>
                <div><i class="fa-regular fa-calendar"></i>${escapeHtml(tgl)}</div>
                <div><i class="fa-regular fa-clock"></i>Jam: ${escapeHtml(jam)}</div>
            </div>
        </div>
        <div class="nps-body">
            <div class="nps-titlerow">
                <div class="nps-title">
                    <h3>NOTA <em>PENERIMAAN</em> SERVICE</h3>
                    <div class="nps-idlabel"><span class="nps-rule"></span><i class="fa-solid fa-play"></i>NOMER SERVICE<span class="nps-rule"></span></div>
                    <div class="nps-id">${escapeHtml(d.no || '-')}</div>
                </div>
                <div class="nps-proof">
                    <span class="nps-proof-ico"><i class="fa-solid fa-clipboard-check"></i></span>
                    <div><b>BUKTI PENERIMAAN BARANG<br><em>UNTUK PERBAIKAN</em></b><span>Harap simpan nota ini untuk pengambilan unit.</span></div>
                </div>
            </div>
            <div class="nps-cols">
                <div class="nps-main">
                    <div class="nps-card">
                        <div class="nps-cap"><span class="nps-ico"><i class="fa-solid fa-user"></i></span>PELANGGAN</div>
                        <div class="nps-name">${escapeHtml(d.nama || '-')}</div>
                        <div class="nps-line"><i class="fa-brands fa-whatsapp"></i>${escapeHtml(d.phone || '-')}</div>
                    </div>
                    <div class="nps-card">
                        <div class="nps-cap"><span class="nps-ico"><i class="fa-solid fa-mobile-screen-button"></i></span>DEVICE</div>
                        <div class="nps-name">${escapeHtml(d.device || '-')}</div>
                        <div class="nps-kv"><span>IMEI</span><b>${escapeHtml(imeiTxt)}</b></div>
                    </div>
                    <div class="nps-card">
                        <div class="nps-cap"><span class="nps-ico"><i class="fa-solid fa-screwdriver-wrench"></i></span>KELUHAN / DIAGNOSA</div>
                        <p class="nps-text">${escapeHtml(d.damage || '-')}</p>
                    </div>
                    <div class="nps-card">
                        <div class="nps-cap"><span class="nps-ico"><i class="fa-solid fa-list-check"></i></span>RENCANA TINDAKAN</div>
                        <p class="nps-text">${escapeHtml(d.plan || '-')}</p>
                    </div>
                    <div class="nps-card">
                        <div class="nps-cap"><span class="nps-ico"><i class="fa-solid fa-box-open"></i></span>KELENGKAPAN SAAT DITERIMA</div>
                        <p class="nps-text">${escapeHtml(lenTxt)}</p>
                    </div>
                    <div class="nps-card">
                        <div class="nps-cap"><span class="nps-ico"><i class="fa-solid fa-triangle-exclamation"></i></span>KONDISI FISIK SAAT DITERIMA</div>
                        <p class="nps-text">${escapeHtml(fisikTxt)}</p>
                    </div>
                </div>
                <div class="nps-side">
                    <div class="nps-cost">
                        <div class="nps-cost-head">ESTIMASI BIAYA (PERKIRAAN)</div>
                        <div class="nps-cost-row"><span>Estimasi</span><b>${escapeHtml(notaRupiah(d.estimate))}</b></div>
                        <div class="nps-cost-row"><span>DP</span><b>${escapeHtml(notaRupiah(d.dp))}</b></div>
                        <div class="nps-cost-row is-total"><span>Sisa</span><b>${escapeHtml(notaRupiah(sisa))}</b></div>
                        <p class="nps-cost-note">${d.garansi ? escapeHtml(d.garansi) : 'Estimasi dapat berubah sesuai hasil diagnosa teknisi.'}</p>
                    </div>
                    <div class="nps-progress">
                        <div class="nps-cap"><span class="nps-ico"><i class="fa-solid fa-chart-line"></i></span>STATUS</div>
                        <div class="nps-statusline">
                            <span class="nps-pill ${st.cls}">${escapeHtml(st.label)}</span>
                        </div>
                        <div class="nps-steps">${NPS_STAGES.map((s, i) => {
                            const cls = st.stage < 0 ? '' : (i < st.stage ? ' is-past' : (i === st.stage ? ' is-now' : ''));
                            return `<div class="nps-tstep${cls}"><span class="nps-tdot"></span>${s}</div>`;
                        }).join('')}</div>
                        ${st.stage >= 0 ? `<div class="nps-segbar">${NPS_STAGES.map((s, i) => `<span class="nps-seg${i <= st.stage ? ' on' : ''}"></span>`).join('')}<span class="nps-segnum">${st.stage + 1}/${NPS_STAGES.length}</span></div>` : ''}
                        <p class="nps-statussub">${escapeHtml(st.sub)}</p>
                        <p class="nps-received">Diterima pada: <b>${escapeHtml(tgl)}</b> | <b>${escapeHtml(jam)}</b></p>
                    </div>
                </div>
            </div>
            <div class="nps-qrbox">
                <div class="nps-qrleft">
                    <div class="nps-qrtitle">CEK <em>STATUS</em> SERVICE</div>
                    <p>Scan QR atau buka link berikut untuk melihat status terbaru unit Anda.</p>
                    <div class="nps-linkpill"><i class="fa-solid fa-globe"></i>boss-sf.id/lacak/${escapeHtml(d.no || '')}</div>
                </div>
                <div class="nps-qrwrap">
                    <img src="${qrUrl}" alt="QR servis" loading="lazy" onerror="this.style.display='none';var f=this.parentNode.querySelector('.nps-kode-fallback');if(f)f.style.display='flex';">
                    <div class="nps-kode-fallback" style="display:none"><span>KODE SERVIS</span><b>${escapeHtml(d.no || '-')}</b></div>
                </div>
                <div class="nps-trust">
                    <div class="nps-trow"><i class="fa-solid fa-shield-halved"></i><div><b>DATA UNIT AMAN</b><span>Kami menjaga data dan privasi perangkat Anda.</span></div></div>
                    <div class="nps-trow"><i class="fa-regular fa-clock"></i><div><b>ESTIMASI PENGERJAAN</b><span>Akan diinformasikan setelah proses diagnosa.</span></div></div>
                    <div class="nps-trow"><i class="fa-solid fa-phone"></i><div><b>BUTUH BANTUAN?</b><span>Hubungi kami di ${escapeHtml(waShop)}</span></div></div>
                </div>
            </div>
        </div>
        <div class="nps-foot">
            <div class="nps-foot-l"><i class="fa-regular fa-circle-check"></i><span>Terima kasih telah mempercayakan perbaikan perangkat Anda kepada kami.</span></div>
            <div class="nps-foot-r"><b>Powered by <em>SUKABUMI FLASHER</em></b><span>BUSINESS OPERATING SYSTEM</span></div>
        </div>
    </div>`;
}

function notaDigitalText(d) {
    return '*NOTA PENERIMAAN SERVICE*\n*SUKABUMI FLASHER - Business Operating System*\n'
        + '--------------------------\n'
        + 'No. Servis : ' + (d.no || '-') + '\n'
        + 'Status : ' + (d.status || '-') + '\n'
        + 'Nama : ' + (d.nama || '-') + '\n'
        + 'WA : ' + (d.phone || '-') + '\n'
        + 'Device : ' + (d.device || '-') + '\n'
        + 'Keluhan : ' + (d.damage || '-') + '\n'
        + 'Estimasi : ' + notaRupiah(d.estimate) + '\n'
        + 'DP : ' + notaRupiah(d.dp) + '\n'
        + 'Teknisi : ' + (notaTechnician(d.technician)) + '\n'
        + 'Tgl Terima : ' + notaTgl(d.tgl) + '\n'
        + (d.garansi ? d.garansi + '\n' : '')
        + '--------------------------\n'
         + 'Simpan nota ini sebagai bukti pengambilan unit. Terima kasih! - *SUKABUMI FLASHER*';
}

function notaDigitalShareWA() {
    const isClaim = (_notaMode === 'CLAIM' && _lastClaim);
    const isWarranty = (_notaMode === 'WARRANTY' && _lastWarranty);
    const d = isClaim ? _lastClaim : isWarranty ? _lastWarranty : notaData();
    if (!d) { notaFlash('Belum ada data nota.', true); return; }
    const msg = isClaim
        ? 'Halo ' + (d.nama || 'Kak') + ', berikut nota digital klaim garansi Anda di SUKABUMI FLASHER.\n\n' + claimNotaDigitalText(d)
        : isWarranty
        ? 'Halo ' + (d.nama || 'Kak') + ', berikut nota digital garansi servis Anda di SUKABUMI FLASHER.\n\n' + warrantyNotaDigitalText(d)
        : 'Halo ' + (d.nama || 'Kak') + ', berikut nota digital servis Anda di SUKABUMI FLASHER.\n\n' + notaDigitalText(d);
    try {
        if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(msg);
    } catch (_) {}
    const num = notaWaNumber(d.phone);
    if (!num) { notaFlash('Nomor WhatsApp kosong — teks nota sudah disalin.', true); return; }
    notaFlash('Nota digital disalin — membuka WhatsApp customer...');
    window.open('https://wa.me/' + num + '?text=' + encodeURIComponent(msg), '_blank');
}

function notaCanvasWrap(ctx, text, maxW) {
    const words = String(text || '-').split(/\s+/);
    const lines = [];
    let cur = '';
    words.forEach(wd => {
        const t = (cur + ' ' + wd).trim();
        if (ctx.measureText(t).width > maxW) { if (cur) lines.push(cur); cur = wd; }
        else cur = t;
    });
    if (cur) lines.push(cur);
    return lines.length ? lines : ['-'];
}

async function notaSaveDigitalImage() {
    const d = notaData();
    if (!d) { notaFlash('Belum ada data nota.', true); return; }
    const node = document.getElementById('notaDigital');
    const sheet = node ? node.querySelector('.nps-sheet') : null;
    if (sheet && typeof html2canvas !== 'undefined') {
        const prevT = sheet.style.transform;
        const prevO = sheet.style.transformOrigin;
        try {
            notaFlash('Menyiapkan gambar nota...');
            // Export exact 1:1 dari kanvas fix 1066px (lepas skala preview dulu).
            sheet.style.transform = '';
            sheet.style.transformOrigin = '';
            const canvas = await html2canvas(sheet, { backgroundColor: '#ffffff', scale: 1, useCORS: true, logging: false });
            const fname = 'nota-digital-' + String(d.no || 'servis').replace(/[^A-Za-z0-9-]/g, '') + '.png';
            if (canvas.toBlob) {
                const blob = await new Promise(res => canvas.toBlob(res, 'image/png'));
                if (blob) {
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url; a.download = fname;
                    document.body.appendChild(a); a.click(); a.remove();
                    setTimeout(() => URL.revokeObjectURL(url), 4000);
                    notaFlash('Gambar nota digital tersimpan ke device.');
                    return;
                }
            }
            const a = document.createElement('a');
            a.href = canvas.toDataURL('image/png'); a.download = fname;
            document.body.appendChild(a); a.click(); a.remove();
            notaFlash('Gambar nota digital tersimpan ke device.');
            return;
        } catch (_) { /* fallback ke gambar manual di bawah */ }
        finally {
            try {
                sheet.style.transform = prevT || '';
                sheet.style.transformOrigin = prevO || '';
                notaDigitalFit();
            } catch (_) {}
        }
    }
    notaSaveDigitalImageManual(d);
}

// Fallback offline / CDN terblokir: gambar manual sederhana (tidak identik preview).
function notaSaveDigitalImageManual(d) {
    const W = 760, pad = 44;
    const maxW = W - pad * 2;
    const meas = document.createElement('canvas').getContext('2d');
    meas.font = '600 24px Inter, system-ui, sans-serif';
    const wrap = t => notaCanvasWrap(meas, t, maxW);
    const blocks = [
        ['PELANGGAN', d.nama + '  •  ' + (d.phone || '-')],
        ['DEVICE', d.device],
        ['NO. SERVIS', d.no + '  •  Tgl: ' + notaTglSlash(d.tgl) + '  •  Jam: ' + notaJam()],
        ['KELUHAN', d.damage],
        ['TINDAKAN', d.plan],
        ['TEKNISI', notaTechnician(d.technician)],
    ];
    const lines = blocks.map(b => wrap(b[1]));
    const lh = 31;
    let H = 170 + 120;
    lines.forEach(L => { H += 30 + L.length * lh + 26; });
    H += 110 + 4 * 30 + 40 + 90;
    const cv = document.createElement('canvas');
    cv.width = W; cv.height = H;
    const c = cv.getContext('2d');
    c.fillStyle = '#ffffff';
    c.fillRect(0, 0, W, H);
    const g = c.createLinearGradient(0, 0, W, 0);
    g.addColorStop(0, '#d31111'); g.addColorStop(1, '#a30d0d');
    c.fillStyle = g;
    c.fillRect(0, 0, W, 150);
    c.fillStyle = '#ffffff';
    c.font = 'italic 800 52px Inter, system-ui, sans-serif';
    c.fillText('SUKABUMI FLASHER', pad, 72);
    c.font = '600 17px Inter, system-ui, sans-serif';
    c.fillText('S E R V I C E   S Y S T E M', pad, 104);
    c.textAlign = 'right';
    c.font = '600 21px Inter, system-ui, sans-serif';
    c.fillText(notaTglSlash(d.tgl), W - pad, 62);
    c.fillText('Jam: ' + notaJam(), W - pad, 96);
    c.textAlign = 'left';
    let y = 150 + 56;
    c.fillStyle = '#111111';
    c.font = '800 38px Inter, system-ui, sans-serif';
    c.fillText('NOTA PENERIMAAN SERVICE', pad, y);
    y += 18;
    c.fillStyle = '#2563eb';
    c.font = '700 25px ui-monospace, monospace';
    c.fillText(d.no || '-', pad, y + 30);
    y += 62;
    c.font = '700 19px Inter, system-ui, sans-serif';
    c.fillStyle = '#94a3b8';
    blocks.forEach((b, i) => {
        c.fillText(b[0], pad, y);
        y += 30;
        c.fillStyle = '#0f172a';
        c.font = '600 24px Inter, system-ui, sans-serif';
        lines[i].forEach(L => { c.fillText(L, pad, y); y += lh; });
        y += 10;
        c.fillStyle = '#e2e8f0';
        c.fillRect(pad, y, maxW, 2);
        y += 28;
        c.fillStyle = '#94a3b8';
        c.font = '700 19px Inter, system-ui, sans-serif';
    });
    c.fillStyle = '#fef2f2';
    c.fillRect(pad, y - 8, maxW, 100);
    c.fillStyle = '#64748b'; c.font = '700 19px Inter, system-ui, sans-serif';
    c.fillText('ESTIMASI BIAYA', pad + 18, y + 28);
    c.fillText('DP MASUK', pad + 18, y + 68);
    c.fillStyle = '#b91c1c'; c.font = '800 26px Inter, system-ui, sans-serif';
    c.fillText(notaRupiah(d.estimate), pad + 250, y + 28);
    c.fillStyle = '#15803d';
    c.fillText(notaRupiah(d.dp), pad + 250, y + 68);
    y += 122;
    c.fillStyle = '#b91c1c'; c.font = '800 22px Inter, system-ui, sans-serif';
    c.fillText('KETENTUAN SERVIS', pad, y);
    y += 12;
    c.fillStyle = '#dc2626';
    c.fillRect(pad + 260, y - 16, maxW - 260, 2);
    y += 26;
    c.fillStyle = '#475569'; c.font = '600 20px Inter, system-ui, sans-serif';
    ['1. Nota wajib dibawa saat pengambilan unit.',
     '2. Estimasi dapat berubah sesuai hasil diagnosa.',
     '3. Data penting harap di-backup sebelum servis.',
     '4. Keputusan teknisi utama dalam penentuan perbaikan.'
    ].forEach(t => { c.fillText(t, pad, y); y += 30; });
    y += 16;
    c.fillStyle = '#111111';
    c.fillRect(0, y, W, H - y);
    c.fillStyle = '#ffffff'; c.font = '600 16px Inter, system-ui, sans-serif';
    c.fillText('Terima kasih telah mempercayakan servis di SUKABUMI FLASHER', pad, y + 38);
    c.textAlign = 'right';
    c.font = '800 22px Inter, system-ui, sans-serif';
    c.fillText('Powered by SUKABUMI FLASHER', W - pad, y + 38);
    c.textAlign = 'left';
    const a = document.createElement('a');
    a.href = cv.toDataURL('image/png');
    a.download = 'nota-digital-' + String(d.no || 'servis').replace(/[^A-Za-z0-9-]/g, '') + '.png';
    document.body.appendChild(a);
    a.click();
    a.remove();
    notaFlash('Gambar nota digital tersimpan ke device.');
}

// ─────────────────────────────────────────────
// KLAIM GARANSI — Penerimaan → Verifikasi → Cek → Keputusan → Proses → Selesai
// Prinsip: servis lama = histori (tidak diubah). Claim = record baru (CLM-...)
// yang berelasi ke servis asal. Claim berulang untuk servis sama bisa.
// ─────────────────────────────────────────────

let _clrOrigin = null; // servis asal terpilih (hasil /claims/lookup)
let _clrResults = []; // hasil pencarian terakhir
let _clrClaim = null; // claim aktif di window ini (hasil /claims/receive)

function openClaimReceive() {
    _clrOrigin = null;
    _clrClaim = null;
    const res = document.getElementById('clrResults');
    if (res) res.innerHTML = '';
    const _wd0 = document.getElementById('clrWarrantyDays');
    if (_wd0) { _wd0.value = 30; _wd0.disabled = false; _wd0.title = ''; }
    ['clrOriginWrap', 'clrFormWrap', 'clrResultWrap'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.classList.add('hidden');
    });
    const fb = document.getElementById('clrFeedback');
    if (fb) fb.classList.add('hidden');
    const wfb = document.getElementById('clrWorkflowFeedback');
    if (wfb) wfb.classList.add('hidden');
    const dt = document.getElementById('clrDate');
    if (dt && !dt.value) dt.value = new Date().toISOString().slice(0, 10);
    document.getElementById('pageClaimReceive').classList.add('open');
    loadClaimTechnicians();
    try { renderChecklist('clr', 'clrCheckGroups', 'Kondisi unit saat klaim diterima.'); } catch (_) {}
    const s = document.getElementById('clrSearch');
    if (s) setTimeout(() => s.focus({ preventScroll: true }), 80);
}

function closeClaimReceive() {
    document.getElementById('pageClaimReceive').classList.remove('open');
    _clrOrigin = null;
    _clrClaim = null;
    _clrResults = [];
}

function clrWarrantyBadge(st) {
    return '<span class="tx-status st-' + escapeHtml(st || '') + '"><i class="fa-solid fa-circle"></i>' + escapeHtml(st || '-') + '</span>';
}

function clrStatusBadge(st) {
    return '<span class="tx-status st-' + String(st || '').toUpperCase().replace(/\s+/g, '_') + '"><i class="fa-solid fa-circle"></i>' + escapeHtml(st || '-') + '</span>';
}

async function claimRSearch() {
    const q = (document.getElementById('clrSearch') || {}).value || '';
    const box = document.getElementById('clrResults');
    if (!box) return;
    if (q.trim().length < 2) {
        box.innerHTML = '<div class="text-[12px] text-gray-400">Ketik minimal 2 huruf untuk mencari.</div>';
        return;
    }
    box.innerHTML = '<div class="text-[12px] text-gray-400"><i class="fa-solid fa-circle-notch fa-spin"></i> Mencari servis asal...</div>';
    try {
        const days = parseInt((document.getElementById('clrWarrantyDays') || {}).value, 10) || 30;
        const rows = await apiGet('/claims/lookup?q=' + encodeURIComponent(q.trim()) + '&warranty_days=' + days);
        _clrResults = rows || [];
        if (!_clrResults.length) {
            box.innerHTML = '<div class="text-[12px] text-gray-400">Servis asal tidak ditemukan. Coba kata kunci lain.</div>';
            return;
        }
        box.innerHTML = _clrResults.map(o => `
            <div class="clr-hit${_clrOrigin && _clrOrigin.id === o.id ? ' is-active' : ''}" onclick="claimRSelect(${o.id})">
                <div class="flex items-center justify-between gap-2 flex-wrap">
                    <b class="text-[13px] text-gray-800 dark:text-gray-100">${escapeHtml(o.no_servis)}</b>
                    ${clrWarrantyBadge(o.warranty_status)}
                </div>
                <div class="text-[12px] text-gray-500 dark:text-gray-400 mt-0.5">${escapeHtml(o.customer_name || '-')} · ${escapeHtml(o.customer_phone || '-')} · ${escapeHtml(o.device || '-')}</div>
                <div class="text-[11px] text-gray-400 mt-0.5">Garansi s/d ${escapeHtml(notaTgl(o.warranty_end))}${o.claim_count ? ' · ' + o.claim_count + ' claim sebelumnya' : ''}</div>
            </div>`).join('');
    } catch (err) {
        box.innerHTML = '<div class="text-[12px] text-red-500">' + escapeHtml(err.message) + '</div>';
    }
}

async function claimRSelect(id) {
    const o = (_clrResults || []).find(x => x.id === id);
    if (!o) return;
    _clrOrigin = o;
    _clrClaim = null;
    document.querySelectorAll('#clrResults .clr-hit').forEach(el => el.classList.remove('is-active'));
    try {
        const rows = await apiGet('/claims/by-service/' + o.id);
        o._freshClaims = rows || [];
    } catch (_) { o._freshClaims = null; }
    const card = document.getElementById('clrOriginCard');
    if (card) {
        const row = (k, v) => `<div><span class="block text-[10.5px] font-bold uppercase tracking-wide text-gray-400">${escapeHtml(k)}</span><b class="text-[13px] text-gray-800 dark:text-gray-100">${escapeHtml(v || '-')}</b></div>`;
        card.innerHTML =
            row('No. Servis', o.no_servis) + row('Tanggal Servis', notaTgl(o.service_date)) +
            row('Pelanggan', o.customer_name) + row('Nomor WhatsApp', o.customer_phone) +
            row('Perangkat', o.device) + row('IMEI', o.imei) +
        row('Keluhan', o.damagetype) + row('Rencana Perbaikan', o.repair_plan) +
            row('Teknisi Penanggung Jawab', o.technician) + row('Garansi Sampai', notaTgl(o.warranty_end) + ' (' + o.warranty_days + ' hari)');
    }
    const badges = document.getElementById('clrBadges');
    if (badges) {
        const _setTxt = (o.warranty_months === null || o.warranty_months === undefined)
            ? o.warranty_days + ' hari (data lama)'
            : (Number(o.warranty_months) === 0 ? 'tanpa garansi toko' : o.warranty_months + ' bulan');
        badges.innerHTML = '<span class="text-[11px] font-bold text-gray-400">GARANSI:</span>' + clrWarrantyBadge(o.warranty_status)
            + '<span class="text-[11px] text-gray-400">(' + escapeHtml(_setTxt) + ')</span>'
            + '<span class="text-[11px] font-bold text-gray-400 ml-2">STATUS SERVIS:</span>' + clrStatusBadge(o.status)
            + (Number(o.warranty_months) === 0 ? '<span class="text-[11px] text-red-500">Servis ini tanpa garansi — claim tercatat EXPIRED (riwayat).</span>' : '');
    }
    const _wdInput = document.getElementById('clrWarrantyDays');
    if (_wdInput) {
        if (o.warranty_months !== null && o.warranty_months !== undefined) {
            _wdInput.value = o.warranty_days;
            _wdInput.disabled = true;
            _wdInput.title = 'Mengikuti setting garansi toko di servis asal';
        } else {
            _wdInput.disabled = false;
            _wdInput.title = '';
        }
    }
    const hist = document.getElementById('clrHistory');
    if (hist) {
        const list = o._freshClaims !== null && o._freshClaims !== undefined ? o._freshClaims : null;
        const items = list !== null ? list : (o.claims || []);
        hist.innerHTML = '<p class="text-[11px] font-bold uppercase tracking-wide text-gray-400 mb-1.5">Histori Klaim Servis Ini (' + items.length + ')</p>'
            + (items.length ? items.map(c => `
                <div class="clr-result">
                    <div class="flex items-center justify-between gap-2 flex-wrap">
                        <b class="text-[12.5px]">${escapeHtml(c.claim_no)}</b>
                        <span class="flex gap-1.5">${clrStatusBadge(c.claim_status)}${c.decision ? clrStatusBadge(c.decision) : ''}</span>
                    </div>
                    <div class="text-[11px] text-gray-400 mt-0.5">Tgl claim: ${escapeHtml(c.claim_date || '-')}</div>
                </div>`).join('')
                : '<div class="text-[12px] text-gray-400">Belum ada claim untuk servis ini — claim baru akan menjadi yang pertama.</div>');
    }
    document.getElementById('clrOriginWrap').classList.remove('hidden');
    document.getElementById('clrFormWrap').classList.remove('hidden');
    document.getElementById('clrResultWrap').classList.add('hidden');
    // Tandai pilihan aktif tanpa render ulang (hasil pencarian tetap terlihat).
    const box = document.getElementById('clrResults');
    if (box) {
        const hits = box.querySelectorAll('.clr-hit');
        (_clrResults || []).forEach((r, i) => { if (hits[i]) hits[i].classList.toggle('is-active', r.id === id); });
    }
}

function claimRFeedback(msg, isErr) {
    const fb = document.getElementById('clrFeedback');
    if (!fb) return;
    fb.classList.remove('hidden', 'success', 'error');
    fb.classList.add(isErr ? 'error' : 'success');
    fb.innerHTML = `<i class="fa-solid ${isErr ? 'fa-triangle-exclamation' : 'fa-circle-check'}"></i> ${escapeHtml(msg)}`;
}

async function claimRSubmit(e) {
    if (e) e.preventDefault();
    if (!_clrOrigin) { claimRFeedback('Pilih dulu servis asalnya.', true); return; }
    const complaint = (document.getElementById('clrComplaint') || {}).value || '';
    if (!complaint.trim()) { claimRFeedback('Keluhan claim wajib diisi.', true); return; }
    const btn = document.getElementById('clrSubmitBtn');
    const txt = document.getElementById('clrSubmitText');
    if (btn) btn.disabled = true;
    if (txt) txt.textContent = 'Menyimpan...';
    try {
        let chk = { fisik: [], len: ['unit_saja'] };
        try { chk = collectChecklist('clr'); } catch (_) {}
        const payload = {
            service_order_id: _clrOrigin.id,
            complaint: complaint.trim(),
            physical_condition: ((document.getElementById('clrPhysical') || {}).value || '').trim(),
            completeness: ((document.getElementById('clrCompleteness') || {}).value || '').trim(),
            cs_note: ((document.getElementById('clrCsNote') || {}).value || '').trim(),
            check_fisik: chk.fisik,
            check_len: chk.len,
            warranty_days: parseInt((document.getElementById('clrWarrantyDays') || {}).value, 10) || 30,
            received_by: ((document.getElementById('clrReceivedBy') || {}).value || '').trim(),
            claim_date: (document.getElementById('clrDate') || {}).value || undefined,
        };
        const c = await apiPost('/claims/receive', payload);
        _clrClaim = c;
        claimRFeedback('Claim ' + c.claim_no + ' dibuat. Servis asal tidak berubah.', false);
        try { applyChecklist('clr', { fisik: [], len: ['unit_saja'] }); } catch (_) {}
        const form = document.getElementById('claimReceiveForm');
        if (form) form.reset();
        const dt = document.getElementById('clrDate');
        if (dt) dt.value = new Date().toISOString().slice(0, 10);
        claimRRenderResult(c);
        document.getElementById('clrResultWrap').classList.remove('hidden');
        document.getElementById('clrResultWrap').scrollIntoView({ behavior: 'smooth', block: 'start' });
    } catch (err) {
        claimRFeedback(err.message, true);
    } finally {
        if (btn) btn.disabled = false;
        if (txt) txt.textContent = 'Buat Claim Garansi';
    }
}

function claimRRenderResult(c) {
    try { claimRRefreshResolusi(c); } catch (_) {}
    const card = document.getElementById('clrResultCard');
    if (card) {
        card.innerHTML = `
            <div class="clr-result">
                <div class="flex items-center justify-between gap-2 flex-wrap">
                    <div><span class="block text-[10.5px] font-bold uppercase tracking-wide text-gray-400">Claim ID</span>
                    <b class="text-[16px] text-gray-800 dark:text-gray-100">${escapeHtml(c.claim_no)}</b></div>
                    ${clrWarrantyBadge(c.warranty_status)}
                </div>
                <div class="text-[12px] text-gray-500 dark:text-gray-400 mt-1">Servis asal <b>${escapeHtml(c.origin_no_servis || '')}</b> · Tgl claim ${escapeHtml(notaTgl(c.claim_date))} · ${escapeHtml(c.customer_name || '')}</div>
                <div class="flex gap-1.5 mt-2 flex-wrap"><span class="text-[11px] font-bold text-gray-400">PROSES:</span>${clrStatusBadge(c.claim_status)}
                <span class="text-[11px] font-bold text-gray-400 ml-1">HASIL:</span>${clrStatusBadge(c.decision)}</div>
            </div>`;
    }
    const set = (id, v) => { const el = document.getElementById(id); if (el) el.value = v === null || v === undefined ? '' : v; };
    set('clrStatus', c.claim_status || 'MASUK');
    set('clrDecision', c.decision || 'BELUM_DIPUTUSKAN');
    set('clrRejectReason', c.reject_reason || '');
    set('clrTechInspection', c.inspection_result || '');
    set('clrCause', c.cause || '');
    set('clrMatches', c.matches_previous || '');
    set('clrTechRec', c.tech_recommendation || '');
    set('clrTechnician', c.technician || '');
    set('clrAction', c.action_needed || '');
    set('clrTechNote', c.tech_note || '');
    set('clrCustomerCost', c.customer_cost || 0);
    set('clrInternalCost', c.internal_cost || 0);
    const chk = (id, v) => { const el = document.getElementById(id); if (el) el.checked = !!v; };
    chk('clrDrop', c.drop_indication);
    chk('clrLiquid', c.liquid_indication);
    chk('clrThirdParty', c.third_party_work);
}

function claimRWorkflowFeedback(msg, isErr) {
    const fb = document.getElementById('clrWorkflowFeedback');
    if (!fb) return;
    fb.classList.remove('hidden', 'success', 'error');
    fb.classList.add(isErr ? 'error' : 'success');
    fb.innerHTML = `<i class="fa-solid ${isErr ? 'fa-triangle-exclamation' : 'fa-circle-check'}"></i> ${escapeHtml(msg)}`;
}

// P2-10: Refund Klaim Garansi (Admin, dana Kas Aset + pre-check).
async function clrRefundGaransi() {
    if (!can('REFUND_GARANSI')) { toast('Aksi ditolak: Refund Garansi adalah keputusan Admin.'); return; }
    if (!_clrClaim) { claimRWorkflowFeedback('Belum ada claim aktif.', true); return; }
    let nominal = Number((_clrClaim.customer_cost || 0));
    const v = prompt('Nominal refund garansi (dana dari Kas Aset), default biaya pelanggan:',
                     nominal ? String(nominal) : '');
    if (v === null) return;
    nominal = Number(v);
    if (!nominal || nominal <= 0) { claimRWorkflowFeedback('Nominal tidak valid.', true); return; }
    try {
        const pre = await apiGet('/refunds/precheck/garansi/' + _clrClaim.id + '&nominal=' + nominal);
        if (pre && pre.cukup === false) {
            claimRWorkflowFeedback('Saldo Kas Aset tidak cukup untuk refund ini.', true);
            return;
        }
        if (!confirm('Refund ' + kuRupiah(nominal) + ' dari Kas Aset untuk klaim ' + _clrClaim.claim_no + '?')) return;
        const r = await apiPost('/refunds/garansi',
            { warranty_claim_id: _clrClaim.id, nominal },
            { idempotencyKey: newIdemKey() });
        claimRWorkflowFeedback('Refund garansi ' + kuRupiah(r.refund.nominal)
            + ' diproses. Saldo Kas Aset ' + kuRupiah(r.saldo_setelah) + '.', false);
        toast('Refund garansi diproses.', 'success');
        try { await loadKuFinance(); } catch (_) {}
    } catch (err) {
        claimRWorkflowFeedback(err.message, true);
    }
}

// Sinkronkan UI resolusi + tombol refund dari data klaim terbaru.
function claimRRefreshResolusi(c) {
    const sel = document.getElementById('clrResolusi');
    if (sel) sel.value = (c && c.resolusi) ? c.resolusi : '';
    const btn = document.getElementById('clrRefundBtn');
    if (btn) {
        btn.classList.toggle('hidden', !can('REFUND_GARANSI'));
        if (c && c.resolusi === 'REFUND' && can('REFUND_GARANSI')) btn.classList.remove('hidden');
    }
}

async function claimRSave() {
    if (!_clrClaim) { claimRWorkflowFeedback('Belum ada claim aktif.', true); return; }
    const decision = (document.getElementById('clrDecision') || {}).value || 'BELUM_DIPUTUSKAN';
    const reject = ((document.getElementById('clrRejectReason') || {}).value || '').trim();
    if (decision === 'DITOLAK' && !reject) {
        claimRWorkflowFeedback('Claim DITOLAK wajib menyertakan alasan penolakan.', true);
        return;
    }
    const btn = document.getElementById('clrSaveBtn');
    const txt = document.getElementById('clrSaveText');
    if (btn) btn.disabled = true;
    if (txt) txt.textContent = 'Menyimpan...';
    try {
        const payload = {
            claim_status: (document.getElementById('clrStatus') || {}).value || undefined,
            decision: decision,
            reject_reason: reject || null,
            inspection_result: ((document.getElementById('clrTechInspection') || {}).value || '').trim() || null,
            cause: ((document.getElementById('clrCause') || {}).value || '').trim() || null,
            matches_previous: (document.getElementById('clrMatches') || {}).value || null,
            tech_recommendation: (document.getElementById('clrTechRec') || {}).value || null,
            technician: (document.getElementById('clrTechnician') || {}).value || null,
            action_needed: ((document.getElementById('clrAction') || {}).value || '').trim() || null,
            tech_note: ((document.getElementById('clrTechNote') || {}).value || '').trim() || null,
            drop_indication: document.getElementById('clrDrop') && document.getElementById('clrDrop').checked ? 1 : 0,
            liquid_indication: document.getElementById('clrLiquid') && document.getElementById('clrLiquid').checked ? 1 : 0,
            third_party_work: document.getElementById('clrThirdParty') && document.getElementById('clrThirdParty').checked ? 1 : 0,
            customer_cost: parseFloat((document.getElementById('clrCustomerCost') || {}).value) || 0,
            internal_cost: parseFloat((document.getElementById('clrInternalCost') || {}).value) || 0,
            // P2-09: resolusi repair/replace/refund (dana refund = tahap Refund).
            resolusi: ((document.getElementById('clrResolusi') || {}).value || '') || null,
        };
        const c = await apiPut('/claims/' + _clrClaim.id, payload);
        _clrClaim = c;
        claimRRenderResult(c);
        try { claimRRefreshResolusi(c); } catch (_) {}
        claimRWorkflowFeedback('Workflow claim ' + c.claim_no + ' tersimpan.', false);
        if (_clrOrigin) { try { claimRSelectRefresh(c); } catch (_) {} }
    } catch (err) {
        claimRWorkflowFeedback(err.message, true);
    } finally {
        if (btn) btn.disabled = false;
        if (txt) txt.textContent = 'Simpan Workflow';
    }
}

// Segarkan badge histori di kartu servis asal setelah workflow berubah.
function claimRSelectRefresh(c) {
    const hist = document.getElementById('clrHistory');
    if (!hist || !_clrOrigin) return;
    const items = (_clrOrigin._freshClaims || _clrOrigin.claims || []).slice();
    const i = items.findIndex(x => x.claim_no === c.claim_no);
    const row = { claim_no: c.claim_no, claim_status: c.claim_status, decision: c.decision, claim_date: c.claim_date };
    if (i >= 0) items[i] = row; else items.unshift(row);
    _clrOrigin._freshClaims = items;
    _clrOrigin.claim_count = items.length;
    hist.querySelectorAll('.clr-result').forEach(() => {});
    // Render ulang ringkas tanpa fetch ulang.
    const tmp = _clrOrigin._freshClaims;
    _clrOrigin._freshClaims = tmp;
    hist.innerHTML = '<p class="text-[11px] font-bold uppercase tracking-wide text-gray-400 mb-1.5">Histori Klaim Servis Ini (' + tmp.length + ')</p>'
        + tmp.map(x => `
            <div class="clr-result">
                <div class="flex items-center justify-between gap-2 flex-wrap">
                    <b class="text-[12.5px]">${escapeHtml(x.claim_no)}</b>
                    <span class="flex gap-1.5">${clrStatusBadge(x.claim_status)}${x.decision ? clrStatusBadge(x.decision) : ''}</span>
                </div>
                <div class="text-[11px] text-gray-400 mt-0.5">Tgl claim: ${escapeHtml(x.claim_date || '-')}</div>
            </div>`).join('');
}

function claimRPrint() {
    if (!_clrClaim) { claimRWorkflowFeedback('Buat dulu claim-nya sebelum mencetak nota.', true); return; }
    openClaimNota(_clrClaim);
}

// Dari halaman Update Data Servis: buat claim baru mengacu ke servis ini.
function usClaimNew() {
    const keyword = _usNo || '';
    openClaimReceive();
    if (keyword) {
        const s = document.getElementById('clrSearch');
        if (s) s.value = keyword;
        claimRSearch();
    }
}

async function usLoadClaimHistory(serviceId) {
    const box = document.getElementById('usClaimHistory');
    if (!box || !serviceId) return;
    box.innerHTML = '<span class="text-gray-400"><i class="fa-solid fa-circle-notch fa-spin"></i> Memuat histori klaim...</span>';
    try {
        const rows = await apiGet('/claims/by-service/' + serviceId);
        if (!rows || !rows.length) {
            box.innerHTML = 'Belum ada claim untuk servis ini.';
            return;
        }
        box.innerHTML = rows.map(c => `
            <div class="clr-result">
                <div class="flex items-center justify-between gap-2 flex-wrap">
                    <b class="text-[12.5px] text-gray-800 dark:text-gray-100">${escapeHtml(c.claim_no)}</b>
                    <span class="flex gap-1.5">${clrStatusBadge(c.claim_status)}${clrStatusBadge(c.decision)}</span>
                </div>
                <div class="text-[11px] text-gray-400 mt-0.5">${escapeHtml(c.complaint || '')}</div>
                ${c.decision === 'DITOLAK' && c.reject_reason ? '<div class="text-[11px] text-red-500 mt-0.5">Alasan: ' + escapeHtml(c.reject_reason) + '</div>' : ''}
            </div>`).join('');
    } catch (_) {
        box.innerHTML = 'Histori klaim tidak dapat dimuat.';
    }
}

// ── Nota Penerimaan CLAIM (berbeda dari nota servis baru) ──

function claimOutToNota(c) {
    return {
        kind: 'CLAIM',
        no: c.claim_no,
        claim_no: c.claim_no,
        origin_no: c.origin_no_servis || '',
        tgl: c.claim_date,
        claim_date: c.claim_date,
        nama: c.customer_name || '',
        phone: c.customer_phone || '',
        device: c.origin_device || '',
        imei: c.origin_imei || '',
        damage: c.complaint || '',
        complaint: c.complaint || '',
        physical: c.physical_condition || '',
        completeness: c.completeness || '',
        plan: c.action_needed || c.cs_note || '',
        estimate: c.customer_cost || 0,
        dp: 0,
        technician: c.technician || '',
        status: c.claim_status || '',
        claim_status: c.claim_status || '',
        decision: c.decision || '',
        warranty_status: c.warranty_status || '',
        warranty_start: c.warranty_start || '',
        warranty_end: c.warranty_end || '',
        cs_note: c.cs_note || '',
        reject_reason: c.reject_reason || '',
    };
}

function openClaimNota(c) {
    const d = claimOutToNota(c);
    _lastClaim = d;
    _notaMode = 'CLAIM';
    renderClaimNotaPreview(d);
    renderClaimNotaDigital(d);
    const fb = document.getElementById('notaFeedback');
    if (fb) fb.classList.add('hidden');
    const win = document.getElementById('pageNota');
    try { document.body.appendChild(win); } catch (_) {}
    win.style.zIndex = '9600';
    win.classList.add('open');
}

function renderClaimNotaPreview(d) {
    const el = document.getElementById('notaPreview');
    if (!el) return;
    const row = (k, v) => `<div class="nt-row"><span>${escapeHtml(k)}</span><b>${escapeHtml(v || '-')}</b></div>`;
    el.innerHTML = `
        <div class="nt-head">
            <div class="nt-brand">SUKABUMI FLASHER</div>
            <div class="nt-sub">BUSINESS OPERATING SYSTEM</div>
            <div class="nt-title">NOTA PENERIMAAN CLAIM GARANSI</div>
        </div>
        <div class="nt-sep"></div>
        ${row('Claim ID', d.claim_no)}
        ${row('Servis Asal', d.origin_no)}
        ${row('Tgl Claim', notaTgl(d.tgl))}
        <div class="nt-sep"></div>
        ${row('Pelanggan', d.nama)}
        ${row('Nomor WhatsApp', d.phone)}
        ${row('Device', d.device)}
        ${row('IMEI', d.imei)}
        <div class="nt-sep"></div>
        <div class="nt-label">Keluhan claim:</div>
        <div class="nt-val">${escapeHtml(d.complaint)}</div>
        <div class="nt-label">Kondisi / kelengkapan:</div>
        <div class="nt-val">${escapeHtml([d.physical, d.completeness].filter(Boolean).join(' · '))}</div>
        <div class="nt-sep"></div>
        ${row('Garansi', d.warranty_status + ' s/d ' + notaTgl(d.warranty_end))}
        ${row('Hasil', d.decision)}
        ${row('Status', d.claim_status)}
        ${row('Biaya', notaRupiah(d.estimate))}
        <div class="nt-sep"></div>
        <div class="nt-foot">Simpan nota claim ini sebagai<br>bukti pengambilan unit.<br>Terima kasih!</div>`;
}

function renderClaimNotaDigital(d) {
    const el = document.getElementById('notaDigital');
    if (!el) return;
    const tgl = notaTglSlash(d.tgl);
    const qrUrl = 'https://api.qrserver.com/v1/create-qr-code/?size=132x132&margin=6&data='
        + encodeURIComponent('SUKABUMI FLASHER ' + (d.claim_no || ''));
    el.innerHTML = `
    <div class="ndr-sheet ndr-doc-claim">
        <div class="ndr-head">
            <div class="ndr-brand">
                <span class="ndr-logo"><img src="/static/assets/logo.png" alt="SUKABUMI FLASHER" onerror="this.style.display='none'"><i class="fa-solid fa-bolt"></i></span>
                <div><b>SUKABUMI FLASHER</b><span>BUSINESS OPERATING SYSTEM</span></div>
            </div>
            <div class="ndr-contact"><div><i class="fa-regular fa-calendar"></i>${escapeHtml(tgl)}</div></div>
        </div>
        <div class="ndr-title-row">
            <div class="ndr-title">
                <h3>NOTA <em>PENERIMAAN</em> CLAIM GARANSI</h3>
                <div class="ndr-doctype"><i class="fa-solid fa-shield-halved"></i><b>PG</b><span>NOTA PENERIMAAN CLAIM GARANSI</span></div>
                <div class="ndr-state ndr-amber">
                    <i class="fa-solid fa-shield-halved"></i>
                    <div><b>GARANSI: ${escapeHtml(d.warranty_status || '-')}</b><span>Claim mengacu ke servis ${escapeHtml(d.origin_no || '-')} — histori servis tidak berubah.</span></div>
                </div>
            </div>
            <div class="ndr-nonum">
                <span>CLAIM ID</span>
                <b>${escapeHtml(d.claim_no || '-')}</b>
                <div class="ndr-strip"><i class="fa-solid fa-shield-halved"></i>Simpan nota claim ini sebagai bukti Anda</div>
            </div>
        </div>
        <div class="ndr-grid3">
            <div class="ndr-card">
                <div class="ndr-cap"><i class="fa-solid fa-user"></i>PELANGGAN</div>
                <div class="ndr-name">${escapeHtml(d.nama)}</div>
                <div class="ndr-line"><i class="fa-solid fa-phone"></i>${escapeHtml(d.phone)}</div>
            </div>
            <div class="ndr-card">
                <div class="ndr-cap"><i class="fa-solid fa-mobile-screen-button"></i>DEVICE</div>
                <div class="ndr-name">${escapeHtml(d.device)}</div>
                <div class="ndr-kv">IMEI <span>${escapeHtml(d.imei)}</span></div>
                <div class="ndr-kv">Servis asal <span>${escapeHtml(d.origin_no)}</span></div>
            </div>
            <div class="ndr-card">
                <div class="ndr-cap"><i class="fa-solid fa-hashtag"></i>CLAIM</div>
                <div class="ndr-name">${escapeHtml(d.claim_no)}</div>
                <div class="ndr-line"><i class="fa-regular fa-calendar"></i>${escapeHtml(tgl)}</div>
                <div class="ndr-line"><i class="fa-solid fa-shield-halved"></i>${escapeHtml(d.warranty_status)}</div>
            </div>
        </div>
        <div class="ndr-grid3">
            <div class="ndr-card">
                <div class="ndr-cap"><i class="fa-solid fa-wrench"></i>DETAIL CLAIM</div>
                <div class="ndr-sec"><span>Keluhan claim</span><p>${escapeHtml(d.complaint)}</p></div>
                <div class="ndr-sec"><span>Kondisi / kelengkapan</span><p>${escapeHtml([d.physical, d.completeness].filter(Boolean).join(' · '))}</p></div>
                <div class="ndr-sec"><span>Teknisi</span><p>${escapeHtml(d.technician || '-')}</p></div>
                <div class="ndr-sec"><span>Biaya pelanggan</span><p class="ndr-price">${escapeHtml(notaRupiah(d.estimate))}</p></div>
            </div>
            <div class="ndr-card is-green">
                <div class="ndr-cap"><i class="fa-solid fa-shield-halved"></i>STATUS CLAIM</div>
                <div class="ndr-sched">
                    <div class="ndr-srow"><span class="ndr-ico"><i class="fa-solid fa-shield-halved"></i></span><div><span>Garansi</span><b>${escapeHtml(d.warranty_status || '-')} s/d ${escapeHtml(notaTglSlash(d.warranty_end))}</b></div></div>
                    <div class="ndr-srow"><span class="ndr-ico"><i class="fa-solid fa-gavel"></i></span><div><span>Hasil</span><b>${escapeHtml(d.decision || '-')}</b></div></div>
                    <div class="ndr-srow"><span class="ndr-ico"><i class="fa-regular fa-clock"></i></span><div><span>Status proses</span><b>${escapeHtml(d.claim_status || '-')}</b></div></div>
                </div>
                <div class="ndr-note"><i class="fa-solid fa-circle-info"></i><span>Garansi VALID bukan berarti claim otomatis diterima — menunggu keputusan teknisi.</span></div>
            </div>
            <div class="ndr-card">
                <div class="ndr-cap is-green-t"><i class="fa-solid fa-shield-halved"></i>SYARAT PENGAMBILAN</div>
                <ul class="ndr-yes">
                    <li><i class="fa-solid fa-check"></i><span>Tunjukkan nota claim / Claim ID</span></li>
                    <li><i class="fa-solid fa-check"></i><span>Tunjukkan nota servis asal</span></li>
                    <li><i class="fa-solid fa-check"></i><span>Cek kondisi unit saat pengambilan</span></li>
                </ul>
                <div class="ndr-nohead"><i class="fa-solid fa-triangle-exclamation"></i>KETENTUAN CLAIM</div>
                <ul class="ndr-no">
                    <li><i class="fa-regular fa-circle-xmark"></i><span>Keputusan teknisi bersifat final</span></li>
                    <li><i class="fa-regular fa-circle-xmark"></i><span>Kerusakan jatuh / cairan tidak ditanggung</span></li>
                </ul>
            </div>
        </div>
        <div class="ndr-grid3 ndr-row3">
            <div class="ndr-card">
                <div class="ndr-cap"><i class="fa-solid fa-shield-halved"></i>VERIFIKASI CLAIM</div>
                <p class="ndr-desc">Scan QR untuk verifikasi nota claim Anda.</p>
                <div class="ndr-pill"><i class="fa-solid fa-globe"></i>boss-sf.id/lacak/${escapeHtml(d.claim_no || '')}</div>
            </div>
            <div class="ndr-qrwrap">
                <img src="${qrUrl}" alt="QR claim" loading="lazy" onerror="this.style.display='none';var f=this.parentNode.querySelector('.ndr-kode-fallback');if(f)f.style.display='flex';">
                <div class="ndr-kode-fallback" style="display:none"><span>KODE CLAIM</span><b>${escapeHtml(d.claim_no || '-')}</b></div>
            </div>
            <div class="ndr-pink">
                <span class="ndr-shield"><i class="fa-solid fa-shield-halved"></i></span>
                <p>Nota claim hanya berlaku di<br><b>SUKABUMI FLASHER<br>BUSINESS OPERATING SYSTEM</b></p>
                <div class="ndr-thanks">Terima kasih telah mempercayakan perbaikan perangkat Anda kepada kami.</div>
            </div>
        </div>
        <div class="ndr-foot">
            <div class="ndr-foot-l"><i class="fa-regular fa-circle-check"></i><span>Claim mengacu ke servis ${escapeHtml(d.origin_no || '-')} — histori servis tidak berubah.</span></div>
            <div class="ndr-foot-r"><b>Powered by <em>SUKABUMI FLASHER</em></b><span>BUSINESS OPERATING SYSTEM</span></div>
        </div>
    </div>`;
}

function claimNotaText(d) {
    const L = [];
    const sep = '--------------------------------';
    const kv = (k, v) => {
        const s = k + ' : ' + (v || '-');
        notaWrap(s, 32).forEach(x => L.push(x));
    };
    L.push('        SUKABUMI FLASHER');
    L.push('   BUSINESS OPERATING SYSTEM');
    L.push(' NOTA PENERIMAAN CLAIM GARANSI');
    L.push(sep);
    kv('Claim', d.claim_no);
    kv('Servis asal', d.origin_no);
    kv('Tgl claim', notaTgl(d.tgl));
    L.push(sep);
    kv('Pelanggan', d.nama);
    kv('WA', d.phone);
    kv('Device', d.device);
    kv('IMEI', d.imei);
    L.push(sep);
    L.push('Keluhan claim:');
    notaWrap(d.complaint, 32).forEach(x => L.push(x));
    L.push('Kondisi:');
    notaWrap([d.physical, d.completeness].filter(Boolean).join(' · '), 32).forEach(x => L.push(x));
    L.push(sep);
    kv('Garansi', (d.warranty_status || '-') + ' s/d ' + notaTgl(d.warranty_end));
    kv('Hasil', d.decision);
    kv('Status', d.claim_status);
    kv('Biaya', notaRupiah(d.estimate));
    kv('Teknisi', notaTechnician(d.technician));
    L.push(sep);
    L.push('Simpan nota claim ini sebagai');
    L.push('bukti pengambilan unit.');
    L.push('Terima kasih!');
    return L.join('\n');
}

function claimNotaDigitalText(d) {
    return '*NOTA PENERIMAAN CLAIM GARANSI*\n*SUKABUMI FLASHER - Business Operating System*\n'
        + '--------------------------\n'
        + 'Claim ID : ' + (d.claim_no || '-') + '\n'
        + 'Servis asal : ' + (d.origin_no || '-') + '\n'
        + 'Garansi : ' + (d.warranty_status || '-') + ' s/d ' + notaTgl(d.warranty_end) + '\n'
        + 'Hasil : ' + (d.decision || '-') + '\n'
        + 'Status : ' + (d.claim_status || '-') + '\n'
        + 'Nama : ' + (d.nama || '-') + '\n'
        + 'WA : ' + (d.phone || '-') + '\n'
        + 'Device : ' + (d.device || '-') + '\n'
        + 'Keluhan : ' + (d.complaint || '-') + '\n'
        + 'Biaya : ' + notaRupiah(d.estimate) + '\n'
        + 'Tgl Claim : ' + notaTgl(d.tgl) + '\n'
        + '--------------------------\n'
        + 'Simpan nota claim ini sebagai bukti pengambilan unit. Terima kasih! - *SUKABUMI FLASHER*';
}

// ── Nota GARANSI (terbit saat SELESAI + LUNAS, awal dari lunas_date/diambil) ──

const WARRANTY_DAYS = 30; // fallback data lama (tanpa setting bulan)

function addMonths(dateStr, months) {
    const m = String(dateStr || '').match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (!m) return '';
    let y = Number(m[1]), mo = Number(m[2]) - 1 + (Number(months) || 0);
    const d = Number(m[3]);
    y += Math.floor(mo / 12); mo = ((mo % 12) + 12) % 12;
    const last = new Date(y, mo + 1, 0).getDate();
    const dt = new Date(y, mo, Math.min(d, last));
    const p = n => String(n).padStart(2, '0');
    return dt.getFullYear() + '-' + p(dt.getMonth() + 1) + '-' + p(dt.getDate());
}

function warrantyLabel(m) {
    if (m === null || m === undefined || m === '') return '30 hari';
    if (Number(m) === 0) return 'Tanpa garansi';
    return m + ' bulan';
}

function warrantyEndFor(cash, m) {
    if (m === null || m === undefined || m === '') return warrantyEndOf(cash, WARRANTY_DAYS);
    if (Number(m) === 0) return '';
    return addMonths(cash, Number(m));
}

// Label garansi untuk pesan WhatsApp, dibaca dari kontrol Update Data Servis
// (nilainya baru berlaku setelah status CASH).
function usWarrantyText() {
    try {
        const m = (document.getElementById('usWarrantyMonths') || {}).value;
        return warrantyLabel(m === undefined ? null : m);
    } catch (_) { return ''; }
}

function usWarrantyMonths() {
    const el = document.getElementById('usWarrantyMonths');
    return el ? parseInt(el.value, 10) : 1;
}

function usWarrantyUpdate() {
    const m = usWarrantyMonths();
    const pill = document.getElementById('usWarrantyPill');
    const info = document.getElementById('usWarrantyInfo');
    const cash = _usLunasDate || new Date().toISOString().slice(0, 10);
    if (Number(m) === 0) {
        if (pill) { pill.className = 'tx-status st-EXPIRED'; pill.innerHTML = '<i class="fa-solid fa-circle"></i>Tanpa garansi'; }
        if (info) info.textContent = 'Servis ini tidak bergaransi toko.';
    } else {
        const end = warrantyEndFor(cash, m);
        if (pill) { pill.className = 'tx-status st-VALID'; pill.innerHTML = '<i class="fa-solid fa-circle"></i>Active'; }
        if (info) info.textContent = warrantyLabel(m) + ' sejak ' + notaTgl(cash) + ' s/d ' + notaTgl(end) + '.';
    }
}

function warrantyEndOf(cashDate, days) {
    const m = String(cashDate || '').match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (!m) return '';
    const dt = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]) + (days || WARRANTY_DAYS));
    const p = n => String(n).padStart(2, '0');
    return dt.getFullYear() + '-' + p(dt.getMonth() + 1) + '-' + p(dt.getDate());
}

async function usWarrantyPrint() {
    if (usGetStatus() !== 'CASH') return;
    // Nota garansi syarat SELESAI + LUNAS (FINAL LOCK).
    if (_txEditId) {
        try {
            const _pay = await apiGet('/payments/by-order/' + _txEditId);
            if (_pay.payment_status !== 'LUNAS') {
                toast('Nota garansi butuh pembayaran LUNAS (sisa ' + usPayRupiah(_pay.sisa) + ').');
                return;
            }
        } catch (err) {
            toast(err.message || 'Gagal cek pembayaran.');
            return;
        }
    }
    // lunas_date dikunci backend saat pelunasan penuh; bila baru lunas & belum
    // disimpan, pakai hari ini sebagai provisional (akan sama saat disimpan).
    const cash = _usLunasDate || new Date().toISOString().slice(0, 10);
    const mths = usWarrantyMonths();
    const d = {
        kind: 'WARRANTY',
        no: _usNo || '-',
        tgl: cash,
        nama: usVal('usNama'),
        phone: usVal('usPhone'),
        device: usVal('usDevice'),
        imei: usVal('usImei'),
        plan: usVal('usPlan'),
        technician: usVal('usTechnician'),
        final: usNum('usFinFinal'),
        part: usVal('usFinPart') === '' ? 0 : usNum('usFinPart'),
        warranty_months: mths,
        warranty_label: warrantyLabel(mths),
        warranty_days: WARRANTY_DAYS,
        warranty_end: warrantyEndFor(cash, mths),
        status: 'CASH',
    };
    _lastWarranty = d;
    _notaMode = 'WARRANTY';
    renderWarrantyNotaPreview(d);
    renderWarrantyNotaDigital(d);
    const fb = document.getElementById('notaFeedback');
    if (fb) fb.classList.add('hidden');
    const win = document.getElementById('pageNota');
    try { document.body.appendChild(win); } catch (_) {}
    win.style.zIndex = '9600';
    win.classList.add('open');
}

function renderWarrantyNotaPreview(d) {
    const el = document.getElementById('notaPreview');
    if (!el) return;
    const row = (k, v) => `<div class="nt-row"><span>${escapeHtml(k)}</span><b>${escapeHtml(v || '-')}</b></div>`;
    el.innerHTML = `
        <div class="nt-head">
            <div class="nt-brand">SUKABUMI FLASHER</div>
            <div class="nt-sub">BUSINESS OPERATING SYSTEM</div>
            <div class="nt-title">NOTA GARANSI SERVICE</div>
        </div>
        <div class="nt-sep"></div>
        ${row('No. Servis', d.no)}
        ${row('Tgl Selesai', notaTgl(d.tgl))}
        <div class="nt-sep"></div>
        ${row('Pelanggan', d.nama)}
        ${row('Nomor WhatsApp', d.phone)}
        ${row('Device', d.device)}
        ${row('IMEI', d.imei)}
        <div class="nt-sep"></div>
        <div class="nt-label">Tindakan perbaikan:</div>
        <div class="nt-val">${escapeHtml(d.plan)}</div>
        ${row('Teknisi', notaTechnician(d.technician))}
        ${row('Biaya Final', notaRupiah(d.final))}
        <div class="nt-sep"></div>
        ${row('Garansi', d.warranty_label)}
        ${row('Berlaku s/d', d.warranty_end ? notaTgl(d.warranty_end) : '-')}
        <div class="nt-sep"></div>
        <div class="nt-foot">${d.warranty_months === 0 ? 'Servis ini tidak bergaransi toko.<br>' : 'Garansi ' + escapeHtml(d.warranty_label) + ' untuk pekerjaan yang sama.<br>'}Simpan nota ini sebagai bukti garansi.<br>Terima kasih!</div>`;
}

function renderWarrantyNotaDigital(d) {
    const el = document.getElementById('notaDigital');
    if (!el) return;
    const tgl = notaTglSlash(d.tgl);
    const sampai = notaTglSlash(d.warranty_end);
    const qrUrl = 'https://api.qrserver.com/v1/create-qr-code/?size=132x132&margin=6&data='
        + encodeURIComponent('SUKABUMI FLASHER GARANSI ' + (d.no || ''));
    el.innerHTML = `
    <div class="ndr-sheet ndr-doc-warranty">
        <div class="ndr-head">
            <div class="ndr-brand">
                <span class="ndr-logo"><img src="/static/assets/logo.png" alt="SUKABUMI FLASHER" onerror="this.style.display='none'"><i class="fa-solid fa-bolt"></i></span>
                <div><b>SUKABUMI FLASHER</b><span>BUSINESS OPERATING SYSTEM</span></div>
            </div>
            <div class="ndr-contact"><div><i class="fa-regular fa-calendar"></i>${escapeHtml(tgl)}</div></div>
        </div>
        <div class="ndr-title-row">
            <div class="ndr-title">
                <h3>NOTA <em>GARANSI</em> SERVICE</h3>
                <div class="ndr-doctype"><i class="fa-solid fa-shield-halved"></i><b>NG</b><span>NOTA GARANSI SERVICE</span></div>
                <div class="ndr-state ndr-green">
                    <i class="fa-solid fa-shield-halved"></i>
                    <div><b>${escapeHtml(d.warranty_months === 0 ? 'TANPA GARANSI' : 'GARANSI ' + String(d.warranty_label).toUpperCase())}</b><span>${escapeHtml(d.warranty_end ? 'Berlaku s/d ' + notaTglSlash(d.warranty_end) + ' untuk pekerjaan yang sama.' : 'Servis ini tidak bergaransi toko.')}</span></div>
                </div>
            </div>
            <div class="ndr-nonum">
                <span>NO. SERVIS</span>
                <b>${escapeHtml(d.no || '-')}</b>
                <div class="ndr-strip"><i class="fa-solid fa-shield-halved"></i>Simpan nota ini sebagai bukti garansi</div>
            </div>
        </div>
        <div class="ndr-grid3">
            <div class="ndr-card">
                <div class="ndr-cap"><i class="fa-solid fa-user"></i>PELANGGAN</div>
                <div class="ndr-name">${escapeHtml(d.nama)}</div>
                <div class="ndr-line"><i class="fa-solid fa-phone"></i>${escapeHtml(d.phone)}</div>
            </div>
            <div class="ndr-card">
                <div class="ndr-cap"><i class="fa-solid fa-mobile-screen-button"></i>DEVICE</div>
                <div class="ndr-name">${escapeHtml(d.device)}</div>
                <div class="ndr-kv">IMEI <span>${escapeHtml(d.imei)}</span></div>
                <div class="ndr-kv">Selesai <span>${escapeHtml(tgl)}</span></div>
            </div>
            <div class="ndr-card">
                <div class="ndr-cap"><i class="fa-solid fa-shield-halved"></i>GARANSI</div>
                <div class="ndr-name">${escapeHtml(d.warranty_label)}</div>
                <div class="ndr-line"><i class="fa-regular fa-calendar-check"></i>${escapeHtml(d.warranty_end ? 's/d ' + sampai : 'tanpa garansi')}</div>
                <div class="ndr-line"><i class="fa-solid fa-screwdriver-wrench"></i>${escapeHtml(d.technician || '-')}</div>
            </div>
        </div>
        <div class="ndr-grid3">
            <div class="ndr-card">
                <div class="ndr-cap"><i class="fa-solid fa-wrench"></i>PEKERJAAN GARANSI</div>
                <div class="ndr-sec"><span>Tindakan perbaikan</span><p class="ndr-check"><i class="fa-solid fa-check"></i>${escapeHtml(d.plan)}</p></div>
                <div class="ndr-sec"><span>Teknisi</span><p>${escapeHtml(d.technician || '-')}</p></div>
                <div class="ndr-sec"><span>Biaya final</span><p class="ndr-price">${escapeHtml(notaRupiah(d.final))}</p></div>
            </div>
            <div class="ndr-card is-green">
                <div class="ndr-cap"><i class="fa-solid fa-shield-halved"></i>MASA GARANSI</div>
                <div class="ndr-sched">
                    <div class="ndr-srow"><span class="ndr-ico"><i class="fa-regular fa-calendar-check"></i></span><div><span>Mulai</span><b>${escapeHtml(tgl)}</b></div></div>
                    <div class="ndr-srow"><span class="ndr-ico"><i class="fa-regular fa-calendar"></i></span><div><span>Berakhir</span><b>${escapeHtml(sampai)}</b></div></div>
                    <div class="ndr-srow"><span class="ndr-ico"><i class="fa-solid fa-shield-halved"></i></span><div><span>Cakupan</span><b>Pekerjaan yang sama</b></div></div>
                </div>
                <div class="ndr-note"><i class="fa-solid fa-circle-info"></i><span>Garansi tidak mencakup kerusakan jatuh, cairan, atau pengerjaan pihak lain.</span></div>
            </div>
            <div class="ndr-card">
                <div class="ndr-cap is-green-t"><i class="fa-solid fa-file-circle-check"></i>KLAIM GARANSI</div>
                <ul class="ndr-yes">
                    <li><i class="fa-solid fa-check"></i><span>Tunjukkan nota garansi ini</span></li>
                    <li><i class="fa-solid fa-check"></i><span>Datang sebelum masa berakhir</span></li>
                    <li><i class="fa-solid fa-check"></i><span>Keluhan sama dengan pekerjaan</span></li>
                </ul>
                <div class="ndr-nohead"><i class="fa-solid fa-triangle-exclamation"></i>TIDAK DITANGGUNG</div>
                <ul class="ndr-no">
                    <li><i class="fa-regular fa-circle-xmark"></i><span>Rusak jatuh / benturan</span></li>
                    <li><i class="fa-regular fa-circle-xmark"></i><span>Kena cairan</span></li>
                    <li><i class="fa-regular fa-circle-xmark"></i><span>Dikerjakan pihak lain</span></li>
                </ul>
            </div>
        </div>
        <div class="ndr-grid3 ndr-row3">
            <div class="ndr-card">
                <div class="ndr-cap"><i class="fa-solid fa-shield-halved"></i>VERIFIKASI GARANSI</div>
                <p class="ndr-desc">Scan QR untuk verifikasi garansi servis Anda.</p>
                <div class="ndr-pill"><i class="fa-solid fa-globe"></i>boss-sf.id/lacak/${escapeHtml(d.no || '')}</div>
            </div>
            <div class="ndr-qrwrap">
                <img src="${qrUrl}" alt="QR garansi" loading="lazy" onerror="this.style.display='none';var f=this.parentNode.querySelector('.ndr-kode-fallback');if(f)f.style.display='flex';">
                <div class="ndr-kode-fallback" style="display:none"><span>GARANSI</span><b>${escapeHtml(d.no || '-')}</b></div>
            </div>
            <div class="ndr-pink">
                <span class="ndr-shield"><i class="fa-solid fa-shield-halved"></i></span>
                <p>Nota garansi hanya berlaku di<br><b>SUKABUMI FLASHER<br>BUSINESS OPERATING SYSTEM</b></p>
                <div class="ndr-thanks">Terima kasih telah mempercayakan perbaikan perangkat Anda kepada kami.</div>
            </div>
        </div>
        <div class="ndr-foot">
            <div class="ndr-foot-l"><i class="fa-regular fa-circle-check"></i><span>${escapeHtml(d.warranty_months === 0 ? 'Servis ini tidak bergaransi toko.' : 'Garansi ' + d.warranty_label + ' untuk pekerjaan yang sama.')}</span></div>
            <div class="ndr-foot-r"><b>Powered by <em>SUKABUMI FLASHER</em></b><span>BUSINESS OPERATING SYSTEM</span></div>
        </div>
    </div>`;
}

function warrantyNotaText(d) {
    const L = [];
    const sep = '--------------------------------';
    const kv = (k, v) => {
        const s = k + ' : ' + (v || '-');
        notaWrap(s, 32).forEach(x => L.push(x));
    };
    L.push('        SUKABUMI FLASHER');
    L.push('   BUSINESS OPERATING SYSTEM');
    L.push('      NOTA GARANSI SERVICE');
    L.push(sep);
    kv('No', d.no);
    kv('Tgl selesai', notaTgl(d.tgl));
    L.push(sep);
    kv('Pelanggan', d.nama);
    kv('WA', d.phone);
    kv('Device', d.device);
    kv('IMEI', d.imei);
    L.push(sep);
    L.push('Tindakan:');
    notaWrap(d.plan, 32).forEach(x => L.push(x));
    kv('Teknisi', notaTechnician(d.technician));
    kv('Biaya final', notaRupiah(d.final));
    L.push(sep);
    kv('Garansi', d.warranty_label);
    kv('Berlaku s/d', d.warranty_end ? notaTgl(d.warranty_end) : '-');
    L.push(sep);
    L.push(d.warranty_months === 0 ? 'Tanpa garansi toko.' : 'Garansi pekerjaan yang sama.');
    L.push('Simpan sebagai bukti garansi.');
    L.push('Terima kasih!');
    return L.join('\n');
}

function warrantyNotaDigitalText(d) {
    return '*NOTA GARANSI SERVICE*\n*SUKABUMI FLASHER - Business Operating System*\n'
        + '--------------------------\n'
        + 'No. Servis : ' + (d.no || '-') + '\n'
        + 'Tgl Selesai : ' + notaTgl(d.tgl) + '\n'
        + 'Nama : ' + (d.nama || '-') + '\n'
        + 'Device : ' + (d.device || '-') + '\n'
        + 'Tindakan : ' + (d.plan || '-') + '\n'
        + 'Teknisi : ' + (notaTechnician(d.technician)) + '\n'
        + 'Biaya Final : ' + notaRupiah(d.final) + '\n'
        + 'Garansi : ' + (d.warranty_label || '-') + (d.warranty_end ? ' s/d ' + notaTgl(d.warranty_end) : '') + '\n'
        + '--------------------------\n'
        + 'Garansi pekerjaan yang sama. Simpan sebagai bukti garansi. Terima kasih! - *SUKABUMI FLASHER*';
}

// Dropdown teknisi di Penerimaan Klaim Garansi. Sumber sama dengan Servis Baru;
// dipanggil ulang tiap overlay dibuka karena token belum ada saat DOMContentLoaded.
async function loadClaimTechnicians() {
    const sel = document.getElementById('clrTechnician');
    if (!sel || sel.options.length > 1) return;
    try {
        const techs = await apiGet('/orders/technicians');
        if (!Array.isArray(techs) || !techs.length) return;
        sel.innerHTML = '<option value="">— Pilih Teknisi —</option>' + techs.map(t => `<option value="${t}">${t}</option>`).join('');
    } catch (_) {}
}

function initClaimReceive() {
    try { renderChecklist('clr', 'clrCheckGroups', 'Kondisi unit saat klaim diterima.'); } catch (_) {}
    loadClaimTechnicians();
    const s = document.getElementById('clrSearch');
    if (s && !s.dataset.clrBound) {
        s.dataset.clrBound = '1';
        s.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); claimRSearch(); } });
    }
    const form = document.getElementById('claimReceiveForm');
    if (form && !form.dataset.clrBound) {
        form.dataset.clrBound = '1';
        form.addEventListener('submit', claimRSubmit);
    }
}

// ─────────────────────────────────────────────
// AUDIT TUTUP KAS (popup dari dashboard — hitung uang laci, dibandingkan saat Tutup Kas)
// ─────────────────────────────────────────────

function openAuditKas() {
    const ov = document.getElementById('auditKasPopup');
    if (!ov) return;
    const input = document.getElementById('auditKasNominal');
    if (input) input.value = '';
    const fb = document.getElementById('auditKasFeedback');
    if (fb) fb.classList.add('hidden');
    const txt = document.getElementById('auditKasLockText');
    if (txt) txt.textContent = 'Kunci & Arsip';
    ov.classList.remove('hidden');
    if (input) setTimeout(() => input.focus({ preventScroll: true }), 60);
}

function closeAuditKas() {
    const ov = document.getElementById('auditKasPopup');
    if (ov) ov.classList.add('hidden');
}

function auditKasFeedback(msg, isErr) {
    const fb = document.getElementById('auditKasFeedback');
    if (!fb) return;
    fb.classList.remove('hidden', 'success', 'error');
    fb.classList.add(isErr ? 'error' : 'success');
    fb.innerHTML = `<i class="fa-solid ${isErr ? 'fa-triangle-exclamation' : 'fa-circle-check'}"></i> ${escapeHtml(msg)}`;
}

function submitAuditKas() {
    const input = document.getElementById('auditKasNominal');
    const nominal = Math.round(parseFloat(input ? input.value : '') || 0);
    if (!(nominal > 0)) {
        auditKasFeedback('Isi dulu total uang fisik di laci (Rp).', true);
        if (input) input.focus({ preventScroll: true });
        return;
    }
    const btn = document.getElementById('auditKasLockBtn');
    const txt = document.getElementById('auditKasLockText');
    if (btn) btn.disabled = true;
    if (txt) txt.textContent = 'Mengunci...';
    try {
        try {
            localStorage.setItem('bsf_audit_kas', JSON.stringify({
                nominal: nominal,
                at: new Date().toISOString(),
            }));
        } catch (_) {}
        const jam = new Date().toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit' });
        auditKasFeedback('Tercatat Rp ' + nominal.toLocaleString('id-ID') + ' • ' + jam + ' — akan dibandingkan saat Tutup Kas.', false);
        setTimeout(closeAuditKas, 1400);
    } finally {
        if (btn) btn.disabled = false;
        if (txt) txt.textContent = 'Kunci & Arsip';
    }
}

if (!window._auditKasKeys) {
    window._auditKasKeys = true;
    document.addEventListener('keydown', function (e) {
        const ov = document.getElementById('auditKasPopup');
        if (!ov || ov.classList.contains('hidden')) return;
        if (e.key === 'Escape') closeAuditKas();
        else if (e.key === 'Enter' && document.activeElement
            && document.activeElement.id === 'auditKasNominal') submitAuditKas();
    });
}

// ─────────────────────────────────────────────
// PENGATURAN BEBAN HARIAN (popup dari dashboard — tersimpan di server, fallback lokal bila offline)
// ─────────────────────────────────────────────

const BEBAN_DEFAULT = [
    { kategori: 'Gaji', nama: 'Analize Service Officer', nilai: 200000 },
    { kategori: 'Gaji', nama: 'Customer Service', nilai: 200000 },
    { kategori: 'Operasional', nama: 'Sewa tempat', nilai: 170000 },
    { kategori: 'Operasional', nama: 'Pulsa', nilai: 5000 },
    { kategori: 'Operasional', nama: 'Listrik', nilai: 14000 },
    { kategori: 'Operasional', nama: 'Internet', nilai: 16000 },
];
const BEBAN_STORE_KEY = 'bsf_beban_harian_v2';

let _bebanList = [];
let _bebanEditIdx = -1;
let _bebanDeleted = [];
let _bebanOnline = true;

function bebanLoad() {
    try {
        const raw = localStorage.getItem(BEBAN_STORE_KEY);
        if (raw) {
            const arr = JSON.parse(raw);
            if (Array.isArray(arr)) return arr;
        }
    } catch (_) {}
    return BEBAN_DEFAULT.map(b => ({ ...b }));
}

function bebanRupiah(v) {
    return 'Rp ' + (Number(v) || 0).toLocaleString('id-ID');
}

function bebanNum(v) {
    return (Number(v) || 0).toLocaleString('en-US');
}

async function bebanMigrateOnce(rows) {
    // Migrasi sekali data lokal lama ke server, lalu hapus kunci lokal.
    try {
        for (const b of rows) {
            await apiPost('/expenses', { kategori: b.kategori, uraian: b.nama, nilai: b.nilai });
        }
    } catch (_) {}
    try { localStorage.removeItem(BEBAN_STORE_KEY); } catch (_) {}
}

async function openBeban() {
    _bebanEditIdx = -1;
    _bebanDeleted = [];
    const kat = document.getElementById('bebanKategori');
    const nama = document.getElementById('bebanNama');
    const nilai = document.getElementById('bebanNilai');
    if (kat) kat.value = 'Operasional';
    if (nama) nama.value = '';
    if (nilai) nilai.value = '';
    const addTxt = document.getElementById('bebanAddText');
    if (addTxt) addTxt.textContent = 'Tambah';
    const fb = document.getElementById('bebanFeedback');
    if (fb) fb.classList.add('hidden');
    _bebanList = [];
    _bebanOnline = true;
    bebanRender();
    document.getElementById('bebanPopup').classList.remove('hidden');
    try {
        const page = await apiGet('/expenses?limit=100');
        const rows = (page && page.items) || [];
        if (!rows.length) {
            // Server kosong: migrasikan HANYA data lokal milik user bila kuncinya ada.
            // Daftar referensi bawaan (BEBAN_DEFAULT) tidak pernah dikirim ke server.
            let arr = null;
            try {
                const raw = localStorage.getItem(BEBAN_STORE_KEY);
                if (raw) { const parsed = JSON.parse(raw); if (Array.isArray(parsed)) arr = parsed; }
            } catch (_) { arr = null; }
            if (arr && arr.length) await bebanMigrateOnce(arr);
            const page2 = await apiGet('/expenses?limit=100');
            _bebanList = ((page2 && page2.items) || []).map(r => ({ id: r.id, kategori: r.kategori, nama: r.uraian, nilai: r.nilai }));
        } else {
            _bebanList = rows.map(r => ({ id: r.id, kategori: r.kategori, nama: r.uraian, nilai: r.nilai }));
        }
    } catch (_) {
        // Offline/fallback: mode lokal seperti sebelumnya.
        _bebanOnline = false;
        _bebanList = bebanLoad();
        bebanFeedback('Server tidak terjangkau — mode lokal (tersimpan di perangkat).', true);
    }
    bebanRender();
    if (nama) setTimeout(() => nama.focus({ preventScroll: true }), 60);
}

function closeBeban() {
    const ov = document.getElementById('bebanPopup');
    if (ov) ov.classList.add('hidden');
    _bebanEditIdx = -1;
}

function bebanRender() {
    const body = document.getElementById('bebanBody');
    if (!body) return;
    if (!_bebanList.length) {
        body.innerHTML = `<tr><td colspan="4"><div class="beban-empty"><i class="fa-solid fa-receipt"></i>Belum ada beban — tambah lewat form di atas.</div></td></tr>`;
    } else {
    body.innerHTML = _bebanList.map((b, i) => {
        const isGaji = String(b.kategori || '').toLowerCase().includes('gaji');
        return `
        <tr>
            <td><span class="beban-cat ${isGaji ? 'is-gaji' : 'is-ops'}">${escapeHtml(b.kategori)}</span></td>
            <td class="font-medium text-gray-800 dark:text-gray-200">${escapeHtml(b.nama)}</td>
            <td>${bebanNum(b.nilai)}</td>
            <td>
                <button type="button" class="beban-ico is-edit" title="Edit" onclick="bebanEdit(${i})"><i class="fa-solid fa-pen"></i></button>
                <button type="button" class="beban-ico is-del" title="Hapus" onclick="bebanDel(${i})"><i class="fa-solid fa-trash"></i></button>
            </td>
        </tr>`;
    }).join('');
    }
    const total = _bebanList.reduce((a, b) => a + (Number(b.nilai) || 0), 0);
    const tfoot = document.getElementById('bebanTotal');
    if (tfoot) tfoot.textContent = bebanNum(total);
    const info = document.getElementById('bebanInfo');
    if (info) info.textContent = _bebanList.length + ' beban • Total ' + bebanRupiah(total);
}

function bebanFeedback(msg, isErr) {
    const fb = document.getElementById('bebanFeedback');
    if (!fb) return;
    fb.classList.remove('hidden', 'success', 'error');
    fb.classList.add(isErr ? 'error' : 'success');
    fb.innerHTML = `<i class="fa-solid ${isErr ? 'fa-triangle-exclamation' : 'fa-circle-check'}"></i> ${escapeHtml(msg)}`;
}

function bebanAdd() {
    const kat = (document.getElementById('bebanKategori') || {}).value || 'Operasional';
    const nama = ((document.getElementById('bebanNama') || {}).value || '').trim();
    const nilai = Math.round(parseFloat((document.getElementById('bebanNilai') || {}).value) || 0);
    if (!nama) {
        bebanFeedback('Isi dulu nama bebannya.', true);
        const el = document.getElementById('bebanNama');
        if (el) el.focus({ preventScroll: true });
        return;
    }
    if (!(nilai >= 0)) {
        bebanFeedback('Nilai harus angka 0 atau lebih.', true);
        return;
    }
    if (_bebanEditIdx >= 0 && _bebanList[_bebanEditIdx]) {
        _bebanList[_bebanEditIdx] = { kategori: kat, nama: nama, nilai: nilai };
        _bebanEditIdx = -1;
        const addTxt = document.getElementById('bebanAddText');
        if (addTxt) addTxt.textContent = 'Tambah';
        bebanFeedback('Beban diperbarui (belum tersimpan — klik Simpan).', false);
    } else {
        _bebanList.push({ kategori: kat, nama: nama, nilai: nilai });
        bebanFeedback('Beban ditambahkan (belum tersimpan — klik Simpan).', false);
    }
    document.getElementById('bebanNama').value = '';
    document.getElementById('bebanNilai').value = '';
    bebanRender();
}

function bebanEdit(i) {
    const b = _bebanList[i];
    if (!b) return;
    _bebanEditIdx = i;
    document.getElementById('bebanKategori').value = b.kategori;
    document.getElementById('bebanNama').value = b.nama;
    document.getElementById('bebanNilai').value = b.nilai;
    const addTxt = document.getElementById('bebanAddText');
    if (addTxt) addTxt.textContent = 'Update';
    document.getElementById('bebanNama').focus({ preventScroll: true });
}

function bebanDel(i) {
    const b = _bebanList[i];
    if (!b) return;
    if (!confirm('Hapus beban "' + b.nama + '"?')) return;
    if (b.id) _bebanDeleted.push(b.id);
    _bebanList.splice(i, 1);
    if (_bebanEditIdx === i) {
        _bebanEditIdx = -1;
        const addTxt = document.getElementById('bebanAddText');
        if (addTxt) addTxt.textContent = 'Tambah';
    }
    bebanRender();
}

async function bebanSave() {
    const total = _bebanList.reduce((a, b) => a + (Number(b.nilai) || 0), 0);
    if (!confirm('Simpan ' + _bebanList.length + ' beban dengan total ' + bebanRupiah(total) + '?')) return;
    const btn = document.getElementById('bebanSaveBtn');
    const txt = document.getElementById('bebanSaveText');
    const LABEL = 'SIMPAN & KEMBALI KE DASHBOARD';
    if (btn) btn.disabled = true;
    if (txt) txt.textContent = 'MENYIMPAN...';
    try {
        if (_bebanOnline) {
            for (const id of _bebanDeleted) {
                try { await apiDel('/expenses/' + id); } catch (_) {}
            }
            _bebanDeleted = [];
            for (const b of _bebanList) {
                if (b.id) {
                    try { await apiPut('/expenses/' + b.id, { kategori: b.kategori, uraian: b.nama, nilai: b.nilai }); } catch (_) {}
                } else {
                    try {
                        const created = await apiPost('/expenses', { kategori: b.kategori, uraian: b.nama, nilai: b.nilai });
                        b.id = created.id;
                    } catch (_) {}
                }
            }
        } else {
            try { localStorage.setItem(BEBAN_STORE_KEY, JSON.stringify(_bebanList)); } catch (_) {}
        }
        bebanFeedback('Tersimpan: ' + _bebanList.length + ' beban, total ' + bebanRupiah(total) + ' — kembali ke dashboard.', false);
        try { await loadDashboard(); } catch (_) {}
        setTimeout(closeBeban, 1200);
    } catch (err) {
        bebanFeedback(err.message, true);
    } finally {
        if (btn) btn.disabled = false;
        if (txt) txt.textContent = LABEL;
    }
}

if (!window._bebanKeys) {
    window._bebanKeys = true;
    document.addEventListener('keydown', function (e) {
        const ov = document.getElementById('bebanPopup');
        if (!ov || ov.classList.contains('hidden')) return;
        if (e.key === 'Escape') closeBeban();
        else if (e.key === 'Enter' && document.activeElement
            && ['bebanNama', 'bebanNilai'].includes(document.activeElement.id)) bebanAdd();
    });
}

document.addEventListener('DOMContentLoaded', async function () {
    initTheme();
    updateClock();
    setInterval(updateClock, 1000);
    initNav();
    renderQuickActions();
    initReceivePage();
    initUpdateServis();
    initClaimReceive();
    initFloatDrag();
    initSparepart();
    initLogin();
    initPasscodeForm();

    window.addEventListener('hashchange', () => {
        if (!getToken()) return;
        if (isReceiveHash()) { openServisBaru(); return; }
        const k = pageFromHash();
        if (k && k !== window._activePage) navigateTo(k);
    });

    const user = await checkSession();
    if (user) {
        setAdminUI(user);
        hideLogin();
        try {
            await loadDashboard();
        } catch (err) {
            console.error('Gagal memuat data dari API:', err);
        }
        const wantReceive = isReceiveHash() || isReceiveOpen();
        navigateTo(pageFromHash() || getSavedPage());
        if (wantReceive) openServisBaru();
    } else {
        showLogin();
    }
});
