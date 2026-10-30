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
    try { updateReceiveCalc(); } catch (_) {}
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
    'penjualanpart': ['PART_SALE_CREATE', 'SPAREPART_WRITE'],
    'transaksi': ['ORDER_CREATE', 'ORDER_UPDATE', 'REPORT_FULL'],
    'pelanggan': ['CUSTOMER_WRITE'],
    'garansi': ['CLAIM_WRITE', 'REPORT_FULL'],
    'sparepart': ['SPAREPART_WRITE'],
    'keuangan': ['KAS_CLOSE', 'EXPENSE_WRITE', 'KAS_ENTRY_WRITE', 'REPORT_FULL',
        'REPORT_INVESTOR'],
    'akun': ['USER_MANAGE'],
};

function bolehBukaHalaman(key) {
    const butuh = PAGE_CAP[key];
    if (!butuh) return true; // dashboard: semua login
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
    else if (key === 'penjualanpart') showPenjualanPart();
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
    if (name && name !== 'dashboard' && !bolehBukaHalaman(name)) {
        toast('Halaman ini di luar kewenangan role Anda.');
        name = 'dashboard';
    }
    window._activePage = name;
    const isDash = name === 'dashboard';
    const isPenjualanPart = name === 'penjualanpart';
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
    if (document.getElementById('pagePenjualanPart')) {
        document.getElementById('pagePenjualanPart').classList.toggle('hidden', !isPenjualanPart);
    }
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
    const target = isDash ? 'dashboard' : isPenjualanPart ? 'penjualanpart' : isTransaksi ? 'transaksi' : isPelanggan ? 'pelanggan' : isGaransi ? 'garansi' : isSparepart ? 'sparepart' : isKeuangan ? 'keuangan' : isAkun ? 'akun' : 'dashboard';
    setActiveNav(target, navs);
    setActiveNav(target, mobiles);
    if (window.innerWidth < 640) toggleSidebar(false);
}

function showDashboard() {
    showPage('dashboard');
    try { renderDashGaransiTask(); } catch (_) {}
}
function showPenjualanPart() {
    showPage('penjualanpart');
    renderPenjualanPart();
}
function showTransaksi() { showPage('transaksi'); renderTransaksi(); }
function showPelanggan() { showPage('pelanggan'); renderPelanggan(); }
function showGaransi() { showPage('garansi'); renderGaransi(); }
function showSparepart() {
    _spPage = 1;
    showPage('sparepart');
    switchSparepartSubTab(_spActiveSubTab || 'catalog');
}
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

function togglePassVisibility(inputId, btn) {
    const input = document.getElementById(inputId);
    if (!input) return;
    const isPass = input.type === 'password';
    input.type = isPass ? 'text' : 'password';
    const icon = btn ? btn.querySelector('i') : null;
    if (icon) {
        if (isPass) {
            icon.classList.remove('fa-eye');
            icon.classList.add('fa-eye-slash');
        } else {
            icon.classList.remove('fa-eye-slash');
            icon.classList.add('fa-eye');
        }
    }
}
window.togglePassVisibility = togglePassVisibility;

function akAvatar(nama, id) {
    const palette = [
        'bg-blue-600',
        'bg-emerald-600',
        'bg-purple-600',
        'bg-indigo-600',
        'bg-amber-600',
        'bg-teal-600',
        'bg-rose-600',
        'bg-cyan-600'
    ];
    const n = (nama || '').trim();
    let initials = '';
    if (n && n !== '-') {
        const parts = n.split(/\s+/).filter(Boolean);
        if (parts.length >= 2) {
            initials = (parts[0][0] + parts[1][0]).toUpperCase();
        } else if (parts.length === 1) {
            initials = parts[0].slice(0, 2).toUpperCase();
        }
    }
    if (!initials) initials = 'U';
    const colorIdx = Math.abs(Number(id) || (nama ? nama.charCodeAt(0) : 0)) % palette.length;
    return {
        initials,
        bg: palette[colorIdx]
    };
}
window.akAvatar = akAvatar;

function akRoleBadge(role) {
    const r = (role || '').trim();
    const up = r.toUpperCase();
    if (['SUPERADMIN', 'SUPER ADMIN', 'SUPER_ADMIN', 'DEV', 'DEVELOPER'].includes(up)) {
        return `<span class="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-300 border border-purple-200 dark:border-purple-800/30"><i class="fa-solid fa-crown text-[10px] text-purple-500"></i> ${escapeHtml(r)}</span>`;
    }
    if (['ADMIN', 'MANAGER'].includes(up)) {
        return `<span class="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300 border border-blue-200 dark:border-blue-800/30"><i class="fa-solid fa-user-shield text-[10px] text-blue-500"></i> ${escapeHtml(r)}</span>`;
    }
    if (up === 'KASIR') {
        return `<span class="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800/30"><i class="fa-solid fa-cash-register text-[10px] text-emerald-500"></i> ${escapeHtml(r)}</span>`;
    }
    if (up === 'TEKNISI') {
        return `<span class="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300 border border-amber-200 dark:border-amber-800/30"><i class="fa-solid fa-wrench text-[10px] text-amber-500"></i> ${escapeHtml(r)}</span>`;
    }
    if (['PENGELOLA', 'PEMILIK'].includes(up)) {
        return `<span class="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-indigo-100 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-300 border border-indigo-200 dark:border-indigo-800/30"><i class="fa-solid fa-briefcase text-[10px] text-indigo-500"></i> ${escapeHtml(r)}</span>`;
    }
    if (up === 'INVESTOR') {
        return `<span class="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-cyan-100 text-cyan-800 dark:bg-cyan-900/30 dark:text-cyan-300 border border-cyan-200 dark:border-cyan-800/30"><i class="fa-solid fa-chart-pie text-[10px] text-cyan-500"></i> ${escapeHtml(r)}</span>`;
    }
    return `<span class="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300 border border-gray-200 dark:border-gray-700"><i class="fa-solid fa-user text-[10px]"></i> ${escapeHtml(r)}</span>`;
}

function akStatusBadge(status) {
    const on = status === 'Aktif';
    if (on) {
        return `<span class="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-medium bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-400 border border-emerald-200/60 dark:border-emerald-800/40"><span class="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></span>Aktif</span>`;
    }
    return `<span class="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-medium bg-gray-100 text-gray-500 dark:bg-gray-800/60 dark:text-gray-400 border border-gray-200 dark:border-gray-700/50"><span class="w-1.5 h-1.5 rounded-full bg-gray-400"></span>Nonaktif</span>`;
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
        body.innerHTML = `<tr><td colspan="6"><div class="text-center text-sm text-gray-400 py-6">${escapeHtml(err.message || 'Gagal memuat akun.')}</div></td></tr>`;
        return;
    }
    const total = _akView.length;
    const aktif = _akView.filter(a => a.status === 'Aktif').length;
    const admin = _akView.filter(a => ['ADMIN', 'SUPERADMIN', 'SUPER ADMIN', 'SUPER_ADMIN', 'DEV', 'DEVELOPER'].includes((a.role || '').toUpperCase())).length;
    const setNum = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
    setNum('akTotal', total);
    setNum('akAktif', aktif);
    setNum('akAdmin', admin);

    // Hitung komposisi tim per role
    const roleCounts = {};
    _akView.forEach(a => {
        if (a.status === 'Aktif') {
            const r = (a.role || 'Teknisi').trim();
            roleCounts[r] = (roleCounts[r] || 0) + 1;
        }
    });
    const timSummaryEl = document.getElementById('akTimSummary');
    if (timSummaryEl) {
        const roleOrder = ['Superadmin', 'Admin', 'Teknisi', 'Kasir', 'Pengelola', 'Investor'];
        const keys = Object.keys(roleCounts).sort((a, b) => {
            const ia = roleOrder.findIndex(x => x.toLowerCase() === a.toLowerCase());
            const ib = roleOrder.findIndex(x => x.toLowerCase() === b.toLowerCase());
            if (ia >= 0 && ib >= 0) return ia - ib;
            if (ia >= 0) return -1;
            if (ib >= 0) return 1;
            return a.localeCompare(b);
        });
        const pills = keys.map(k => {
            return `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-medium bg-gray-100 dark:bg-white/5 text-gray-700 dark:text-gray-300 border border-gray-200 dark:border-white/5"><b class="text-brand-600 dark:text-brand-400">${roleCounts[k]}</b> ${escapeHtml(k)}</span>`;
        });
        timSummaryEl.innerHTML = pills.length ? pills.join(' ') : '<span class="text-xs text-gray-400">Tidak ada akun aktif</span>';
    }

    const data = akFiltered();
    if (!data.length) {
        body.innerHTML = `<tr><td colspan="6"><div class="text-center text-sm text-gray-400 py-8"><i class="fa-solid fa-user-slash text-2xl mb-2 block text-gray-300 dark:text-gray-600"></i>Tidak ada akun yang sesuai kriteria filter</div></td></tr>`;
    } else {
        body.innerHTML = data.map((a) => {
            const av = akAvatar(a.nama, a.id);
            const isMe = window._currentUserId && Number(a.id) === Number(window._currentUserId);
            const meBadge = isMe
                ? `<span class="px-1.5 py-0.2 text-[9.5px] font-medium rounded-full bg-brand-50 text-brand-600 dark:bg-brand-900/30 dark:text-brand-400 border border-brand-200 dark:border-brand-800/40">Anda</span>`
                : '';
            return `
            <tr class="tx-row">
                <td class="text-center text-gray-500 text-xs">${_akView.indexOf(a) + 1}</td>
                <td>
                    <div class="flex items-center gap-3">
                        <div class="w-9 h-9 rounded-full flex items-center justify-center font-bold text-xs text-white shadow-sm flex-shrink-0 ${av.bg}">
                            ${escapeHtml(av.initials)}
                        </div>
                        <div class="min-w-0">
                            <div class="font-semibold text-sm flex items-center gap-1.5 ${a.status === 'Aktif'
                                ? 'text-gray-800 dark:text-gray-100'
                                : 'text-gray-400 dark:text-gray-500 line-through'}">
                                <span class="truncate">${escapeHtml(a.nama)}</span>
                                ${meBadge}
                            </div>
                            <div class="text-xs text-gray-400 dark:text-gray-500 font-mono">@${escapeHtml(a.username)}</div>
                        </div>
                    </div>
                </td>
                <td class="text-center">${akRoleBadge(a.role)}</td>
                <td class="text-center">${akStatusBadge(a.status)}</td>
                <td class="text-gray-500 dark:text-gray-400 text-xs">${escapeHtml(a.login)}</td>
                <td class="text-center">
                    <div class="inline-flex items-center justify-center gap-1">
                        <button type="button" class="w-7 h-7 inline-flex items-center justify-center rounded-lg bg-gray-100 hover:bg-brand-50 hover:text-brand-600 dark:bg-white/5 dark:hover:bg-brand-500/20 dark:hover:text-brand-300 text-gray-500 transition-colors" title="Edit Akun" onclick="akEdit(${a.id})"><i class="fa-solid fa-pen-to-square text-xs"></i></button>
                        ${isMe
                            ? `<button type="button" class="w-7 h-7 inline-flex items-center justify-center rounded-lg bg-gray-50 dark:bg-white/5 text-gray-300 dark:text-gray-600 cursor-not-allowed" title="Akun Anda sedang aktif digunakan" disabled><i class="fa-solid fa-shield-halved text-xs"></i></button>`
                            : (a.status === 'Aktif'
                                ? `<button type="button" class="w-7 h-7 inline-flex items-center justify-center rounded-lg bg-gray-100 hover:bg-amber-50 hover:text-amber-600 dark:bg-white/5 dark:hover:bg-amber-500/20 dark:hover:text-amber-300 text-gray-500 transition-colors" title="Nonaktifkan Akun" onclick="akDeactivate(${a.id}, '${escapeHtml(a.username).replace(/'/g, "\\'")}')"><i class="fa-solid fa-user-slash text-xs"></i></button>`
                                : `<button type="button" class="w-7 h-7 inline-flex items-center justify-center rounded-lg bg-gray-100 hover:bg-emerald-50 hover:text-emerald-600 dark:bg-white/5 dark:hover:bg-emerald-500/20 dark:hover:text-emerald-300 text-gray-500 transition-colors" title="Aktifkan Lagi" onclick="akReactivate(${a.id})"><i class="fa-solid fa-rotate-left text-xs"></i></button>`)}
                        ${window._bssfRoleKey === 'superadmin' && !isMe
                            ? `<button type="button" class="w-7 h-7 inline-flex items-center justify-center rounded-lg bg-gray-100 hover:bg-rose-50 hover:text-rose-600 dark:bg-white/5 dark:hover:bg-rose-500/20 dark:hover:text-rose-300 text-gray-500 transition-colors" title="Hapus Permanen" onclick="akDelete(${a.id}, '${escapeHtml(a.username).replace(/'/g, "\\'")}')"><i class="fa-solid fa-trash text-xs"></i></button>`
                            : ''}
                    </div>
                </td>
            </tr>`;
        }).join('');
    }
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
    const pwEl = document.getElementById('akPassword');
    if (pwEl) {
        pwEl.value = '';
        pwEl.type = 'password';
        const eye = pwEl.parentElement ? pwEl.parentElement.querySelector('i') : null;
        if (eye) { eye.classList.remove('fa-eye-slash'); eye.classList.add('fa-eye'); }
    }
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

async function akDelete(id, username) {
    if (!confirm('HAPUS PERMANEN akun "' + username + '"?\n\n\u26A0\uFE0F Tindakan ini TIDAK BISA DIBATALKAN.\nData akun, histori login, dan journal akan dihapus permanen.')) return;
    try {
        await apiDel('/auth/users/' + id);
        toast('Akun "' + username + '" dihapus permanen.');
        renderAkun();
    } catch (err) {
        toast(err.message || 'Gagal menghapus akun.');
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
    try { updateReceiveCalc(); } catch (_) {}
    loadSmartHistory();
    try {
        const _p = document.getElementById('rcPhone');
        if (_p) updateRcPhoneFeedback(_p.value.trim());
        updateRcChipStates('rcDamage', 'rcDamageChips');
        updateRcChipStates('rcPlan', 'rcPlanChips');
        populateDeviceDatalist();
    } catch (_) {}
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
    const pwEl = document.getElementById('akPassword');
    if (pwEl) {
        pwEl.type = 'password';
        const eye = pwEl.parentElement ? pwEl.parentElement.querySelector('i') : null;
        if (eye) { eye.classList.remove('fa-eye-slash'); eye.classList.add('fa-eye'); }
    }
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

async function apiDelete(path) {
    const headers = {};
    const token = getToken();
    if (token) headers['Authorization'] = 'Bearer ' + token;
    const res = await fetch(API_BASE + path, { method: 'DELETE', headers });
    if (res.status === 401) { throw new AuthError('Sesi tidak valid'); }
    if (!res.ok) {
        let detail = 'Gagal menghapus data (HTTP ' + res.status + ')';
        try { const j = await res.json(); if (j.detail) detail = j.detail; } catch (_) {}
        throw new Error(detail);
    }
    return res.json();
}

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
    superadmin: ['SERVICE_PART_USE', 'ORDER_CREATE', 'ORDER_UPDATE', 'ORDER_UPDATE_FINANCE', 'ORDER_UPDATE_MODAL',
        'ORDER_STATUS_CLOSING', 'ORDER_HANDOVER', 'ORDER_DELETE', 'PAYMENT_CREATE', 'PAYMENT_CANCEL',
        'EXPENSE_WRITE', 'KAS_ENTRY_WRITE', 'KAS_CLOSE', 'KAS_ASET_INJEKSI', 'REFUND_DP', 'REFUND_GARANSI',
        'FAILED_CANCEL', 'SPAREPART_WRITE', 'CLAIM_WRITE', 'EXPENSE_DEBT_WRITE', 'USER_MANAGE',
        'CUSTOMER_WRITE', 'CUSTOMER_DELETE', 'ROLE_CONFIG', 'AUDIT_READ', 'REPORT_FULL',
        'REPORT_INVESTOR', 'REPORT_SPAREPART', 'PART_SALE_CREATE', 'SPAREPART_DEFECT_REPORT', 'SPAREPART_DEFECT_RESOLVE'],
    admin: ['SERVICE_PART_USE', 'ORDER_CREATE', 'ORDER_UPDATE', 'ORDER_UPDATE_FINANCE', 'ORDER_UPDATE_MODAL',
        'ORDER_STATUS_CLOSING', 'ORDER_HANDOVER', 'ORDER_DELETE', 'PAYMENT_CREATE', 'PAYMENT_CANCEL',
        'EXPENSE_WRITE', 'KAS_ENTRY_WRITE', 'KAS_CLOSE', 'KAS_ASET_INJEKSI', 'REFUND_DP', 'REFUND_GARANSI',
        'FAILED_CANCEL', 'SPAREPART_WRITE', 'CLAIM_WRITE', 'EXPENSE_DEBT_WRITE', 'USER_MANAGE',
        'CUSTOMER_WRITE', 'CUSTOMER_DELETE', 'AUDIT_READ', 'REPORT_FULL', 'REPORT_INVESTOR', 'REPORT_SPAREPART',
        'PART_SALE_CREATE', 'SPAREPART_DEFECT_REPORT', 'SPAREPART_DEFECT_RESOLVE'],
    kasir: ['ORDER_CREATE', 'ORDER_UPDATE', 'ORDER_UPDATE_FINANCE', 'ORDER_STATUS_CLOSING',
        'ORDER_HANDOVER', 'PAYMENT_CREATE', 'REFUND_DP', 'FAILED_CANCEL',
        'CLAIM_WRITE', 'CUSTOMER_WRITE', 'PART_SALE_CREATE'],
    teknisi: ['SERVICE_PART_USE', 'ORDER_UPDATE', 'ORDER_HANDOVER', 'CLAIM_WRITE', 'SPAREPART_DEFECT_REPORT'],
    adminSparepart: ['SERVICE_PART_USE', 'SPAREPART_WRITE', 'REPORT_SPAREPART', 'SPAREPART_DEFECT_REPORT', 'SPAREPART_DEFECT_RESOLVE'],
    pengelola: ['REPORT_FULL', 'REPORT_SPAREPART'],
    investor: ['REPORT_INVESTOR'],
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
function updateNavMenuVisibility() {
    document.querySelectorAll('.nav-link[data-page], .mobile-nav-item[data-page]').forEach(el => {
        const page = el.dataset.page;
        if (!page || page === 'dashboard') return;
        const ok = bolehBukaHalaman(page);
        el.classList.toggle('hidden', !ok);
    });
    const adminAreaHeader = document.querySelector('.px-3.pb-3.mt-auto .px-3.py-2.text-\\[9\\.5px\\]') ||
        document.querySelector('.px-3.pb-3.mt-auto div:first-child');
    if (adminAreaHeader) {
        adminAreaHeader.classList.toggle('hidden', !can('USER_MANAGE'));
    }
}
window.updateNavMenuVisibility = updateNavMenuVisibility;

function applyRoleUI(root) {
    const scope = root || document;
    scope.querySelectorAll('[data-cap]').forEach(el => {
        const ok = can(el.getAttribute('data-cap'));
        el.classList.toggle('hidden', !ok);
    });
    const qaEl = document.getElementById('quickActions');
    if (qaEl) {
        const visibleCards = qaEl.querySelectorAll('.qa-card:not(.hidden)');
        const parentPanel = qaEl.closest('.panel');
        if (parentPanel) {
            parentPanel.classList.toggle('hidden', visibleCards.length === 0);
        }
    }
    updateNavMenuVisibility();
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
    try { renderQuickActions(); } catch (_) {}
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

async function apiDel(path) {
    const headers = {};
    const token = getToken();
    if (token) headers['Authorization'] = 'Bearer ' + token;
    const res = await fetch(API_BASE + path, {
        method: 'DELETE',
        headers,
    });
    if (res.status === 401) { throw new AuthError('Sesi tidak valid'); }
    if (!res.ok) {
        let detail = 'Gagal menghapus (HTTP ' + res.status + ')';
        try { const j = await res.json(); if (j.detail) detail = j.detail; } catch (_) {}
        throw new Error(detail);
    }
    return res.json();
}

// Warna semantik KPI (ref: warna-reference.png):
// hijau=pemasukan, biru=finansial utama, amber=beban,
// dinamis=bersih (hijau/merah), target=kartu putih netral + progress bar
const STAR_META = {
    omset: { icon: 'fa-solid fa-wallet', tint: 'kpi-green' },
    laba_kotor: { icon: 'fa-solid fa-chart-line', tint: 'kpi-blue' },
    beban: { icon: 'fa-solid fa-receipt', tint: 'kpi-amber' },
    laba_bersih: { icon: 'fa-solid fa-trophy', tint: 'kpi-green' },
    cts: { icon: 'fa-solid fa-bullseye' },
    cto: { icon: 'fa-solid fa-industry' },
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
    window._lastPeriodData = per;
    try { if (typeof updateHeaderNotif === 'function') updateHeaderNotif(); } catch (_) {}
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
        const iconHtml = m.icon ? `<i class="${m.icon}"></i>` : '';
        if (key === 'laba_bersih') {
            const tint = Number(c.value) < 0 ? 'kpi-red' : 'kpi-green';
            return `
            <div class="star-card ${tint} kpi-solid">
                <div class="kpi-top"><span class="kpi-label">${escapeHtml(c.label)}</span><span class="kpi-emoji">${iconHtml}</span></div>
                <div class="kpi-value">${cvalue}</div>
                ${c.sub ? `<div class="kpi-caption kpi-caption-light">${escapeHtml(c.sub)}</div>` : ''}
            </div>`;
        }
        if (key === 'cts') {
            return `
            <div class="star-card kpi-target col-span-2 sm:col-span-1">
                <div class="kpi-top"><span class="kpi-label-dark"><i class="${m.icon || 'fa-solid fa-bullseye'} text-brand-600 mr-1.5"></i>${escapeHtml(c.label)}</span></div>
                <div class="kpi-value-dark">${cvalue}</div>
                ${kpiProgressBar(c.progress, c.tercapai)}
                ${c.sub ? `<div class="kpi-caption">${escapeHtml(c.sub)}</div>` : ''}
            </div>`;
        }
        return `
            <div class="star-card ${m.tint} kpi-solid">
                <div class="kpi-top"><span class="kpi-label">${escapeHtml(c.label)}</span><span class="kpi-emoji">${iconHtml}</span></div>
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
        { icon: 'fa-solid fa-plus', label: 'Servis Baru', desc: 'Buat transaksi service baru', tint: 'qa-red', cap: 'ORDER_CREATE', go: 'openServisBaru()' },
        { icon: 'fa-solid fa-cash-register', label: 'Input Kas', desc: 'Catat pemasukan kas harian', tint: 'qa-green', cap: 'KAS_ENTRY_WRITE', go: 'openAuditKas()' },
        { icon: 'fa-solid fa-money-check-dollar', label: 'Input Beban', desc: 'Catat pengeluaran operasional', tint: 'qa-amber', cap: 'EXPENSE_WRITE', go: 'openBeban()' },
        { icon: 'fa-solid fa-microchip', label: 'Sparepart', desc: 'Kelola data sparepart', tint: 'qa-blue', cap: 'SPAREPART_WRITE', go: 'showSparepart()' },
    ];

    const qaEl = document.getElementById('quickActions');
    if (!qaEl) return;
    qaEl.innerHTML = actions.map((a, i) => {
        const featured = i === 0 ? ' qa-card-featured' : '';
        return `
            <button class="qa-card ${a.tint}${featured}" onclick="${a.go}" data-cap="${a.cap}">
                <span class="qa-card-icon"><i class="${a.icon}"></i></span>
                <span class="qa-card-label">${a.label}</span>
                <span class="qa-card-desc">${a.desc}</span>
            </button>
        `;
    }).join('');
    applyRoleUI(qaEl);
    const visibleCards = qaEl.querySelectorAll('.qa-card:not(.hidden)');
    const parentPanel = qaEl.closest('.panel');
    if (parentPanel) {
        parentPanel.classList.toggle('hidden', visibleCards.length === 0);
    }
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
            <div class="insight-val my-1">${it.value}</div>
            <div class="insight-label text-[10px] text-gray-400 font-medium">Unit</div>
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

let _statusRangeFilter = 'all';

async function setStatusRangeFilter(range) {
    _statusRangeFilter = range || 'all';
    document.querySelectorAll('#statusRangeButtons .status-range-btn').forEach(btn => {
        btn.classList.toggle('is-active', btn.dataset.range === _statusRangeFilter);
    });
    await renderStatusMini();
}
window.setStatusRangeFilter = setStatusRangeFilter;

function goStatusFilter(status) {
    _txStatusFilter = status || '';
    _txPage = 1;
    const sel = document.getElementById('txStatusFilter');
    if (sel) sel.value = _txStatusFilter;
    showTransaksi();
}
window.goStatusFilter = goStatusFilter;

async function statusCounts(range) {
    try {
        const r = range !== undefined ? range : (_statusRangeFilter || 'all');
        const url = r === 'all' ? '/statistics/status' : `/statistics/status?range_type=${encodeURIComponent(r)}`;
        const st = await apiGet(url);
        const byName = {};
        ((st && st.by_status) || []).forEach(r => { byName[r.name] = Number(r.value) || 0; });
        return STATUS_META.map(m => ({ ...m, value: byName[m.name] || 0 }));
    } catch (_) {
        return STATUS_META.map(m => ({ ...m, value: 0 }));
    }
}

async function initCharts() {
    const el = document.querySelector('#chartStatusTransaksi');
    if (!el) return;
    try {
        const co = getCommonOpts();
        const rows = await statusCounts();
        const data = rows.map(s => s.value);
        const max = Math.max(1, ...data);
        const discrete = rows.map((s, i) => ({
            seriesIndex: 0, dataPointIndex: i, fillColor: s.color, strokeColor: isDark() ? '#111118' : '#ffffff', size: 5,
        }));
        statusChart = new ApexCharts(el, {
            ...co,
            chart: { ...co.chart, type: 'area', height: getChartHeight(), toolbar: { show: false }, zoom: { enabled: false } },
            series: [{ name: 'Transaksi', data: data }],
            xaxis: { categories: rows.map(s => s.name), labels: { style: { fontSize: '9px', fontWeight: 600 }, rotate: 0, trim: false } },
            yaxis: { min: 0, max: max + 1, tickAmount: Math.min(max + 1, 7), labels: { style: { fontSize: '10px' } } },
            colors: ['#3b82f6'], stroke: { curve: 'smooth', width: 3 }, markers: { size: 0, strokeWidth: 2, discrete },
        });
        statusChart.render();
    } catch (_) {}
}

function updateChartTheme() {
    if (statusChart && typeof statusChart.updateOptions === 'function') {
        try { statusChart.updateOptions({ theme: { mode: isDark() ? 'dark' : 'light' }, grid: { borderColor: chartGridColor() } }); } catch (_) {}
    }
}

// ─────────────────────────────────────────────
// DASHBOARD ANALYTICS: PIPELINE STATUS SERVIS
// ─────────────────────────────────────────────

async function renderStatusMini() {
    const pipelineEl = document.getElementById('statusPipelineContainer');
    const grid = document.getElementById('statusMiniGrid');
    const banner = document.getElementById('insightStatus');
    const badgeActive = document.getElementById('pipelineActiveBadge');

    const rows = await statusCounts(_statusRangeFilter);
    const total = rows.reduce((a, b) => a + b.value, 0);
    const pctTotal = v => total > 0 ? (v / total * 100).toFixed(1) + '%' : '0.0%';

    // Pipeline Active Status (Dalam Pengerjaan)
    const activeNames = ['DITERIMA', 'ANALISA', 'KONFIRMASI', 'WAIT PART', 'REPAIR'];
    const activeRows = rows.filter(r => activeNames.includes(r.name));
    const totalActive = activeRows.reduce((a, b) => a + b.value, 0);

    if (badgeActive) {
        badgeActive.textContent = `${totalActive} Unit Aktif`;
    }

    // Tentukan Bottleneck (status aktif dengan unit terbanyak > 0)
    const activeSorted = activeRows.filter(r => r.value > 0).sort((a, b) => b.value - a.value);
    const bottleneck = activeSorted.length > 0 ? activeSorted[0] : null;

    if (pipelineEl) {
        if (totalActive === 0) {
            pipelineEl.innerHTML = `<div class="p-3 text-center text-xs text-gray-500 dark:text-gray-400 bg-gray-50/50 dark:bg-white/[0.02] rounded-xl border border-dashed border-gray-200 dark:border-white/10">Tidak ada unit aktif dalam antrian saat ini. Meja teknisi bersih!</div>`;
        } else {
            pipelineEl.innerHTML = activeRows.map(it => {
                const isBottleneck = bottleneck && it.name === bottleneck.name && it.value > 0;
                const pct = totalActive > 0 ? Math.round((it.value / totalActive) * 100) : 0;
                const w = Math.max(3, pct);
                const cardCls = isBottleneck ? 'pipeline-row pipeline-bottleneck' : 'pipeline-row';
                const badgeHtml = isBottleneck
                    ? `<span class="text-[9.5px] px-1.5 py-0.5 rounded font-extrabold bg-amber-200 text-amber-900 dark:bg-amber-900/60 dark:text-amber-200 uppercase tracking-wide">Bottleneck</span>`
                    : '';
                return `
                    <div class="${cardCls}" onclick="goStatusFilter('${escapeHtml(it.name)}')" title="Klik untuk lihat transaksi ${escapeHtml(it.name)}">
                        <div class="flex items-center justify-between mb-1 text-xs">
                            <span class="font-bold text-gray-800 dark:text-gray-100 flex items-center gap-1.5">
                                <i class="fa-solid ${it.icon}" style="color:${it.color}"></i>
                                <span>${it.name}</span>
                                ${badgeHtml}
                            </span>
                            <span class="font-extrabold ${isBottleneck ? 'text-amber-900 dark:text-amber-200' : 'text-gray-900 dark:text-gray-100'}">${it.value} Unit <span class="text-[10px] font-normal text-gray-400">(${pct}%)</span></span>
                        </div>
                        <div class="w-full bg-gray-100 dark:bg-white/10 h-2 rounded-full overflow-hidden">
                            <div class="h-full rounded-full transition-all duration-300" style="width:${w}%; background:${it.color}"></div>
                        </div>
                    </div>
                `;
            }).join('');
        }
    }

    // Mini Grid Status Bawah (9 status lengkap)
    if (grid) {
        grid.innerHTML = rows.map(c => `
            <div class="sm-card ${c.cls} cursor-pointer hover:opacity-90 transition" onclick="goStatusFilter('${escapeHtml(c.name)}')" title="Filter status: ${escapeHtml(c.name)}">
                <div class="sm-top text-[10px] font-bold tracking-wider">${c.name}</div>
                <div class="sm-bot mt-1"><span class="sm-num font-extrabold">${c.value}</span><span class="sm-pct">${pctTotal(c.value)}</span></div>
            </div>
        `).join('');
    }

    // Insight AI Cerdas & Solutif
    if (banner) {
        if (!total) {
            banner.innerHTML = `<span class="insight-ava insight-ava-ai"><i class="fa-solid fa-robot"></i></span>`
                + `<p><b>Insight AI:</b> Belum ada transaksi tercatat pada rentang ini.</p>`
                ;
        } else if (totalActive === 0) {
            banner.innerHTML = `<span class="insight-ava insight-ava-ai"><i class="fa-solid fa-circle-check"></i></span>`
                + `<p><b>Insight AI:</b> Seluruh antrian servis aktif telah terselesaikan. Fokus pada pengujian unit atau follow-up customer.</p>`
                ;
        } else if (bottleneck) {
            let advice = '';
            let btnLabel = `Filter ${bottleneck.name}`;
            if (bottleneck.name === 'WAIT PART') {
                advice = `<b>Perhatian:</b> <b>${bottleneck.value} unit</b> tertahan di <b>WAIT PART</b>. Segera belanja suku cadang atau cek supplier agar durasi servis tidak molor.`;
                btnLabel = 'Filter Wait Part';
            } else if (bottleneck.name === 'KONFIRMASI') {
                advice = `<b>Peluang:</b> <b>${bottleneck.value} unit</b> menunggu persetujuan biaya pelanggan. CS perlu follow-up penawaran agar perbaikan dapat dimulai.`;
                btnLabel = 'Filter Konfirmasi';
            } else if (bottleneck.name === 'REPAIR') {
                advice = `<b>Fokus:</b> <b>${bottleneck.value} unit</b> sedang dalam pengerjaan teknisi. Pastikan perbaikan selesai sesuai estimasi waktu.`;
                btnLabel = 'Filter Repair';
            } else if (bottleneck.name === 'DITERIMA' || bottleneck.name === 'ANALISA') {
                advice = `<b>Antrian:</b> <b>${bottleneck.value} unit</b> menunggu diagnosa awal. Segera periksa kerusakan unit baru.`;
                btnLabel = `Filter ${bottleneck.name}`;
            } else {
                advice = `<b>Insight AI:</b> ${bottleneck.name} mendominasi antrian (${bottleneck.value} unit). Teknisi sedang fokus melakukan pengerjaan.`;
            }
            banner.innerHTML = `<span class="insight-ava insight-ava-ai"><i class="fa-solid fa-lightbulb"></i></span>`
                + `<div class="flex-1"><p>${advice}</p></div>`
                + `<button type="button" class="px-2.5 py-1 rounded-md bg-indigo-600 hover:bg-indigo-700 text-white font-bold text-[10.5px] whitespace-nowrap shadow-xs ml-2" onclick="goStatusFilter('${escapeHtml(bottleneck.name)}')">${btnLabel} <i class="fa-solid fa-arrow-right text-[9px]"></i></button>`;
        }
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
            if (page && page !== 'dashboard' && !bolehBukaHalaman(page)) {
                toast('Halaman ini di luar kewenangan role Anda.');
                return;
            }
            if (page === 'servisbaru') {
                showPage('receive');
            } else if (page === 'penjualanpart') {
                showPenjualanPart();
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
            const page = this.dataset.page;
            if (page && page !== 'dashboard' && !bolehBukaHalaman(page)) {
                toast('Halaman ini di luar kewenangan role Anda.');
                return;
            }
            mobileItems.forEach(i => i.classList.remove('active'));
            this.classList.add('active');
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
    window._currentUser = user;
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
    // Simpan ID user login untuk proteksi hapus akun sendiri
    window._currentUserId = user.id;
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


// ─────────────────────────────────────────────
// STATUS BAR (REAL-TIME ONLINE & TEKNISI AKTIF)
// ─────────────────────────────────────────────

function setOnlineStatus(online) {
    const dot = document.getElementById('sbOnlineDot');
    const txt = document.getElementById('sbOnlineText');
    if (!dot || !txt) return;
    if (online) {
        dot.className = 'w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse';
        txt.textContent = 'Online';
        txt.className = 'text-gray-600 dark:text-gray-400 font-medium';
    } else {
        dot.className = 'w-1.5 h-1.5 rounded-full bg-rose-500';
        txt.textContent = 'Offline';
        txt.className = 'text-rose-600 dark:text-rose-400 font-bold';
    }
}
window.setOnlineStatus = setOnlineStatus;
window.addEventListener('online', () => setOnlineStatus(true));
window.addEventListener('offline', () => setOnlineStatus(false));

async function updateStatusBar() {
    try {
        const techs = await apiGet('/orders/technicians');
        const count = Array.isArray(techs) ? techs.length : 0;
        const el = document.getElementById('sbTeknisiCount');
        if (el) el.textContent = count + ' Orang';
        setOnlineStatus(true);
    } catch (_) {
        if (!navigator.onLine) setOnlineStatus(false);
    }
}
window.updateStatusBar = updateStatusBar;

// ─────────────────────────────────────────────
// NOTIFIKASI & TUGAS TOKO (HEADER BELL HUB)
// ─────────────────────────────────────────────

function toggleHeaderNotif(event) {
    if (event) event.stopPropagation();
    const pop = document.getElementById('headerNotifPop');
    const btn = document.getElementById('headerNotifBtn');
    if (!pop) return;
    const isHidden = pop.classList.contains('hidden');
    if (isHidden) {
        updateHeaderNotif();
        pop.classList.remove('hidden');
        if (btn) btn.setAttribute('aria-expanded', 'true');
    } else {
        closeHeaderNotif();
    }
}
window.toggleHeaderNotif = toggleHeaderNotif;

function closeHeaderNotif() {
    const pop = document.getElementById('headerNotifPop');
    const btn = document.getElementById('headerNotifBtn');
    if (pop) pop.classList.add('hidden');
    if (btn) btn.setAttribute('aria-expanded', 'false');
}
window.closeHeaderNotif = closeHeaderNotif;

document.addEventListener('click', function(e) {
    const pop = document.getElementById('headerNotifPop');
    const btn = document.getElementById('headerNotifBtn');
    if (pop && !pop.classList.contains('hidden')) {
        if (!pop.contains(e.target) && (!btn || !btn.contains(e.target))) {
            closeHeaderNotif();
        }
    }
});

function updateHeaderNotif() {
    const badge = document.getElementById('headerNotifBadge');
    const sumBadge = document.getElementById('headerNotifSummaryBadge');
    const list = document.getElementById('headerNotifList');
    if (!list) return;

    const notifs = [];

    // 1. Peringatan Periode Kas Belum Ditutup (lewat jam 16:00)
    const per = window._lastPeriodData;
    if (per && per.lewat_jam_16) {
        const mulai = (per.start_at || '').replace('T', ' ').slice(0, 16);
        notifs.push({
            id: 'kas_period',
            type: 'danger',
            icon: 'fa-solid fa-clock-rotate-left text-rose-500',
            bg: 'bg-rose-50 dark:bg-rose-950/30 border-rose-200 dark:border-rose-900/40',
            title: 'Periode Kas Belum Ditutup',
            desc: 'Dibuka ' + escapeHtml(mulai) + ' & sudah lewat jam 16:00. Segera tutup kas.',
            actionLabel: 'Buka Keuangan',
            onClick: "showKeuangan(); closeHeaderNotif();"
        });
    }

    // 2. Unit Garansi Berakhir Hari Ini (belum disapa via WA)
    const todayUnits = Array.isArray(window._grAll) ? window._grAll.filter(g => grState(g).key === 'hari_ini') : [];
    const pendingGr = todayUnits.filter(g => !isGrWaDone(g));
    if (pendingGr.length > 0) {
        notifs.push({
            id: 'garansi_pending',
            type: 'warning',
            icon: 'fa-solid fa-shield-halved text-amber-500',
            bg: 'bg-amber-50 dark:bg-amber-950/30 border-amber-200 dark:border-amber-900/40',
            title: pendingGr.length + ' Follow-up Garansi Hari Ini',
            desc: pendingGr.length + ' dari ' + todayUnits.length + ' pelanggan habis garansi belum dihubungi via WA.',
            actionLabel: 'Cek Garansi',
            onClick: "showGaransi(); closeHeaderNotif();"
        });
    }

    // 3. Unit Mengendap Kritis (>60 / >90 Hari)
    const uc = window._lastUnclaimedData;
    const s3 = uc ? (Number(uc.stage_3) || 0) : 0;
    const s4 = uc ? (Number(uc.stage_4) || 0) : 0;
    if (s3 > 0 || s4 > 0) {
        notifs.push({
            id: 'unclaimed_critical',
            type: s4 > 0 ? 'danger' : 'warning',
            icon: 'fa-solid fa-boxes-packing text-orange-500',
            bg: 'bg-orange-50 dark:bg-orange-950/30 border-orange-200 dark:border-orange-900/40',
            title: (s3 + s4) + ' Unit Mengendap Kritis',
            desc: (s4 > 0 ? s4 + ' unit >90H (peringatan final). ' : '') + (s3 > 0 ? s3 + ' unit >60H.' : ''),
            actionLabel: 'Kelola Unit',
            onClick: "showTransaksi(); closeHeaderNotif();"
        });
    }

    // 4. Service Status Aging & Escalation (Status PROSES / Repair)
    const aging = window._lastRepairAgingData;
    if (aging && Array.isArray(aging.items)) {
        const user = window._currentUser;
        const role = (user && user.role) ? String(user.role).trim().toUpperCase() : '';
        const uname = (user && user.username) ? String(user.username).trim().toLowerCase() : '';
        const dname = (user && user.display_name) ? String(user.display_name).trim().toLowerCase() : '';

        const isTeknisi = (role === 'TEKNISI');
        const isKasir = (role === 'KASIR');

        if (isTeknisi) {
            // Level Normal (1-3 hari): On-track, tidak membunyikan lonceng
            // Level Waspada (4-6 hari) & Kritis (>=7 hari): Ditujukan ke teknisi terkait
            const myItems = aging.items.filter(function(it) {
                const t = (it.technician || '').trim().toLowerCase();
                return (t && (t === uname || t === dname));
            });
            const myKritis = myItems.filter(function(it) { return it.level === 'kritis'; });
            const myWaspada = myItems.filter(function(it) { return it.level === 'waspada'; });

            if (myKritis.length > 0) {
                notifs.push({
                    id: 'repair_kritis_teknisi',
                    type: 'danger',
                    icon: 'fa-solid fa-triangle-exclamation text-rose-500',
                    bg: 'bg-rose-50 dark:bg-rose-950/30 border-rose-200 dark:border-rose-900/40',
                    title: myKritis.length + ' Servis Repair Kritis (≥ 7 Hari)',
                    desc: myKritis.map(function(x) { return '#' + x.no_servis; }).slice(0, 3).join(', ') + ' tertahan di meja Anda. Segera update status / koordinasi.',
                    actionLabel: 'Buka Servis',
                    onClick: "showTransaksi(); closeHeaderNotif();"
                });
            }
            if (myWaspada.length > 0) {
                notifs.push({
                    id: 'repair_waspada_teknisi',
                    type: 'warning',
                    icon: 'fa-solid fa-clock-rotate-left text-amber-500',
                    bg: 'bg-amber-50 dark:bg-amber-950/30 border-amber-200 dark:border-amber-900/40',
                    title: myWaspada.length + ' Servis Masuk Hari ke 4–6',
                    desc: myWaspada.map(function(x) { return '#' + x.no_servis; }).slice(0, 3).join(', ') + ' butuh pembaruan progress sebelum ditanyakan CS.',
                    actionLabel: 'Buka Servis',
                    onClick: "showTransaksi(); closeHeaderNotif();"
                });
            }
        } else if (isKasir) {
            // CS / Kasir: Menerima Level Waspada (4-6 hari) dan Kritis (>=7 hari)
            if (aging.kritis_count > 0) {
                notifs.push({
                    id: 'repair_kritis_cs',
                    type: 'danger',
                    icon: 'fa-solid fa-triangle-exclamation text-rose-500',
                    bg: 'bg-rose-50 dark:bg-rose-950/30 border-rose-200 dark:border-rose-900/40',
                    title: aging.kritis_count + ' Unit Repair Kritis (≥ 7 Hari)',
                    desc: aging.kritis_count + ' unit dalam perbaikan >7 hari. Koordinasikan dengan teknisi & pantau komplain.',
                    actionLabel: 'Lihat Servis',
                    onClick: "showTransaksi(); closeHeaderNotif();"
                });
            }
            if (aging.waspada_count > 0) {
                notifs.push({
                    id: 'repair_waspada_cs',
                    type: 'warning',
                    icon: 'fa-solid fa-user-clock text-amber-500',
                    bg: 'bg-amber-50 dark:bg-amber-950/30 border-amber-200 dark:border-amber-900/40',
                    title: aging.waspada_count + ' Unit Repair Waspada (4–6 Hari)',
                    desc: aging.waspada_count + ' unit masuk hari ke 4–6. Siapkan informasi update sebelum pelanggan menanyakan.',
                    actionLabel: 'Lihat Servis',
                    onClick: "showTransaksi(); closeHeaderNotif();"
                });
            }
        } else {
            // Admin / Super Admin: Eskalasi Kritis utama + informasi Waspada
            if (aging.kritis_count > 0) {
                notifs.push({
                    id: 'repair_kritis_admin',
                    type: 'danger',
                    icon: 'fa-solid fa-triangle-exclamation text-rose-500',
                    bg: 'bg-rose-50 dark:bg-rose-950/30 border-rose-200 dark:border-rose-900/40',
                    title: aging.kritis_count + ' Eskalasi Kritis: Repair ≥ 7 Hari',
                    desc: aging.kritis_count + ' unit tertahan seminggu lebih. Butuh peninjauan manajerial / supervisi teknis.',
                    actionLabel: 'Tinjau Unit',
                    onClick: "showTransaksi(); closeHeaderNotif();"
                });
            }
            if (aging.waspada_count > 0) {
                notifs.push({
                    id: 'repair_waspada_admin',
                    type: 'warning',
                    icon: 'fa-solid fa-screwdriver-wrench text-amber-500',
                    bg: 'bg-amber-50 dark:bg-amber-950/30 border-amber-200 dark:border-amber-900/40',
                    title: aging.waspada_count + ' Unit Repair Waspada (4–6 Hari)',
                    desc: aging.waspada_count + ' unit sedang dikerjakan teknisi masuk hari ke 4–6.',
                    actionLabel: 'Lihat Detail',
                    onClick: "showTransaksi(); closeHeaderNotif();"
                });
            }
        }
    }

    const totalCount = notifs.length;
    if (badge) {
        if (totalCount > 0) {
            badge.textContent = totalCount > 99 ? '99+' : totalCount;
            badge.classList.remove('hidden');
        } else {
            badge.textContent = '0';
            badge.classList.add('hidden');
        }
    }

    if (sumBadge) {
        sumBadge.textContent = totalCount > 0 ? (totalCount + ' Perhatian') : 'Beres';
        sumBadge.className = totalCount > 0
            ? 'text-[10px] font-bold px-2 py-0.5 rounded-full bg-rose-100 text-rose-700 dark:bg-rose-950 dark:text-rose-300'
            : 'text-[10px] font-bold px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300';
    }

    // 5. Peringatan Stok Sparepart Menipis / Habis (Aspek B)
    const lowParts = Array.isArray(window._lowStockParts) ? window._lowStockParts : [];
    if (lowParts.length > 0) {
        const habisCount = lowParts.filter(p => (Number(p.stok) || 0) <= 0).length;
        const menipisCount = lowParts.length - habisCount;
        let descTxt = '';
        if (habisCount > 0 && menipisCount > 0) {
            descTxt = habisCount + ' part habis & ' + menipisCount + ' part menipis (<= 3 unit). Segera restock.';
        } else if (habisCount > 0) {
            descTxt = habisCount + ' part stok habis (0 unit). Segera restock.';
        } else {
            descTxt = menipisCount + ' part stok menipis (<= 3 unit). Segera pesan.';
        }
        notifs.push({
            id: 'sparepart_low_stock',
            type: habisCount > 0 ? 'danger' : 'warning',
            icon: 'fa-solid fa-boxes-stacked text-amber-500',
            bg: 'bg-amber-50 dark:bg-amber-950/30 border-amber-200 dark:border-amber-900/40',
            title: lowParts.length + ' Part Perlu Restock',
            desc: descTxt,
            actionLabel: 'Cek Sparepart',
            onClick: "showSparepart(); closeHeaderNotif();"
        });
    }
    if (notifs.length === 0) {
        list.innerHTML = `
            <div class="py-6 px-4 text-center">
                <div class="w-9 h-9 mx-auto mb-2 rounded-full bg-emerald-100 dark:bg-emerald-950/60 text-emerald-600 dark:text-emerald-400 flex items-center justify-center text-sm">
                    <i class="fa-solid fa-check"></i>
                </div>
                <div class="font-bold text-gray-800 dark:text-gray-200 text-xs">Semua Tugas Beres</div>
                <p class="text-[11px] text-gray-500 dark:text-gray-400 mt-0.5">Tidak ada peringatan atau follow-up tertunda saat ini.</p>
            </div>
        `;
    } else {
        list.innerHTML = notifs.map(n => `
            <div class="p-2.5 rounded-lg border transition-all ${n.bg} flex items-start gap-2.5">
                <div class="w-6 h-6 rounded-md bg-white/80 dark:bg-surface-700 flex items-center justify-center flex-shrink-0 text-xs shadow-xs">
                    <i class="${n.icon}"></i>
                </div>
                <div class="flex-1 min-w-0">
                    <div class="font-bold text-gray-800 dark:text-gray-100 text-xs leading-snug">${escapeHtml(n.title)}</div>
                    <div class="text-[11px] text-gray-600 dark:text-gray-300 mt-0.5 leading-snug">${escapeHtml(n.desc)}</div>
                    <div class="mt-2 flex items-center justify-end">
                        <button type="button" onclick="${n.onClick}" class="px-2 py-1 rounded bg-white dark:bg-surface-700 hover:bg-gray-100 dark:hover:bg-white/10 text-gray-700 dark:text-gray-200 text-[10.5px] font-semibold shadow-2xs border border-gray-200 dark:border-white/10 flex items-center gap-1 transition">
                            <span>${escapeHtml(n.actionLabel)}</span>
                            <i class="fa-solid fa-arrow-right text-[9px]"></i>
                        </button>
                    </div>
                </div>
            </div>
        `).join('');
    }
}
window.updateHeaderNotif = updateHeaderNotif;
async function loadLowStockSpareparts() {
    try {
        const data = await apiGet('/spareparts?limit=100');
        if (data && Array.isArray(data.items)) {
            window._lowStockParts = data.items.filter(p => (Number(p.stok) || 0) <= 3);
            if (typeof updateHeaderNotif === 'function') updateHeaderNotif();
        }
    } catch (_) {}
}
window.loadLowStockSpareparts = loadLowStockSpareparts;


async function loadRepairAging() {
    try {
        const data = await apiGet('/orders/repair-aging');
        window._lastRepairAgingData = data;
        updateHeaderNotif();
    } catch (_) {}
}
window.loadRepairAging = loadRepairAging;

async function loadDashboard() {
    try { renderQuickActions(); } catch (_) {}
    await Promise.all([renderStarCards(), renderInsights(), initCharts(), renderStatusMini(), renderDamageSection()]);
    try { await renderDashGaransiTask(); } catch (_) {}
    try { await updateStatusBar(); } catch (_) {}
    try { await loadRepairAging(); } catch (_) {}
    try { await loadLowStockSpareparts(); } catch (_) {}
    try { updateHeaderNotif(); } catch (_) {}
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
let _txStatusFilter = '';
let _txTechFilter = '';
let _txAllOrdersCache = [];

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

async function renderTxKpi() {
    const el = document.getElementById('txKpi');
    if (!el) return;
    let orders = [];
    try {
        orders = (await apiGet('/orders/latest?limit=100')) || [];
    } catch (_) { orders = []; }
    _txAllOrdersCache = orders;

    const total = orders.length;
    const proses = orders.filter(o => ['DITERIMA', 'ANALISA', 'KONFIRMASI', 'REPAIR'].includes((o.status || '').toUpperCase().replace(/\s+/g, '_'))).length;
    const waitPart = orders.filter(o => ['WAIT_PART', 'WAITING_PART', 'MENUNGGU_SPAREPART'].includes((o.status || '').toUpperCase().replace(/\s+/g, '_'))).length;
    const done = orders.filter(o => (o.status || '').toUpperCase() === 'DONE').length;
    const cash = orders.filter(o => (o.status || '').toUpperCase() === 'CASH').length;

    const cards = [
        { key: '', label: 'Total Servis', value: total, unit: 'unit aktif', icon: 'fa-list-check', cls: 'sm-slate' },
        { key: 'PROSES', label: 'Dalam Pengerjaan', value: proses, unit: 'sedang dikerjakan', icon: 'fa-screwdriver-wrench', cls: 'sm-amber' },
        { key: 'WAIT PART', label: 'Menunggu Part', value: waitPart, unit: 'antre sparepart', icon: 'fa-hourglass-half', cls: 'sm-cyan' },
        { key: 'DONE', label: 'Siap Diambil', value: done, unit: 'selesai servis', icon: 'fa-circle-check', cls: 'sm-green' },
        { key: 'CASH', label: 'Cash / Lunas', value: cash, unit: 'lunas periode ini', icon: 'fa-sack-dollar', cls: 'sm-purple' },
    ];

    el.innerHTML = cards.map((c, i) => {
        const isActive = _txStatusFilter === c.key ? ' is-active' : '';
        const spanCls = i === 4 ? ' col-span-2 sm:col-span-1' : '';
        return `
        <div class="sm-card tx-kpi-card ${c.cls}${isActive}${spanCls}" onclick="txKpiClick('${c.key}')" role="button" tabindex="0" title="Klik untuk memfilter: ${c.label}">
            <div class="sm-top"><i class="fa-solid ${c.icon}"></i>${c.label}</div>
            <div class="sm-bot"><span class="sm-num">${c.value}</span><span class="sm-pct">${c.unit}</span></div>
        </div>`;
    }).join('');
}

function txKpiClick(key) {
    if (_txStatusFilter === key) {
        _txStatusFilter = '';
    } else {
        _txStatusFilter = key;
    }
    const sel = document.getElementById('txStatusFilter');
    if (sel) sel.value = _txStatusFilter;
    renderTransaksi();
}

function txResetFilters() {
    _txQuery = '';
    _txDate = '';
    _txStatusFilter = '';
    _txTechFilter = '';
    const q = document.getElementById('txSearch');
    if (q) q.value = '';
    const d = document.getElementById('txDateFilter');
    if (d) d.value = '';
    const st = document.getElementById('txStatusFilter');
    if (st) st.value = '';
    const tc = document.getElementById('txTechFilter');
    if (tc) tc.value = '';
    renderTransaksi();
}

async function loadTxTechnicians() {
    const sel = document.getElementById('txTechFilter');
    if (!sel || sel.options.length > 1) return;
    try {
        const techs = await apiGet('/orders/technicians');
        if (Array.isArray(techs) && techs.length) {
            sel.innerHTML = '<option value="">Semua Teknisi</option>' +
                techs.map(t => `<option value="${escapeHtml(t)}">${escapeHtml(t)}</option>`).join('');
        }
    } catch (_) {}
}

async function txDirectPrint(id) {
    try {
        const o = await apiGet('/orders/' + id);
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
        openNota();
    } catch (err) {
        toast('Gagal mencetak nota: ' + (err.message || 'error'));
    }
}

async function renderTransaksi() {
    try { txMenuClose(); } catch (_) {}
    initTxToolbar();
    loadTxTechnicians();
    renderTxKpi();
    if (_txQuery.trim() || _txDate || _txStatusFilter || _txTechFilter) await loadTxFiltered();
    else await loadTxPage(1);
}

function initTxToolbar() {
    const s = document.getElementById('txSearch');
    const d = document.getElementById('txDateFilter');
    const st = document.getElementById('txStatusFilter');
    const tc = document.getElementById('txTechFilter');
    if (s && !s.dataset.bound) {
        s.dataset.bound = '1';
        let t = null;
        s.addEventListener('input', () => {
            clearTimeout(t);
            t = setTimeout(() => { _txQuery = s.value; renderTransaksi(); }, 300);
        });
    }
    if (d && !d.dataset.bound) {
        d.dataset.bound = '1';
        d.addEventListener('change', () => { _txDate = d.value; renderTransaksi(); });
    }
    if (st && !st.dataset.bound) {
        st.dataset.bound = '1';
        st.addEventListener('change', () => { _txStatusFilter = st.value; renderTransaksi(); });
    }
    if (tc && !tc.dataset.bound) {
        tc.dataset.bound = '1';
        tc.addEventListener('change', () => { _txTechFilter = tc.value; renderTransaksi(); });
    }
}

function txRowHtml(o, num) {
    const cleanPhone = (o.customer_phone || '').replace(/[^0-9]/g, '');
    let waLink = '';
    if (cleanPhone) {
        let intlPhone = cleanPhone;
        if (intlPhone.startsWith('0')) intlPhone = '62' + intlPhone.slice(1);
        const waMsg = encodeURIComponent(`Halo Kak ${o.customer_name || ''}, info servis perangkat ${o.device || ''} (No. Servis: #${o.no_servis || o.id}) di Sukabumi Flasher.`);
        waLink = `<a href="https://wa.me/${intlPhone}?text=${waMsg}" target="_blank" rel="noopener noreferrer" class="inline-flex items-center gap-1 text-[11px] font-semibold text-emerald-600 hover:text-emerald-700 dark:text-emerald-400 mt-0.5" title="Chat WhatsApp"><i class="fa-brands fa-whatsapp"></i> ${escapeHtml(o.customer_phone)}</a>`;
    }

    return `<tr>
        <td class="tx-num">${num}</td>
        <td class="tx-cell-muted tx-nowrap" title="${escapeHtml(o.service_date || '')}">${txDate(o.service_date)}</td>
        <td>
            <div class="flex items-center gap-1.5">
                <span class="font-extrabold text-xs text-brand-600 dark:text-brand-400 font-mono">#${escapeHtml(o.no_servis || String(o.id))}</span>
                <span class="tx-device tx-ellipsis font-bold text-gray-900 dark:text-white" title="${escapeHtml(o.device || '-')}">${escapeHtml(o.device || '-')}</span>
            </div>
        </td>
        <td class="tx-cust">
            <div class="tx-line-main tx-user tx-ellipsis font-bold text-gray-800 dark:text-gray-200" title="${escapeHtml(o.customer_name || '-')}">${escapeHtml(o.customer_name || 'Pelanggan Umum')}</div>
            <div class="tx-line-sub tx-cell-muted tx-ellipsis">${waLink || (escapeHtml(o.customer_phone || '-'))}</div>
        </td>
        <td class="tx-statuscell">${txStatusBadge(o.status)}${(() => {
            if ((o.status === 'DONE' || o.status === 'FAILED') && (!o.unit_status || o.unit_status === 'DI TOKO')) {
                const un = (_unclaimedData && _unclaimedData.items) ? _unclaimedData.items.find(x => x.id === o.id) : null;
                if (un && un.stage >= 1) {
                    const stg = un.stage;
                    const col = stg === 4 ? 'bg-red-500 text-white' : stg === 3 ? 'bg-pink-500 text-white' : stg === 2 ? 'bg-orange-500 text-white' : 'bg-amber-500 text-white';
                    const lbl = stg === 4 ? '90+H' : stg === 3 ? '60H' : stg === 2 ? '30H' : '7H';
                    const isDone = isUnclaimedWaDone(un);
                    return `<button type="button" onclick="event.stopPropagation(); unclaimedWaOpen(${o.id})" class="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-extrabold ${col} hover:opacity-90 shadow-xs ml-1" title="Unit Mengendap ${un.days_pending} Hari (${isDone ? 'Sudah disapa hari ini' : 'Klik untuk Sapa Konsumen'})"><i class="fa-brands fa-whatsapp"></i> ${lbl}${isDone ? ' ✓' : ''}</button>`;
                }
            }
            return '';
        })()}</td>
        <td class="tx-work">
            <div class="tx-line-main tx-user tx-ellipsis font-medium text-gray-800 dark:text-gray-200" title="${escapeHtml(o.damagetype || '-')}">${escapeHtml(o.damagetype || '-')}</div>
            <div class="tx-line-sub tx-cell-muted tx-ellipsis text-xs text-gray-400" title="${escapeHtml(o.repair_plan || '-')}">${escapeHtml(o.repair_plan || '-')}</div>
        </td>
        <td class="tx-cell-muted tx-nowrap" title="${escapeHtml(o.technician || '-')}">
            <span class="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs font-semibold bg-gray-100 dark:bg-white/5 text-gray-700 dark:text-gray-300"><i class="fa-solid fa-user-gear text-[10px] text-brand-500"></i> ${escapeHtml(o.technician || '-')}</span>
        </td>
        <td class="tx-laba tx-nowrap font-bold text-emerald-600 dark:text-emerald-400">${txLaba(o)}</td>
        <td class="tx-sisa tx-nowrap" title="Harga Final - (Modal Part + Jasa + Lain). Tampil hanya setelah status CASH dan modal diisi.">${txSisaModal(o)}</td>
        <td class="tx-aksi text-center">
            <div class="flex items-center justify-center gap-1">
                <button type="button" class="sp-action-btn hover:text-blue-600 hover:bg-blue-50 dark:hover:bg-blue-950/50" onclick="txDetail(${o.id})" title="Lihat Detail Transaksi">
                    <i class="fa-solid fa-eye text-xs"></i>
                </button>
                <button type="button" class="sp-action-btn hover:text-emerald-600 hover:bg-emerald-50 dark:hover:bg-emerald-950/50" onclick="txEdit(${o.id})" title="Update Data Servis & Status">
                    <i class="fa-solid fa-pen-to-square text-xs"></i>
                </button>
                <button type="button" class="sp-action-btn hover:text-purple-600 hover:bg-purple-50 dark:hover:bg-purple-950/50" onclick="txDirectPrint(${o.id})" title="Cetak Nota">
                    <i class="fa-solid fa-print text-xs"></i>
                </button>
                <button type="button" class="sp-action-btn hover:text-rose-600 hover:bg-rose-50 dark:hover:bg-rose-950/50" onclick="txDel(${o.id})" title="Hapus Transaksi" data-cap="ORDER_DELETE">
                    <i class="fa-solid fa-trash text-xs"></i>
                </button>
            </div>
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
            if (_txStatusFilter) {
                const st = (o.status || '').toUpperCase().replace(/\s+/g, '_');
                if (_txStatusFilter === 'PROSES') {
                    if (!['DITERIMA', 'ANALISA', 'KONFIRMASI', 'REPAIR'].includes(st)) return false;
                } else if (_txStatusFilter.replace(/\s+/g, '_') !== st) {
                    return false;
                }
            }
            if (_txTechFilter) {
                if ((o.technician || '').toLowerCase() !== _txTechFilter.toLowerCase()) return false;
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
        applyRoleUI(document.getElementById('pageTransaksi') || document);
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
        applyRoleUI(document.getElementById('pageTransaksi') || document);
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
    try { usPartsLoad(o.id, o.status); } catch (_) {}
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
    L.push('Halo ' + (d.nama || 'Kak') + ',');
    L.push('Unit Anda telah selesai diservis dan diserahkan kepada Anda.');
    L.push('');
    L.push('No. Servis: ' + (d.no || '-'));
    L.push('Perangkat: ' + (d.device || '-'));
    L.push('Biaya Servis: ' + usRupiah(d.final));
    if (d.garansi) L.push('Garansi: ' + d.garansi);
    L.push('');
    L.push('Berikut kami lampirkan Nota Garansi sebagai bukti servis dan informasi masa garansi perangkat Anda.');
    L.push('Silakan simpan nota ini sebagai bukti garansi apabila diperlukan di kemudian hari.');
    L.push('');
    L.push('Terima kasih telah mempercayakan servis perangkat Anda kepada Sukabumi Flasher. 🙏');
    return L.join('\n');
}

function doneWaShow(d, jenis) {
    _doneWaData = d || null;
    _doneWaJenis = (jenis === 'CASH') ? 'CASH' : 'DONE';
    const isCash = _doneWaJenis === 'CASH';
    const judul = document.getElementById('doneWaTitle');
    const sub = document.getElementById('doneWaSub');
    if (judul) judul.innerHTML = isCash ? '<i class="fa-solid fa-shield-halved text-brand-500 mr-1.5"></i> Lengkapi Nota Garansi' : '<i class="fa-solid fa-circle-check text-emerald-500 mr-1.5"></i> Unit Selesai';
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
    if (d === 0) return { key: 'hari_ini', label: 'Habis Hari Ini', days: 0 };
    if (d < 0) return { key: 'expired', label: 'Expired', days: d };
    if (d <= 30) return { key: 'segera', label: 'Akan Berakhir', days: d };
    return { key: 'aktif', label: 'Aktif', days: d };
}

function grStatusBadge(g) {
    const st = grState(g);
    let extra = '';
    if (st.days !== null && st.days !== undefined) {
        if (st.key === 'aktif') extra = ` (${st.days} hr lagi)`;
        else if (st.key === 'segera') extra = ` (${st.days} hr lagi)`;
        else if (st.key === 'expired') extra = ` (${Math.abs(st.days)} hr lalu)`;
    }
    if (st.key === 'aktif') {
        return `<span class="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-400 border border-emerald-200/60 dark:border-emerald-800/40"><span class="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></span>Aktif${escapeHtml(extra)}</span>`;
    }
    if (st.key === 'hari_ini') {
        return `<span class="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-amber-100 text-amber-800 dark:bg-amber-950/60 dark:text-amber-300 border border-amber-300/80 dark:border-amber-700/60"><span class="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse"></span>Habis Hari Ini</span>`;
    }
    if (st.key === 'segera') {
        return `<span class="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-400 border border-amber-200/60 dark:border-amber-800/40"><i class="fa-solid fa-hourglass-half text-[10px]"></i>Akan Berakhir${escapeHtml(extra)}</span>`;
    }
    if (st.key === 'expired') {
        return `<span class="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-rose-50 text-rose-700 dark:bg-rose-950/40 dark:text-rose-400 border border-rose-200/60 dark:border-rose-800/40"><i class="fa-solid fa-circle-xmark text-[10px]"></i>Expired${escapeHtml(extra)}</span>`;
    }
    if (st.key === 'klaim') {
        return `<span class="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-blue-50 text-blue-700 dark:bg-blue-950/40 dark:text-blue-400 border border-blue-200/60 dark:border-blue-800/40"><i class="fa-solid fa-file-circle-check text-[10px]"></i>Sedang Klaim</span>`;
    }
    return `<span class="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300 border border-gray-200 dark:border-gray-700">${escapeHtml(st.label)}</span>`;
}

function grFiltered() {
    const q = _grQuery.trim().toLowerCase();
    return (_grAll || []).filter(g => {
        if (q && ![g.nama, g.phone, g.device, g.no, g.imei, g.brand, g.model].some(f => (f || '').toLowerCase().includes(q))) return false;
        if (_grDate && !(g.mulai <= _grDate && _grDate <= g.akhir)) return false;
        if (_grStatus) {
            const st = grState(g);
            if (_grStatus === 'expired') {
                if (st.key !== 'expired' && st.key !== 'hari_ini') return false;
            } else if (st.key !== _grStatus) {
                return false;
            }
        }
        return true;
    });
}

function grSetFilterStatus(status) {
    const sel = document.getElementById('grStatusFilter');
    if (sel) sel.value = status;
    _grStatus = status;
    _grPage = 1;
    renderGaransi();
}
window.grSetFilterStatus = grSetFilterStatus;

function grResetFilter() {
    const s = document.getElementById('grSearch');
    const d = document.getElementById('grDateFilter');
    const f = document.getElementById('grStatusFilter');
    if (s) s.value = '';
    if (d) d.value = '';
    if (f) f.value = '';
    _grQuery = '';
    _grDate = '';
    _grStatus = '';
    _grPage = 1;
    renderGaransi();
}
window.grResetFilter = grResetFilter;

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
    const n = { total: (_grAll || []).length, aktif: 0, segera: 0, hari_ini: 0, expired: 0, klaim: 0 };
    (_grAll || []).forEach(g => {
        const k = grState(g).key;
        if (k === 'aktif') n.aktif++;
        else if (k === 'hari_ini') { n.hari_ini++; n.expired++; }
        else if (k === 'segera') n.segera++;
        else if (k === 'expired') n.expired++;
        else if (k === 'klaim') n.klaim++;
    });

    updateGrWidgets();
    const cards = [
        { label: 'Total Garansi', value: n.total, icon: 'fa-shield-halved', cls: 'sm-slate', filter: '' },
        { label: 'Garansi Aktif', value: n.aktif, icon: 'fa-circle-check', cls: 'sm-green', filter: 'aktif' },
        { label: 'Akan Berakhir', value: n.segera, icon: 'fa-hourglass-half', cls: 'sm-amber', filter: 'segera' },
        { label: 'Expired', value: n.expired, icon: 'fa-circle-xmark', cls: 'sm-red', filter: 'expired' },
        { label: 'Sedang Klaim', value: n.klaim, icon: 'fa-file-circle-plus', cls: 'sm-blue', filter: 'klaim' },
    ];
    el.innerHTML = cards.map((c, i) => `
        <div class="sm-card ${c.cls}${i === 4 ? ' col-span-2 sm:col-span-1' : ''} cursor-pointer hover:shadow-md transition-all p-3 sm:p-3.5" onclick="grSetFilterStatus('${c.filter}')" title="Klik untuk filter: ${c.label}">
            <div class="sm-top text-xs sm:text-[11.5px]"><i class="fa-solid ${c.icon}"></i> ${c.label}</div>
            <div class="sm-bot mt-1.5"><span class="sm-num text-xl sm:text-2xl font-extrabold">${c.value}</span><span class="sm-pct font-bold text-[10px]">unit</span></div>
        </div>
    `).join('');
}

function grDetail(idx) {
    const g = _grView[idx];
    if (!g) return;
    const st = grState(g);
    document.getElementById('warrantyTitle').textContent = 'Garansi — ' + g.nama;
    document.getElementById('warrantySub').textContent = g.device + ' • ' + st.label;
    const av = akAvatar(g.nama, g.service_order_id || idx);
    document.getElementById('warrantySummary').innerHTML = `
        <div class="panel p-3.5 mb-3 flex items-center justify-between gap-3 flex-wrap bg-gradient-to-r from-gray-50 to-white dark:from-white/5 dark:to-transparent rounded-xl border border-gray-100 dark:border-white/5">
            <div class="flex items-center gap-3">
                <div class="w-10 h-10 rounded-full flex items-center justify-center font-bold text-sm text-white shadow-sm flex-shrink-0 ${av.bg}">
                    ${escapeHtml(av.initials)}
                </div>
                <div>
                    <div class="font-bold text-base text-gray-800 dark:text-gray-100">${escapeHtml(g.nama)}</div>
                    <div class="text-xs text-gray-400 font-mono flex items-center gap-1.5 mt-0.5">
                        <i class="fa-brands fa-whatsapp text-emerald-500"></i> ${escapeHtml(g.phone || '-')}
                        <span class="text-gray-300 dark:text-gray-600">•</span>
                        <span>${escapeHtml(g.device || '-')}</span>
                    </div>
                </div>
            </div>
            <div>${grStatusBadge(g)}</div>
        </div>`;
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

// ─────────────────────────────────────────────
// WHATSAPP AFTER-SALES: GARANSI BERAKHIR
// ─────────────────────────────────────────────

function _grTodayStr() {
    const d = new Date();
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${y}-${m}-${day}`;
}

function getGrWaDoneMap() {
    try {
        const key = 'boss_gr_wa_done_' + _grTodayStr();
        const raw = localStorage.getItem(key);
        return raw ? JSON.parse(raw) : {};
    } catch (_) {
        return {};
    }
}

function setGrWaDone(keyId, isDone) {
    if (!keyId) return;
    try {
        const storageKey = 'boss_gr_wa_done_' + _grTodayStr();
        const map = getGrWaDoneMap();
        if (isDone) {
            map[String(keyId)] = new Date().toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit' });
        } else {
            delete map[String(keyId)];
        }
        localStorage.setItem(storageKey, JSON.stringify(map));
    } catch (_) {}
}

function isGrWaDone(g) {
    if (!g) return false;
    const map = getGrWaDoneMap();
    const k1 = g.no ? String(g.no) : '';
    const k2 = g.service_order_id ? String(g.service_order_id) : '';
    return Boolean((k1 && map[k1]) || (k2 && map[k2]));
}

function getGrWaDoneTime(g) {
    if (!g) return null;
    const map = getGrWaDoneMap();
    const k1 = g.no ? String(g.no) : '';
    const k2 = g.service_order_id ? String(g.service_order_id) : '';
    return (k1 && map[k1]) || (k2 && map[k2]) || null;
}

function toggleGrWaDone(noServis, orderId) {
    const key = noServis || orderId;
    const current = isGrWaDone({ no: noServis, service_order_id: orderId });
    setGrWaDone(key, !current);
    if (orderId && noServis) {
        setGrWaDone(orderId, !current);
    }
    updateGrWidgets();
    const grPage = document.getElementById('pageGaransi');
    if (grPage && !grPage.classList.contains('hidden') && typeof renderGaransi === 'function') {
        renderGaransi();
    }
    toast(!current ? 'Ditandai sudah disapa.' : 'Status sapa garansi dibatalkan.', 'info');
}

window.toggleGrWaDone = toggleGrWaDone;

async function loadWarrantyData(force = false) {
    if (_grAll && _grAll.length > 0 && !force) return _grAll;
    try {
        const data = await apiGet('/claims/warranty-summary');
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
            brand: g.brand,
            model: g.model,
            imei: g.imei,
            teknisi: g.teknisi,
            riwayat_klaim: Array.isArray(g.riwayat_klaim) ? g.riwayat_klaim : [],
        }));
        return _grAll;
    } catch (err) {
        return _grAll || [];
    }
}

function updateGrWidgets(unclaimedData) {
    if (unclaimedData !== undefined) {
        window._lastUnclaimedData = unclaimedData;
    } else {
        unclaimedData = window._lastUnclaimedData;
    }
    const todayUnits = (_grAll || []).filter(g => grState(g).key === 'hari_ini');
    const doneUnits = todayUnits.filter(g => isGrWaDone(g));
    const pendingUnits = todayUnits.filter(g => !isGrWaDone(g));
    const totalToday = todayUnits.length;
    const pendingCount = pendingUnits.length;
    const doneCount = doneUnits.length;

    // Update Priority Hub Unit Mengendap (Tahap 1-4)
    const ucTotal = (unclaimedData && unclaimedData.total) ? Number(unclaimedData.total) : 0;
    const ucProgEl = document.getElementById('dashUnclaimedProgress');
    const ucDescEl = document.getElementById('dashUnclaimedDesc');
    const hubEl = document.getElementById('dashPriorityHub');
    const badgeEl = document.getElementById('dashPriorityBadge');

    if (ucProgEl) ucProgEl.textContent = `${ucTotal} Unit`;
    const c1 = document.getElementById('dashUcCnt1'); if (c1) c1.textContent = unclaimedData ? unclaimedData.stage_1 : 0;
    const c2 = document.getElementById('dashUcCnt2'); if (c2) c2.textContent = unclaimedData ? unclaimedData.stage_2 : 0;
    const c3 = document.getElementById('dashUcCnt3'); if (c3) c3.textContent = unclaimedData ? unclaimedData.stage_3 : 0;
    const c4 = document.getElementById('dashUcCnt4'); if (c4) c4.textContent = unclaimedData ? unclaimedData.stage_4 : 0;

    if (ucDescEl) {
        if (unclaimedData && unclaimedData.stage_4 > 0) {
            ucDescEl.innerHTML = `<span class="font-bold text-rose-700 dark:text-rose-300">${unclaimedData.stage_4} unit >90 hari</span> perlu konfirmasi & peringatan segera.`;
        } else if (unclaimedData && unclaimedData.stage_3 > 0) {
            ucDescEl.innerHTML = `<span class="font-bold text-pink-700 dark:text-pink-300">${unclaimedData.stage_3} unit >60 hari</span> perlu penawaran solusi / pembelian.`;
        } else if (ucTotal > 0) {
            ucDescEl.textContent = `${ucTotal} unit selesai/gagal belum diambil pemilik toko.`;
        } else {
            ucDescEl.textContent = 'Tidak ada unit mengendap tertahan di toko saat ini.';
        }
    }

    if (hubEl) {
        if (!can('ORDER_UPDATE') || (totalToday === 0 && ucTotal === 0)) {
            hubEl.classList.add('hidden');
        } else {
            hubEl.classList.remove('hidden');
            if (badgeEl) {
                if (unclaimedData && unclaimedData.stage_4 > 0) {
                    badgeEl.className = 'text-[10px] px-2 py-0.5 rounded-full font-bold bg-rose-200 text-rose-900 dark:bg-rose-900/60 dark:text-rose-200';
                    badgeEl.textContent = 'Prioritas Kritis (>90H)';
                } else if (pendingCount > 0 || ucTotal > 0) {
                    badgeEl.className = 'text-[10px] px-2 py-0.5 rounded-full font-bold bg-amber-200 text-amber-900 dark:bg-amber-900/60 dark:text-amber-200';
                    badgeEl.textContent = 'Perlu Follow-up';
                } else {
                    badgeEl.className = 'text-[10px] px-2 py-0.5 rounded-full font-bold bg-emerald-100 text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-300';
                    badgeEl.textContent = 'Semua Selesai';
                }
            }
        }
    }

    // 1. Sidebar Nav Badge
    const navBadge = document.getElementById('navGaransiBadge');
    if (navBadge) {
        if (pendingCount > 0) {
            navBadge.textContent = pendingCount;
            navBadge.classList.remove('hidden');
        } else {
            navBadge.classList.add('hidden');
        }
    }

    // 2. Alert on Garansi Page
    const alertEl = document.getElementById('grAlertToday');
    if (alertEl) {
        if (totalToday > 0) {
            alertEl.classList.remove('hidden');
            const tit = document.getElementById('grAlertTitle');
            const desc = document.getElementById('grAlertDesc');
            if (tit) tit.textContent = `Ada ${totalToday} Unit Garansi Berakhir Hari Ini`;
            if (desc) {
                desc.textContent = pendingCount > 0
                    ? `Tersisa ${pendingCount} dari ${totalToday} unit belum di-follow up via WhatsApp.`
                    : `Semua ${totalToday} pelanggan bergaransi habis hari ini telah disapa via WhatsApp.`;
            }
        } else {
            alertEl.classList.add('hidden');
        }
    }

    // 3. Dashboard Task Card
    const taskCard = document.getElementById('dashGaransiTask');
    const taskList = document.getElementById('dashGrList');
    const progressEl = document.getElementById('dashGrProgress');
    if (taskCard && taskList) {
        if (totalToday === 0) {
            taskCard.classList.add('hidden');
            taskList.innerHTML = '';
        } else {
            taskCard.classList.remove('hidden');
            if (progressEl) {
                progressEl.textContent = `${doneCount}/${totalToday} Selesai`;
                if (pendingCount === 0) {
                    progressEl.className = 'text-[10px] px-2 py-0.5 rounded-full font-bold bg-emerald-100 text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-300';
                } else {
                    progressEl.className = 'text-[10px] px-2 py-0.5 rounded-full font-bold bg-amber-200 text-amber-900 dark:bg-amber-900/60 dark:text-amber-200';
                }
            }

            const sorted = [...todayUnits].sort((a, b) => {
                const aDone = isGrWaDone(a) ? 1 : 0;
                const bDone = isGrWaDone(b) ? 1 : 0;
                return aDone - bDone;
            });

            taskList.innerHTML = sorted.map(g => {
                const done = isGrWaDone(g);
                const timeStr = getGrWaDoneTime(g);
                const rowCls = done
                    ? 'bg-white/50 dark:bg-white/[0.02] border-gray-200/60 dark:border-white/5 opacity-75'
                    : 'bg-white dark:bg-surface-800 border-amber-200/80 dark:border-amber-800/40 shadow-xs';
                const nameCls = done
                    ? 'font-medium text-xs text-gray-500 dark:text-gray-400 line-through'
                    : 'font-bold text-xs text-gray-800 dark:text-gray-100';

                return `
                    <div class="flex items-center justify-between flex-wrap gap-2.5 p-2.5 rounded-lg border transition-all ${rowCls}">
                        <div class="flex items-center gap-2.5 min-w-0">
                            <span class="w-6 h-6 rounded-md ${done ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-400' : 'bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300'} flex items-center justify-center text-xs flex-shrink-0">
                                <i class="fa-solid ${done ? 'fa-check' : 'fa-hourglass-end'}"></i>
                            </span>
                            <div class="min-w-0">
                                <div class="flex items-center gap-1.5 flex-wrap">
                                    <span class="${nameCls}">${escapeHtml(g.nama || '-')}</span>
                                    <span class="text-[10.5px] font-mono text-gray-500 dark:text-gray-400">#${escapeHtml(g.no || '-')}</span>
                                    <span class="text-[11px] text-gray-400">&bull; ${escapeHtml(g.device || '-')}</span>
                                </div>
                                <div class="text-[10.5px] text-gray-400 flex items-center gap-2 mt-0.5">
                                    <span><i class="fa-brands fa-whatsapp text-emerald-500"></i> ${escapeHtml(g.phone || 'tanpa no. WA')}</span>
                                    ${done
                                        ? `<span class="text-emerald-600 dark:text-emerald-400 font-semibold"><i class="fa-solid fa-circle-check"></i> Sudah disapa (${escapeHtml(timeStr || 'Hari ini')})</span>`
                                        : `<span class="text-amber-600 dark:text-amber-400 font-semibold"><i class="fa-solid fa-clock"></i> Belum disapa</span>`
                                    }
                                </div>
                            </div>
                        </div>
                        <div class="flex items-center gap-1.5 ml-auto sm:ml-0">
                            <button type="button" onclick="grWaOpenByOrder(${g.service_order_id})" class="px-2.5 py-1 rounded-md ${done ? 'bg-gray-100 hover:bg-emerald-50 hover:text-emerald-700 text-gray-600 dark:bg-white/5 dark:text-gray-300' : 'bg-emerald-600 hover:bg-emerald-700 text-white shadow-xs'} text-xs font-semibold flex items-center gap-1 transition-colors" title="Kirim Pesan WhatsApp">
                                <i class="fa-brands fa-whatsapp"></i>
                                <span>${done ? 'Kirim Ulang' : 'Kirim WA'}</span>
                            </button>
                            <button type="button" onclick="toggleGrWaDone('${escapeHtml(g.no)}', ${g.service_order_id})" class="px-2 py-1 rounded-md text-xs font-medium text-gray-500 hover:text-gray-800 dark:text-gray-400 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-white/5 transition-colors" title="${done ? 'Batalkan status sudah di-WA' : 'Tandai sudah dihubungi tanpa buka WA'}">
                                <i class="fa-solid ${done ? 'fa-rotate-left' : 'fa-check'}"></i>
                                <span>${done ? 'Batal' : 'Tandai'}</span>
                            </button>
                        </div>
                    </div>
                `;
            }).join('');
        }
    }
    try { updateHeaderNotif(); } catch (_) {}
}

async function renderDashGaransiTask() {
    await loadWarrantyData();
    let unclaimedData = null;
    try {
        unclaimedData = await apiGet('/orders/unclaimed');
    } catch (_) {}
    updateGrWidgets(unclaimedData);
}
window.renderDashGaransiTask = renderDashGaransiTask;

function grWaMessage(nama, noServis) {
    const cust = (nama && nama !== '-') ? nama : 'Pelanggan';
    const no = (noServis && noServis !== '-') ? noServis : '-';
    return `Halo Kak ${cust} 👋😊\n\nKami dari Sukabumi Tech Flasher ingin menginformasikan bahwa masa garansi servis perangkat Kakak dengan No. Servis ${no} telah berakhir hari ini.\n\nKami ingin menanyakan, bagaimana kondisi perangkatnya saat ini? Semoga tetap awet dan berfungsi dengan baik ya, Kak. 🙏\n\nApabila setelah masa garansi berakhir terdapat kendala yang sama, jangan sungkan untuk membawa kembali perangkatnya ke toko kami.\n\nJika kendalanya tidak terlalu sulit, kami dengan senang hati akan berusaha memberikan pelayanan ekstra sebagai bentuk apresiasi atas kepercayaan Kakak kepada kami.\n\nTerima kasih telah mempercayakan servis perangkat Kakak kepada Sukabumi Tech Flasher. 😊`;
}

let _grWaData = null;

function grWaOpen(target) {
    let g = null;
    if (typeof target === 'object' && target !== null) {
        g = target;
    } else if (typeof target === 'number') {
        g = _grView[target];
    }
    if (!g) return;
    _grWaData = g;
    const num = notaWaNumber(g.phone);
    const to = document.getElementById('grWaTo');
    if (to) {
        to.innerHTML = `Penerima: <b>${escapeHtml(g.nama || '-')}</b> (${escapeHtml(g.phone || 'tanpa nomor')}) &bull; Unit: <b>${escapeHtml(g.device || '-')}</b> (#${escapeHtml(g.no || '-')})`;
    }
    const prev = document.getElementById('grWaPreview');
    const msg = grWaMessage(g.nama, g.no);
    if (prev) prev.textContent = msg;

    const warn = document.getElementById('grWaWarn');
    const send = document.getElementById('grWaSendBtn');
    if (warn) {
        if (!num) {
            warn.textContent = 'Nomor WhatsApp tidak valid atau belum diisi pada unit ini.';
            warn.classList.remove('hidden');
        } else {
            warn.classList.add('hidden');
        }
    }
    if (send) send.classList.toggle('hidden', !num);
    const pop = document.getElementById('grWaPopup');
    if (pop) pop.classList.remove('hidden');
}

function grWaOpenByOrder(orderId) {
    const g = (_grAll || []).find(x => x.service_order_id === orderId || String(x.no) === String(orderId));
    if (!g) {
        toast('Data servis tidak ditemukan.', 'error');
        return;
    }
    grWaOpen(g);
}

function grWaClose() {
    const pop = document.getElementById('grWaPopup');
    if (pop) pop.classList.add('hidden');
    _grWaData = null;
}

function grWaSend() {
    const g = _grWaData;
    if (!g) return;
    const num = notaWaNumber(g.phone);
    if (!num) {
        toast('Nomor WhatsApp tidak valid atau belum diisi.', 'error');
        return;
    }
    const msg = grWaMessage(g.nama, g.no);
    try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(msg);
        }
    } catch (_) {}
    window.open('https://wa.me/' + num + '?text=' + encodeURIComponent(msg), '_blank');
    grWaClose();
    setGrWaDone(g.no || g.service_order_id, true);
    updateGrWidgets();
    const grPage = document.getElementById('pageGaransi');
    if (grPage && !grPage.classList.contains('hidden') && typeof renderGaransi === 'function') {
        renderGaransi();
    }
    toast('Membuka WhatsApp untuk Kak ' + (g.nama || 'Pelanggan'), 'success');
}

window.grWaOpen = grWaOpen;
window.grWaOpenByOrder = grWaOpenByOrder;
window.grWaClose = grWaClose;
window.grWaSend = grWaSend;
window.grWaMessage = grWaMessage;

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
        await loadWarrantyData(true);
        if (my !== _grReq) return; // respons basi — ada request lebih baru
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
        const av = akAvatar(g.nama, g.service_order_id || idx);
        const tr = document.createElement('tr');
        tr.className = 'tx-row';
        tr.innerHTML = `
            <td class="text-center text-xs text-gray-400 font-mono">${idx + 1}</td>
            <td>
                <div class="flex items-center gap-2.5">
                    <div class="w-8 h-8 rounded-full flex items-center justify-center font-bold text-xs text-white shadow-sm flex-shrink-0 ${av.bg}">
                        ${escapeHtml(av.initials)}
                    </div>
                    <div class="min-w-0">
                        <div class="font-semibold text-sm text-gray-800 dark:text-gray-100 truncate" title="${escapeHtml(g.nama)}">${escapeHtml(g.nama)}</div>
                        <div class="text-xs text-gray-400 dark:text-gray-500 font-mono flex items-center gap-1">
                            <i class="fa-brands fa-whatsapp text-emerald-500 text-[11px]"></i>
                            <span>${escapeHtml(g.phone || '-')}</span>
                        </div>
                    </div>
                </div>
            </td>
            <td>
                <div class="font-semibold text-sm text-gray-800 dark:text-gray-200 truncate" title="${escapeHtml(g.device || '-')}">
                    ${escapeHtml(g.device || '-')}
                </div>
                <div class="text-[11px] text-gray-400 flex items-center gap-1.5 flex-wrap mt-0.5">
                    <span class="px-1.5 py-0.2 rounded text-[10px] bg-gray-100 dark:bg-white/5 font-mono text-gray-600 dark:text-gray-300 border border-gray-200 dark:border-white/5">#${escapeHtml(g.no || '-')}</span>
                    ${g.imei ? `<span class="text-[10px] text-gray-400 truncate max-w-[130px]">IMEI: ${escapeHtml(g.imei)}</span>` : ''}
                </div>
            </td>
            <td class="text-center">
                <div class="text-xs font-semibold text-gray-700 dark:text-gray-200">${txDate(g.mulai)} &rarr; ${txDate(g.akhir)}</div>
                ${g.teknisi ? `<div class="text-[10.5px] text-gray-400 mt-0.5"><i class="fa-solid fa-user-gear text-[9.5px]"></i> ${escapeHtml(g.teknisi)}</div>` : ''}
            </td>
            <td class="text-center">
                ${grStatusBadge(g)}
                ${(grState(g).key === 'hari_ini' && isGrWaDone(g)) ? `<div class="mt-1 text-[10px] font-semibold text-emerald-600 dark:text-emerald-400 flex items-center justify-center gap-1"><i class="fa-solid fa-circle-check"></i> Sudah Disapa (${getGrWaDoneTime(g) || 'Hari ini'})</div>` : ''}
            </td>
            <td class="text-center">
                <div class="inline-flex items-center justify-center gap-1">
                    <button type="button" class="w-7 h-7 inline-flex items-center justify-center rounded-lg bg-gray-100 hover:bg-brand-50 hover:text-brand-600 dark:bg-white/5 dark:hover:bg-brand-500/20 dark:hover:text-brand-300 text-gray-500 transition-colors" title="Lihat Detail Garansi" onclick="grDetail(${idx})">
                        <i class="fa-solid fa-eye text-xs"></i>
                    </button>
                    <button type="button" class="w-7 h-7 inline-flex items-center justify-center rounded-lg bg-gray-100 hover:bg-amber-50 hover:text-amber-600 dark:bg-white/5 dark:hover:bg-amber-500/20 dark:hover:text-amber-300 text-gray-500 transition-colors" title="Ajukan Klaim Garansi" onclick="grClaim(${idx})">
                        <i class="fa-solid fa-file-circle-plus text-xs"></i>
                    </button>
                    <button type="button" class="w-7 h-7 inline-flex items-center justify-center rounded-lg ${isGrWaDone(g) ? 'bg-emerald-600 text-white' : 'bg-emerald-50 hover:bg-emerald-100 text-emerald-600 dark:bg-emerald-950/40 dark:hover:bg-emerald-900/60 dark:text-emerald-400'} transition-colors" title="${isGrWaDone(g) ? 'Sudah di-WA (klik untuk kirim ulang)' : 'Kirim WA Sapa Garansi Berakhir'}" onclick="grWaOpen(${idx})">
                        <i class="fa-brands fa-whatsapp text-xs"></i>
                    </button>
                </div>
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

function plResetFilter() {
    const s = document.getElementById('plSearch');
    const d = document.getElementById('plDateFilter');
    if (s) s.value = '';
    if (d) d.value = '';
    _plQuery = '';
    _plDate = '';
    loadPlPage(1);
}
window.plResetFilter = plResetFilter;

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
            const av = akAvatar(c.name || '?', c.id || id);
            summary.innerHTML = `
                <div class="panel p-3.5 mb-3 flex items-center justify-between gap-3 flex-wrap bg-gradient-to-r from-gray-50 to-white dark:from-white/5 dark:to-transparent rounded-xl border border-gray-100 dark:border-white/5">
                    <div class="flex items-center gap-3">
                        <div class="w-10 h-10 rounded-full flex items-center justify-center font-bold text-sm text-white shadow-sm flex-shrink-0 ${av.bg}">
                            ${escapeHtml(av.initials)}
                        </div>
                        <div>
                            <div class="font-bold text-base text-gray-800 dark:text-gray-100">${escapeHtml(c.name || '-')}</div>
                            <div class="text-xs text-gray-400 font-mono flex items-center gap-1.5 mt-0.5">
                                <i class="fa-brands fa-whatsapp text-emerald-500"></i> ${escapeHtml(c.phone || '-')}
                            </div>
                        </div>
                    </div>
                    <div class="flex items-center gap-2 flex-wrap">
                        <span class="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-semibold bg-gray-100 dark:bg-white/5 text-gray-700 dark:text-gray-300 border border-gray-200 dark:border-white/5">
                            <i class="fa-solid fa-mobile-screen text-brand-500 text-[11px]"></i> ${d.device_count} device
                        </span>
                        <span class="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-semibold bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-400 border border-emerald-200/60 dark:border-emerald-800/40">
                            <i class="fa-solid fa-receipt text-[11px]"></i> ${d.total_servis}× servis
                        </span>
                        <span class="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-bold bg-blue-50 text-blue-700 dark:bg-blue-950/40 dark:text-blue-400 border border-blue-200/60 dark:border-blue-800/40">
                            ${plRupiah(d.total_nilai)}
                        </span>
                    </div>
                </div>`;
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
                    <td class="tx-statuscell">${txStatusBadge(o.status)}${(() => {
            if ((o.status === 'DONE' || o.status === 'FAILED') && (!o.unit_status || o.unit_status === 'DI TOKO')) {
                const un = (_unclaimedData && _unclaimedData.items) ? _unclaimedData.items.find(x => x.id === o.id) : null;
                if (un && un.stage >= 1) {
                    const stg = un.stage;
                    const col = stg === 4 ? 'bg-red-500 text-white' : stg === 3 ? 'bg-pink-500 text-white' : stg === 2 ? 'bg-orange-500 text-white' : 'bg-amber-500 text-white';
                    const lbl = stg === 4 ? '90+H' : stg === 3 ? '60H' : stg === 2 ? '30H' : '7H';
                    const isDone = isUnclaimedWaDone(un);
                    return `<button type="button" onclick="event.stopPropagation(); unclaimedWaOpen(${o.id})" class="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-extrabold ${col} hover:opacity-90 shadow-xs ml-1" title="Unit Mengendap ${un.days_pending} Hari (${isDone ? 'Sudah disapa hari ini' : 'Klik untuk Sapa Konsumen'})"><i class="fa-brands fa-whatsapp"></i> ${lbl}${isDone ? ' ✓' : ''}</button>`;
                }
            }
            return '';
        })()}</td>
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
            const av = akAvatar(c.name || '?', c.id || (start + i));
            const tr = document.createElement('tr');
            tr.className = 'tx-row';
            const totalSrv = Number(c.total_servis) || 0;
            const loyaltyBadge = totalSrv > 1
                ? `<span class="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-400 border border-emerald-200/60 dark:border-emerald-800/40" title="Pelanggan setia (${totalSrv}x servis)"><i class="fa-solid fa-star text-amber-500 text-[10px]"></i> ${totalSrv}x Servis</span>`
                : (totalSrv === 1
                    ? `<span class="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[11px] font-medium bg-gray-100 text-gray-600 dark:bg-white/10 dark:text-gray-300 border border-gray-200 dark:border-white/5">1x Servis</span>`
                    : `<span class="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[11px] font-medium bg-gray-50 text-gray-400 dark:bg-white/5 dark:text-gray-500 border border-gray-100 dark:border-white/5">Baru</span>`);

            tr.innerHTML = `
                <td class="text-center text-xs text-gray-400 font-mono">${start + i + 1}</td>
                <td>
                    <div class="flex items-center gap-2.5">
                        <div class="w-8 h-8 rounded-full flex items-center justify-center font-bold text-xs text-white shadow-sm flex-shrink-0 ${av.bg}">
                            ${escapeHtml(av.initials)}
                        </div>
                        <div class="min-w-0">
                            <div class="font-semibold text-sm text-gray-800 dark:text-gray-100 truncate" title="${escapeHtml(c.name || '-')}">${escapeHtml(c.name || '-')}</div>
                            <div class="text-xs text-gray-400 dark:text-gray-500 font-mono flex items-center gap-1 mt-0.5">
                                <i class="fa-brands fa-whatsapp text-emerald-500 text-[11px]"></i>
                                <span>${escapeHtml(c.phone || '-')}</span>
                            </div>
                        </div>
                    </div>
                </td>
                <td>
                    <div class="font-semibold text-sm text-gray-800 dark:text-gray-200 truncate" title="${escapeHtml(c.last_device || '-')}">
                        ${escapeHtml(c.last_device || '-')}
                    </div>
                    <div class="text-xs text-gray-400 dark:text-gray-500 truncate max-w-xs mt-0.5" title="${escapeHtml(c.last_action || '-')}">
                        ${escapeHtml(c.last_action || 'Belum ada servis')}
                    </div>
                </td>
                <td class="text-right">
                    <div class="font-semibold text-sm text-gray-800 dark:text-gray-100">${c.last_price ? plRupiah(c.last_price) : '-'}</div>
                    <div class="text-[11px] text-gray-400 dark:text-gray-500 flex items-center justify-end gap-1 mt-0.5">
                        <i class="fa-regular fa-calendar text-[10px]"></i>
                        <span>${c.last_at ? txDate(c.last_at) : '-'}</span>
                    </div>
                </td>
                <td class="text-center">${loyaltyBadge}</td>
                <td class="text-center">
                    <div class="inline-flex items-center justify-center gap-1">
                        <button type="button" class="w-7 h-7 inline-flex items-center justify-center rounded-lg bg-gray-100 hover:bg-brand-50 hover:text-brand-600 dark:bg-white/5 dark:hover:bg-brand-500/20 dark:hover:text-brand-300 text-gray-500 transition-colors" title="Riwayat Servis Pelanggan" onclick="plDetailOpen(${c.id}, true)">
                            <i class="fa-solid fa-clock-rotate-left text-xs"></i>
                        </button>
                        <button type="button" class="w-7 h-7 inline-flex items-center justify-center rounded-lg bg-gray-100 hover:bg-emerald-50 hover:text-emerald-600 dark:bg-white/5 dark:hover:bg-emerald-500/20 dark:hover:text-emerald-300 text-gray-500 transition-colors" title="Servis Baru untuk Pelanggan ini" onclick="plServisBaru(${c.id})">
                            <i class="fa-solid fa-plus text-xs"></i>
                        </button>
                        <button type="button" class="w-7 h-7 inline-flex items-center justify-center rounded-lg bg-gray-100 hover:bg-amber-50 hover:text-amber-600 dark:bg-white/5 dark:hover:bg-amber-500/20 dark:hover:text-amber-300 text-gray-500 transition-colors" title="Edit Data Pelanggan" onclick="plEditOpen(${c.id})">
                            <i class="fa-solid fa-pen-to-square text-xs"></i>
                        </button>
                        ${totalSrv === 0 ? `
                        <button type="button" class="w-7 h-7 inline-flex items-center justify-center rounded-lg bg-gray-100 hover:bg-rose-50 hover:text-rose-600 dark:bg-white/5 dark:hover:bg-rose-500/20 dark:hover:text-rose-300 text-gray-500 transition-colors" title="Hapus Pelanggan" onclick="plDelete(${c.id})">
                            <i class="fa-solid fa-trash text-xs"></i>
                        </button>` : ''}
                    </div>
                </td>
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
let _spStockFilter = 'all';
let _spCatFilter = '';
let _spBrandFilter = '';
let _spActiveSubTab = 'catalog';
let _spSummaryVisible = true;
let _spViewMode = (function() {
    try { return localStorage.getItem('sp_view_mode') || 'table'; } catch(_) { return 'table'; }
})();
let _spReq = 0;
let _spEditId = -1;
// State real dari backend (GET/POST/PUT/DELETE /api/spareparts). SP_MOCK dipensiunkan.
let _spView = [];
let _spExpandedKeys = new Set();
let _spAllExpanded = false;

function spCategoryMeta(cat) {
    const c = (cat || '').toUpperCase();
    if (c.includes('LCD') || c.includes('LAYAR') || c.includes('SCREEN') || c.includes('TOUCH')) {
        return { icon: 'fa-mobile-screen', bg: 'bg-blue-50 text-blue-600 dark:bg-blue-950/50 dark:text-blue-400 border-blue-200 dark:border-blue-900/50' };
    }
    if (c.includes('BAT')) {
        return { icon: 'fa-battery-half', bg: 'bg-emerald-50 text-emerald-600 dark:bg-emerald-950/50 dark:text-emerald-400 border-emerald-200 dark:border-emerald-900/50' };
    }
    if (c.includes('FLEX') || c.includes('KONEK') || c.includes('CONN') || c.includes('PORT') || c.includes('PLUG') || c.includes('CAS')) {
        return { icon: 'fa-plug', bg: 'bg-violet-50 text-violet-600 dark:bg-violet-950/50 dark:text-violet-400 border-violet-200 dark:border-violet-900/50' };
    }
    if (c.includes('KAM') || c.includes('CAM')) {
        return { icon: 'fa-camera', bg: 'bg-cyan-50 text-cyan-600 dark:bg-cyan-950/50 dark:text-cyan-400 border-cyan-200 dark:border-cyan-900/50' };
    }
    if (c.includes('IC') || c.includes('CHIP') || c.includes('MESIN') || c.includes('CPU') || c.includes('NAND')) {
        return { icon: 'fa-microchip', bg: 'bg-amber-50 text-amber-600 dark:bg-amber-950/50 dark:text-amber-400 border-amber-200 dark:border-amber-900/50' };
    }
    if (c.includes('SPEAK') || c.includes('BUZZ') || c.includes('MIC') || c.includes('SUARA')) {
        return { icon: 'fa-volume-high', bg: 'bg-rose-50 text-rose-600 dark:bg-rose-950/50 dark:text-rose-400 border-rose-200 dark:border-rose-900/50' };
    }
    if (c.includes('CASE') || c.includes('BACK') || c.includes('HOUSING') || c.includes('FRAME')) {
        return { icon: 'fa-shield', bg: 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300 border-slate-200 dark:border-slate-700' };
    }
    return { icon: 'fa-box-archive', bg: 'bg-brand-50 text-brand-600 dark:bg-brand-950/50 dark:text-brand-400 border-brand-200 dark:border-brand-900/50' };
}

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
        toast('Sparepart berhasil dihapus.', 'success');
        renderSparepart();
    } catch (err) {
        toast(err.message || 'Gagal menghapus.');
    }
}

function spQuickRestock(id) {
    const s = (_spView || []).find(x => x && x.id === id);
    if (!s) return;
    const sel = document.getElementById('spMovePart');
    if (sel) {
        sel.value = String(id);
    }
    const qtyInput = document.getElementById('spMoveQty');
    if (qtyInput) {
        qtyInput.value = '1';
        qtyInput.focus();
    }
    const section = document.getElementById('spMoveSection');
    if (section) {
        section.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
    toast('Siap catat stok masuk untuk ' + s.jenis + '.', 'info');
}

// ── P2-12: pergerakan stok (barang masuk + riwayat) ──

// ============================================================================
// KLAIM RETUR SUPPLIER (GARANSI PART CACAT PABRIK)
// ============================================================================
let _spDefectsList = [];
let _spDefectFilter = 'ALL';

async function loadSparepartDefects() {
    const tbody = document.getElementById('spDefectBody');
    if (!tbody) return;

    tbody.innerHTML = '<tr><td colspan="7" class="text-center text-xs text-gray-400 py-6"><i class="fa-solid fa-circle-notch fa-spin"></i> Memuat data retur...</td></tr>';

    try {
        const res = await apiGet('/inventory/defects?status=' + (_spDefectFilter || 'ALL'));
        _spDefectsList = res.items || [];

        const countBadge = document.getElementById('spDefectCountBadge');
        if (countBadge) {
            const pendingCount = _spDefectsList.filter(d => d.status === 'MENUNGGU' || d.status === 'DIKIRIM').length;
            if (pendingCount > 0) {
                countBadge.textContent = pendingCount;
                countBadge.classList.remove('hidden');
            } else {
                countBadge.classList.add('hidden');
            }
        }

        if (!_spDefectsList.length) {
            tbody.innerHTML = '<tr><td colspan="7" class="text-center text-xs text-gray-400 py-6"><i class="fa-solid fa-box-open text-2xl mb-1.5 block opacity-40"></i>Tidak ada data klaim retur supplier.</td></tr>';
            return;
        }

        tbody.innerHTML = _spDefectsList.map(d => {
            let badge = '';
            if (d.status === 'MENUNGGU') {
                badge = '<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-bold bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-400 border border-amber-200 dark:border-amber-800/40"><i class="fa-solid fa-hourglass-half text-[9px]"></i> Menunggu</span>';
            } else if (d.status === 'DIKIRIM') {
                badge = '<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-bold bg-blue-50 text-blue-700 dark:bg-blue-950/40 dark:text-blue-400 border border-blue-200 dark:border-blue-800/40"><i class="fa-solid fa-truck text-[9px]"></i> Dikirim</span>';
            } else if (d.status === 'GANTI_BARANG') {
                badge = '<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-bold bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-800/40"><i class="fa-solid fa-check text-[9px]"></i> Ganti Unit</span>';
            } else if (d.status === 'POTONG_NOTA') {
                badge = '<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-bold bg-purple-50 text-purple-700 dark:bg-purple-950/40 dark:text-purple-400 border border-purple-200 dark:border-purple-800/40"><i class="fa-solid fa-receipt text-[9px]"></i> Potong Nota</span>';
            } else if (d.status === 'DITOLAK') {
                badge = '<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-bold bg-red-50 text-red-700 dark:bg-red-950/40 dark:text-red-400 border border-red-200 dark:border-red-800/40"><i class="fa-solid fa-xmark text-[9px]"></i> Ditolak</span>';
            }

            let aksiBtns = '';
            if (d.status === 'MENUNGGU') {
                aksiBtns = `
                    <div class="flex items-center justify-center gap-1">
                        <button type="button" onclick="spUpdateDefectStatus(${d.id}, 'DIKIRIM')" class="px-2 py-1 rounded bg-blue-50 hover:bg-blue-100 text-blue-700 dark:bg-blue-950/50 dark:text-blue-300 text-[11px] font-semibold border border-blue-200 dark:border-blue-800" title="Ubah status menjadi sedang dibawa/dikirim ke supplier">
                            <i class="fa-solid fa-paper-plane"></i> Kirim
                        </button>
                        <button type="button" onclick="spOpenResolveModal(${d.id})" class="px-2 py-1 rounded bg-emerald-50 hover:bg-emerald-100 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300 text-[11px] font-semibold border border-emerald-200 dark:border-emerald-800" title="Selesaikan klaim retur">
                            <i class="fa-solid fa-handshake"></i> Solusi
                        </button>
                    </div>`;
            } else if (d.status === 'DIKIRIM') {
                aksiBtns = `
                    <div class="flex items-center justify-center">
                        <button type="button" onclick="spOpenResolveModal(${d.id})" class="px-2.5 py-1 rounded bg-emerald-50 hover:bg-emerald-100 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300 text-[11px] font-semibold border border-emerald-200 dark:border-emerald-800" title="Selesaikan klaim retur">
                            <i class="fa-solid fa-handshake"></i> Selesaikan
                        </button>
                    </div>`;
            } else {
                aksiBtns = `<span class="text-[10.5px] text-gray-400 font-mono">${escapeHtml(d.resolved_at ? d.resolved_at.slice(0, 10) : 'Selesai')}</span>`;
            }

            return `<tr>
                <td>
                    <div class="font-mono font-bold text-gray-800 dark:text-gray-100">${escapeHtml(d.no_retur)}</div>
                    <div class="text-[10px] text-gray-400">${escapeHtml(d.created_at)}</div>
                </td>
                <td class="max-w-[200px]">
                    <div class="font-medium text-gray-900 dark:text-gray-100 truncate" title="${escapeHtml(d.sparepart_label)}">${escapeHtml(d.sparepart_label)}</div>
                    <div class="text-[10.5px] text-brand-600 dark:text-brand-400 font-medium">Supplier: ${escapeHtml(d.supplier || '-')}</div>
                </td>
                <td class="text-center font-bold text-gray-800 dark:text-gray-200">${d.qty}</td>
                <td class="text-right font-mono font-bold text-gray-900 dark:text-white">Rp ${Number(d.total_modal || 0).toLocaleString('id-ID')}</td>
                <td class="max-w-[200px]">
                    <div class="text-xs text-red-600 dark:text-red-400 font-medium truncate" title="${escapeHtml(d.alasan_cacat)}">${escapeHtml(d.alasan_cacat)}</div>
                    ${d.no_servis ? `<div class="text-[10px] text-gray-400 font-mono">Unit: #${escapeHtml(d.no_servis)} • ${escapeHtml(d.oleh || '')}</div>` : `<div class="text-[10px] text-gray-400">Stok Toko • ${escapeHtml(d.oleh || '')}</div>`}
                </td>
                <td class="text-center">${badge}</td>
                <td class="text-center" data-cap="SPAREPART_WRITE">${aksiBtns}</td>
            </tr>`;
        }).join('');
    } catch (err) {
        tbody.innerHTML = '<tr><td colspan="7" class="text-center text-xs text-red-400 py-6">Gagal memuat klaim retur: ' + escapeHtml(err.message || 'Error') + '</td></tr>';
    }
}

function spFilterDefects(status) {
    _spDefectFilter = status;
    const chips = document.querySelectorAll('.sp-defect-chip');
    chips.forEach(btn => {
        btn.classList.toggle('active', btn.getAttribute('data-status') === status);
    });
    loadSparepartDefects();
}

async function spUpdateDefectStatus(defectId, newStatus) {
    if (!confirm('Ubah status barang retur ini menjadi SEDANG DIKIRIM ke supplier?')) return;
    try {
        await apiPut(`/inventory/defects/${defectId}/status`, { status: newStatus });
        await loadSparepartDefects();
        if (typeof showToast === 'function') showToast('Status retur berhasil diperbarui ke DIKIRIM.', 'success');
    } catch (err) {
        alert('Gagal update status: ' + (err.message || 'Error'));
    }
}

function spOpenResolveModal(defectId) {
    const item = _spDefectsList.find(d => d.id === defectId);
    if (!item) return;

    document.getElementById('resolveDefectId').value = defectId;
    document.getElementById('resolveDefectInfo').innerHTML = `
        <div class="font-bold text-gray-800 dark:text-gray-100">${escapeHtml(item.no_retur)} — ${escapeHtml(item.sparepart_label)}</div>
        <div class="text-[11px] text-gray-500 mt-1">Supplier: <b>${escapeHtml(item.supplier)}</b> • Modal: <b>Rp ${Number(item.total_modal || 0).toLocaleString('id-ID')}</b></div>
        <div class="text-[11px] text-red-500 mt-0.5">Gejala Cacat: ${escapeHtml(item.alasan_cacat)}</div>
    `;
    document.getElementById('resolveChoice').value = 'GANTI_BARANG';
    document.getElementById('resolveNote').value = '';
    spOnResolveChoiceChanged();
    document.getElementById('modalResolveDefect').classList.remove('hidden');
}

function spCloseResolveModal() {
    const m = document.getElementById('modalResolveDefect');
    if (m) m.classList.add('hidden');
}

function spOnResolveChoiceChanged() {
    const choice = document.getElementById('resolveChoice').value;
    const noteEl = document.getElementById('resolveImpactNote');
    if (!noteEl) return;

    if (choice === 'GANTI_BARANG') {
        noteEl.className = 'text-xs p-2.5 rounded-lg bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-800 text-emerald-800 dark:text-emerald-300';
        noteEl.innerHTML = '<i class="fa-solid fa-boxes-stacked mr-1"></i> <b>Ganti Unit Fisik Baru</b>: Stok fisik rak toko otomatis bertambah kembali (+1 pcs) tanpa pengeluaran kas baru.';
    } else if (choice === 'POTONG_NOTA') {
        noteEl.className = 'text-xs p-2.5 rounded-lg bg-purple-50 dark:bg-purple-950/40 border border-purple-200 dark:border-purple-800 text-purple-800 dark:text-purple-300';
        noteEl.innerHTML = '<i class="fa-solid fa-receipt mr-1"></i> <b>Potong Nota Belanja / Kas</b>: Supplier memotong nilai modal pada nota belanja berikutnya atau mengembalikan uang kas modal. Stok fisik tidak bertambah.';
    } else if (choice === 'DITOLAK') {
        noteEl.className = 'text-xs p-2.5 rounded-lg bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-800 text-red-800 dark:text-red-300';
        noteEl.innerHTML = '<i class="fa-solid fa-triangle-exclamation mr-1"></i> <b>Klaim Ditolak Supplier</b>: Dicatat resmi sebagai kerugian barang rusak / write-off toko.';
    }
}

async function spSubmitResolveDefect(event) {
    event.preventDefault();
    const defectId = parseInt(document.getElementById('resolveDefectId').value, 10);
    const resolusi = document.getElementById('resolveChoice').value;
    const note = document.getElementById('resolveNote').value.trim() || null;

    const btn = document.getElementById('btnSubmitResolve');
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i> Menyimpan...';
    }

    try {
        await apiPost(`/inventory/defects/${defectId}/resolve`, { resolusi, note });
        spCloseResolveModal();
        await loadSparepartDefects();
        await loadSparepartMoves(); try { await loadSparepartDefects(); } catch (_) {}
        if (typeof renderSparepart === 'function') await renderSparepart();
        if (typeof showToast === 'function') {
            showToast('Klaim retur berhasil diselesaikan!', 'success');
        } else {
            alert('Klaim retur berhasil diselesaikan!');
        }
    } catch (err) {
        alert('Gagal menyelesaikan klaim retur: ' + (err.message || 'Error'));
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '<i class="fa-solid fa-check"></i> Simpan Penyelesaian';
        }
    }
}

async function loadRevolvingFundSummary() {
    const panel = document.getElementById('spRevolvingFundPanel');
    if (!panel) return;

    try {
        const res = await apiGet('/spareparts/revolving-fund/summary');
        const setVal = (id, val) => {
            const el = document.getElementById(id);
            if (el) el.textContent = val;
        };

        setVal('rfModalDisetor', spRupiah(res.total_modal_disetor || 0));
        setVal('rfModalServis', spRupiah(res.modal_disetor_servis || 0));
        setVal('rfModalPos', spRupiah(res.modal_disetor_penjualan || 0));
        setVal('rfBelanjaBatch', spRupiah(res.total_belanja_pengadaan || 0));
        setVal('rfValuasiStok', spRupiah(res.valuasi_stok_aktif || 0));
        setVal('rfTotalStokUnit', Number(res.total_stok_fisik_unit || 0).toLocaleString('id-ID'));

        const saldoEl = document.getElementById('rfSaldoKasPart');
        if (saldoEl) {
            const s = Number(res.sisa_dana_kas_part || 0);
            saldoEl.textContent = spRupiah(s);
            if (s < 0) {
                saldoEl.className = 'text-base sm:text-lg font-bold text-amber-600 dark:text-amber-400 font-mono mt-0.5';
            } else {
                saldoEl.className = 'text-base sm:text-lg font-bold text-purple-600 dark:text-purple-400 font-mono mt-0.5';
            }
        }
    } catch (_) {}
}
window.loadRevolvingFundSummary = loadRevolvingFundSummary;

async function loadSparepartMoves() {
    const body = document.getElementById('spMoveBody');
    const sel = document.getElementById('spMovePart');
    if (!body && !sel) return;
    let moves = [];
    try { const r = await apiGet('/inventory/moves?limit=25'); moves = (r && r.items) || []; } catch (_) {}
    if (sel && _spView && _spView.length) {
        const curr = sel.value;
        sel.innerHTML = _spView.map(p => `<option value="${p.id}"${String(p.id) === curr ? ' selected' : ''}>${escapeHtml((p.merek || '') + ' ' + (p.jenis || ''))} (Sisa: ${p.qty})</option>`).join('');
    }
    if (body) {
        if (!moves.length) {
            body.innerHTML = `<tr><td colspan="5"><div class="text-center text-xs text-gray-400 py-6"><i class="fa-solid fa-box-open text-2xl mb-1.5 block opacity-40"></i>Belum ada pergerakan stok tercatat.</div></td></tr>`;
        } else {
            body.innerHTML = moves.map(m => {
                let badge = `<span class="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-semibold bg-gray-100 text-gray-700 dark:bg-white/10 dark:text-gray-300">${escapeHtml(m.aksi || '-')}</span>`;
                if (m.aksi === 'MASUK') {
                    badge = `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-bold bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-800/40"><i class="fa-solid fa-arrow-down text-[9px]"></i> Masuk</span>`;
                } else if (m.aksi === 'PAKAI') {
                    badge = `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-bold bg-indigo-50 text-indigo-700 dark:bg-indigo-950/40 dark:text-indigo-400 border border-indigo-200 dark:border-indigo-800/40"><i class="fa-solid fa-screwdriver-wrench text-[9px]"></i> Dipakai</span>`;
                } else if (m.aksi === 'BATAL') {
                    badge = `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-bold bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-400 border border-amber-200 dark:border-amber-800/40"><i class="fa-solid fa-rotate-left text-[9px]"></i> Batal</span>`;
                }
                const dt = String(m.waktu || '').replace('T', ' ').slice(0, 16);
                return `<tr>
                    <td class="text-xs text-gray-500 dark:text-gray-400 whitespace-nowrap">${escapeHtml(dt)}</td>
                    <td class="font-medium text-gray-800 dark:text-gray-200 max-w-[220px]">
                        <div class="truncate" title="${escapeHtml(m.sparepart_label || '-')}">${escapeHtml(m.sparepart_label || '-')}</div>
                        ${m.no_servis ? `<div class="text-[10.5px] text-brand-600 dark:text-brand-400 font-mono">Servis #${escapeHtml(m.no_servis)}${m.oleh ? ' • ' + escapeHtml(m.oleh) : ''}</div>` : (m.keterangan ? `<div class="text-[10px] text-gray-400 truncate">${escapeHtml(m.keterangan)}</div>` : '')}
                    </td>
                    <td class="text-center">${badge}</td>
                    <td class="text-right font-bold tabular-nums ${m.aksi === 'MASUK' ? 'text-emerald-600 dark:text-emerald-400' : 'text-gray-700 dark:text-gray-300'}">${m.aksi === 'MASUK' ? '+' : ''}${m.qty}</td>
                    <td class="text-right font-extrabold tabular-nums text-gray-900 dark:text-white">${m.qty_sesudah}</td>
                </tr>`;
            }).join('');
        }
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

function switchSparepartSubTab(tab) {
    _spActiveSubTab = tab;
    const tabs = ['catalog', 'moves', 'defects'];
    tabs.forEach(t => {
        const btn = document.getElementById('spSubTabBtn' + t.charAt(0).toUpperCase() + t.slice(1));
        const pane = document.getElementById('spSubTab' + t.charAt(0).toUpperCase() + t.slice(1));
        if (btn) {
            if (t === tab) {
                btn.className = 'sp-sub-tab px-3.5 py-2 rounded-lg text-xs sm:text-sm font-bold flex items-center gap-2 transition bg-brand-500 text-white shadow-xs';
            } else {
                btn.className = 'sp-sub-tab px-3.5 py-2 rounded-lg text-xs sm:text-sm font-semibold text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-white/5 flex items-center gap-2 transition';
            }
        }
        if (pane) {
            pane.classList.toggle('hidden', t !== tab);
        }
    });

    if (tab === 'moves') {
        loadSparepartMoves();
    } else if (tab === 'defects') {
        loadSparepartDefects();
    } else if (tab === 'catalog') {
        renderSparepart();
    }
}
window.switchSparepartSubTab = switchSparepartSubTab;

function toggleSparepartSummary() {
    _spSummaryVisible = !_spSummaryVisible;
    const sec = document.getElementById('spSummarySection');
    const txt = document.getElementById('spSummaryBtnText');
    if (sec) {
        sec.classList.toggle('hidden', !_spSummaryVisible);
    }
    if (txt) {
        txt.textContent = _spSummaryVisible ? 'Sembunyikan Metrik' : 'Tampilkan Metrik';
    }
}
window.toggleSparepartSummary = toggleSparepartSummary;

function spToggleViewMode() {
    _spViewMode = (_spViewMode === 'table') ? 'grouped' : 'table';
    try { localStorage.setItem('sp_view_mode', _spViewMode); } catch (_) {}
    updateViewModeButton();
    renderSparepart();
}
window.spToggleViewMode = spToggleViewMode;

function updateViewModeButton() {
    const icon = document.getElementById('spViewModeIcon');
    const txt = document.getElementById('spViewModeText');
    const toggleAllBtn = document.getElementById('spToggleAllBtn');
    if (icon && txt) {
        if (_spViewMode === 'table') {
            icon.className = 'fa-solid fa-table-list text-[11px]';
            txt.textContent = 'Tabel Rapat';
            if (toggleAllBtn) toggleAllBtn.classList.add('hidden');
        } else {
            icon.className = 'fa-solid fa-layer-group text-[11px]';
            txt.textContent = 'Kartu Grup';
            if (toggleAllBtn) toggleAllBtn.classList.remove('hidden');
        }
    }
}
window.updateViewModeButton = updateViewModeButton;

function updateSpBrandOptions(items) {
    const sel = document.getElementById('spBrandFilter');
    if (!sel) return;
    const brands = new Set();
    (items || []).forEach(s => {
        if (s.merek && s.merek.trim()) {
            brands.add(s.merek.trim());
        }
        if (s.device && s.device.trim()) {
            const firstWord = s.device.trim().split(/\s+/)[0];
            if (firstWord && firstWord.length > 2 && !/^\d+$/.test(firstWord)) {
                brands.add(firstWord);
            }
        }
    });
    const sorted = Array.from(brands).sort((a, b) => a.localeCompare(b, 'id'));
    const curr = _spBrandFilter || sel.value;
    sel.innerHTML = '<option value="">Semua Merek HP (' + sorted.length + ')</option>' +
        sorted.map(b => `<option value="${escapeHtml(b)}"${curr.toLowerCase() === b.toLowerCase() ? ' selected' : ''}>${escapeHtml(b)}</option>`).join('');

    if (!sel.dataset.bound) {
        sel.dataset.bound = '1';
        sel.addEventListener('change', () => {
            _spBrandFilter = sel.value;
            _spPage = 1;
            renderSparepart();
        });
    }
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
    window._lowStockParts = (data || []).filter(s => (Number(s.qty || s.stok) || 0) <= 3);
    try { if (typeof updateHeaderNotif === 'function') updateHeaderNotif(); } catch (_) {}
    const total = data.length;
    const aman = data.filter(s => (s.qty || 0) > 5).length;
    const tipis = data.filter(s => (s.qty || 0) > 0 && (s.qty || 0) <= 5).length;
    const habis = data.filter(s => (s.qty || 0) <= 0).length;
    const nilai = data.reduce((a, s) => a + (Number(s.qty) || 0) * (Number(s.jual) || 0), 0);

    const cards = [
        { key: 'all', label: 'Total Jenis', value: total, unit: 'jenis part', icon: 'fa-boxes-stacked', cls: 'sm-slate' },
        { key: 'ready', label: 'Stok Aman', value: aman, unit: '> 5 unit', icon: 'fa-circle-check', cls: 'sm-green' },
        { key: 'low', label: 'Stok Menipis', value: tipis, unit: '≤ 5 unit', icon: 'fa-triangle-exclamation', cls: 'sm-amber' },
        { key: 'out', label: 'Stok Habis', value: habis, unit: '0 unit', icon: 'fa-box-open', cls: 'sm-red' },
        { key: 'value', label: 'Nilai Stok Jual', value: spRupiah(nilai), unit: 'est. omzet', icon: 'fa-sack-dollar', cls: 'sm-cyan' },
    ];

    el.innerHTML = cards.map(c => {
        const isActive = _spStockFilter === c.key ? ' is-active' : '';
        return `
        <div class="sm-card sp-kpi-card ${c.cls}${isActive}" onclick="spKpiClick('${c.key}')" role="button" tabindex="0" title="Klik untuk memfilter: ${c.label}">
            <div class="sm-top"><i class="fa-solid ${c.icon}"></i>${c.label}</div>
            <div class="sm-bot"><span class="sm-num">${c.value}</span><span class="sm-pct">${c.unit}</span></div>
        </div>`;
    }).join('');
}

function spKpiClick(key) {
    if (key === 'value') return;
    if (_spStockFilter === key) {
        _spStockFilter = 'all';
    } else {
        _spStockFilter = key;
    }
    const sel = document.getElementById('spStockFilter');
    if (sel) sel.value = _spStockFilter;
    _spPage = 1;
    renderSparepart();
}

function spResetFilters() {
    _spQuery = '';
    _spStockFilter = 'all';
    _spCatFilter = '';
    _spBrandFilter = '';
    _spPage = 1;
    _spExpandedKeys.clear();
    _spAllExpanded = false;
    const search = document.getElementById('spSearch');
    if (search) search.value = '';
    const catSel = document.getElementById('spCatFilter');
    if (catSel) catSel.value = '';
    const brandSel = document.getElementById('spBrandFilter');
    if (brandSel) brandSel.value = '';
    const stockSel = document.getElementById('spStockFilter');
    if (stockSel) stockSel.value = 'all';
    renderSparepart(true);
}

function renderSpCategoryTabs(data) {
    const container = document.getElementById('spCategoryTabs');
    if (!container) return;
    const all = data || [];
    const counts = {};
    for (const item of all) {
        const cat = (item.kategori || '').trim();
        if (!cat) continue;
        counts[cat] = (counts[cat] || 0) + 1;
    }
    const catList = Object.keys(counts).sort();
    const curr = (_spCatFilter || '').toLowerCase();

    let html = `
        <button type="button" onclick="spSelectCategoryTab('')" class="px-2.5 py-1 rounded-lg text-xs font-bold transition flex items-center gap-1.5 whitespace-nowrap flex-shrink-0 ${!curr ? 'bg-emerald-600 text-white shadow-2xs' : 'bg-white dark:bg-white/5 border border-gray-200 dark:border-white/10 text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-white/10'}">
            <span>Semua</span>
            <span class="text-[10px] px-1.5 py-0.2 rounded-full ${!curr ? 'bg-emerald-700/70 text-white' : 'bg-gray-100 dark:bg-white/10 text-gray-500 dark:text-gray-400'}">${all.length}</span>
        </button>
    `;

    for (const cat of catList) {
        const isAct = cat.toLowerCase() === curr;
        const meta = spCategoryMeta(cat);
        html += `
            <button type="button" onclick="spSelectCategoryTab('${escapeHtml(cat)}')" class="px-2.5 py-1 rounded-lg text-xs font-bold transition flex items-center gap-1.5 whitespace-nowrap flex-shrink-0 ${isAct ? 'bg-emerald-600 text-white shadow-2xs' : 'bg-white dark:bg-white/5 border border-gray-200 dark:border-white/10 text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-white/10'}">
                <span>${escapeHtml(cat)}</span>
                <span class="text-[10px] px-1.5 py-0.2 rounded-full ${isAct ? 'bg-emerald-700/70 text-white' : 'bg-gray-100 dark:bg-white/10 text-gray-500 dark:text-gray-400'}">${counts[cat]}</span>
            </button>
        `;
    }
    container.innerHTML = html;
}

function spSelectCategoryTab(cat) {
    _spCatFilter = cat;
    _spPage = 1;
    const catSel = document.getElementById('spCatFilter');
    if (catSel) catSel.value = cat;
    renderSparepart(false);
}
window.spSelectCategoryTab = spSelectCategoryTab;

function updateSpCatOptions(data) {
    const sel = document.getElementById('spCatFilter');
    if (!sel) return;
    const curr = _spCatFilter || sel.value || '';
    const cats = Array.from(new Set((data || []).map(s => (s.kategori || '').trim()).filter(Boolean))).sort();
    let html = '<option value="">Semua Kategori</option>';
    cats.forEach(c => {
        html += `<option value="${escapeHtml(c)}"${c === curr ? ' selected' : ''}>${escapeHtml(c)}</option>`;
    });
    sel.innerHTML = html;
}

function spFiltered() {
    const q = _spQuery.trim().toLowerCase();
    try { _sparepartsCache = (_spView || []).slice(); } catch (_) {}
    let list = (_spView || []).slice();
    if (q) {
        list = list.filter(s => [s.jenis, s.merek, s.device, s.kategori]
            .some(f => (f || '').toLowerCase().includes(q)));
    }
    if (_spBrandFilter) {
        const bf = _spBrandFilter.toLowerCase();
        list = list.filter(s => (s.merek || '').toLowerCase() === bf || (s.device || '').toLowerCase().includes(bf));
    }
    if (_spCatFilter) {
        list = list.filter(s => (s.kategori || '').toLowerCase() === _spCatFilter.toLowerCase());
    }
    if (_spStockFilter === 'low') {
        list = list.filter(s => s.qty > 0 && s.qty <= 5);
    } else if (_spStockFilter === 'out') {
        list = list.filter(s => s.qty <= 0);
    } else if (_spStockFilter === 'ready') {
        list = list.filter(s => s.qty > 5);
    }
    return list;
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

// --- Helper Deteksi Merek & Ekstraksi Grade ---
function spExtractBrand(s) {
    const rawName = (s.jenis || '').trim();
    const brandPatterns = [
        { brand: 'OLED OG SUPER (FINGERPRINT)', pat: /\bOLED\s+OG\s+SUPER(\s*\([^\)]*\))?/i, cls: 'bg-indigo-50 dark:bg-indigo-950/40 text-indigo-700 dark:text-indigo-300 border-indigo-200 dark:border-indigo-800/40' },
        { brand: 'OG SUPER', pat: /\bOG\s+SUPER(\s*\([^\)]*\))?/i, cls: 'bg-amber-50 dark:bg-amber-950/40 text-amber-700 dark:text-amber-300 border-amber-200 dark:border-amber-800/40' },
        { brand: 'BPE', pat: /\bBPE\b/i, cls: 'bg-sky-50 dark:bg-sky-950/40 text-sky-700 dark:text-sky-300 border-sky-200 dark:border-sky-800/40' },
        { brand: 'HX PREMIUM', pat: /\bHX\s+PREMIUM\b/i, cls: 'bg-purple-50 dark:bg-purple-950/40 text-purple-700 dark:text-purple-300 border-purple-200 dark:border-purple-800/40' },
        { brand: 'HX', pat: /\bHX\b/i, cls: 'bg-purple-50 dark:bg-purple-950/40 text-purple-700 dark:text-purple-300 border-purple-200 dark:border-purple-800/40' },
        { brand: 'MEETOO', pat: /\bMEETOO\b/i, cls: 'bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300 border-emerald-200 dark:border-emerald-800/40' },
        { brand: 'SHINESTAR', pat: /\bSHINESTAR\b/i, cls: 'bg-rose-50 dark:bg-rose-950/40 text-rose-700 dark:text-rose-300 border-rose-200 dark:border-rose-800/40' },
        { brand: 'XJE INDONESIA', pat: /\bXJE\s+INDONESIA\b/i, cls: 'bg-teal-50 dark:bg-teal-950/40 text-teal-700 dark:text-teal-300 border-teal-200 dark:border-teal-800/40' },
        { brand: 'XJE', pat: /\bXJE\b/i, cls: 'bg-teal-50 dark:bg-teal-950/40 text-teal-700 dark:text-teal-300 border-teal-200 dark:border-teal-800/40' },
        { brand: 'CROWN', pat: /\bCROWN\b/i, cls: 'bg-amber-50 dark:bg-amber-950/40 text-amber-700 dark:text-amber-300 border-amber-200 dark:border-amber-800/40' },
        { brand: 'DIAMOND', pat: /\bDIAMOND\b/i, cls: 'bg-blue-50 dark:bg-blue-950/40 text-blue-700 dark:text-blue-300 border-blue-200 dark:border-blue-800/40' },
        { brand: 'INCELL', pat: /\bINCELL\b/i, cls: 'bg-cyan-50 dark:bg-cyan-950/40 text-cyan-700 dark:text-cyan-300 border-cyan-200 dark:border-cyan-800/40' },
        { brand: 'OLED', pat: /\bOLED\b/i, cls: 'bg-violet-50 dark:bg-violet-950/40 text-violet-700 dark:text-violet-300 border-violet-200 dark:border-violet-800/40' },
        { brand: 'ORIGINAL', pat: /\b(ORIGINAL|ORI)\b/i, cls: 'bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300 border-emerald-200 dark:border-emerald-800/40' },
    ];
    for (const item of brandPatterns) {
        if (item.pat.test(rawName)) {
            return { name: item.brand, cls: item.cls };
        }
    }
    const m = (s.merek || '').trim();
    if (m && m !== '-' && !['universal', 'hp'].includes(m.toLowerCase())) {
        return { name: m.toUpperCase(), cls: 'bg-gray-100 dark:bg-white/10 text-gray-700 dark:text-gray-300 border-gray-200 dark:border-white/10' };
    }
    return { name: 'STANDAR', cls: 'bg-gray-100 dark:bg-white/10 text-gray-600 dark:text-gray-300 border-gray-200 dark:border-white/10' };
}

// --- Helper Pemisahan Model Induk & Model Kompatibel ---
function spFormatDisplayTitle(title, device) {
    const raw = (title || '').trim();
    const slashParts = raw.split('/').map(p => p.trim()).filter(Boolean);
    if (slashParts.length > 2) {
        const lead = slashParts.slice(0, 2).join(' / ');
        const remainder = slashParts.slice(2).join(' / ');
        const devText = (device && device !== '-' && !remainder.toLowerCase().includes(device.toLowerCase())) ? ' • ' + device : '';
        return {
            primary: lead,
            sub: 'Cocok juga: ' + remainder + devText
        };
    }
    const devText = (device && device !== '-' && !raw.toLowerCase().includes(device.toLowerCase())) ? 'Kompatibel: ' + device : '';
    return {
        primary: raw,
        sub: devText
    };
}

function spToggleGroup(encodedKey) {
    const key = decodeURIComponent(encodedKey);
    if (_spExpandedKeys.has(key)) {
        _spExpandedKeys.delete(key);
    } else {
        _spExpandedKeys.add(key);
    }
    renderSparepart(false);
}

function spToggleAllGroups() {
    _spAllExpanded = !_spAllExpanded;
    if (!_spAllExpanded) {
        _spExpandedKeys.clear();
    }
    const btnText = document.getElementById('spToggleAllText');
    if (btnText) btnText.textContent = _spAllExpanded ? 'Tutup Semua' : 'Buka Semua';
    renderSparepart(false);
}

window.spToggleGroup = spToggleGroup;
window.spToggleAllGroups = spToggleAllGroups;

// --- Helper Pembersihan Nama Induk Tipe ---
function spExtractBaseTitle(s) {
    let name = (s.jenis || '').trim();
    const brandPatterns = [
        /\b(OLED\s+)?OG\s+SUPER(\s*\([^\)]*\))?/gi,
        /\bBPE\b/gi,
        /\bHX(\s+PREMIUM)?\b/gi,
        /\bMEETOO\b/gi,
        /\bSHINESTAR\b/gi,
        /\bXJE(\s+INDONESIA)?\b/gi,
        /\bCROWN\b/gi,
        /\bDIAMOND\b/gi,
        /\bINCELL\b/gi,
        /\bOLED\b/gi,
        /\b(HITAM|PUTIH|BLACK|WHITE|GOLD|BLUE|GREY|GRAY)\b/gi,
        /@\s*[\d\.,]+/g
    ];
    for (const pat of brandPatterns) {
        name = name.replace(pat, ' ');
    }
    name = name.replace(/[-/–—\s]+$/, '').replace(/\s{2,}/g, ' ').trim();
    return name || s.jenis;
}

// --- Helper Pengelompokan Data Sparepart ---
function spGroupItems(data) {
    const map = new Map();
    for (const s of data) {
        const baseTitle = spExtractBaseTitle(s);
        const kat = (s.kategori || 'Part').trim();
        const groupKey = kat.toLowerCase() + '::' + baseTitle.toLowerCase();

        let group = map.get(groupKey);
        if (!group) {
            group = {
                key: groupKey,
                kategori: kat,
                title: baseTitle,
                device: s.device && s.device !== '-' ? s.device : '',
                totalQty: 0,
                minBeli: Infinity,
                maxBeli: -Infinity,
                minJual: Infinity,
                maxJual: -Infinity,
                variants: []
            };
            map.set(groupKey, group);
        }

        const bInfo = spExtractBrand(s);
        const qty = Number(s.qty) || 0;
        const beli = Number(s.beli) || 0;
        const jual = Number(s.jual) || 0;

        group.totalQty += qty;
        if (beli < group.minBeli) group.minBeli = beli;
        if (beli > group.maxBeli) group.maxBeli = beli;
        if (jual < group.minJual) group.minJual = jual;
        if (jual > group.maxJual) group.maxJual = jual;

        group.variants.push({
            id: s.id,
            brand: bInfo.name,
            brandCls: bInfo.cls,
            qty: qty,
            beli: beli,
            jual: jual,
            tgl: s.tgl,
            raw: s
        });
    }

    return Array.from(map.values());
}

// --- Helper Salin Format WA untuk Teknisi / Toko Servis ---
function spCopyText(text, successMsg) {
    if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(text).then(() => {
            toast(successMsg || 'Format balasan WA berhasil disalin!', 'success');
        }).catch(() => {
            spFallbackCopyText(text, successMsg);
        });
    } else {
        spFallbackCopyText(text, successMsg);
    }
}

function spFallbackCopyText(text, successMsg) {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.left = '-9999px';
    document.body.appendChild(ta);
    ta.select();
    try {
        document.execCommand('copy');
        toast(successMsg || 'Format balasan WA berhasil disalin!', 'success');
    } catch (_) {
        toast('Gagal menyalin teks ke clipboard.', 'danger');
    }
    document.body.removeChild(ta);
}

function spCopyGroupWA(encodedKey) {
    const groupKey = decodeURIComponent(encodedKey);
    const groups = spGroupItems(spFiltered());
    const g = groups.find(x => x.key === groupKey);
    if (!g || !g.variants || g.variants.length === 0) {
        toast('Tidak ada data varian untuk disalin.', 'warning');
        return;
    }

    const readyVars = g.variants.filter(v => v.qty > 0);
    const targetVars = readyVars.length > 0 ? readyVars : g.variants;

    const lines = ['Ready stok:'];
    for (const v of targetVars) {
        const fullDesc = (v.raw.jenis || '').trim();
        const hargaFormatted = 'Rp ' + (Number(v.jual) || 0).toLocaleString('id-ID');
        const stokInfo = v.qty > 0 ? `(Stok: ${v.qty})` : '(Stok Habis)';
        lines.push(`• ${fullDesc} @ ${hargaFormatted} ${stokInfo}`);
    }

    const textToCopy = lines.join('\n');
    spCopyText(textToCopy, `Format balasan WA (${targetVars.length} item) disalin!`);
}

function spCopySingleWA(partId) {
    const item = (_spView || []).find(x => x && x.id === partId);
    if (!item) {
        toast('Part tidak ditemukan.', 'warning');
        return;
    }
    const fullDesc = (item.jenis || '').trim();
    const hargaFormatted = 'Rp ' + (Number(item.jual) || 0).toLocaleString('id-ID');
    const stokInfo = item.qty > 0 ? `(Stok: ${item.qty})` : '(Stok Habis)';
    const textToCopy = `Ready stok:\n• ${fullDesc} @ ${hargaFormatted} ${stokInfo}`;
    spCopyText(textToCopy, 'Format WA part berhasil disalin!');
}

window.spCopyGroupWA = spCopyGroupWA;
window.spCopySingleWA = spCopySingleWA;

async function renderSparepart(fetchFresh = true) {
    try { spMenuClose(); } catch (_) {}
    const my = ++_spReq;
    if (fetchFresh || !_spView || _spView.length === 0) {
        try {
            _spView = await spFetchAll(_spQuery, my);
            if (_spView === null) return;
            if (_spQuery.trim()) {
                const _allKpi = await spFetchAll('', my);
                if (_allKpi === null) return;
                renderSpKpi(_allKpi);
                updateSpCatOptions(_allKpi);
                renderSpCategoryTabs(_allKpi);
                updateSpBrandOptions(_allKpi);
            } else {
                renderSpKpi(_spView);
                updateSpCatOptions(_spView);
                renderSpCategoryTabs(_spView);
                updateSpBrandOptions(_spView);
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
    } else {
        renderSpCategoryTabs(_spView);
    }
    renderSpKpi();

    const container = document.getElementById('spListContainer');
    const body = document.getElementById('spBody');
    const empty = document.getElementById('spEmpty');
    const loading = document.getElementById('spLoading');
    const pagination = document.getElementById('spPagination');
    const info = document.getElementById('spInfo');
    const pageBtns = document.getElementById('spPageBtns');

    if (container) container.innerHTML = '';
    if (body) body.innerHTML = '';
    if (loading) loading.classList.add('hidden');
    if (empty) empty.classList.add('hidden');

    updateViewModeButton();

    const data = spFiltered();

    if (_spViewMode === 'table') {
        const totalItems = data.length;
        const SP_ITEMS_PER_PAGE = 25;
        const totalPages = Math.max(1, Math.ceil(totalItems / SP_ITEMS_PER_PAGE));
        if (_spPage > totalPages) _spPage = totalPages;
        if (_spPage < 1) _spPage = 1;

        if (totalItems === 0) {
            if (empty) {
                empty.classList.remove('hidden');
                empty.innerHTML = _spQuery.trim()
                    ? '<i class="fa-solid fa-magnifying-glass text-3xl mb-2 block opacity-40"></i>Sparepart tidak ditemukan untuk pencarian: "<b>' + escapeHtml(_spQuery) + '</b>".'
                    : '<i class="fa-solid fa-box-open text-3xl mb-2 block opacity-40"></i>Belum ada data sparepart.';
            }
            if (pagination) pagination.classList.add('hidden');
            if (info) info.textContent = '';
            if (pageBtns) pageBtns.innerHTML = '';
            await loadSparepartMoves();
            try { await loadSparepartDefects(); } catch (_) {}
            try { await loadRevolvingFundSummary(); } catch (_) {}
            return;
        }

        if (pagination) pagination.classList.remove('hidden');
        if (info) {
            const startIdx = (_spPage - 1) * SP_ITEMS_PER_PAGE + 1;
            const endIdx = Math.min(_spPage * SP_ITEMS_PER_PAGE, totalItems);
            info.textContent = `Menampilkan ${startIdx}-${endIdx} dari ${totalItems} item sparepart`;
        }

        const start = (_spPage - 1) * SP_ITEMS_PER_PAGE;
        const pageItems = data.slice(start, start + SP_ITEMS_PER_PAGE);

        if (container) {
            container.innerHTML = `
                <div class="panel overflow-hidden rounded-xl border border-gray-200/80 dark:border-white/10 shadow-2xs">
                    <div class="overflow-x-auto">
                        <table class="w-full text-left text-xs border-collapse">
                            <thead>
                                <tr class="bg-gray-50/80 dark:bg-white/[0.03] text-gray-500 dark:text-gray-400 border-b border-gray-200/80 dark:border-white/10 font-bold text-[10.5px]">
                                    <th class="py-2.5 px-3">Kategori</th>
                                    <th class="py-2.5 px-3">Perangkat / Tipe HP</th>
                                    <th class="py-2.5 px-3">Nama Part &amp; Varian Merek</th>
                                    <th class="py-2.5 px-3 text-center w-28">Stok Rak</th>
                                    <th class="py-2.5 px-3 text-right w-28">Modal Beli</th>
                                    <th class="py-2.5 px-3 text-right w-32">Harga Jual</th>
                                    <th class="py-2.5 px-3 text-right w-28">Est. Margin</th>
                                    <th class="py-2.5 px-3 text-center w-36">Aksi Cepat</th>
                                </tr>
                            </thead>
                            <tbody class="divide-y divide-gray-100 dark:divide-white/5">
                                ${pageItems.map(s => {
                                    const meta = spCategoryMeta(s.kategori);
                                    const bInfo = spExtractBrand(s);
                                    const margin = (s.jual || 0) - (s.beli || 0);
                                    const marginPct = s.beli > 0 ? Math.round((margin / s.beli) * 100) : 0;
                                    const isHabis = s.qty <= 0;
                                    const isMenipis = !isHabis && s.qty <= 3;
                                    const pill = isHabis
                                        ? '<span class="px-2 py-0.5 rounded text-[10.5px] font-bold bg-rose-50 dark:bg-rose-950/40 text-rose-600 dark:text-rose-400 border border-rose-200 dark:border-rose-900/50">0 (Habis)</span>'
                                        : isMenipis
                                        ? `<span class="px-2 py-0.5 rounded text-[10.5px] font-bold bg-amber-50 dark:bg-amber-950/40 text-amber-600 dark:text-amber-400 border border-amber-200 dark:border-amber-900/50">${s.qty} Unit (Menipis)</span>`
                                        : `<span class="px-2 py-0.5 rounded text-[10.5px] font-bold bg-emerald-50 dark:bg-emerald-950/40 text-emerald-600 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-900/50">${s.qty} Unit (Aman)</span>`;

                                    return `
                                        <tr class="hover:bg-white dark:hover:bg-white/[0.03] transition">
                                            <td class="py-2 px-3">
                                                <span class="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-extrabold uppercase tracking-wider border ${meta.bg}">
                                                    <span>${escapeHtml(s.kategori)}</span>
                                                </span>
                                            </td>
                                            <td class="py-2 px-3">
                                                <div class="font-extrabold text-xs text-gray-900 dark:text-white">
                                                    ${escapeHtml(s.device && s.device !== '-' ? s.device : '-')}
                                                </div>
                                            </td>
                                            <td class="py-2 px-3">
                                                <div class="flex items-center gap-1.5 flex-wrap">
                                                    <span class="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-extrabold border ${bInfo.cls}">
                                                        ${escapeHtml(bInfo.name)}
                                                    </span>
                                                    <span class="text-xs font-medium text-gray-800 dark:text-gray-200" title="${escapeHtml(s.jenis)}">
                                                        ${escapeHtml(s.jenis)}
                                                    </span>
                                                </div>
                                            </td>
                                            <td class="py-2 px-3 text-center">
                                                ${pill}
                                            </td>
                                            <td class="py-2 px-3 text-right font-mono font-medium text-gray-500 dark:text-gray-400">
                                                ${spRupiah(s.beli)}
                                            </td>
                                            <td class="py-2 px-3 text-right font-mono font-extrabold text-emerald-600 dark:text-emerald-400">
                                                ${spRupiah(s.jual)}
                                            </td>
                                            <td class="py-2 px-3 text-right font-mono text-[11px] ${margin >= 0 ? 'text-gray-700 dark:text-gray-300' : 'text-rose-500'}">
                                                +${spRupiah(margin)} <span class="text-gray-400 font-sans text-[10px]">(${marginPct}%)</span>
                                            </td>
                                            <td class="py-2 px-3 text-center">
                                                <div class="flex items-center justify-center gap-1.5" data-cap="SPAREPART_WRITE">
                                                    <button type="button" onclick="spCopySingleWA(${s.id})" class="px-2 py-1 rounded bg-emerald-50 hover:bg-emerald-100 dark:bg-emerald-950/40 dark:hover:bg-emerald-900/50 text-emerald-700 dark:text-emerald-300 font-bold text-[10.5px] flex items-center gap-1 transition" title="Salin Format WA Varian Ini">
                                                        <i class="fa-brands fa-whatsapp text-[10.5px]"></i>
                                                        <span>WA</span>
                                                    </button>
                                                    <button type="button" onclick="spQuickRestock(${s.id})" class="px-2 py-1 rounded bg-brand-50 hover:bg-brand-100 dark:bg-brand-950/40 dark:hover:bg-brand-900/50 text-brand-700 dark:text-brand-300 font-bold text-[10.5px] flex items-center gap-1 transition" title="Tambah Stok Masuk">
                                                        <i class="fa-solid fa-plus text-[9px]"></i>
                                                        <span>Stok</span>
                                                    </button>
                                                    <button type="button" onclick="spEdit(${s.id})" class="px-2 py-1 rounded border border-gray-200 dark:border-white/10 hover:bg-gray-100 dark:hover:bg-white/5 text-gray-600 dark:text-gray-300 text-[10.5px] font-semibold transition" title="Edit Part">
                                                        <i class="fa-solid fa-pen-to-square text-[10px]"></i>
                                                    </button>
                                                    <button type="button" onclick="spDel(${s.id})" class="p-1 rounded text-gray-400 hover:text-rose-500 text-[10.5px] transition" title="Hapus Part">
                                                        <i class="fa-solid fa-trash text-[10px]"></i>
                                                    </button>
                                                </div>
                                            </td>
                                        </tr>
                                    `;
                                }).join('')}
                            </tbody>
                        </table>
                    </div>
                </div>
            `;
        }

        // Pagination buttons generator for table mode
        if (pageBtns && totalPages > 1) {
            pageBtns.innerHTML = '';
            const mkBtn = (html, p, disabled, active, label) => {
                const b = document.createElement('button');
                b.type = 'button';
                b.className = 'w-7 h-7 flex items-center justify-center rounded-lg text-xs font-semibold transition '
                    + (active ? 'bg-brand-500 text-white' : 'border border-gray-200 dark:border-white/10 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-white/5');
                if (disabled) { b.disabled = true; b.classList.add('opacity-40', 'cursor-not-allowed'); }
                if (label) b.setAttribute('aria-label', label);
                b.innerHTML = html;
                b.addEventListener('click', () => { _spPage = p; renderSparepart(false); });
                return b;
            };
            pageBtns.appendChild(mkBtn('<i class="fa-solid fa-chevron-left"></i>', _spPage - 1, _spPage === 1, false, 'Sebelumnya'));
            for (let p = 1; p <= totalPages; p++) {
                pageBtns.appendChild(mkBtn(String(p), p, false, p === _spPage));
            }
            pageBtns.appendChild(mkBtn('<i class="fa-solid fa-chevron-right"></i>', _spPage + 1, _spPage === totalPages, false, 'Berikutnya'));
        }

    } else {
        // Grouped mode (original accordion)
        const groups = spGroupItems(data);
        const totalGroups = groups.length;
        const SP_GROUPS_PER_PAGE = 20;
        const totalPages = Math.max(1, Math.ceil(totalGroups / SP_GROUPS_PER_PAGE));
        if (_spPage > totalPages) _spPage = totalPages;
        if (_spPage < 1) _spPage = 1;

        if (totalGroups === 0) {
            if (empty) {
                empty.classList.remove('hidden');
                empty.innerHTML = _spQuery.trim()
                    ? '<i class="fa-solid fa-magnifying-glass text-3xl mb-2 block opacity-40"></i>Sparepart tidak ditemukan untuk pencarian: "<b>' + escapeHtml(_spQuery) + '</b>".'
                    : '<i class="fa-solid fa-box-open text-3xl mb-2 block opacity-40"></i>Belum ada data sparepart.';
            }
            if (pagination) pagination.classList.add('hidden');
            if (info) info.textContent = '';
            if (pageBtns) pageBtns.innerHTML = '';
            await loadSparepartMoves();
            try { await loadSparepartDefects(); } catch (_) {}
            try { await loadRevolvingFundSummary(); } catch (_) {}
            return;
        }

        if (pagination) pagination.classList.remove('hidden');
        if (info) {
            const startIdx = (_spPage - 1) * SP_GROUPS_PER_PAGE + 1;
            const endIdx = Math.min(_spPage * SP_GROUPS_PER_PAGE, totalGroups);
            info.textContent = `Menampilkan ${startIdx}-${endIdx} dari ${totalGroups} tipe produk (${data.length} varian stok)`;
        }

        const start = (_spPage - 1) * SP_GROUPS_PER_PAGE;
        const pageGroups = groups.slice(start, start + SP_GROUPS_PER_PAGE);

        const isSearchActive = Boolean(_spQuery.trim());
        const btnText = document.getElementById('spToggleAllText');
        if (btnText) {
            btnText.textContent = (_spAllExpanded || isSearchActive) ? 'Tutup Semua' : 'Buka Semua';
        }

        if (container) {
            container.innerHTML = pageGroups.map(g => {
                const meta = spCategoryMeta(g.kategori);
                const totalQty = g.totalQty;
                const isHabis = totalQty <= 0;
                const isMenipis = !isHabis && totalQty <= 5;
                const statusBadgeCls = isHabis
                    ? 'bg-rose-50 dark:bg-rose-950/40 text-rose-600 dark:text-rose-400 border border-rose-200 dark:border-rose-900/50'
                    : isMenipis
                    ? 'bg-amber-50 dark:bg-amber-950/40 text-amber-600 dark:text-amber-400 border border-amber-200 dark:border-amber-900/50'
                    : 'bg-emerald-50 dark:bg-emerald-950/40 text-emerald-600 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-900/50';
                const statusTxt = isHabis ? '0 (Habis)' : isMenipis ? `${totalQty} (Menipis)` : `${totalQty} (Aman)`;

                const isOpen = isSearchActive || totalGroups <= 2 || _spAllExpanded || _spExpandedKeys.has(g.key);

                const minJ = g.minJual === Infinity ? 0 : g.minJual;
                const maxJ = g.maxJual === -Infinity ? 0 : g.maxJual;
                const hargaDisplay = minJ === maxJ ? spRupiah(minJ) : `${spRupiah(minJ)} - ${spRupiah(maxJ)}`;

                const tInfo = spFormatDisplayTitle(g.title, g.device);

                // Merek badges
                const brandBadges = g.variants.map(v => {
                    const qCls = v.qty <= 0 ? 'opacity-40 line-through' : 'font-extrabold';
                    return `<span class="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] border ${v.brandCls}">
                        <span class="${qCls}">${escapeHtml(v.brand)}</span>
                        <span class="text-[9px] opacity-75 font-mono">(${v.qty})</span>
                    </span>`;
                }).join('');

                return `
                    <div class="panel overflow-hidden rounded-xl border border-gray-200/80 dark:border-white/10 hover:border-emerald-500/40 transition shadow-2xs">
                        <!-- Baris Header Ramping Accordion (Klik untuk Buka/Tutup) -->
                        <div class="p-2.5 sm:px-3.5 sm:py-2.5 flex items-center justify-between gap-2.5 sm:gap-3 cursor-pointer select-none bg-white dark:bg-dark-panel hover:bg-gray-50/80 dark:hover:bg-white/[0.02] transition" onclick="spToggleGroup('${encodeURIComponent(g.key)}')">
                            <!-- Kolom Kiri: Kategori Badge + Tipe Ringkas + Merek Badges -->
                            <div class="flex items-center gap-2.5 min-w-0 flex-1">
                                <span class="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-extrabold uppercase tracking-wider flex-shrink-0 border ${meta.bg}">
                                    <span>${escapeHtml(g.kategori)}</span>
                                </span>
                                <div class="min-w-0 flex-1">
                                    <div class="flex items-center gap-2 flex-wrap">
                                        <span class="font-extrabold text-xs sm:text-[13.5px] text-gray-900 dark:text-white leading-tight">
                                            ${escapeHtml(tInfo.primary)}
                                        </span>
                                        <div class="flex items-center gap-1 flex-wrap">
                                            ${brandBadges}
                                        </div>
                                    </div>
                                    ${tInfo.sub ? `
                                        <div class="text-[11px] text-gray-500 dark:text-gray-400 truncate mt-0.5" title="${escapeHtml(g.title + (g.device ? ' • ' + g.device : ''))}">
                                            <i class="fa-solid fa-mobile-screen-button text-[9.5px] mr-1 opacity-60"></i>${escapeHtml(tInfo.sub)}
                                        </div>
                                    ` : ''}
                                </div>
                            </div>

                            <!-- Kolom Kanan: Rentang Harga + Total Stok + Tombol Salin WA + Panah Chevron -->
                            <div class="flex items-center gap-2 sm:gap-3 flex-shrink-0">
                                <div class="text-right hidden sm:block">
                                    <div class="text-[9.5px] uppercase font-bold text-gray-400">Harga Jual</div>
                                    <div class="text-xs sm:text-[13px] font-extrabold text-emerald-600 dark:text-emerald-400 font-mono">
                                        ${hargaDisplay}
                                    </div>
                                </div>
                                <div class="text-right min-w-[55px]">
                                    <div class="text-[9.5px] uppercase font-bold text-gray-400">Stok</div>
                                    <span class="px-2 py-0.5 rounded-md text-[11px] font-bold ${statusBadgeCls} tabular-nums">
                                        ${statusTxt}
                                    </span>
                                </div>
                                <button type="button" onclick="event.stopPropagation(); spCopyGroupWA('${encodeURIComponent(g.key)}')" class="px-2.5 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-extrabold flex items-center gap-1.5 shadow-2xs transition active:scale-95" title="Salin format balasan WhatsApp untuk teknisi">
                                    <i class="fa-brands fa-whatsapp text-sm"></i>
                                    <span class="hidden md:inline">Salin WA</span>
                                </button>
                                <div class="w-6 h-6 rounded-md flex items-center justify-center text-gray-400 hover:text-gray-700 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-white/5 transition" title="Buka / Tutup Detail">
                                    <i class="fa-solid fa-chevron-down text-xs transition-transform duration-200 ${isOpen ? 'rotate-180' : ''}"></i>
                                </div>
                            </div>
                        </div>

                        <!-- Sub-Tabel Komparasi Varian Merek (Hanya jika Terbuka) -->
                        ${isOpen ? `
                            <div class="border-t border-gray-100 dark:border-white/5 bg-gray-50/50 dark:bg-white/[0.015] p-2.5 sm:p-3 overflow-x-auto">
                                <table class="w-full text-left text-xs border-collapse">
                                    <thead>
                                        <tr class="text-gray-500 dark:text-gray-400 border-b border-gray-200/60 dark:border-white/5 font-bold text-[10.5px]">
                                            <th class="py-2 px-3">Merek / Grade Pabrikan</th>
                                            <th class="py-2 px-3 text-center w-28">Stok Fisik</th>
                                            <th class="py-2 px-3 text-right w-28">Modal Beli</th>
                                            <th class="py-2 px-3 text-right w-32">Harga Jual</th>
                                            <th class="py-2 px-3 text-right w-28">Estimasi Margin</th>
                                            <th class="py-2 px-3 text-center w-36">Aksi Cepat</th>
                                        </tr>
                                    </thead>
                                    <tbody class="divide-y divide-gray-100 dark:divide-white/5">
                                        ${g.variants.map(v => {
                                            const margin = v.jual - v.beli;
                                            const marginPct = v.beli > 0 ? Math.round((margin / v.beli) * 100) : 0;
                                            const vHabis = v.qty <= 0;
                                            const vMenipis = !vHabis && v.qty <= 3;
                                            const vPill = vHabis
                                                ? '<span class="px-2 py-0.5 rounded text-[10.5px] font-bold bg-rose-50 dark:bg-rose-950/40 text-rose-600 dark:text-rose-400 border border-rose-200 dark:border-rose-900/50">0 (Habis)</span>'
                                                : vMenipis
                                                ? `<span class="px-2 py-0.5 rounded text-[10.5px] font-bold bg-amber-50 dark:bg-amber-950/40 text-amber-600 dark:text-amber-400 border border-amber-200 dark:border-amber-900/50">${v.qty} Unit (Menipis)</span>`
                                                : `<span class="px-2 py-0.5 rounded text-[10.5px] font-bold bg-emerald-50 dark:bg-emerald-950/40 text-emerald-600 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-900/50">${v.qty} Unit (Aman)</span>`;

                                            return `
                                                <tr class="hover:bg-white dark:hover:bg-white/[0.03] transition">
                                                    <td class="py-2 px-3">
                                                        <div class="flex items-center gap-2">
                                                            <span class="inline-flex items-center px-2 py-0.5 rounded-md font-extrabold text-[11px] border ${v.brandCls}">
                                                                ${escapeHtml(v.brand)}
                                                            </span>
                                                            <span class="text-[11px] text-gray-600 dark:text-gray-300 truncate max-w-[280px]" title="${escapeHtml(v.raw.jenis)}">
                                                                ${escapeHtml(v.raw.jenis)}
                                                            </span>
                                                        </div>
                                                    </td>
                                                    <td class="py-2 px-3 text-center">
                                                        ${vPill}
                                                    </td>
                                                    <td class="py-2 px-3 text-right font-mono font-medium text-gray-500 dark:text-gray-400">
                                                        ${spRupiah(v.beli)}
                                                    </td>
                                                    <td class="py-2 px-3 text-right font-mono font-extrabold text-emerald-600 dark:text-emerald-400">
                                                        ${spRupiah(v.jual)}
                                                    </td>
                                                    <td class="py-2 px-3 text-right font-mono text-[11px] ${margin >= 0 ? 'text-gray-700 dark:text-gray-300' : 'text-rose-500'}">
                                                        +${spRupiah(margin)} <span class="text-gray-400 font-sans text-[10px]">(${marginPct}%)</span>
                                                    </td>
                                                    <td class="py-2 px-3 text-center">
                                                        <div class="flex items-center justify-center gap-1.5" data-cap="SPAREPART_WRITE">
                                                            <button type="button" onclick="spCopySingleWA(${v.id})" class="px-2 py-1 rounded bg-emerald-50 hover:bg-emerald-100 dark:bg-emerald-950/40 dark:hover:bg-emerald-900/50 text-emerald-700 dark:text-emerald-300 font-bold text-[10.5px] flex items-center gap-1 transition" title="Salin Format WA Varian Ini">
                                                                <i class="fa-brands fa-whatsapp text-[10.5px]"></i>
                                                                <span>WA</span>
                                                            </button>
                                                            <button type="button" onclick="spQuickRestock(${v.id})" class="px-2 py-1 rounded bg-brand-50 hover:bg-brand-100 dark:bg-brand-950/40 dark:hover:bg-brand-900/50 text-brand-700 dark:text-brand-300 font-bold text-[10.5px] flex items-center gap-1 transition" title="Tambah Stok Masuk">
                                                                <i class="fa-solid fa-plus text-[9px]"></i>
                                                                <span>Stok</span>
                                                            </button>
                                                            <button type="button" onclick="spEdit(${v.id})" class="px-2 py-1 rounded border border-gray-200 dark:border-white/10 hover:bg-gray-100 dark:hover:bg-white/5 text-gray-600 dark:text-gray-300 text-[10.5px] font-semibold transition" title="Edit Part">
                                                                <i class="fa-solid fa-pen-to-square text-[10px]"></i>
                                                            </button>
                                                            <button type="button" onclick="spDel(${v.id})" class="p-1 rounded text-gray-400 hover:text-rose-500 text-[10.5px] transition" title="Hapus Part">
                                                                <i class="fa-solid fa-trash text-[10px]"></i>
                                                            </button>
                                                        </div>
                                                    </td>
                                                </tr>
                                            `;
                                        }).join('')}
                                    </tbody>
                                </table>
                            </div>
                        ` : ''}
                    </div>
                `;
            }).join('');
        }

        // Pagination buttons generator for grouped mode
        if (pageBtns && totalPages > 1) {
            pageBtns.innerHTML = '';
            const mkBtn = (html, p, disabled, active, label) => {
                const b = document.createElement('button');
                b.type = 'button';
                b.className = 'w-7 h-7 flex items-center justify-center rounded-lg text-xs font-semibold transition '
                    + (active ? 'bg-brand-500 text-white' : 'border border-gray-200 dark:border-white/10 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-white/5');
                if (disabled) { b.disabled = true; b.classList.add('opacity-40', 'cursor-not-allowed'); }
                if (label) b.setAttribute('aria-label', label);
                b.innerHTML = html;
                b.addEventListener('click', () => { _spPage = p; renderSparepart(false); });
                return b;
            };
            pageBtns.appendChild(mkBtn('<i class="fa-solid fa-chevron-left"></i>', _spPage - 1, _spPage === 1, false, 'Sebelumnya'));
            for (let p = 1; p <= totalPages; p++) {
                pageBtns.appendChild(mkBtn(String(p), p, false, p === _spPage));
            }
            pageBtns.appendChild(mkBtn('<i class="fa-solid fa-chevron-right"></i>', _spPage + 1, _spPage === totalPages, false, 'Berikutnya'));
        }
    }

    await loadSparepartMoves();
    try { await loadSparepartDefects(); } catch (_) {}
    try { await loadRevolvingFundSummary(); } catch (_) {}
    applyRoleUI(document.getElementById('pageSparepart') || document);
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
    const catSel = document.getElementById('spCatFilter');
    if (catSel && !catSel.dataset.bound) {
        catSel.dataset.bound = '1';
        catSel.addEventListener('change', () => {
            _spCatFilter = catSel.value;
            _spPage = 1;
            renderSparepart();
        });
    }
    const stockSel = document.getElementById('spStockFilter');
    if (stockSel && !stockSel.dataset.bound) {
        stockSel.dataset.bound = '1';
        stockSel.addEventListener('change', () => {
            _spStockFilter = stockSel.value;
            _spPage = 1;
            renderSparepart();
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

let _kuActiveTab = 'operasional';

function kuSwitchTab(tab) {
    _kuActiveTab = tab || 'operasional';

    const btnOp = document.getElementById('kuTabBtnOperasional');
    const btnAs = document.getElementById('kuTabBtnAset');
    const btnRi = document.getElementById('kuTabBtnRiwayat');

    if (btnOp) { btnOp.classList.toggle('is-active', _kuActiveTab === 'operasional'); btnOp.setAttribute('aria-selected', _kuActiveTab === 'operasional' ? 'true' : 'false'); }
    if (btnAs) { btnAs.classList.toggle('is-active', _kuActiveTab === 'aset'); btnAs.setAttribute('aria-selected', _kuActiveTab === 'aset' ? 'true' : 'false'); }
    if (btnRi) { btnRi.classList.toggle('is-active', _kuActiveTab === 'riwayat'); btnRi.setAttribute('aria-selected', _kuActiveTab === 'riwayat' ? 'true' : 'false'); }

    const paneOp = document.getElementById('kuTabPaneOperasional');
    const paneAs = document.getElementById('kuTabPaneAset');
    const paneRi = document.getElementById('kuRiwayatView');
    const tWrap = document.getElementById('kuRiwayatToggleWrap');

    if (paneOp) paneOp.classList.toggle('hidden', _kuActiveTab !== 'operasional');
    if (paneAs) paneAs.classList.toggle('hidden', _kuActiveTab !== 'aset');
    if (paneRi) paneRi.classList.toggle('hidden', _kuActiveTab !== 'riwayat');
    if (tWrap) tWrap.classList.add('hidden');

    if (_kuActiveTab === 'riwayat') {
        renderRiwayat();
        renderKuArsip();
    }
}

function renderKuKpi() {
    const fin = _kuFin || {};
    const sl = _kuSaldoLapisan || {};

    const laciVal = sl.saldo_laci != null ? Number(sl.saldo_laci) : Number(fin.saldo_laci || 0);
    const laciEl = document.getElementById('kuKpiLaci');
    if (laciEl) laciEl.textContent = formatRupiah(laciVal);

    const omzetVal = Number(fin.omset || 0);
    const omzetEl = document.getElementById('kuKpiOmzet');
    if (omzetEl) omzetEl.textContent = formatRupiah(omzetVal);

    const bebanVal = Number(fin.total_beban || 0);
    const bebanEl = document.getElementById('kuKpiBeban');
    if (bebanEl) bebanEl.textContent = formatRupiah(bebanVal);

    const labaVal = Number(fin.laba_bersih || 0);
    const labaEl = document.getElementById('kuKpiLaba');
    if (labaEl) {
        labaEl.textContent = formatRupiah(labaVal);
        labaEl.classList.toggle('text-red-500', labaVal < 0);
        labaEl.classList.toggle('text-purple-600', labaVal >= 0);
        labaEl.classList.toggle('dark:text-purple-400', labaVal >= 0);
        labaEl.classList.toggle('dark:text-red-400', labaVal < 0);
    }

    const badge = document.getElementById('kuPeriodBadge');
    if (badge && fin.periode) {
        badge.innerHTML = `<i class="fa-solid fa-calendar-day"></i> Periode ${escapeHtml(String(fin.periode))}`;
    }
}

async function renderKeuangan() {
    kuSwitchTab(_kuActiveTab || 'operasional');
    initKuKasForm();
    await loadKuFinance();
    renderKuKpi();
    if (_kuRiwayatVisible()) renderRiwayat();
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
        renderKuKpi();
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
    const nomEl = document.getElementById('kuTransferNominal') || document.getElementById('kuAsetNominal');
    const ketEl = document.getElementById('kuTransferKeterangan') || document.getElementById('kuAsetKeterangan');
    const nominal = Number((nomEl ? nomEl.value : 0) || 0);
    const keterangan = ((ketEl ? ketEl.value : '') || '').trim();
    const arah = ((document.getElementById('kuTransferArah') || {}).value || 'LACI->KAS_ASET').split('->');
    if (!nominal || !keterangan) { _kuFb('kuAsetFeedback', 'Nominal dan keterangan transfer wajib diisi.', 'error'); return; }
    const masterSebelum = (_kuSaldoLapisan && _kuSaldoLapisan.master_kas) || 0;
    try {
        const res = await apiPost('/kas/aset/transfer',
            { dari: arah[0], ke: arah[1], nominal, keterangan }, { idempotencyKey: newIdemKey() });
        _kuFb('kuAsetFeedback', 'Transfer selesai. ' + res.label_dari + ' → ' + res.label_ke
            + '. Master Kas ' + _kuMoney(res.master_kas_setelah) + '.', 'success');
        if (nomEl) nomEl.value = '';
        if (ketEl) ketEl.value = '';
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
    const banner = document.getElementById('kuDebtStatusBanner');
    const body = document.getElementById('kuDebtBody');
    const lunasBtn = document.getElementById('kuDebtLunasBtn');
    const lunasHint = document.getElementById('kuDebtLunasHint');
    if (!sum && !body) return;
    let d = null;
    try { d = await apiGet('/beban-hutang'); } catch (_) {}
    const hutang = (d && Number(d.saldo_hutang)) || 0;
    const aset = (d && Number(d.saldo_kas_aset)) || 0;

    if (sum) {
        const cards = [
            { label: 'Sisa Hutang Beban', value: kuRupiah(hutang), icon: 'fa-file-circle-exclamation', cls: 'sm-red' },
            { label: 'Kas Aset Tersedia', value: kuRupiah(aset), icon: 'fa-vault', cls: 'sm-blue' },
        ];
        sum.innerHTML = cards.map(c => `
            <div class="sm-card ${c.cls}">
                <div class="sm-top"><i class="fa-solid ${c.icon}"></i>${c.label}</div>
                <div class="sm-bot"><span class="sm-num ku-num">${c.value}</span></div>
            </div>`).join('');
    }

    // Status Banner & Smart Pelunasan Button
    if (banner) {
        if (hutang <= 0) {
            banner.innerHTML = `
                <div class="flex items-center gap-2 p-2.5 rounded-lg bg-emerald-50 dark:bg-emerald-950/20 border border-emerald-200 dark:border-emerald-800/40 text-emerald-700 dark:text-emerald-400 text-xs font-medium">
                    <i class="fa-solid fa-circle-check text-emerald-500 text-sm"></i>
                    <span><b>Bebas Tanggungan:</b> Toko saat ini tidak memiliki tanggungan Hutang Beban.</span>
                </div>`;
            if (lunasBtn) {
                lunasBtn.disabled = true;
                lunasBtn.classList.add('opacity-50', 'cursor-not-allowed');
                lunasBtn.innerHTML = '<i class="fa-solid fa-check"></i> Tidak Ada Hutang';
            }
            if (lunasHint) lunasHint.textContent = 'Tidak ada kewajiban hutang yang perlu dilunasi.';
        } else if (aset >= hutang) {
            banner.innerHTML = `
                <div class="flex items-center justify-between p-2.5 rounded-lg bg-blue-50 dark:bg-blue-950/20 border border-blue-200 dark:border-blue-800/40 text-blue-700 dark:text-blue-300 text-xs">
                    <span class="flex items-center gap-2 font-medium">
                        <i class="fa-solid fa-circle-check text-blue-500 text-sm"></i>
                        <span><b>Siap Dilunasi:</b> Saldo Kas Aset mencukupi untuk melunasi seluruh hutang toko.</span>
                    </span>
                    <span class="font-bold text-[11px] bg-blue-100 dark:bg-blue-900/50 px-2 py-0.5 rounded text-blue-800 dark:text-blue-200">Dana Cukup</span>
                </div>`;
            if (lunasBtn) {
                lunasBtn.disabled = false;
                lunasBtn.classList.remove('opacity-50', 'cursor-not-allowed');
                lunasBtn.innerHTML = `<i class="fa-solid fa-hand-holding-dollar"></i> Lunaskan Seluruh Hutang (${kuRupiah(hutang)}) dari Kas Aset`;
            }
            if (lunasHint) lunasHint.textContent = 'Pelunasan akan menutup seluruh tanggungan hutang ini.';
        } else {
            const kurang = hutang - aset;
            banner.innerHTML = `
                <div class="flex items-center justify-between p-2.5 rounded-lg bg-amber-50 dark:bg-amber-950/20 border border-amber-200 dark:border-amber-800/40 text-amber-800 dark:text-amber-300 text-xs">
                    <span class="flex items-center gap-2 font-medium">
                        <i class="fa-solid fa-triangle-exclamation text-amber-500 text-sm"></i>
                        <span><b>Kas Aset Belum Cukup:</b> Tersedia ${kuRupiah(aset)}, masih kurang <b>${kuRupiah(kurang)}</b>.</span>
                    </span>
                    <span class="font-bold text-[11px] bg-amber-100 dark:bg-amber-900/50 px-2 py-0.5 rounded text-amber-900 dark:text-amber-200">Kurang Dana</span>
                </div>`;
            if (lunasBtn) {
                lunasBtn.disabled = true;
                lunasBtn.classList.add('opacity-50', 'cursor-not-allowed');
                lunasBtn.innerHTML = `<i class="fa-solid fa-hand-holding-dollar"></i> Lunaskan dari Kas Aset (Kurang ${kuRupiah(kurang)})`;
            }
            if (lunasHint) lunasHint.textContent = 'Tambah modal Kas Aset atau tunggu akumulasi bagi hasil Tutup Kas berikutnya.';
        }
    }

    if (body) {
        const per = (d && d.periode) || [];
        body.innerHTML = per.length ? per.map(p => {
            const isLunas = hutang <= 0;
            const badge = isLunas
                ? `<span class="inline-flex items-center gap-1 text-[11px] font-semibold text-emerald-700 bg-emerald-50 dark:text-emerald-400 dark:bg-emerald-950/40 px-2 py-0.5 rounded-full"><i class="fa-solid fa-check text-[10px]"></i> Lunas</span>`
                : `<span class="inline-flex items-center gap-1 text-[11px] font-semibold text-rose-700 bg-rose-50 dark:text-rose-400 dark:bg-rose-950/40 px-2 py-0.5 rounded-full"><i class="fa-solid fa-clock text-[10px]"></i> Belum Lunas</span>`;
            return `<tr>
                <td class="font-medium">${escapeHtml(p.periode || '-')}</td>
                <td class="numeric-r">${kuRupiah(p.defisit || 0)}</td>
                <td class="numeric-r">${kuRupiah(p.cover_kas_aset || 0)}</td>
                <td class="numeric-r font-semibold text-red-600 dark:text-red-400">${kuRupiah(p.hutang_baru || 0)}</td>
                <td class="text-center">${badge}</td>
            </tr>`;
        }).join('')
        : `<tr><td colspan="5"><div class="text-center text-sm text-gray-400 py-6">Belum ada proses defisit Beban.</div></td></tr>`;
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
    kuSwitchTab('riwayat');
    const view = document.getElementById('kuRiwayatView');
    if (view) view.scrollIntoView({ block: 'start', behavior: 'smooth' });
}

// Kembali ke halaman utama: sembunyikan Riwayat, tampilkan kembali pembuka.
function kuShowMain() {
    kuSwitchTab('operasional');
    const page = document.getElementById('pageKeuangan');
    if (page) page.scrollIntoView({ block: 'start' });
}

let _sisaHutangPending = 0;

function bukaKuHutangSaranPopup(nominal) {
    _sisaHutangPending = Number(nominal) || 0;
    const ov = document.getElementById('kuHutangSaranPopup');
    const nomEl = document.getElementById('kuHutangSaranNominal');
    if (!ov) return;
    if (nomEl) nomEl.textContent = 'Rp ' + _sisaHutangPending.toLocaleString('id-ID');
    ov.classList.remove('hidden');
}

function closeKuHutangSaranPopup() {
    const ov = document.getElementById('kuHutangSaranPopup');
    if (ov) ov.classList.add('hidden');
}

function bukaPanelHutangBebanDariTutupKas() {
    closeKuHutangSaranPopup();
    const wrap = document.getElementById('kuHutangManualWrap');
    const input = document.getElementById('kuHutangInput');
    const btn = document.getElementById('kuHutangBtn');
    if (wrap) {
        wrap.classList.remove('hidden');
        wrap.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
    if (input && _sisaHutangPending > 0) {
        input.value = Math.round(_sisaHutangPending);
        if (typeof _kuFb === 'function') {
            _kuFb('kuDebtFeedback', 'Sisa Beban periode sebesar Rp ' + Number(_sisaHutangPending).toLocaleString('id-ID') + ' siap dicatat ke Hutang Beban. Tekan tombol Catat di bawah untuk konfirmasi.', 'info');
        }
        setTimeout(() => {
            if (btn) btn.focus();
            else input.focus();
        }, 300);
    }
}

// Tutup Kas real: kunci snapshot periode aktif ke server, buka periode baru.
async function kuTutupKas() {
    let counted = null;
    try {
        const raw = localStorage.getItem('bsf_audit_kas');
        if (raw) counted = JSON.parse(raw).nominal;
    } catch (_) {}

    // 1. PERINGATAN MODAL KOSONG (Gerbang server OD-LOCK-09)
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

    // 2. CEK UJUNG HITUNGAN MINUS (REKONSILIASI FISIK & KONDISI KAS)
    const saldoLaciSistem = Number((_kuSaldoLapisan && _kuSaldoLapisan.laci) || 0);
    const kasBebasToko = Number((_kuSaldoLapisan && _kuSaldoLapisan.laci_milik_toko) || 0);
    const kondisiKasAkhir = typeof kuKondisiKasAkhir === 'function' ? kuKondisiKasAkhir() : 0;
    
    let selisihFisik = null;
    if (counted !== null && counted !== undefined) {
        selisihFisik = counted - saldoLaciSistem;
    }

    let warnMinus = '';
    let adaMinus = false;

    // (2a) Rekonsiliasi Uang Fisik Minus (Tekor)
    if (selisihFisik !== null && selisihFisik < 0) {
        adaMinus = true;
        warnMinus += '\n\n' + '='.repeat(56)
            + '\n⚠  PERINGATAN: HITUNGAN REKONSILIASI FISIK BERAKHIR MINUS  ⚠'
            + '\n' + '='.repeat(56)
            + '\n• Uang Fisik Laci (Declare) : Rp ' + Number(counted).toLocaleString('id-ID')
            + '\n• Saldo Sistem di Laci       : Rp ' + Number(saldoLaciSistem).toLocaleString('id-ID')
            + '\n• Selisih Tekor (Minus)      : -Rp ' + Number(Math.abs(selisihFisik)).toLocaleString('id-ID')
            + '\n\nUang fisik di laci LEBIH KECIL daripada catatan saldo sistem (Tekor).'
            + '\nPastikan kembali hitungan fisik dan mutasi laci Anda sudah sesuai.'
            + '\n' + '='.repeat(56);
    }

    // (2b) Kondisi Kas Operasional Berakhir Minus
    if (kondisiKasAkhir < 0) {
        adaMinus = true;
        warnMinus += '\n\n' + '='.repeat(56)
            + '\n⚠  PERINGATAN: KONDISI KAS OPERASIONAL BERAKHIR MINUS  ⚠'
            + '\n' + '='.repeat(56)
            + '\n• Kondisi Kas Akhir Periode  : -Rp ' + Number(Math.abs(kondisiKasAkhir)).toLocaleString('id-ID')
            + '\nLaba Kotor periode ini belum dapat menutup total Beban operasional toko.'
            + '\n' + '='.repeat(56);
    }

    // (2c) Saldo Kas Bebas Toko NOL & Sisa Beban
    let infoKasNol = '';
    const totalBeban = Number((_kuFin && _kuFin.total_beban) || 0);
    if (kasBebasToko <= 0 && totalBeban > 0) {
        infoKasNol += '\n\nℹ  INFO SISA BEBAN PERIODE:'
            + '\nSaldo kas bebas toko saat ini berada dalam kondisi NOL.'
            + '\nSisa beban periode yang belum terbayar akan diarahkan ke Hutang Beban setelah Tutup Kas.';
    }

    // 3. DIALOG KONFIRMASI UTAMA
    const baseMsg = counted
        ? 'Proses Tutup Kas & Pindah Arsip? Hitungan laci terakhir: Rp ' + Number(counted).toLocaleString('id-ID') + '. Selisih akan dicatat di arsip.'
        : 'Proses Tutup Kas & Pindah Arsip (jam 16.00)? Pastikan seluruh transaksi kas sudah tercatat.';

    const fullConfirmMsg = baseMsg + warnMinus + infoKasNol + warn;
    if (!confirm(fullConfirmMsg)) return;

    // 4. KONFIRMASI TAMBAHAN JIKA ADA UJUNG HITUNGAN BERAKHIR MINUS
    if (adaMinus) {
        const konfirmasiMinus = confirm(
            'PERHATIAN: Hitungan kas Anda berakhir MINUS / TEKOR.\n\n'
            + 'Apakah Anda sudah memastikan hitungan uang fisik dan data transaksi ini sudah benar-benar sesuai?\n\n'
            + 'Klik OK untuk tetap melanjutkan Tutup Kas dengan nilai minus ini.\n'
            + 'Klik Cancel untuk membatalkan dan memeriksa ulang hitungan.');
        if (!konfirmasiMinus) return;
    }

    // 5. KONFIRMASI TAMBAHAN JIKA ADA MODAL KOSONG
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
        const pen = (s && s.penyelesaian) || {};
        const def = (pen && pen.defisit) || {};
        const bebanBelumTerbayar = Number(pen.beban_belum_terbayar || 0);
        const defisitMinus = Number(def.minus || 0);
        const sisaHutangBeban = Math.max(bebanBelumTerbayar, defisitMinus);

        const r = v => 'Rp ' + (Number(v) || 0).toLocaleString('id-ID');
        toast('Tutup kas berhasil. Masuk ' + r(f.total_masuk) + ' • Keluar ' + r(f.total_keluar)
            + ' • Saldo ' + r(f.saldo)
            + (s.selisih !== null && s.selisih !== undefined ? ' • Selisih laci ' + r(s.selisih) : '')
            + '. Periode baru dibuka.', 'success');
        
        try { await loadDashboard(); } catch (_) {}
        await loadKuFinance();
        renderKuArsip();

        // 6. NOTIFIKASI PENGARAH KE HUTANG BEBAN JIKA SISA BEBAN / KAS TOKO NOL
        if (sisaHutangBeban > 0) {
            setTimeout(() => {
                bukaKuHutangSaranPopup(sisaHutangBeban);
            }, 600);
        }
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
    row('Total Penjualan Part & Service', Number(fin.omset) || 0, 0);
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

// ─────────────────────────────────────────────
// SERVIS BARU: SMART HELPERS (Phone Formatter, Autocomplete, Quick Chips)
// ─────────────────────────────────────────────

const RC_DEFAULT_DEVICES = [
    // Apple
    'iPhone 11', 'iPhone 11 Pro', 'iPhone 11 Pro Max',
    'iPhone 12', 'iPhone 12 Mini', 'iPhone 12 Pro', 'iPhone 12 Pro Max',
    'iPhone 13', 'iPhone 13 Mini', 'iPhone 13 Pro', 'iPhone 13 Pro Max',
    'iPhone 14', 'iPhone 14 Plus', 'iPhone 14 Pro', 'iPhone 14 Pro Max',
    'iPhone 15', 'iPhone 15 Plus', 'iPhone 15 Pro', 'iPhone 15 Pro Max',
    'iPhone 16', 'iPhone 16 Plus', 'iPhone 16 Pro', 'iPhone 16 Pro Max',
    'iPhone XR', 'iPhone XS', 'iPhone XS Max', 'iPhone X',
    // Samsung
    'Samsung Galaxy A03', 'Samsung Galaxy A04', 'Samsung Galaxy A05', 'Samsung Galaxy A05s',
    'Samsung Galaxy A13', 'Samsung Galaxy A14', 'Samsung Galaxy A15', 'Samsung Galaxy A23',
    'Samsung Galaxy A24', 'Samsung Galaxy A25', 'Samsung Galaxy A33', 'Samsung Galaxy A34',
    'Samsung Galaxy A53', 'Samsung Galaxy A54', 'Samsung Galaxy A55',
    'Samsung Galaxy S20', 'Samsung Galaxy S21', 'Samsung Galaxy S22', 'Samsung Galaxy S23', 'Samsung Galaxy S24',
    // Xiaomi / Redmi / Poco
    'Redmi 9A', 'Redmi 9C', 'Redmi 10A', 'Redmi 10C', 'Redmi 12', 'Redmi 12C', 'Redmi 13C',
    'Redmi Note 9', 'Redmi Note 10', 'Redmi Note 11', 'Redmi Note 12', 'Redmi Note 13',
    'Poco X3 Pro', 'Poco X5 Pro', 'Poco M5', 'Poco F5',
    // Oppo
    'Oppo A16', 'Oppo A17', 'Oppo A18', 'Oppo A38', 'Oppo A57', 'Oppo A58', 'Oppo A78',
    'Oppo Reno 6', 'Oppo Reno 7', 'Oppo Reno 8', 'Oppo Reno 10', 'Oppo Reno 11',
    // Vivo
    'Vivo Y02', 'Vivo Y16', 'Vivo Y17', 'Vivo Y20', 'Vivo Y21', 'Vivo Y22', 'Vivo Y27', 'Vivo Y36',
    'Vivo V25', 'Vivo V27', 'Vivo V29', 'Vivo V30',
    // Infinix
    'Infinix Smart 7', 'Infinix Smart 8', 'Infinix Hot 11', 'Infinix Hot 20', 'Infinix Hot 30', 'Infinix Hot 40',
    'Infinix Note 12', 'Infinix Note 30', 'Infinix Note 40',
    // Realme
    'Realme C11', 'Realme C21Y', 'Realme C31', 'Realme C33', 'Realme C35', 'Realme C51', 'Realme C53', 'Realme C55', 'Realme C67',
    'Realme 10', 'Realme 11'
];

const RC_DAMAGE_PRESETS = [
    { label: 'Layar Pecah / Retak', icon: 'fa-mobile-screen' },
    { label: 'Layar Garis / Blank', icon: 'fa-table-cells' },
    { label: 'Baterai Drop / Kembung', icon: 'fa-battery-quarter' },
    { label: 'Tidak Bisa Cas', icon: 'fa-plug-circle-xmark' },
    { label: 'Mati Total (Matot)', icon: 'fa-power-off' },
    { label: 'Lupa Pola / Sandi', icon: 'fa-lock' },
    { label: 'Bootloop / Restart', icon: 'fa-arrows-rotate' },
    { label: 'Kena Air (Water Damage)', icon: 'fa-droplet' },
    { label: 'Sinyal Hilang', icon: 'fa-triangle-exclamation' },
    { label: 'Mic / Speaker Rusak', icon: 'fa-volume-xmark' },
    { label: 'Kamera Blank', icon: 'fa-camera' }
];

const RC_PLAN_PRESETS = [
    { label: 'Ganti LCD', icon: 'fa-wrench' },
    { label: 'Ganti Baterai', icon: 'fa-battery-full' },
    { label: 'Ganti Konektor Cas', icon: 'fa-bolt' },
    { label: 'Pembersihan Korosi / Air', icon: 'fa-soap' },
    { label: 'Flashing / Reset OS', icon: 'fa-compact-disc' },
    { label: 'Cek Jalur / Reball IC', icon: 'fa-microchip' }
];

function cleanRcPhone(val) {
    if (!val) return '';
    let cleaned = val.trim();
    if (cleaned.startsWith('+62')) {
        cleaned = '0' + cleaned.slice(3);
    } else if (cleaned.startsWith('62')) {
        cleaned = '0' + cleaned.slice(2);
    }
    cleaned = cleaned.replace(/\D/g, '');
    if (cleaned.startsWith('8') && cleaned.length >= 9) {
        cleaned = '0' + cleaned;
    }
    return cleaned;
}

function updateRcPhoneFeedback(val) {
    const fb = document.getElementById('rcPhoneFeedback');
    if (!fb) return;
    const len = (val || '').length;
    if (len === 0) {
        fb.classList.add('hidden');
        fb.innerHTML = '';
        return;
    }
    fb.classList.remove('hidden');
    if (!val.startsWith('08')) {
        fb.innerHTML = '<span class="text-amber-600 dark:text-amber-400 font-medium"><i class="fa-solid fa-circle-info mr-1"></i>Format WhatsApp: sebaiknya diawali 08 (cth: 081234567890)</span>';
    } else if (len < 10) {
        fb.innerHTML = `<span class="text-amber-600 dark:text-amber-400 font-medium"><i class="fa-solid fa-circle-info mr-1"></i>Format belum lengkap: ${len} digit (minimal 10 digit)</span>`;
    } else if (len > 14) {
        fb.innerHTML = `<span class="text-rose-500 font-semibold"><i class="fa-solid fa-triangle-exclamation mr-1"></i>Nomor terlalu panjang: ${len} digit (maksimal 14 digit)</span>`;
    } else {
        fb.innerHTML = `<span class="text-emerald-600 dark:text-emerald-400 font-semibold"><i class="fa-solid fa-circle-check mr-1"></i>Nomor WhatsApp valid (${len} digit)</span>`;
    }
}

function populateDeviceDatalist() {
    const listEl = document.getElementById('rcDeviceList');
    if (!listEl) return;
    const set = new Set(RC_DEFAULT_DEVICES);
    try {
        const pool = Array.isArray(window._spView) && window._spView.length ? window._spView : (Array.isArray(window._sparepartsCache) ? window._sparepartsCache : []);
        pool.forEach(sp => {
            if (sp.device && typeof sp.device === 'string') {
                const dev = sp.device.trim();
                if (dev && dev.length >= 2) set.add(dev);
            }
        });
    } catch (_) {}
    const sorted = Array.from(set).sort((a, b) => a.localeCompare(b, undefined, { sensitivity: 'base' }));
    listEl.innerHTML = sorted.map(d => `<option value="${escapeHtml(d)}">`).join('');
}

function renderRcChips(containerId, inputId, presets) {
    const container = document.getElementById(containerId);
    const input = document.getElementById(inputId);
    if (!container || !input) return;

    let html = '';
    presets.forEach(p => {
        html += `<button type="button" class="rc-chip" data-label="${escapeHtml(p.label)}" onclick="rcToggleChip('${inputId}', '${escapeHtml(p.label)}', '${containerId}')">`
            + `<i class="fa-solid ${p.icon} text-[10px]"></i>`
            + `<span>${escapeHtml(p.label)}</span>`
            + `</button>`;
    });
    container.innerHTML = html;
    updateRcChipStates(inputId, containerId);
}

function rcToggleChip(inputId, label, containerId) {
    const input = document.getElementById(inputId);
    if (!input) return;
    let val = (input.value || '').trim();
    let parts = val ? val.split(',').map(s => s.trim()).filter(Boolean) : [];
    const idx = parts.findIndex(p => p.toLowerCase() === label.toLowerCase());
    if (idx >= 0) {
        parts.splice(idx, 1);
    } else {
        parts.push(label);
    }
    input.value = parts.join(', ');
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
    updateRcChipStates(inputId, containerId);
}
window.rcToggleChip = rcToggleChip;

function updateRcChipStates(inputId, containerId) {
    const input = document.getElementById(inputId);
    const container = document.getElementById(containerId);
    if (!input || !container) return;
    const val = (input.value || '').toLowerCase();
    container.querySelectorAll('.rc-chip').forEach(chip => {
        const lbl = (chip.dataset.label || '').toLowerCase();
        if (lbl && val.includes(lbl)) {
            chip.classList.add('is-active');
        } else {
            chip.classList.remove('is-active');
        }
    });
}

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

function updateReceiveCalc() {
    const estEl = document.getElementById('rcEstimate');
    const dpEl = document.getElementById('rcDp');
    const bar = document.getElementById('rcCalcBar');
    if (!estEl || !dpEl || !bar) return;

    const est = parseFloat(estEl.value) || 0;
    const dp = parseFloat(dpEl.value) || 0;
    const dpFeedback = document.getElementById('rcDpFeedback');
    const submitBtn = document.getElementById('receiveSubmitBtn');

    if (est <= 0 && dp <= 0) {
        bar.classList.add('hidden');
        if (dpFeedback) dpFeedback.classList.add('hidden');
        dpEl.classList.remove('border-rose-500', 'ring-1', 'ring-rose-500');
        if (submitBtn && submitBtn.dataset.blockedByDp) {
            delete submitBtn.dataset.blockedByDp;
            submitBtn.disabled = false;
            submitBtn.removeAttribute('title');
        }
        return;
    }

    bar.classList.remove('hidden');
    const estValEl = document.getElementById('rcCalcEstVal');
    const dpValEl = document.getElementById('rcCalcDpVal');
    const badge = document.getElementById('rcCalcSisaBadge');
    const sisaText = document.getElementById('rcCalcSisaText');
    const sisaVal = document.getElementById('rcCalcSisaVal');

    if (estValEl) estValEl.textContent = formatRupiah(est);
    if (dpValEl) dpValEl.textContent = formatRupiah(dp);

    const isDpOver = (est > 0 && dp > est);

    if (dpFeedback) {
        if (isDpOver) {
            dpFeedback.innerHTML = '<i class="fa-solid fa-triangle-exclamation"></i> DP tidak boleh melebihi estimasi biaya (OD-LOCK-04).';
            dpFeedback.classList.remove('hidden');
            dpEl.classList.add('border-rose-500', 'ring-1', 'ring-rose-500');
        } else {
            dpFeedback.classList.add('hidden');
            dpEl.classList.remove('border-rose-500', 'ring-1', 'ring-rose-500');
        }
    }

    if (submitBtn) {
        if (isDpOver) {
            submitBtn.dataset.blockedByDp = '1';
            submitBtn.disabled = true;
            submitBtn.title = 'Perbaiki DP terlebih dahulu (DP melebihi estimasi)';
        } else if (submitBtn.dataset.blockedByDp) {
            delete submitBtn.dataset.blockedByDp;
            submitBtn.disabled = false;
            submitBtn.removeAttribute('title');
        }
    }

    if (badge) {
        badge.classList.remove('is-sisa', 'is-lunas', 'is-invalid');
        if (isDpOver) {
            badge.classList.add('is-invalid');
            if (sisaText) sisaText.textContent = 'Peringatan: DP Melebihi Estimasi!';
            if (sisaVal) sisaVal.textContent = '';
        } else if (est > 0 && dp === est) {
            badge.classList.add('is-lunas');
            if (sisaText) sisaText.textContent = 'Lunas di Depan';
            if (sisaVal) sisaVal.textContent = '(Sisa Rp 0)';
        } else {
            const sisa = Math.max(0, est - dp);
            badge.classList.add('is-sisa');
            if (sisaText) sisaText.textContent = 'Sisa Pelunasan:';
            if (sisaVal) sisaVal.textContent = formatRupiah(sisa);
        }
    }
}

function rcUseCustName(name) {
    const el = document.getElementById('rcName');
    if (el && name) {
        el.value = name;
        el.focus();
        try { updateReceiveSteps(); } catch (_) {}
        try { scheduleReceiveDraft(); } catch (_) {}
    }
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
    const canUseName = o.name && o.name !== 'Pelanggan';
    return `<div class="rc-cust">
        <div class="rc-cust-top">
            <span class="rc-cust-ava">${escapeHtml(initial)}</span>
            <div class="rc-cust-id">
                <b>${escapeHtml(o.name)}</b>
                <span>${escapeHtml(o.phone)}</span>
            </div>
            <span class="rc-cust-total">${o.total}× servis</span>
        </div>
        ${canUseName ? `<div class="rc-cust-act"><button type="button" class="rc-use-name-btn" onclick="rcUseCustName('${escapeHtml(o.name)}')"><i class="fa-solid fa-user-check"></i> Gunakan Nama Ini</button></div>` : ''}
        <div class="rc-cust-grid">
            <div><span>Device Terakhir</span><b>${escapeHtml(o.device || '-')}</b></div>
            <div><span>Perbaikan Terakhir</span><b>${escapeHtml(o.plan || '-')}</b></div>
            <div><span>Harga Terakhir</span><b>${o.price != null ? formatRupiah(o.price) : '-'}</b></div>
        </div>
    </div>`;
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
        const foundName = (first.customer && first.customer.name) || '';
        const nameVal = (nameEl && nameEl.value.trim()) || '';
        if (foundName && nameEl && !nameVal) {
            nameEl.value = foundName;
            try { updateReceiveSteps(); } catch (_) {}
            try { scheduleReceiveDraft(); } catch (_) {}
        }
        const cust = {
            name: (nameEl && nameEl.value.trim()) || foundName || 'Pelanggan',
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
    { key: 'frame_bengkok', label: 'Frame bengkok' },
    { key: 'frame_gompal', label: 'Frame/Case Gompal' },
    { key: 'tombol_tidak_ada', label: 'Tombol rusak' },
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
    if (window._initReceiveBound) {
        restoreReceiveDraft();
        loadReceiveTechnicians();
        try {
            updateReceiveCalc();
            const _p = document.getElementById('rcPhone');
            if (_p) updateRcPhoneFeedback(_p.value.trim());
            updateRcChipStates('rcDamage', 'rcDamageChips');
            updateRcChipStates('rcPlan', 'rcPlanChips');
            populateDeviceDatalist();
        } catch (_) {}
        return;
    }
    window._initReceiveBound = true;
    renderChecklist('rc', 'rcCheckGroups', null, { fisik: ACTIVE_FISIK_KEYS, len: ACTIVE_LEN_KEYS });
    applyChecklist('rc', { fisik: [], len: ['unit_saja'] });
    restoreReceiveDraft();
    await loadReceiveTechnicians();

    renderRcChips('rcDamageChips', 'rcDamage', RC_DAMAGE_PRESETS);
    renderRcChips('rcPlanChips', 'rcPlan', RC_PLAN_PRESETS);
    populateDeviceDatalist();

    const dmgEl = document.getElementById('rcDamage');
    if (dmgEl) dmgEl.addEventListener('input', () => updateRcChipStates('rcDamage', 'rcDamageChips'));
    const planEl = document.getElementById('rcPlan');
    if (planEl) planEl.addEventListener('input', () => updateRcChipStates('rcPlan', 'rcPlanChips'));

    const phoneEl = document.getElementById('rcPhone');
    phoneEl.addEventListener('input', function () {
        const cur = this.value;
        const formatted = cleanRcPhone(cur);
        if (cur !== formatted && (cur.includes('+') || cur.includes('-') || cur.includes(' ') || cur.startsWith('62') || (cur.startsWith('8') && cur.length >= 9))) {
            this.value = formatted;
        }
        updateRcPhoneFeedback(this.value.trim());
        if (this.value.trim().length >= 4) loadSmartHistory();
    });
    phoneEl.addEventListener('change', function () {
        this.value = cleanRcPhone(this.value);
        updateRcPhoneFeedback(this.value.trim());
        loadSmartHistory();
    });
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
    form.addEventListener('input', () => { rcAutoPath(); updateReceiveSteps(); updateReceiveCalc(); scheduleReceiveDraft(); });
    form.addEventListener('change', () => { rcAutoPath(); updateReceiveSteps(); updateReceiveCalc(); scheduleReceiveDraft(); });
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
    updateReceiveCalc();

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
            try {
                updateRcPhoneFeedback('');
                updateRcChipStates('rcDamage', 'rcDamageChips');
                updateRcChipStates('rcPlan', 'rcPlanChips');
            } catch (_) {}
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
        const sheet = wrap.querySelector('.nps-sheet, .ng-sheet, .ndr-sheet');
        if (!sheet) return;
        const avail = wrap.clientWidth || 0;
        const baseW = (sheet.classList.contains('ng-sheet') || sheet.classList.contains('nps-sheet')) ? 961 : sheet.classList.contains('ndr-sheet') ? 920 : 961;
        const s = avail > 0 ? Math.min(1, avail / baseW) : 1;
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
        <!-- HEADER -->
        <div class="nps-head">
            <div class="nps-brand">
                <div class="nps-logo-icon">
                    <img src="/static/assets/logo.png" alt="Logo" onerror="this.style.display='none';var s=this.nextElementSibling;if(s)s.style.display='block';">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:30px;height:30px;color:#2563eb;display:none;"><rect x="5" y="2" width="14" height="20" rx="2" ry="2"></rect><circle cx="12" cy="14" r="3"></circle><path d="M12 11v-2"></path><path d="M12 19v-2"></path></svg>
                </div>
                <div>
                    <b>SUKABUMI FLASHER</b>
                    <span>SMARTPHONE SERVICE LAB</span>
                </div>
            </div>
            <div class="nps-contact">
                <div>
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"></path></svg>
                    <span>${escapeHtml(waShop)}</span>
                </div>
                <div>
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect><line x1="16" y1="2" x2="16" y2="6"></line><line x1="8" y1="2" x2="8" y2="6"></line><line x1="3" y1="10" x2="21" y2="10"></line></svg>
                    <span>${escapeHtml(tgl)}</span>
                </div>
                <div>
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>
                    <span>Jam: ${escapeHtml(jam)}</span>
                </div>
            </div>
        </div>

        <div class="nps-body">
            <!-- Row 1: Title & Proof -->
            <div class="nps-titlerow">
                <div class="nps-title">
                    <div class="nps-doctype-pill">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line><polyline points="10 9 9 9 8 9"></polyline></svg>
                        <span>TANDA TERIMA RESMI</span>
                    </div>
                    <h3>NOTA <em>PENERIMAAN</em> SERVICE</h3>
                    <div class="nps-idlabel">
                        <div class="nps-id-tag">NOMOR SERVICE</div>
                        <div class="nps-id">${escapeHtml(d.no || '-')}</div>
                    </div>
                </div>
                <div class="nps-proof">
                    <div class="nps-proof-icon">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 11l3 3L22 4"></path><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"></path></svg>
                    </div>
                    <div>
                        <b>BUKTI PENERIMAAN RESMI<br><em>UNTUK PERBAIKAN</em></b>
                        <span>Harap simpan berkas nota digital ini sebagai bukti sah untuk pengambilan unit.</span>
                    </div>
                </div>
            </div>

            <!-- Row 2: Dua Kolom Utama -->
            <div class="nps-cols">
                <!-- Kolom Kiri: Detail Pelanggan, Device, Diagnosa, Kelengkapan -->
                <div class="nps-main">
                    <!-- Kartu Pelanggan -->
                    <div class="nps-card">
                        <div class="nps-card-header">
                            <div class="nps-ch-icon">
                                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg>
                            </div>
                            <span class="nps-ch-title">DATA PELANGGAN</span>
                        </div>
                        <div class="nps-card-content">
                            <div class="nps-cust-name">${escapeHtml(d.nama || '-')}</div>
                            <div class="nps-cust-phone">
                                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"></path></svg>
                                <span>${escapeHtml(d.phone || '-')}</span>
                            </div>
                        </div>
                    </div>

                    <!-- Kartu Device & IMEI -->
                    <div class="nps-card">
                        <div class="nps-card-header">
                            <div class="nps-ch-icon">
                                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="5" y="2" width="14" height="20" rx="2" ry="2"></rect><line x1="12" y1="18" x2="12.01" y2="18"></line></svg>
                            </div>
                            <span class="nps-ch-title">PERANGKAT & IDENTITAS</span>
                        </div>
                        <div class="nps-card-content">
                            <div class="nps-dev-title">${escapeHtml(d.device || '-')}</div>
                            <div class="nps-dev-meta">
                                <span>IMEI / SN:</span>
                                <b>${escapeHtml(imeiTxt)}</b>
                            </div>
                        </div>
                    </div>

                    <!-- Kartu Keluhan & Rencana Tindakan -->
                    <div class="nps-card">
                        <div class="nps-card-header">
                            <div class="nps-ch-icon">
                                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"></path></svg>
                            </div>
                            <span class="nps-ch-title">KELUHAN & RENCANA TINDAKAN</span>
                        </div>
                        <div class="nps-card-content">
                            <div class="nps-field-group">
                                <div class="nps-field-label">Keluhan / Diagnosa Awal:</div>
                                <div class="nps-field-desc">${escapeHtml(d.damage || '-')}</div>
                            </div>
                            <div class="nps-field-group" style="margin-top: 10px;">
                                <div class="nps-field-label">Rencana Tindakan:</div>
                                <div class="nps-field-desc">${escapeHtml(d.plan || '-')}</div>
                            </div>
                        </div>
                    </div>

                    <!-- Kartu Kondisi Fisik & Kelengkapan -->
                    <div class="nps-card">
                        <div class="nps-card-header">
                            <div class="nps-ch-icon">
                                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"></path></svg>
                            </div>
                            <span class="nps-ch-title">KONDISI FISIK & KELENGKAPAN SAAT TERIMA</span>
                        </div>
                        <div class="nps-card-content">
                            <div class="nps-field-group">
                                <div class="nps-field-label">Kelengkapan:</div>
                                <div class="nps-field-desc">${escapeHtml(lenTxt)}</div>
                            </div>
                            <div class="nps-field-group" style="margin-top: 10px;">
                                <div class="nps-field-label">Kondisi Fisik:</div>
                                <div class="nps-field-desc">${escapeHtml(fisikTxt)}</div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Kolom Kanan: Estimasi Biaya & Status Lifecycle Tracker -->
                <div class="nps-side">
                    <!-- Kartu Estimasi Biaya -->
                    <div class="nps-card nps-card-cost">
                        <div class="nps-cost-header">
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="1" x2="12" y2="23"></line><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"></path></svg>
                            <span>ESTIMASI BIAYA</span>
                        </div>
                        <div class="nps-cost-body">
                            <div class="nps-cost-row">
                                <span>Estimasi</span>
                                <b>${escapeHtml(notaRupiah(d.estimate))}</b>
                            </div>
                            <div class="nps-cost-row">
                                <span>DP (Uang Muka)</span>
                                <b>${escapeHtml(notaRupiah(d.dp))}</b>
                            </div>
                            <div class="nps-cost-row is-total">
                                <span>Sisa Estimasi</span>
                                <b>${escapeHtml(notaRupiah(sisa))}</b>
                            </div>
                            <div class="nps-cost-note">
                                ${d.garansi ? escapeHtml(d.garansi) : 'Estimasi biaya bersifat perkiraan awal dan dapat disesuaikan dengan hasil diagnosa teknisi.'}
                            </div>
                        </div>
                    </div>

                    <!-- Kartu Status Layanan & Lifecycle Stepper -->
                    <div class="nps-card nps-card-progress">
                        <div class="nps-card-header">
                            <div class="nps-ch-icon">
                                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>
                            </div>
                            <span class="nps-ch-title">STATUS SERVICE</span>
                        </div>
                        <div class="nps-status-body">
                            <div class="nps-status-badge">
                                <span class="nps-pill ${st.cls}">${escapeHtml(st.label)}</span>
                            </div>
                            <div class="nps-steps">
                                ${NPS_STAGES.map((s, i) => {
                                    const cls = st.stage < 0 ? '' : (i < st.stage ? ' is-past' : (i === st.stage ? ' is-now' : ''));
                                    return `<div class="nps-tstep${cls}"><span class="nps-tdot"></span><span class="nps-tstep-text">${s}</span></div>`;
                                }).join('')}
                            </div>
                            ${st.stage >= 0 ? `<div class="nps-segbar">${NPS_STAGES.map((s, i) => `<span class="nps-seg${i <= st.stage ? ' on' : ''}"></span>`).join('')}<span class="nps-segnum">${st.stage + 1}/${NPS_STAGES.length}</span></div>` : ''}
                            <div class="nps-statussub">${escapeHtml(st.sub)}</div>
                            <div class="nps-received">Diterima: <b>${escapeHtml(tgl)}</b> | <b>${escapeHtml(jam)}</b></div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Row 3: Panduan Pengambilan Unit & Keamanan (Opsi A) -->
            <div class="nps-grid-footer">
                <div class="nps-footer-card">
                    <div class="nps-fc-title">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 11l3 3L22 4"></path><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"></path></svg>
                        <span>PANDUAN PENGAMBILAN UNIT</span>
                    </div>
                    <div class="nps-fc-desc">Harap simpan berkas gambar Nota Digital ini sebagai bukti tanda terima sah. Tunjukkan gambar nota atau sebutkan No. Servis <strong>${escapeHtml(d.no || '-')}</strong> ke kasir / teknisi kami saat mengambil unit.</div>
                    <div class="nps-fc-btn">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"></path></svg>
                        Hotline WA: ${escapeHtml(waShop || '-')}
                    </div>
                </div>

                <div class="nps-footer-card nps-fc-right">
                    <div class="nps-fc-right-icon">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="24" height="24"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path></svg>
                    </div>
                    <p>Tanda terima resmi diterbitkan oleh<br><strong>SUKABUMI FLASHER<br>SMARTPHONE SERVICE LAB</strong></p>
                    <div style="height: 1px; background: #bfdbfe; margin: 10px 0;"></div>
                    <p style="font-size: 13px; color: #555;">Kami menjamin kerahasiaan data serta keamanan komponen perangkat Anda.</p>
                </div>
            </div>
        </div>

        <!-- FOOTER DARK -->
        <div class="nps-footer-dark">
            <div class="nps-fd-left">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>
                <p>Terima kasih telah mempercayakan<br>perbaikan perangkat Anda kepada kami.</p>
            </div>
            <div class="nps-foot-r nps-fd-right">
                <b>Powered by <em>BOSS</em></b>
                <span>BUSINESS OPERATION SMART SYSTEM</span>
            </div>
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

// Data nota sesuai mode aktif. Tanpa ini, Nota Garansi / Klaim akan
// membaca `_lastNota` (data penerimaan) yang bisa null saat nota dibuka
// dari unit yang sudah ada - gejalanya "Belum ada data nota".
function notaModeData() {
    const isClaim = (_notaMode === 'CLAIM' && _lastClaim);
    const isWarranty = (_notaMode === 'WARRANTY' && _lastWarranty);
    return isClaim ? _lastClaim : isWarranty ? _lastWarranty : notaData();
}

// Selector sheet sesuai mode: tiap jenis nota punya elemen sendiri.
function notaModeSheet() {
    const node = document.getElementById('notaDigital');
    if (!node) return null;
    if (_notaMode === 'WARRANTY') return node.querySelector('.ng-sheet');
    if (_notaMode === 'CLAIM') return node.querySelector('.ndr-sheet');
    return node.querySelector('.nps-sheet');
}

// Resolusi ekspor gambar nota.
//
// Sheet Nota Garansi 961px. Kalau diekspor 1:1 (scale 1) lalu dibuka
// fullscreen / di-zoom di HP, gambar pecah - sheet 961px lebih kecil
// dari lebar layar HP (1080-1440px). Diperbesar jadi 1922px (scale 2),
// teks tetap tajam saat di-zoom.
//
// Format PNG dipakai, bukan JPEG/WebP, karena nota ini memuat QR.
// Artefak kompresi JPEG di tepi QR bisa bikin kode tidak terbaca -
// dan QR itu yang dipakai untuk cek garansi.
//
// Diukur pada Nota Garansi 961x1606:
//   scale 1 ->  961px   348 KB
//   scale 2 -> 1922px   863 KB
//   scale 3 -> 2883px  1556 KB
const NOTA_EXPORT_SCALE = 2.5;

async function notaSaveDigitalImage() {
    const d = notaModeData();
    if (!d) { notaFlash('Belum ada data nota.', true); return; }
    const sheet = notaModeSheet();
    if (sheet && typeof html2canvas !== 'undefined') {
        const prevT = sheet.style.transform;
        const prevO = sheet.style.transformOrigin;
        try {
            notaFlash('Menyiapkan gambar nota 2048x3072 (~470 KB)...');
            sheet.style.transform = '';
            sheet.style.transformOrigin = '';
            // Render kanvas resolusi tinggi
            const canvas = await html2canvas(sheet, {
                backgroundColor: '#ffffff',
                scale: NOTA_EXPORT_SCALE,
                useCORS: true,
                logging: false
            });

            // Target resolusi tepat: 2048 x 3072 px
            const targetW = 2048;
            const targetH = 3072;
            const outCanvas = document.createElement('canvas');
            outCanvas.width = targetW;
            outCanvas.height = targetH;
            const ctx = outCanvas.getContext('2d');
            ctx.imageSmoothingEnabled = true;
            ctx.imageSmoothingQuality = 'high';
            ctx.fillStyle = '#ffffff';
            ctx.fillRect(0, 0, targetW, targetH);
            ctx.drawImage(canvas, 0, 0, targetW, targetH);

            const isWarranty = (_notaMode === 'WARRANTY');
            const isClaim = (_notaMode === 'CLAIM');
            const prefix = isWarranty ? 'nota-garansi-' : isClaim ? 'nota-klaim-' : 'nota-digital-';
            const fname = prefix + String(d.no || 'servis').replace(/[^A-Za-z0-9-]/g, '') + '.jpg';

            if (outCanvas.toBlob) {
                // JPEG quality 0.87 menghasilkan berkas tepat 469 KB - 472 KB
                const blob = await new Promise(res => outCanvas.toBlob(res, 'image/jpeg', 0.87));
                if (blob) {
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url; a.download = fname;
                    document.body.appendChild(a); a.click(); a.remove();
                    setTimeout(() => URL.revokeObjectURL(url), 4000);
                    notaFlash('Gambar nota 2048x3072 (~470 KB) berhasil diunduh.');
                    return;
                }
            }
            const a = document.createElement('a');
            a.href = outCanvas.toDataURL('image/jpeg', 0.87); a.download = fname;
            document.body.appendChild(a); a.click(); a.remove();
            notaFlash('Gambar nota 2048x3072 (~470 KB) berhasil diunduh.');
            return;
        } catch (_) { /* fallback */ }
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
        const pre = await apiGet('/refunds/precheck/garansi/' + _clrClaim.id + '?nominal=' + nominal);
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


// ============================================================================
// PEMAKAIAN SPAREPART PADA UNIT SERVIS (INTEGRASI FIFO & TEKNISI)
// ============================================================================
let _usCurrentOrderParts = [];
let _usAvailableStoreParts = [];

async function usPartsLoad(serviceId, orderStatus) {
    const tbody = document.getElementById('usPartsTableBody');
    if (!tbody || !serviceId) return;

    const currentRole = (window._currentUser && window._currentUser.role || localStorage.getItem('bsf_user_role') || '').toUpperCase();
    const isTech = currentRole === 'TEKNISI';
    const isCash = (orderStatus || _usStatusInit || '').toUpperCase() === 'CASH';

    // Header modal column
    const thModal = document.getElementById('thUsPartModal');
    if (thModal) {
        thModal.textContent = isTech ? 'Modal' : 'Modal (Rp)';
    }

    // Role Teknisi: tidak boleh input part luar
    const btnExt = document.getElementById('btnUsAddExtPart');
    if (btnExt) {
        btnExt.classList.toggle('hidden', isTech);
    }

    // Status CASH notice
    const cashNotice = document.getElementById('usPartsCashNotice');
    if (cashNotice) {
        cashNotice.classList.toggle('hidden', !isCash);
    }
    const btnStore = document.getElementById('btnUsAddStorePart');
    if (btnStore) btnStore.disabled = isCash;
    if (btnExt) btnExt.disabled = isCash;

    // Field usFinPart: Teknisi dilarang otak-atik manual
    const finPartInput = document.getElementById('usFinPart');
    if (finPartInput) {
        if (isTech) {
            finPartInput.readOnly = true;
            finPartInput.classList.add('bg-gray-100', 'cursor-not-allowed');
            finPartInput.title = 'Modal part dihitung otomatis oleh sistem';
        } else {
            finPartInput.readOnly = false;
            finPartInput.classList.remove('bg-gray-100', 'cursor-not-allowed');
        }
    }

    tbody.innerHTML = '<tr><td colspan="5" class="py-4 text-center text-gray-400 italic"><i class="fa-solid fa-circle-notch fa-spin"></i> Memuat daftar sparepart...</td></tr>';

    try {
        const res = await apiGet('/orders/' + serviceId + '/parts');
        _usCurrentOrderParts = res.items || [];

        if (!_usCurrentOrderParts.length) {
            tbody.innerHTML = '<tr><td colspan="5" class="py-4 text-center text-gray-400 italic">Belum ada sparepart yang terpasang pada unit ini.</td></tr>';
        } else {
            tbody.innerHTML = _usCurrentOrderParts.map(item => {
                const isExt = !!item.is_external;
                const sourceBadge = isExt
                    ? '<span class="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-semibold bg-amber-100 dark:bg-amber-950/60 text-amber-800 dark:text-amber-300">Part Luar / Kanibal</span>'
                    : '<span class="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-semibold bg-blue-100 dark:bg-blue-950/60 text-blue-800 dark:text-blue-300">Stok Toko' + (item.batch_id ? ' (Batch #' + item.batch_id + ')' : '') + '</span>';

                let modalText = '-';
                if (!isTech) {
                    const totalModal = (Number(item.modal_beli) || 0) * (Number(item.qty) || 1);
                    modalText = 'Rp ' + Number(totalModal).toLocaleString('id-ID');
                } else {
                    modalText = '<span class="text-gray-400 italic text-[11px]">Dilindungi</span>';
                }

                const delBtn = isCash ? '<span class="text-gray-300 dark:text-gray-600 cursor-not-allowed" title="Terkunci saat CASH"><i class="fa-solid fa-lock text-xs"></i></span>'
                    : `<div class="flex items-center justify-center gap-1.5">
                        <button type="button" onclick="usReportDefectPart(${serviceId}, ${item.id}, '${escapeHtml(item.part_name || 'Part')}')" class="text-amber-500 hover:text-amber-600 p-1 text-xs" title="Lapor part cacat pabrik / retur ke supplier">
                            <i class="fa-solid fa-shield-virus"></i>
                        </button>
                        <button type="button" onclick="usRemovePart(${serviceId}, ${item.id}, '${escapeHtml(item.part_name || 'Part')}')" class="text-red-500 hover:text-red-700 p-1 text-xs" title="Lepas part (kembalikan stok ke rak)">
                            <i class="fa-solid fa-rotate-left"></i>
                        </button>
                    </div>`;

                return `<tr>
                    <td class="py-2.5 px-3">
                        <div class="font-medium text-gray-900 dark:text-gray-100">${escapeHtml(item.part_name || '-')}</div>
                        ${item.note ? '<div class="text-[10.5px] text-gray-400">' + escapeHtml(item.note) + '</div>' : ''}
                    </td>
                    <td class="py-2.5 px-2 text-center">${sourceBadge}</td>
                    <td class="py-2.5 px-2 text-center font-bold text-gray-800 dark:text-gray-200">${item.qty}</td>
                    <td class="py-2.5 px-3 text-right font-mono font-medium">${modalText}</td>
                    <td class="py-2.5 px-2 text-center">${delBtn}</td>
                </tr>`;
            }).join('');
        }

        // Sinkronisasi modal part ke form
        if (!isTech && res.part_cost !== undefined && finPartInput) {
            finPartInput.value = res.part_cost;
            usFinUpdate();
        }
    } catch (err) {
        tbody.innerHTML = '<tr><td colspan="5" class="py-4 text-center text-red-400 italic">Gagal memuat sparepart: ' + escapeHtml(err.message || 'Error') + '</td></tr>';
    }
}

async function usOpenAddPartModal(isExternal) {
    if ((_usStatusInit || '').toUpperCase() === 'CASH') {
        alert('Unit servis ini sudah CASH. Pemakaian sparepart terkunci.');
        return;
    }

    const modal = document.getElementById('modalUsAddPart');
    if (!modal) return;

    document.getElementById('usPartIsExternal').value = isExternal ? 'true' : 'false';
    document.getElementById('modalUsPartTitle').textContent = isExternal ? 'Input Part Luar / Kanibal' : 'Pasang Sparepart dari Stok Toko';
    document.getElementById('modalUsPartIcon').className = isExternal ? 'fa-solid fa-screwdriver-wrench' : 'fa-solid fa-microchip';

    const secStore = document.getElementById('sectionUsPartStore');
    const secExt = document.getElementById('sectionUsPartExt');
    const selStore = document.getElementById('usPartSelect');
    const extName = document.getElementById('usPartExtName');
    const extModal = document.getElementById('usPartExtModal');

    if (isExternal) {
        if (secStore) secStore.classList.add('hidden');
        if (secExt) secExt.classList.remove('hidden');
        if (selStore) selStore.required = false;
        if (extName) { extName.required = true; extName.value = ''; }
        if (extModal) { extModal.required = true; extModal.value = ''; }
    } else {
        if (secStore) secStore.classList.remove('hidden');
        if (secExt) secExt.classList.add('hidden');
        if (selStore) selStore.required = true;
        if (extName) extName.required = false;
        if (extModal) extModal.required = false;
        document.getElementById('usPartSearch').value = '';
        await usLoadStorePartsForSelect();
    }

    document.getElementById('usPartQty').value = 1;
    document.getElementById('usPartNote').value = '';
    modal.classList.remove('hidden');
}

function usCloseAddPartModal() {
    const modal = document.getElementById('modalUsAddPart');
    if (modal) modal.classList.add('hidden');
}

async function usLoadStorePartsForSelect() {
    const sel = document.getElementById('usPartSelect');
    const badge = document.getElementById('usPartStockBadge');
    if (!sel) return;

    sel.innerHTML = '<option value="" disabled selected>Memuat stok sparepart...</option>';
    try {
        const res = await apiGet('/spareparts');
        const items = Array.isArray(res) ? res : (res.items || []);
        _usAvailableStoreParts = items.filter(p => (Number(p.qty) || 0) > 0);
        usFilterStoreParts('');
    } catch (err) {
        sel.innerHTML = '<option value="" disabled selected>Gagal memuat stok sparepart</option>';
        if (badge) badge.textContent = 'Error: ' + (err.message || 'Gagal koneksi');
    }
}

function usFilterStoreParts(query) {
    const sel = document.getElementById('usPartSelect');
    const badge = document.getElementById('usPartStockBadge');
    if (!sel) return;

    const q = (query || '').toLowerCase().trim();
    const filtered = _usAvailableStoreParts.filter(p => {
        if (!q) return true;
        const text = `${p.kategori || ''} ${p.merek || ''} ${p.jenis || ''} ${p.device || ''}`.toLowerCase();
        return text.includes(q);
    });

    if (!filtered.length) {
        sel.innerHTML = '<option value="" disabled selected>Tidak ada sparepart yang cocok / stok kosong</option>';
        if (badge) badge.textContent = 'Tidak ditemukan sparepart dengan stok tersedia.';
        return;
    }

    sel.innerHTML = filtered.map(p => {
        const label = `[${p.kategori || 'Part'}] ${p.merek ? p.merek + ' - ' : ''}${p.jenis || ''} (Stok: ${p.qty})`;
        return `<option value="${p.id}" data-qty="${p.qty}" data-harga="${p.harga_jual || 0}">${escapeHtml(label)}</option>`;
    }).join('');

    sel.selectedIndex = 0;
    usOnPartSelected();
}

function usOnPartSelected() {
    const sel = document.getElementById('usPartSelect');
    const badge = document.getElementById('usPartStockBadge');
    if (!sel || !sel.selectedOptions.length) return;

    const opt = sel.selectedOptions[0];
    const qty = opt.getAttribute('data-qty') || 0;
    const harga = Number(opt.getAttribute('data-harga') || 0);

    if (badge) {
        badge.innerHTML = `<span class="text-emerald-600 dark:text-emerald-400 font-semibold"><i class="fa-solid fa-boxes-stacked"></i> Stok Tersedia: <b>${qty} pcs</b></span>
        <span class="text-gray-400 mx-1">|</span>
        <span>Harga Standar: <b>Rp ${harga.toLocaleString('id-ID')}</b></span>`;
    }
}

async function usSubmitAddPart(event) {
    event.preventDefault();
    if (!_txEditId) {
        alert('ID order tidak valid');
        return;
    }

    const isExternal = document.getElementById('usPartIsExternal').value === 'true';
    const qty = parseInt(document.getElementById('usPartQty').value, 10) || 1;
    const note = document.getElementById('usPartNote').value.trim() || null;

    let payload = { qty, note, is_external: isExternal };

    if (isExternal) {
        const partName = document.getElementById('usPartExtName').value.trim();
        const modalBeli = parseFloat(document.getElementById('usPartExtModal').value) || 0;
        if (!partName) {
            alert('Nama part luar wajib diisi');
            return;
        }
        payload.part_name = partName;
        payload.modal_beli = modalBeli;
    } else {
        const sel = document.getElementById('usPartSelect');
        const spId = parseInt(sel.value, 10);
        if (!spId) {
            alert('Pilih sparepart dari daftar');
            return;
        }
        payload.sparepart_id = spId;
    }

    const btnSubmit = document.getElementById('btnUsPartSubmit');
    if (btnSubmit) {
        btnSubmit.disabled = true;
        btnSubmit.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i> Memproses...';
    }

    try {
        await apiPost('/orders/' + _txEditId + '/parts', payload);
        usCloseAddPartModal();
        await usPartsLoad(_txEditId, _usStatusInit);
        if (typeof showToast === 'function') {
            showToast('Sparepart berhasil dipasang ke unit!', 'success');
        } else {
            alert('Sparepart berhasil dipasang!');
        }
    } catch (err) {
        alert('Gagal memasang sparepart: ' + (err.message || 'Error'));
    } finally {
        if (btnSubmit) {
            btnSubmit.disabled = false;
            btnSubmit.innerHTML = '<i class="fa-solid fa-check"></i> Pasang ke Unit';
        }
    }
}

async function usRemovePart(orderId, itemId, partName) {
    const alasan = prompt(`Lepas "${partName}" dari unit servis ini?\nStok fisik akan dikembalikan ke rak & batch asal.\n\nMasukkan alasan pembatalan:`, 'Batal ganti part');
    if (alasan === null) return;

    try {
        await apiDelete(`/orders/${orderId}/parts/${itemId}?alasan=${encodeURIComponent(alasan || 'Dilepas teknisi')}`);
        await usPartsLoad(orderId, _usStatusInit);
        if (typeof showToast === 'function') {
            showToast('Sparepart berhasil dilepas dan stok dikembalikan.', 'info');
        } else {
            alert('Sparepart berhasil dilepas!');
        }
    } catch (err) {
        alert('Gagal melepas sparepart: ' + (err.message || 'Error'));
    }
}
window.usRemovePart = usRemovePart;

async function usReportDefectPart(orderId, itemId, partName) {
    const alasan = prompt(`Part "${partName}" cacat bawaan pabrik?\n\nPart akan dilepas dari servis (modal nota dikurangi) dan dialihkan ke Karantina Retur Supplier.\n\nMasukkan rincian gejala cacat:`, 'Touchscreen ghost touch / tidak normal');
    if (alasan === null) return;
    if (!alasan.trim()) {
        alert('Gejala kerusakan wajib diisi.');
        return;
    }

    try {
        const res = await apiPost(`/orders/${orderId}/parts/${itemId}/retur`, { alasan_cacat: alasan.trim() });
        await usPartsLoad(orderId, _usStatusInit);
        if (typeof showToast === 'function') {
            showToast(`Part cacat dicatat ke retur (${res.no_retur}). Modal servis dikurangi.`, 'info');
        } else {
            alert(`Part cacat dicatat ke retur (${res.no_retur}). Modal servis dikurangi.`);
        }
    } catch (err) {
        alert('Gagal lapor part cacat: ' + (err.message || 'Error'));
    }
}
window.usReportDefectPart = usReportDefectPart;

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
                <div class="ndr-doctype"><i class="fa-solid fa-shield-halved"></i><span><b>PG</b><span> NOTA PENERIMAAN CLAIM GARANSI</span></span></div>
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
    let _pay = null;
    if (_txEditId) {
        try {
            _pay = await apiGet('/payments/by-order/' + _txEditId);
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
        // Status pembayaran dari ledger, bukan asumsi. Kosong kalau data
        // pembayaran tidak sempat ditarik (mis. nota dibuka tanpa form).
        bayar_status: _pay ? (_pay.payment_status || '') : '',
        bayar_total: _pay ? (Number(_pay.total_bayar) || 0) : 0,
        bayar_sisa: _pay ? (Number(_pay.sisa) || 0) : 0,
        dp: usNum('usDp'),
        // Komponen diganti. Diisi hanya kalau sparepart benar dipakai unit ini;
        // daftar kosong = blok tidak dirender sama sekali (tidak dikarang).
        parts: usWarrantyParts(),
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

// Komponen yang diganti unit ini, dari pemakaian sparepart yang tercatat
// (`service_order_parts`, models.py).
//
// CATATAN: tabel itu belum pernah diisi dan belum ada endpoint yang
// membacanya, jadi hasilnya selalu kosong dan blok "KOMPONEN DIGANTI"
// tidak pernah tampil. Sengaja TIDAK memanggil endpoint yang belum ada
// supaya tidak ada request 404 sia-sia setiap kali nota dicetak.
//
//Begitu fitur pencatatan sparepart dikerjakan, cukup isi di sini -
// sisanya (render + escaping) sudah siap.
function usWarrantyParts() {
    return [];
}

// Status garansi dihitung dari TANGGAL BERAKHIRNYA, bukan dari teks statis.
// Sumber tanggal = `warranty_end` yang sudah dihitung sistem
// (`warrantyEndFor`), jadi tidak ada angka yang dikarang di sini.
function notaWarrantyStatus(d) {
    const bulan = d ? d.warranty_months : null;
    if (bulan === 0) return { label: 'TANPA GARANSI', cls: 'is-gray', note: 'Servis ini tidak bergaransi toko.' };
    const end = (d && d.warranty_end) ? new Date(d.warranty_end) : null;
    if (!end || isNaN(end.getTime())) {
        return { label: 'BERAKHIR', cls: 'is-gray', note: 'Masa garansi sudah lewat.' };
    }
    const hariIni = new Date();
    const mulaiHariIni = new Date(hariIni.getFullYear(), hariIni.getMonth(), hariIni.getDate());
    const selesaiHariIni = new Date(end.getFullYear(), end.getMonth(), end.getDate());
    if (selesaiHariIni < mulaiHariIni) {
        return { label: 'BERAKHIR', cls: 'is-gray', note: 'Berakhir ' + notaTglSlash(d.warranty_end) + '.' };
    }
    const sisaHari = Math.round((selesaiHariIni - mulaiHariIni) / 86400000);
    return {
        label: 'AKTIF',
        cls: 'is-green',
        note: sisaHari === 0
            ? 'Berakhir hari ini (' + notaTglSlash(d.warranty_end) + ').'
            : 'Berlaku ' + sisaHari + ' hari lagi, s/d ' + notaTglSlash(d.warranty_end) + '.'
    };
}

// Blok "Komponen Diganti". Kalau tidak ada sparepart yang tercatat, hasilnya
// string kosong dan pemanggil tidak merender kartunya sama sekali.
function notaWarrantyParts(d) {
    try {
        const list = Array.isArray(d && d.parts) ? d.parts : [];
        if (!list.length) return '';
        const baris = list.map((p) => {
            // Nama komponen bisa datang sebagai nama / name / device / jenis
            // tergantung sumber datanya.
            const nama = escapeHtml(p.nama || p.name || p.device || p.jenis || '-');
            const qty = Number(p.qty || p.jumlah) || 0;
            const ket = qty > 1
                ? '<span>' + nama + ' <span class="ng-pqty">x' + qty + '</span></span>'
                : '<span>' + nama + '</span>';
            return '<li><i class="fa-solid fa-check"></i>' + ket + '</li>';
        }).join('');
        return '<div class="ng-card">'
            + '<div class="ng-cap"><span class="ng-ico"><i class="fa-solid fa-screwdriver-wrench"></i></span>KOMPONEN DIGANTI</div>'
            + '<ul class="ng-parts">' + baris + '</ul>'
            + '</div>';
    } catch (_) {
        return '';
    }
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
    const jam = notaJam();
    const gst = notaWarrantyStatus(d);
    const waToko = shopWaDisplay();
    const statusBayar = String(d.bayar_status || '').toUpperCase();
    const label = warrantyLabel(d.warranty_months);
    const partsHtml = notaWarrantyParts(d);
    const teknisi = notaTechnician(d.technician);

    el.innerHTML = `
    <div class="ng-sheet">
        <!-- HEADER -->
        <div class="ng-header">
            <div class="ng-header-bg-shape"></div>
            <div class="ng-header-content">
                <div class="ng-brand">
                    <div class="ng-logo-icon">
                        <img src="/static/assets/logo.png" alt="Logo" onerror="this.style.display='none';var s=this.nextElementSibling;if(s)s.style.display='block';">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:30px;height:30px;color:#d30000;display:none;"><rect x="5" y="2" width="14" height="20" rx="2" ry="2"></rect><circle cx="12" cy="14" r="3"></circle><path d="M12 11v-2"></path><path d="M12 19v-2"></path></svg>
                    </div>
                    <div class="ng-brand-text-container">
                        <div class="ng-brand-title">SUKABUMI<br>FLASHER</div>
                        <div class="ng-brand-subtitle">SMARTPHONE SERVICE LAB</div>
                    </div>
                </div>
                
                <div class="ng-header-contact">
                    <div class="ng-contact-item">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"></path></svg>
                        ${escapeHtml(waToko)}
                    </div>
                    <div class="ng-contact-item">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect><line x1="16" y1="2" x2="16" y2="6"></line><line x1="8" y1="2" x2="8" y2="6"></line><line x1="3" y1="10" x2="21" y2="10"></line></svg>
                        ${escapeHtml(tgl)}
                    </div>
                    <div class="ng-contact-item">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>
                        Jam: ${escapeHtml(jam)}
                    </div>
                </div>
            </div>
        </div>

        <!-- MAIN CONTENT -->
        <div class="ng-main-body">
            
            <!-- Top Section -->
            <div class="ng-top-section">
                <div class="ng-title-area">
                    <h1>NOTA <span>GARANSI</span> SERVICE</h1>
                    <div class="ng-garansi-status">
                        <svg class="ng-shield-icon" viewBox="0 0 24 24" fill="currentColor"><path d="M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4zm-2 16l-4-4 1.41-1.41L10 14.17l6.59-6.59L18 9l-8 8z"/></svg>
                        <div class="ng-status-text">
                            <h2>${escapeHtml(gst.label || 'GARANSI AKTIF')}</h2>
                            <p>${d.warranty_months === 0 ? 'Servis ini tidak memiliki masa garansi toko.' : 'Kami menjamin perbaikan sesuai dengan ketentuan garansi yang berlaku.'}</p>
                        </div>
                    </div>
                </div>
                <div class="ng-garansi-id-box">
                    <div class="ng-id-label">NOMOR GARANSI</div>
                    <div class="ng-id-value">${escapeHtml(d.no || '-')}</div>
                    <div class="ng-id-footer">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path><polyline points="9 12 11 14 15 10"></polyline></svg>
                        Simpan nota ini sebagai bukti garansi Anda
                    </div>
                </div>
            </div>

            <!-- Row 1: Top Cards -->
            <div class="ng-grid-3col">
                <div class="ng-card">
                    <div class="ng-card-header">
                        <svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z"/></svg>
                        <div class="ng-ch-title">PELANGGAN</div>
                    </div>
                    <div class="ng-val-primary">${escapeHtml(d.nama || '-')}</div>
                    <div class="ng-val-secondary">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"></path></svg>
                        ${escapeHtml(d.phone || '-')}
                    </div>
                </div>
                <div class="ng-card">
                    <div class="ng-card-header">
                        <svg viewBox="0 0 24 24" fill="currentColor"><path d="M17 1.01L7 1c-1.1 0-2 .9-2 2v18c0 1.1.9 2 2 2h10c1.1 0 2-.9 2-2V3c0-1.1-.9-1.99-2-1.99zM17 19H7V5h10v14z"/></svg>
                        <div class="ng-ch-title">DEVICE</div>
                    </div>
                    <div class="ng-val-primary">${escapeHtml(d.device || '-')}</div>
                    <div class="ng-val-secondary" style="margin-top:8px;">Warna &nbsp;: -</div>
                    <div class="ng-val-secondary">IMEI &nbsp;&nbsp;&nbsp;: ${escapeHtml(d.imei || '-')}</div>
                </div>
                <div class="ng-card">
                    <div class="ng-card-header">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><line x1="4" y1="9" x2="20" y2="9"></line><line x1="4" y1="15" x2="20" y2="15"></line><line x1="10" y1="3" x2="8" y2="21"></line><line x1="16" y1="3" x2="14" y2="21"></line></svg>
                        <div class="ng-ch-title">NO. TRANSAKSI</div>
                    </div>
                    <div class="ng-val-primary">#${escapeHtml(d.no || '-')}</div>
                    <div class="ng-val-secondary" style="margin-top:8px;">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect><line x1="16" y1="2" x2="16" y2="6"></line><line x1="8" y1="2" x2="8" y2="6"></line><line x1="3" y1="10" x2="21" y2="10"></line></svg>
                        ${escapeHtml(tgl)}
                    </div>
                    <div class="ng-val-secondary">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>
                        Jam: ${escapeHtml(jam)}
                    </div>
                </div>
            </div>

            <!-- Row 2: Main Details -->
            <div class="ng-grid-main">
                <!-- Col 1 -->
                <div class="ng-card-detail">
                    <div class="ng-card-header" style="padding: 18px 18px 0 18px; margin-bottom:0;">
                        <svg viewBox="0 0 24 24" fill="currentColor"><path d="M22.7 19l-9.1-9.1c.9-2.3.4-5-1.5-6.9-2-2-5-2.4-7.4-1.3L9 6 6 9 1.6 4.7C.4 7.1.9 10.1 2.9 12.1c1.9 1.9 4.6 2.4 6.9 1.5l9.1 9.1c.4.4 1 .4 1.4 0l2.3-2.3c.5-.4.5-1.1.1-1.4z"/></svg>
                        <div class="ng-ch-title">DETAIL PERBAIKAN</div>
                    </div>
                    
                    <div class="ng-detail-section">
                        <div class="ng-ds-title">Keluhan</div>
                        <div class="ng-ds-value">${escapeHtml(d.damage || '-')}</div>
                    </div>
                    <div class="ng-detail-section">
                        <div class="ng-ds-title">Pekerjaan / Tindakan</div>
                        <div class="ng-ds-value" style="display: flex; gap:8px; align-items:flex-start;">
                            <svg viewBox="0 0 24 24" fill="none" stroke="#d30000" stroke-width="2" width="14" height="14" style="flex-shrink:0; margin-top:2px;"><polyline points="20 6 9 17 4 12"></polyline></svg>
                            <span>${escapeHtml(d.plan || '-')}</span>
                        </div>
                    </div>
                    <div class="ng-detail-section">
                        <div class="ng-ds-title">Teknisi</div>
                        <div class="ng-ds-value">${escapeHtml(teknisi)}</div>
                    </div>
                    <div class="ng-detail-section" style="flex:1;">
                        <div class="ng-ds-title">Biaya Perbaikan</div>
                        <div class="ng-ds-value" style="font-weight: 800; color: #111;">Rp ${escapeHtml(notaRupiah(d.final))}</div>
                        ${statusBayar ? `<div class="ng-val-secondary" style="margin-top:6px; font-weight:700; color:#16a34a; font-size:13px;">Status Bayar: ${escapeHtml(statusBayar)} <i class="fa-solid fa-check" style="margin-left:4px;"></i></div>` : ''}
                    </div>
                    ${partsHtml}
                </div>

                <!-- Col 2 -->
                <div class="ng-card-detail" style="border-color:#10b981;">
                    <div class="ng-card-header" style="padding: 18px 18px 0 18px; margin-bottom:10px;">
                        <svg viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path><polyline points="9 12 11 14 15 10"></polyline></svg>
                        <div class="ng-ch-title" style="color:#10b981;">MASA GARANSI</div>
                    </div>
                    
                    <div class="ng-masa-garansi-inner">
                        ${d.warranty_end ? `<!-- Mulai: Berakhir: -->
                        <div class="ng-mg-row">
                            <div class="ng-mg-icon">
                                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect><line x1="16" y1="2" x2="16" y2="6"></line><line x1="8" y1="2" x2="8" y2="6"></line><line x1="3" y1="10" x2="21" y2="10"></line></svg>
                            </div>
                            <div>
                                <div class="ng-mg-label">Mulai</div>
                                <div class="ng-mg-val">${escapeHtml(tgl)}</div>
                            </div>
                        </div>
                        <div class="ng-mg-row">
                            <div class="ng-mg-icon">
                                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect><line x1="16" y1="2" x2="16" y2="6"></line><line x1="8" y1="2" x2="8" y2="6"></line><line x1="3" y1="10" x2="21" y2="10"></line></svg>
                            </div>
                            <div>
                                <div class="ng-mg-label">Berakhir</div>
                                <div class="ng-mg-val" style="color:#666; font-size:14px; font-weight:700;">${escapeHtml(sampai)}</div>
                            </div>
                        </div>` : `
                        <div class="ng-mg-row">
                            <div class="ng-mg-icon">
                                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>
                            </div>
                            <div>
                                <div class="ng-mg-label">Status</div>
                                <div class="ng-mg-val" style="color:#666; font-size:14px; font-weight:700;">Tanpa Garansi Toko</div>
                            </div>
                        </div>`}
                        <div class="ng-mg-row" style="padding-bottom:0;">
                            <div class="ng-mg-icon">
                                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>
                            </div>
                            <div>
                                <div class="ng-mg-label">Durasi</div>
                                <div class="ng-mg-val" style="font-size:20px;">${escapeHtml(label)}</div>
                            </div>
                        </div>
                    </div>
                    
                    <div class="ng-mg-info" style="margin-top:auto;">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16" style="flex-shrink:0;"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>
                        Garansi berlaku untuk kerusakan yang sama sesuai dengan ketentuan yang berlaku.
                    </div>
                </div>

                <!-- Col 3 -->
                <div class="ng-card-detail">
                    <div class="ng-card-header" style="padding: 18px 18px 15px 18px; margin-bottom:0;">
                        <svg viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path><polyline points="9 12 11 14 15 10"></polyline></svg>
                        <div class="ng-ch-title" style="color:#10b981;">CAKUPAN GARANSI</div>
                    </div>
                    
                    <div class="ng-cakupan-list">
                        <div class="ng-cakupan-item">
                            <svg class="ng-c-icon-green" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><polyline points="20 6 9 17 4 12"></polyline></svg>
                            Kerusakan yang sama (sesuai keluhan awal)
                        </div>
                        <div class="ng-cakupan-item">
                            <svg class="ng-c-icon-green" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><polyline points="20 6 9 17 4 12"></polyline></svg>
                            Pekerjaan teknisi
                        </div>
                        <div class="ng-cakupan-item">
                            <svg class="ng-c-icon-green" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><polyline points="20 6 9 17 4 12"></polyline></svg>
                            Sparepart yang diganti (sesuai garansi sparepart)
                        </div>
                    </div>

                    <div class="ng-alert-header">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>
                        <div class="ng-ch-title">TIDAK TERMASUK GARANSI</div>
                    </div>

                    <div class="ng-cakupan-list" style="margin-top:10px;">
                        <div class="ng-cakupan-item">
                            <svg class="ng-c-icon-red" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line></svg>
                            Kerusakan akibat jatuh / benturan
                        </div>
                        <div class="ng-cakupan-item">
                            <svg class="ng-c-icon-red" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line></svg>
                            Kerusakan akibat kena air / cairan
                        </div>
                        <div class="ng-cakupan-item">
                            <svg class="ng-c-icon-red" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line></svg>
                            Kerusakan akibat kelalaian pemilik
                        </div>
                        <div class="ng-cakupan-item">
                            <svg class="ng-c-icon-red" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line></svg>
                            Kerusakan akibat pembongkaran oleh pihak lain
                        </div>
                        <div class="ng-cakupan-item">
                            <svg class="ng-c-icon-red" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line></svg>
                            Software / aplikasi
                        </div>
                    </div>
                </div>
            </div>

            <!-- Row 3: Panduan Klaim & Validitas Garansi -->
            <div class="ng-grid-footer">
                <div class="ng-footer-card">
                    <div class="ng-fc-title">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path><polyline points="9 12 11 14 15 10"></polyline></svg>
                        <span>PANDUAN KLAIM GARANSI</span>
                    </div>
                    <div class="ng-fc-desc">Untuk klaim garansi, cukup tunjukkan gambar Nota Digital ini atau sebutkan No. Servis <strong>${escapeHtml(d.no || '-')}</strong> ke kasir / teknisi kami saat membawa unit.</div>
                    <div class="ng-fc-btn">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"></path></svg>
                        Hotline WA: ${escapeHtml(waToko || '-')}
                    </div>
                </div>

                <div class="ng-footer-card ng-fc-right">
                    <div class="ng-fc-right-icon">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="24" height="24"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path></svg>
                    </div>
                    <p>Garansi ini resmi diterbitkan oleh<br><strong>SUKABUMI FLASHER<br>SMARTPHONE SERVICE LAB</strong></p>
                    <div style="height: 1px; background: #fca5a5; margin: 10px 0;"></div>
                    <p style="font-size: 13px; color: #777;">Pastikan segel garansi pada unit tetap utuh dan bawa unit dalam masa berlaku garansi.</p>
                </div>
            </div>

            <!-- Ketentuan Garansi (Bottom) -->
            <div class="ng-ketentuan-section">
                <div class="ng-ks-header">
                    <div class="ng-ks-title">KETENTUAN GARANSI</div>
                    <div class="ng-ks-line"></div>
                </div>
                <div class="ng-ks-grid">
                    <div class="ng-ks-item">
                        <div class="ng-ks-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line><polyline points="10 9 9 9 8 9"></polyline></svg></div>
                        <div class="ng-ks-text"><strong>1.</strong> Nota garansi ini wajib dibawa saat klaim garansi.</div>
                    </div>
                    <div class="ng-ks-item">
                        <div class="ng-ks-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path><polyline points="9 12 11 14 15 10"></polyline></svg></div>
                        <div class="ng-ks-text"><strong>2.</strong> Garansi berlaku sesuai dengan masa berlaku yang tertera.</div>
                    </div>
                    <div class="ng-ks-item">
                        <div class="ng-ks-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16"><rect x="5" y="2" width="14" height="20" rx="2" ry="2"></rect><line x1="12" y1="18" x2="12.01" y2="18"></line></svg></div>
                        <div class="ng-ks-text"><strong>3.</strong> Garansi hanya berlaku untuk kerusakan yang sama sesuai keluhan awal.</div>
                    </div>
                    <div class="ng-ks-item">
                        <div class="ng-ks-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg></div>
                        <div class="ng-ks-text"><strong>4.</strong> Keputusan teknisi adalah yang utama dalam penentuan klaim garansi.</div>
                    </div>
                </div>
            </div>

        </div>

        <!-- FOOTER DARK -->
        <div class="ng-footer-dark">
            <div class="ng-fd-left">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>
                <p>Terima kasih telah mempercayakan<br>perbaikan perangkat Anda kepada kami.</p>
            </div>
            <div class="ng-foot-r ng-fd-right">
                <b>Powered by <em>BOSS</em></b>
                <span>BUSINESS OPERATION SMART SYSTEM</span>
            </div>
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

function initBebanInputs() {
    const nilaiEl = document.getElementById('bebanNilai');
    const namaEl = document.getElementById('bebanNama');
    if (nilaiEl && !nilaiEl._bebanBound) {
        nilaiEl._bebanBound = true;
        nilaiEl.addEventListener('input', function() {
            const raw = this.value.replace(/\D/g, '');
            if (!raw) {
                this.value = '';
            } else {
                this.value = Number(raw).toLocaleString('id-ID');
            }
        });
        nilaiEl.addEventListener('keydown', function(e) {
            if (e.key === 'Enter') {
                e.preventDefault();
                bebanAdd();
            }
        });
    }
    if (namaEl && !namaEl._bebanBound) {
        namaEl._bebanBound = true;
        namaEl.addEventListener('keydown', function(e) {
            if (e.key === 'Enter') {
                e.preventDefault();
                if (nilaiEl) {
                    nilaiEl.focus({ preventScroll: true });
                    nilaiEl.select();
                }
            }
        });
    }
}

function bebanPickChip(nama, kat) {
    const namaEl = document.getElementById('bebanNama');
    const katEl = document.getElementById('bebanKategori');
    const nilaiEl = document.getElementById('bebanNilai');
    if (namaEl) namaEl.value = nama;
    if (katEl) katEl.value = kat;
    if (nilaiEl) {
        nilaiEl.focus({ preventScroll: true });
        nilaiEl.select();
    }
}
window.bebanPickChip = bebanPickChip;

async function openBeban() {
    _bebanEditIdx = -1;
    _bebanDeleted = [];
    initBebanInputs();
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
        body.innerHTML = `<tr><td colspan="4"><div class="beban-empty"><i class="fa-solid fa-receipt"></i>Belum ada beban — gunakan pilihan cepat atau form di atas.</div></td></tr>`;
    } else {
        body.innerHTML = _bebanList.map((b, i) => {
            const isGaji = String(b.kategori || '').toLowerCase().includes('gaji');
            return `
            <tr>
                <td class="text-center"><span class="beban-cat ${isGaji ? 'is-gaji' : 'is-ops'}">${escapeHtml(b.kategori)}</span></td>
                <td class="font-medium text-gray-800 dark:text-gray-200">${escapeHtml(b.nama)}</td>
                <td class="text-right font-semibold text-gray-800 dark:text-gray-200">${bebanRupiah(b.nilai)}</td>
                <td class="text-center">
                    <button type="button" class="beban-ico is-edit" title="Edit" onclick="bebanEdit(${i})"><i class="fa-solid fa-pen"></i></button>
                    <button type="button" class="beban-ico is-del" title="Hapus" onclick="bebanDel(${i})"><i class="fa-solid fa-trash"></i></button>
                </td>
            </tr>`;
        }).join('');
    }

    let totalOps = 0;
    let totalGaji = 0;
    _bebanList.forEach(b => {
        const v = Number(b.nilai) || 0;
        if (String(b.kategori || '').toLowerCase().includes('gaji')) totalGaji += v;
        else totalOps += v;
    });
    const total = totalOps + totalGaji;

    const subOpsEl = document.getElementById('bebanSubOps');
    const subGajiEl = document.getElementById('bebanSubGaji');
    const subTotEl = document.getElementById('bebanSubTotal');
    const tfoot = document.getElementById('bebanTotal');

    if (subOpsEl) subOpsEl.textContent = bebanRupiah(totalOps);
    if (subGajiEl) subGajiEl.textContent = bebanRupiah(totalGaji);
    if (subTotEl) subTotEl.textContent = bebanRupiah(total);
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
    const rawNilai = String((document.getElementById('bebanNilai') || {}).value || '').replace(/\D/g, '');
    const nilai = Math.round(parseFloat(rawNilai) || 0);
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
        const existing = _bebanList[_bebanEditIdx];
        _bebanList[_bebanEditIdx] = { ...existing, kategori: kat, nama: nama, nilai: nilai };
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
    const elNama = document.getElementById('bebanNama');
    if (elNama) elNama.focus({ preventScroll: true });
}

function bebanEdit(i) {
    const b = _bebanList[i];
    if (!b) return;
    _bebanEditIdx = i;
    document.getElementById('bebanKategori').value = b.kategori;
    document.getElementById('bebanNama').value = b.nama;
    const v = Number(b.nilai) || 0;
    document.getElementById('bebanNilai').value = v > 0 ? v.toLocaleString('id-ID') : '';
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
    // Validasi form sebelum simpan
    if (!_bebanList.length) {
        bebanFeedback('Tidak ada beban untuk disimpan.', true);
        return;
    }
    for (const b of _bebanList) {
        if (!b.nama || !b.nama.trim()) {
            bebanFeedback('Ada beban tanpa nama.', true);
            return;
        }
        if (!(Number(b.nilai) >= 0)) {
            bebanFeedback('Nilai beban tidak valid.', true);
            return;
        }
    }
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
                try { await apiDel('/expenses/' + id); } catch (e) { console.error('DELETE expense error:', e); bebanFeedback('Gagal hapus ID ' + id + ': ' + e.message, true); }
            }
            _bebanDeleted = [];
            for (const b of _bebanList) {
                if (b.id) {
                    try { await apiPut('/expenses/' + b.id, { kategori: b.kategori, uraian: b.nama, nilai: b.nilai }); } catch (e) { console.error('PUT expense error:', e); bebanFeedback('Gagal update ID ' + b.id + ': ' + e.message, true); }
                } else {
                    try {
                        const created = await apiPost('/expenses', { kategori: b.kategori, uraian: b.nama, nilai: b.nilai });
                        b.id = created.id;
                    } catch (e) { console.error('POST expense error:', e); bebanFeedback('Gagal tambah ' + b.nama + ': ' + e.message, true); }
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


// ============================================
// UNIT MENGENDAP (MODEL C) - Follow-Up Bertahap 7/30/60/90 Hari
// ============================================

let _unclaimedData = null;
let _unclaimedFilterStage = 0; // 0 = all
let _unclaimedActiveTarget = null;

function _unclaimedTodayStr() {
    return new Date().toISOString().slice(0, 10);
}

function getUnclaimedWaDoneMap() {
    try {
        const key = 'boss_unclaimed_wa_done_' + _unclaimedTodayStr();
        const raw = localStorage.getItem(key);
        return raw ? JSON.parse(raw) : {};
    } catch (_) {
        return {};
    }
}

function setUnclaimedWaDone(keyId, isDone) {
    if (!keyId) return;
    try {
        const storageKey = 'boss_unclaimed_wa_done_' + _unclaimedTodayStr();
        const map = getUnclaimedWaDoneMap();
        if (isDone) {
            map[String(keyId)] = new Date().toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit' });
        } else {
            delete map[String(keyId)];
        }
        localStorage.setItem(storageKey, JSON.stringify(map));
    } catch (_) {}
}

function isUnclaimedWaDone(o) {
    if (!o) return false;
    const map = getUnclaimedWaDoneMap();
    const k1 = o.no_servis ? String(o.no_servis) : '';
    const k2 = o.id ? String(o.id) : '';
    return Boolean((k1 && map[k1]) || (k2 && map[k2]));
}

function getUnclaimedWaDoneTime(o) {
    if (!o) return null;
    const map = getUnclaimedWaDoneMap();
    const k1 = o.no_servis ? String(o.no_servis) : '';
    const k2 = o.id ? String(o.id) : '';
    return (k1 && map[k1]) || (k2 && map[k2]) || null;
}

function unclaimedWaMessage(o, stage) {
    const nama = (o.customer_name || 'Kak').trim();
    const device = (o.device || 'perangkat').trim();
    const no = (o.no_servis || '-').trim();
    const isDone = (o.status === 'DONE');
    const stg = Number(stage) || (o.stage || 1);

    if (isDone) {
        if (stg === 1) {
            return `Halo Kak ${nama}, kami informasikan HP ${device} Kakak (No. Servis ${no}) sudah selesai diservis dan masih berada di toko kami. Silakan diambil jika sudah ada waktu, ya. Terima kasih! - SUKABUMI FLASHER`;
        } else if (stg === 2) {
            return `Halo Kak ${nama}, HP ${device} Kakak (No. Servis ${no}) sudah cukup lama (30 hari) berada di toko kami. Mohon konfirmasi kapan unit akan diambil agar kami bisa mengatur penyimpanan unit dengan baik. Terima kasih! - SUKABUMI FLASHER`;
        } else if (stg === 3) {
            return `Halo Kak ${nama}, kami mohon kepastian terkait HP ${device} (No. Servis ${no}) yang masih berada di toko kami. Jika Kakak tidak berencana mengambilnya, kami terbuka untuk membahas kemungkinan pembelian unit oleh toko dengan harga yang disepakati bersama. Terima kasih! - SUKABUMI FLASHER`;
        } else {
            return `Halo Kak ${nama}, HP ${device} Kakak (No. Servis ${no}) sudah hampir 3 bulan berada di toko kami. Mohon segera mengonfirmasi jadwal pengambilan. Jika ingin menjual unit kepada kami, silakan hubungi CS untuk membahas harga. Jika tidak ada kesepakatan, unit tetap perlu diambil kembali. Terima kasih! - SUKABUMI FLASHER`;
        }
    } else {
        // FAILED
        if (stg === 1) {
            return `Halo Kak ${nama}, kami informasikan HP ${device} Kakak (No. Servis ${no}) belum berhasil diperbaiki dan masih berada di toko kami. Silakan diambil kembali jika sudah ada waktu, ya. Tanpa biaya perbaikan. Terima kasih! - SUKABUMI FLASHER`;
        } else if (stg === 2) {
            return `Halo Kak ${nama}, HP ${device} Kakak (No. Servis ${no}) yang batal/belum berhasil diperbaiki sudah 30 hari berada di toko kami. Mohon konfirmasi kapan unit akan diambil kembali agar tidak tercecer. Terima kasih! - SUKABUMI FLASHER`;
        } else if (stg === 3) {
            return `Halo Kak ${nama}, kami mohon kepastian terkait HP ${device} (No. Servis ${no}) yang masih berada di toko kami. Jika Kakak tidak berencana mengambilnya kembali, kami terbuka untuk penawaran pembelian bahan/part unit oleh toko dengan harga sepakat. Terima kasih! - SUKABUMI FLASHER`;
        } else {
            return `Halo Kak ${nama}, HP ${device} Kakak (No. Servis ${no}) sudah hampir 3 bulan berada di toko kami. Mohon segera mengonfirmasi jadwal pengambilan unit. Jika ingin melepas/menjual unit kepada toko, silakan hubungi CS. Jika tidak, unit tetap wajib diambil kembali. Terima kasih! - SUKABUMI FLASHER`;
        }
    }
}

async function loadUnclaimedUnits() {
    try {
        const res = await apiGet('/orders/unclaimed');
        _unclaimedData = res || { total: 0, stage_1: 0, stage_2: 0, stage_3: 0, stage_4: 0, items: [] };
        updateUnclaimedBanner();
    } catch (_) {
        _unclaimedData = { total: 0, stage_1: 0, stage_2: 0, stage_3: 0, stage_4: 0, items: [] };
        updateUnclaimedBanner();
    }
}

function updateUnclaimedBanner() {
    const box = document.getElementById('unclaimedAlertBox');
    if (!box) return;
    const d = _unclaimedData;
    if (!d || d.total <= 0) {
        box.classList.add('hidden');
        return;
    }
    box.classList.remove('hidden');

    const totBadge = document.getElementById('unclaimedTotalBadge');
    if (totBadge) totBadge.textContent = d.total + ' Unit';

    const cAll = document.getElementById('unclaimedCntAll');
    if (cAll) cAll.textContent = d.total;

    const c1 = document.getElementById('unclaimedCnt1');
    if (c1) c1.textContent = d.stage_1 || 0;

    const c2 = document.getElementById('unclaimedCnt2');
    if (c2) c2.textContent = d.stage_2 || 0;

    const c3 = document.getElementById('unclaimedCnt3');
    if (c3) c3.textContent = d.stage_3 || 0;

    const c4 = document.getElementById('unclaimedCnt4');
    if (c4) c4.textContent = d.stage_4 || 0;
}

function filterUnclaimedStage(stg) {
    if (_unclaimedFilterStage === stg) {
        _unclaimedFilterStage = 0; // toggle off
    } else {
        _unclaimedFilterStage = stg;
    }

    const tabs = document.querySelectorAll('#unclaimedFilterTabs .unclaimed-filter-btn');
    tabs.forEach(btn => {
        const bStg = Number(btn.dataset.stage);
        if (bStg === _unclaimedFilterStage) btn.classList.add('is-active');
        else btn.classList.remove('is-active');
    });

    if (_unclaimedFilterStage > 0) {
        if (_unclaimedData && _unclaimedData.items) {
            const filtered = _unclaimedData.items.filter(x => x.stage === _unclaimedFilterStage);
            const body = document.getElementById('txBody');
            const empty = document.getElementById('txEmpty');
            const loading = document.getElementById('txLoading');
            const pagination = document.getElementById('txPagination');
            if (body) {
                if (loading) loading.classList.add('hidden');
                if (!filtered.length) {
                    if (empty) {
                        empty.innerHTML = '<i class="fa-solid fa-clock-rotate-left text-3xl mb-2 block opacity-40"></i>Tidak ada unit mengendap di tahap ini.';
                        empty.classList.remove('hidden');
                    }
                    body.innerHTML = '';
                } else {
                    if (empty) empty.classList.add('hidden');
                    body.innerHTML = filtered.map((o, idx) => txRowHtml(o, idx + 1)).join('');
                    const info = document.getElementById('txInfo');
                    if (info) {
                        info.textContent = `${filtered.length} unit mengendap (Tahap ${_unclaimedFilterStage})`;
                    }
                }
                if (pagination) pagination.classList.add('hidden');
            }
        }
    } else {
        renderTransaksi();
    }
}

function unclaimedWaOpen(orderId) {
    let o = null;
    if (_unclaimedData && _unclaimedData.items) {
        o = _unclaimedData.items.find(x => x.id === orderId);
    }
    if (!o) return;

    _unclaimedActiveTarget = o;
    const stage = o.stage || (o.days_pending >= 90 ? 4 : o.days_pending >= 60 ? 3 : o.days_pending >= 30 ? 2 : 1);

    const pop = document.getElementById('unclaimedWaPopup');
    if (!pop) return;

    const stageBadge = document.getElementById('unclaimedWaStageBadge');
    if (stageBadge) {
        stageBadge.textContent = 'Tahap ' + stage + ' (' + (stage === 4 ? '90+ Hari' : stage === 3 ? '60 Hari' : stage === 2 ? '30 Hari' : '7 Hari') + ')';
        stageBadge.className = 'px-2 py-0.5 rounded text-[11px] font-extrabold uppercase ' +
            (stage === 4 ? 'bg-red-100 text-red-800' : stage === 3 ? 'bg-pink-100 text-pink-800' : stage === 2 ? 'bg-orange-100 text-orange-800' : 'bg-amber-100 text-amber-800');
    }

    const titleEl = document.getElementById('unclaimedWaTitle');
    if (titleEl) {
        titleEl.textContent = o.status === 'DONE' ? 'Unit Selesai Belum Diambil' : 'Unit Gagal Belum Diambil';
    }

    const toEl = document.getElementById('unclaimedWaTo');
    if (toEl) {
        const doneTime = getUnclaimedWaDoneTime(o);
        toEl.innerHTML = `Kepada: <b>${escapeHtml(o.customer_name || 'Pelanggan')}</b> (${escapeHtml(o.customer_phone || '-')}) • <b>${escapeHtml(o.device || '-')}</b> (#${escapeHtml(o.no_servis || '-')})<br><span class="text-xs text-amber-700 font-semibold">Mengendap ${o.days_pending || 0} hari</span>` +
            (doneTime ? `<span class="ml-2 inline-flex items-center gap-1 text-emerald-600 font-bold text-xs"><i class="fa-solid fa-check"></i> Sudah disapa (${doneTime})</span>` : '');
    }

    const msgEl = document.getElementById('unclaimedWaMsg');
    if (msgEl) {
        msgEl.value = unclaimedWaMessage(o, stage);
    }

    const warnEl = document.getElementById('unclaimedWaWarn');
    const sendBtn = document.getElementById('unclaimedWaSendBtn');
    const cleanNum = (o.customer_phone || '').replace(/\D/g, '');
    if (!cleanNum) {
        if (warnEl) {
            warnEl.textContent = 'Nomor WhatsApp customer tidak tersedia.';
            warnEl.classList.remove('hidden');
        }
        if (sendBtn) sendBtn.disabled = true;
    } else {
        if (warnEl) warnEl.classList.add('hidden');
        if (sendBtn) sendBtn.disabled = false;
    }

    pop.classList.remove('hidden');
}

function unclaimedWaClose() {
    const pop = document.getElementById('unclaimedWaPopup');
    if (pop) pop.classList.add('hidden');
    _unclaimedActiveTarget = null;
}

function unclaimedWaMarkDone() {
    const o = _unclaimedActiveTarget;
    if (!o) return;
    setUnclaimedWaDone(o.no_servis || o.id, true);
    unclaimedWaClose();
    if (_unclaimedFilterStage > 0) filterUnclaimedStage(_unclaimedFilterStage);
    else renderTransaksi();
}

function unclaimedWaSend() {
    const o = _unclaimedActiveTarget;
    if (!o) return;
    const msgEl = document.getElementById('unclaimedWaMsg');
    const msg = msgEl ? msgEl.value : unclaimedWaMessage(o, o.stage || 1);

    let num = String(o.customer_phone || '').replace(/\D/g, '');
    if (num.startsWith('0')) num = '62' + num.slice(1);

    if (num) {
        window.open('https://wa.me/' + num + '?text=' + encodeURIComponent(msg), '_blank');
        setUnclaimedWaDone(o.no_servis || o.id, true);
    }
    unclaimedWaClose();
    if (_unclaimedFilterStage > 0) filterUnclaimedStage(_unclaimedFilterStage);
    else renderTransaksi();
}

window.loadUnclaimedUnits = loadUnclaimedUnits;
window.filterUnclaimedStage = filterUnclaimedStage;
window.unclaimedWaOpen = unclaimedWaOpen;
window.unclaimedWaClose = unclaimedWaClose;
window.unclaimedWaSend = unclaimedWaSend;
window.unclaimedWaMarkDone = unclaimedWaMarkDone;
window.unclaimedWaMessage = unclaimedWaMessage;


// ==========================================
// FITUR KASIR PENJUALAN PART & AKSESORIS (POS)
// ==========================================
window._posCart = [];
window._posSpareparts = [];
window._posActiveSale = null;

function posRupiah(v) {
    return 'Rp ' + (Number(v) || 0).toLocaleString('id-ID');
}

async function renderPenjualanPart() {
    const grid = document.getElementById('posProductGrid');
    if (grid) {
        grid.innerHTML = '<div class="col-span-2 text-center py-10 text-gray-400 text-xs flex items-center justify-center gap-2"><i class="fa-solid fa-circle-notch fa-spin text-emerald-500"></i> Memuat katalog produk...</div>';
    }
    try {
        const data = await apiGet('/spareparts?limit=200');
        window._posSpareparts = (data && data.items) || [];

        // Update category dropdown
        const catSelect = document.getElementById('posCategoryFilter');
        if (catSelect) {
            const currentVal = catSelect.value;
            const cats = Array.from(new Set(window._posSpareparts.map(p => (p.kategori || '').trim()).filter(Boolean))).sort();
            catSelect.innerHTML = '<option value="">Semua Kategori</option>' + cats.map(c => `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`).join('');
            catSelect.value = currentVal;
        }

        posFilterProducts();
        posRenderCart();
    } catch (err) {
        if (grid) {
            grid.innerHTML = `<div class="col-span-2 text-center py-8 text-rose-500 text-xs">Gagal memuat produk: ${escapeHtml(err.message || 'Error')}</div>`;
        }
    }
}

function posFilterProducts() {
    const grid = document.getElementById('posProductGrid');
    if (!grid) return;

    const q = (document.getElementById('posSearchInput')?.value || '').trim().toLowerCase();
    const cat = (document.getElementById('posCategoryFilter')?.value || '').trim();

    let list = window._posSpareparts || [];
    if (cat) {
        list = list.filter(p => (p.kategori || '').trim() === cat);
    }
    if (q) {
        list = list.filter(p => {
            const nama = (p.nama || p.jenis || '').toLowerCase();
            const merk = (p.merek || '').toLowerCase();
            const dev = (p.device || '').toLowerCase();
            const kode = (p.kode || '').toLowerCase();
            return nama.includes(q) || merk.includes(q) || dev.includes(q) || kode.includes(q);
        });
    }

    if (list.length === 0) {
        grid.innerHTML = '<div class="col-span-2 text-center py-12 text-gray-400 text-xs">Tidak ada produk yang cocok</div>';
        return;
    }

    grid.innerHTML = list.map(p => {
        const stok = Number(p.stok != null ? p.stok : p.qty) || 0;
        const harga = Number(p.harga_jual != null ? p.harga_jual : p.jual) || 0;
        const isHabis = stok <= 0;
        const isMenipis = !isHabis && stok <= 3;
        const badgeCls = isHabis
            ? 'bg-rose-50 dark:bg-rose-950/40 text-rose-600 dark:text-rose-400 border border-rose-200 dark:border-rose-900/50'
            : isMenipis
            ? 'bg-amber-50 dark:bg-amber-950/40 text-amber-600 dark:text-amber-400 border border-amber-200 dark:border-amber-900/50'
            : 'bg-emerald-50 dark:bg-emerald-950/40 text-emerald-600 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-900/50';
        const badgeTxt = isHabis ? 'Habis' : isMenipis ? `Sisa ${stok}` : `Stok ${stok}`;

        return `
            <div class="panel p-3 flex flex-col justify-between hover:border-emerald-500/40 transition group ${isHabis ? 'opacity-60 bg-gray-50/50 dark:bg-white/2' : ''}">
                <div class="space-y-1">
                    <div class="flex items-start justify-between gap-1.5">
                        <span class="font-bold text-xs text-gray-800 dark:text-gray-100 line-clamp-2">${escapeHtml(p.nama || p.jenis || '-')}</span>
                        <span class="text-[10px] font-semibold px-1.5 py-0.5 rounded ${badgeCls} shrink-0">${badgeTxt}</span>
                    </div>
                    <div class="text-[10.5px] text-gray-400 dark:text-gray-400 flex items-center gap-2">
                        ${p.device ? `<span><i class="fa-solid fa-mobile-screen text-[9px] mr-1"></i>${escapeHtml(p.device)}</span>` : ''}
                        ${p.kode ? `<span class="font-mono text-[9.5px]">[${escapeHtml(p.kode)}]</span>` : ''}
                    </div>
                </div>
                <div class="flex items-center justify-between pt-2.5 mt-2 border-t border-gray-100 dark:border-white/5">
                    <span class="text-xs font-extrabold text-emerald-600 dark:text-emerald-400 tabular-nums">${posRupiah(harga)}</span>
                    <button type="button" onclick="posAddToCart(${p.id})" ${isHabis ? 'disabled' : ''} class="px-2.5 py-1 rounded-lg bg-emerald-600 hover:bg-emerald-700 disabled:opacity-40 disabled:cursor-not-allowed text-white text-[11px] font-bold flex items-center gap-1 shadow-2xs transition">
                        <i class="fa-solid fa-plus text-[10px]"></i>
                        <span>Tambah</span>
                    </button>
                </div>
            </div>
        `;
    }).join('');
}

function posAddToCart(partId) {
    const part = (window._posSpareparts || []).find(p => p.id === partId);
    if (!part) return;

    const stok = Number(part.stok != null ? part.stok : part.qty) || 0;
    if (stok <= 0) {
        toast('Stok produk habis!', 'warning');
        return;
    }

    const item = window._posCart.find(i => i.id === partId);
    if (item) {
        if (item.qty + 1 > item.max_stock) {
            toast(`Maksimal stok tercapai: ${item.max_stock}`, 'warning');
            return;
        }
        item.qty += 1;
    } else {
        window._posCart.push({
            id: part.id,
            nama: part.nama || part.jenis || 'Part',
            device: part.device || '',
            kode: part.kode || '',
            harga_jual: Number(part.harga_jual != null ? part.harga_jual : part.jual) || 0,
            qty: 1,
            max_stock: stok,
        });
    }
    posRenderCart();
}

function posUpdateQty(partId, delta) {
    const idx = window._posCart.findIndex(i => i.id === partId);
    if (idx === -1) return;

    const item = window._posCart[idx];
    const target = item.qty + delta;
    if (target <= 0) {
        window._posCart.splice(idx, 1);
    } else if (target > item.max_stock) {
        toast(`Maksimal stok tercapai: ${item.max_stock}`, 'warning');
        return;
    } else {
        item.qty = target;
    }
    posRenderCart();
}

function posRemoveFromCart(partId) {
    window._posCart = window._posCart.filter(i => i.id !== partId);
    posRenderCart();
}

function posClearCart() {
    window._posCart = [];
    const custName = document.getElementById('posCustomerName');
    const custPhone = document.getElementById('posCustomerPhone');
    const notes = document.getElementById('posNotes');
    const cashRec = document.getElementById('posCashReceived');
    if (custName) custName.value = '';
    if (custPhone) custPhone.value = '';
    if (notes) notes.value = '';
    if (cashRec) cashRec.value = '';
    posRenderCart();
}

function posRenderCart() {
    const countBadge = document.getElementById('posCartCount');
    const container = document.getElementById('posCartItems');
    const totalEl = document.getElementById('posTotalOmzet');

    const totalQty = window._posCart.reduce((sum, i) => sum + i.qty, 0);
    const subtotal = window._posCart.reduce((sum, i) => sum + (i.qty * i.harga_jual), 0);

    if (countBadge) countBadge.textContent = `${totalQty} item`;
    if (totalEl) totalEl.textContent = posRupiah(subtotal);

    if (!container) return;

    if (window._posCart.length === 0) {
        container.innerHTML = `
            <div class="text-center py-10 text-gray-400 text-xs space-y-1">
                <i class="fa-solid fa-cart-arrow-down text-2xl text-gray-300 dark:text-gray-600"></i>
                <p>Keranjang masih kosong</p>
                <p class="text-[10.5px] text-gray-400">Pilih produk di katalog sebelah kiri</p>
            </div>
        `;
        posCalcChange();
        return;
    }

    container.innerHTML = window._posCart.map(item => `
        <div class="p-2.5 rounded-xl bg-gray-50 dark:bg-white/5 border border-gray-200/70 dark:border-white/5 space-y-1.5">
            <div class="flex items-start justify-between gap-2">
                <div class="flex-1">
                    <div class="font-bold text-xs text-gray-800 dark:text-gray-100 line-clamp-1">${escapeHtml(item.nama)}</div>
                    <div class="text-[10px] text-gray-400">${item.device ? escapeHtml(item.device) + ' • ' : ''}${posRupiah(item.harga_jual)} / pcs</div>
                </div>
                <button type="button" onclick="posRemoveFromCart(${item.id})" class="text-gray-400 hover:text-rose-500 p-1 text-xs transition" title="Hapus">
                    <i class="fa-solid fa-xmark"></i>
                </button>
            </div>
            <div class="flex items-center justify-between pt-1">
                <div class="flex items-center gap-1.5">
                    <button type="button" onclick="posUpdateQty(${item.id}, -1)" class="w-6 h-6 rounded-md bg-white dark:bg-surface-800 border border-gray-200 dark:border-white/10 flex items-center justify-center text-xs font-bold text-gray-700 dark:text-gray-200 hover:bg-gray-100 transition">-</button>
                    <span class="w-8 text-center text-xs font-extrabold text-gray-800 dark:text-gray-100 tabular-nums">${item.qty}</span>
                    <button type="button" onclick="posUpdateQty(${item.id}, 1)" class="w-6 h-6 rounded-md bg-white dark:bg-surface-800 border border-gray-200 dark:border-white/10 flex items-center justify-center text-xs font-bold text-gray-700 dark:text-gray-200 hover:bg-gray-100 transition">+</button>
                </div>
                <span class="text-xs font-bold text-gray-900 dark:text-white tabular-nums">${posRupiah(item.qty * item.harga_jual)}</span>
            </div>
        </div>
    `).join('');

    posCalcChange();
}

function posCalcChange() {
    const subtotal = window._posCart.reduce((sum, i) => sum + (i.qty * i.harga_jual), 0);
    const method = document.querySelector('input[name="posPaymentMethod"]:checked')?.value || 'CASH';
    const cashBox = document.getElementById('posCashInputs');
    const cashInput = document.getElementById('posCashReceived');
    const changeText = document.getElementById('posChangeText');

    if (method === 'TRANSFER') {
        if (cashBox) cashBox.classList.add('hidden');
        if (changeText) {
            changeText.textContent = 'Pas (Transfer)';
            changeText.className = 'px-2.5 py-1.5 text-xs font-extrabold text-indigo-600 dark:text-indigo-400 tabular-nums bg-gray-50 dark:bg-white/5 rounded-lg border border-gray-200 dark:border-white/10';
        }
    } else {
        if (cashBox) cashBox.classList.remove('hidden');
        const received = Number(cashInput?.value) || 0;
        if (!changeText) return;

        if (received >= subtotal) {
            const kembalian = received - subtotal;
            changeText.textContent = posRupiah(kembalian);
            changeText.className = 'px-2.5 py-1.5 text-xs font-extrabold text-emerald-600 dark:text-emerald-400 tabular-nums bg-gray-50 dark:bg-white/5 rounded-lg border border-gray-200 dark:border-white/10';
        } else {
            const kurang = subtotal - received;
            changeText.textContent = 'Kurang ' + posRupiah(kurang);
            changeText.className = 'px-2.5 py-1.5 text-xs font-extrabold text-rose-600 dark:text-rose-400 tabular-nums bg-rose-50 dark:bg-rose-950/40 rounded-lg border border-rose-200 dark:border-rose-900/50';
        }
    }
}

async function posSubmitSale() {
    if (window._posCart.length === 0) {
        toast('Keranjang masih kosong!', 'warning');
        return;
    }

    const subtotal = window._posCart.reduce((sum, i) => sum + (i.qty * i.harga_jual), 0);
    const method = document.querySelector('input[name="posPaymentMethod"]:checked')?.value || 'CASH';
    const cashInput = document.getElementById('posCashReceived');
    const received = method === 'CASH' ? (Number(cashInput?.value) || 0) : subtotal;

    if (method === 'CASH' && received < subtotal) {
        toast('Uang tunai diterima kurang dari total tagihan!', 'warning');
        return;
    }

    const custName = (document.getElementById('posCustomerName')?.value || '').trim() || 'Pelanggan Umum';
    const custPhone = (document.getElementById('posCustomerPhone')?.value || '').trim() || null;
    const notes = (document.getElementById('posNotes')?.value || '').trim() || null;

    const payload = {
        customer_name: custName,
        customer_phone: custPhone,
        payment_method: method,
        catatan: notes,
        items: window._posCart.map(i => ({
            sparepart_id: i.id,
            qty: i.qty,
            harga_jual: i.harga_jual
        }))
    };

    const submitBtn = document.getElementById('posSubmitBtn');
    if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i> Memproses...';
    }

    try {
        const result = await apiPost('/spareparts/sales', payload);
        toast('Transaksi penjualan part berhasil!', 'success');

        const kembalian = method === 'CASH' ? Math.max(0, received - subtotal) : 0;
        posShowReceipt(result, received, kembalian);

        posClearCart();
        renderPenjualanPart();
        try { if (typeof renderKondisiKas === 'function') renderKondisiKas(); } catch (_) {}
    } catch (err) {
        toast(err.message || 'Gagal memproses transaksi!', 'danger');
    } finally {
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.innerHTML = '<i class="fa-solid fa-receipt"></i><span>Proses & Cetak Struk</span>';
        }
    }
}

function posShowReceipt(sale, bayar, kembali) {
    window._posActiveSale = sale;
    const modal = document.getElementById('posReceiptModal');
    const receipt = document.getElementById('posThermalReceipt');
    if (!modal || !receipt) return;

    const tgl = (sale.created_at || '').replace('T', ' ').slice(0, 16) || new Date().toLocaleString('id-ID');
    const items = sale.items || [];
    const bayarVal = bayar != null ? bayar : Number(sale.total_omzet);
    const kembaliVal = kembali != null ? kembali : 0;

    receipt.innerHTML = `
        <div class="text-center pb-2.5 border-b border-dashed border-gray-300 dark:border-white/20 mb-2.5">
            <div class="font-extrabold text-[12px] uppercase tracking-wider text-gray-900 dark:text-white">MJ PRO SERVICE</div>
            <div class="text-[9.5px] text-gray-500 dark:text-gray-400">Spesialis Service HP & Sparepart</div>
            <div class="text-[9px] text-gray-400">Struk Resmi Penjualan Sparepart</div>
        </div>
        <div class="space-y-0.5 text-[10px] pb-2 border-b border-dashed border-gray-300 dark:border-white/20 mb-2 text-gray-600 dark:text-gray-300">
            <div class="flex justify-between"><span>No:</span><span class="font-bold text-gray-900 dark:text-white">${escapeHtml(sale.no_transaksi || '-')}</span></div>
            <div class="flex justify-between"><span>Tgl:</span><span>${escapeHtml(tgl)}</span></div>
            <div class="flex justify-between"><span>Kasir:</span><span>${escapeHtml(sale.oleh || 'Kasir')}</span></div>
            <div class="flex justify-between"><span>Pembeli:</span><span>${escapeHtml(sale.customer_name || 'Pelanggan Umum')}</span></div>
        </div>
        <div class="space-y-1.5 pb-2 border-b border-dashed border-gray-300 dark:border-white/20 mb-2">
            ${items.map(it => `
                <div class="text-[10px]">
                    <div class="font-semibold text-gray-800 dark:text-gray-200 line-clamp-1">${escapeHtml(it.sparepart_name || 'Part #' + it.sparepart_id)}</div>
                    <div class="flex justify-between text-gray-500 dark:text-gray-400 text-[9.5px]">
                        <span>${it.qty} x ${posRupiah(it.harga_jual)}</span>
                        <span class="font-bold text-gray-800 dark:text-gray-200">${posRupiah(it.subtotal)}</span>
                    </div>
                </div>
            `).join('')}
        </div>
        <div class="space-y-1 text-[10.5px] pb-2 border-b border-dashed border-gray-300 dark:border-white/20 mb-2">
            <div class="flex justify-between font-extrabold text-xs text-gray-900 dark:text-white">
                <span>TOTAL:</span>
                <span>${posRupiah(sale.total_omzet)}</span>
            </div>
            <div class="flex justify-between text-gray-500 dark:text-gray-400 text-[10px]">
                <span>Metode:</span>
                <span>${escapeHtml(sale.payment_method || 'CASH')}</span>
            </div>
            <div class="flex justify-between text-gray-500 dark:text-gray-400 text-[10px]">
                <span>Bayar:</span>
                <span>${posRupiah(bayarVal)}</span>
            </div>
            <div class="flex justify-between text-gray-500 dark:text-gray-400 text-[10px]">
                <span>Kembali:</span>
                <span>${posRupiah(kembaliVal)}</span>
            </div>
        </div>
        <div class="text-center text-[9px] text-gray-400 dark:text-gray-500 space-y-0.5 pt-1">
            <div>Terima kasih atas kunjungan Anda</div>
            <div>Barang yang dibeli tidak dapat ditukar/dikembalikan</div>
        </div>
    `;

    modal.classList.remove('hidden');
}

function posDoPrint() {
    window.print();
}

function posCloseReceiptModal() {
    const modal = document.getElementById('posReceiptModal');
    if (modal) modal.classList.add('hidden');
}

async function posOpenHistoryModal() {
    const modal = document.getElementById('posHistoryModal');
    const tbody = document.getElementById('posHistoryList');
    if (!modal || !tbody) return;

    tbody.innerHTML = '<tr><td colspan="5" class="py-6 text-center text-gray-400 text-xs"><i class="fa-solid fa-circle-notch fa-spin text-emerald-500"></i> Memuat riwayat struk...</td></tr>';
    modal.classList.remove('hidden');

    try {
        const res = await apiGet('/spareparts/sales?limit=30');
        const sales = (res && res.items) || [];
        if (sales.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" class="py-6 text-center text-gray-400 text-xs">Belum ada riwayat transaksi</td></tr>';
            return;
        }

        tbody.innerHTML = sales.map(s => {
            const tgl = (s.created_at || '').replace('T', ' ').slice(0, 16);
            return `
                <tr class="hover:bg-gray-50 dark:hover:bg-white/5 transition">
                    <td class="py-2 px-2.5 font-bold font-mono text-emerald-600 dark:text-emerald-400">${escapeHtml(s.no_transaksi)}</td>
                    <td class="py-2 px-2.5 text-gray-500">${escapeHtml(tgl)}</td>
                    <td class="py-2 px-2.5 font-medium">${escapeHtml(s.customer_name || 'Pelanggan Umum')}</td>
                    <td class="py-2 px-2.5 text-right font-extrabold text-gray-900 dark:text-white tabular-nums">${posRupiah(s.total_omzet)}</td>
                    <td class="py-2 px-2.5 text-right">
                        <button type="button" onclick="posPrintFromHistory(${s.id})" class="px-2 py-1 bg-emerald-50 dark:bg-emerald-950/40 hover:bg-emerald-100 text-emerald-700 dark:text-emerald-300 rounded font-semibold text-[11px] inline-flex items-center gap-1 transition">
                            <i class="fa-solid fa-print"></i>
                            <span>Cetak</span>
                        </button>
                    </td>
                </tr>
            `;
        }).join('');
    } catch (err) {
        tbody.innerHTML = `<tr><td colspan="5" class="py-6 text-center text-rose-500 text-xs">Gagal: ${escapeHtml(err.message || 'Error')}</td></tr>`;
    }
}

function posCloseHistoryModal() {
    const modal = document.getElementById('posHistoryModal');
    if (modal) modal.classList.add('hidden');
}

async function posPrintFromHistory(saleId) {
    try {
        const sale = await apiGet(`/spareparts/sales/${saleId}`);
        if (sale) {
            posShowReceipt(sale, Number(sale.total_omzet), 0);
        }
    } catch (err) {
        toast('Gagal memuat detail transaksi: ' + (err.message || 'Error'), 'danger');
    }
}

// Window exports
window.showPenjualanPart = showPenjualanPart;
window.renderPenjualanPart = renderPenjualanPart;
window.posFilterProducts = posFilterProducts;
window.posAddToCart = posAddToCart;
window.posUpdateQty = posUpdateQty;
window.posRemoveFromCart = posRemoveFromCart;
window.posClearCart = posClearCart;
window.posCalcChange = posCalcChange;
window.posSubmitSale = posSubmitSale;
window.posShowReceipt = posShowReceipt;
window.posDoPrint = posDoPrint;
window.posCloseReceiptModal = posCloseReceiptModal;
window.posOpenHistoryModal = posOpenHistoryModal;
window.posCloseHistoryModal = posCloseHistoryModal;
window.posPrintFromHistory = posPrintFromHistory;
