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
function getRemember() { return localStorage.getItem('bsf_remember') !== '0'; }
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

const VALID_PAGES = ['dashboard', 'transaksi', 'pelanggan', 'garansi', 'sparepart', 'keuangan'];

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
const RECEIVE_DRAFT_FIELDS = ['rcName', 'rcPhone', 'rcDevice', 'rcPassword', 'rcImei', 'rcDamage', 'rcPlan', 'rcEstimate', 'rcDp', 'rcTechnician', 'rcStatus'];
let _rcDraftTimer = null;

function collectReceiveDraft() {
    const d = {};
    RECEIVE_DRAFT_FIELDS.forEach(id => {
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
    if (!d) return false;
    RECEIVE_DRAFT_FIELDS.forEach(id => {
        const el = document.getElementById(id);
        if (!el || d[id] === undefined) return;
        // Jangan timpa pilihan teknisi bila option-nya belum ada (daftar async).
        if (id === 'rcTechnician' && d[id] && !Array.from(el.options).some(o => o.value === d[id])) return;
        el.value = d[id];
    });
    try {
        if (d._checklist && typeof applyChecklist === 'function') applyChecklist('rc', d._checklist);
    } catch (_) {}
    try { updateReceiveSteps(); } catch (_) {}
    return true;
}

function clearReceiveDraft() {
    try { localStorage.removeItem(RECEIVE_DRAFT_KEY); } catch (_) {}
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

function navigateTo(key) {
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
function showSparepart() { showPage('sparepart'); renderSparepart(); }
function showKeuangan() { showPage('keuangan'); renderKeuangan(); }
function showAkun() { showPage('akun'); renderAkun(); }

// ─────────────────────────────────────────────
// KELOLA AKUN (tahap UI: dummy in-memory, backend tahap berikutnya)
// ─────────────────────────────────────────────
const AKUN_DUMMY = [
    { nama: 'Andi Pratama', username: 'andi_admin', role: 'Admin', status: 'Aktif', login: 'Hari ini, 08:30' },
    { nama: 'Budi Santoso', username: 'budi_super', role: 'Admin', status: 'Aktif', login: 'Kemarin, 14:15' },
    { nama: 'Citra Kirana', username: 'citra_tek', role: 'Teknisi', status: 'Aktif', login: 'Hari ini, 09:05' },
    { nama: 'Doni Setiawan', username: 'doni_tek', role: 'Teknisi', status: 'Aktif', login: 'Hari ini, 10:20' },
    { nama: 'Eko Wahyudi', username: 'eko_tek', role: 'Teknisi', status: 'Nonaktif', login: '12 Ags 2026, 16:45' },
];

let _akQuery = '';
let _akRole = '';
let _akStatus = '';
let _akEditIdx = -1;

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
    return AKUN_DUMMY.filter(a => {
        if (_akRole && a.role !== _akRole) return false;
        if (_akStatus && a.status !== _akStatus) return false;
        if (!q) return true;
        return [a.nama, a.username].some(f => (f || '').toLowerCase().includes(q));
    });
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

function renderAkun() {
    initAkToolbar();
    initAkunForm();
    const body = document.getElementById('akBody');
    if (!body) return;
    const total = AKUN_DUMMY.length;
    const aktif = AKUN_DUMMY.filter(a => a.status === 'Aktif').length;
    const admin = AKUN_DUMMY.filter(a => a.role === 'Admin').length;
    const setNum = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
    setNum('akTotal', total);
    setNum('akAktif', aktif);
    setNum('akAdmin', admin);
    const data = akFiltered();
    body.innerHTML = data.map((a, i) => {
        const idx = AKUN_DUMMY.indexOf(a);
        return `
        <tr class="tx-row${i % 2 ? ' bg-gray-50/50 dark:bg-white/[0.02]' : ''}">
            <td class="text-center text-gray-500">${i + 1}</td>
            <td class="font-semibold text-gray-800 dark:text-gray-200">${escapeHtml(a.nama)}</td>
            <td class="text-gray-500">${escapeHtml(a.username)}</td>
            <td class="text-center">${akRoleBadge(a.role)}</td>
            <td class="text-center">${akStatusBadge(a.status)}</td>
            <td class="text-gray-500 text-[11px]">${escapeHtml(a.login)}</td>
            <td class="text-center">
                <button class="w-7 h-7 rounded bg-gray-100 dark:bg-white/5 hover:bg-brand-50 dark:hover:bg-brand-500/10 text-gray-500 hover:text-brand-500 transition-colors" title="Edit Akun" onclick="akEdit(${idx})"><i class="fa-solid fa-pen-to-square"></i></button>
                <button class="tx-view-btn tx-del-btn" title="Hapus Akun" onclick="akDel(${idx})"><i class="fa-solid fa-trash"></i></button>
            </td>
        </tr>`;
    }).join('');
    const info = document.getElementById('akInfo');
    if (info) info.textContent = data.length === total
        ? 'Menampilkan 1-' + total + ' dari ' + total + ' akun'
        : 'Menampilkan ' + data.length + ' dari ' + total + ' akun (filter)';
}

function akEdit(i) {
    const a = AKUN_DUMMY[i];
    if (!a) return;
    _akEditIdx = i;
    document.getElementById('akFormTitle').textContent = 'Edit Akun';
    document.getElementById('akNama').value = a.nama || '';
    document.getElementById('akUsername').value = a.username || '';
    document.getElementById('akPassword').value = '';
    document.getElementById('akRole').value = a.role || 'Teknisi';
    document.getElementById('akStatus').value = a.status || 'Aktif';
    openFormAkun();
}

function akDel(i) {
    const a = AKUN_DUMMY[i];
    if (!a) return;
    if (!confirm('Hapus akun "' + a.username + '"? (lokal, tidak memengaruhi database)')) return;
    AKUN_DUMMY.splice(i, 1);
    renderAkun();
}

function initAkunForm() {
    const form = document.getElementById('akunForm');
    if (!form || form.dataset.bound) return;
    form.dataset.bound = '1';
    form.addEventListener('submit', function (e) {
        e.preventDefault();
        const nama = document.getElementById('akNama').value.trim();
        const username = document.getElementById('akUsername').value.trim();
        if (!nama || !username) return;
        if (AKUN_DUMMY.some((a, j) => j !== _akEditIdx && a.username.toLowerCase() === username.toLowerCase())) {
            alert('Username sudah dipakai akun lain.');
            return;
        }
        const item = {
            nama: nama,
            username: username,
            role: document.getElementById('akRole').value,
            status: document.getElementById('akStatus').value,
            login: (_akEditIdx >= 0 && AKUN_DUMMY[_akEditIdx]) ? AKUN_DUMMY[_akEditIdx].login : 'Belum pernah login',
        };
        if (_akEditIdx >= 0 && AKUN_DUMMY[_akEditIdx]) {
            AKUN_DUMMY[_akEditIdx] = item;
        } else {
            AKUN_DUMMY.push(item);
        }
        renderAkun();
        closeFormAkun();
    });
}

function openServisBaru() {
    document.getElementById('pageReceive').classList.add('open');
    try { localStorage.setItem(RECEIVE_OPEN_KEY, '1'); } catch (_) {}
    closeReceiveSuccessPopup(false);
    restoreReceiveDraft();
    setReceiveHash();
    const _nb = document.getElementById('receiveNotaBtn');
    if (_nb) _nb.classList.add('hidden');
    const _st = document.getElementById('receiveSubmitText');
    if (_st) _st.textContent = 'Terima dan Daftarkan Unit Servis';
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
    _akEditIdx = -1;
    document.getElementById('akFormTitle').textContent = 'Tambah Akun';
    document.getElementById('akunForm').reset();
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

async function apiPost(path, body) {
    const headers = { 'Content-Type': 'application/json' };
    const token = getToken();
    if (token) headers['Authorization'] = 'Bearer ' + token;
    const res = await fetch(API_BASE + path, {
        method: 'POST',
        headers,
        body: JSON.stringify(body || {}),
    });
    if (res.status === 401) { throw new AuthError('Sesi tidak valid'); }
    if (!res.ok) {
        let detail = 'Gagal menyimpan data (HTTP ' + res.status + ')';
        try { const j = await res.json(); if (j.detail) detail = j.detail; } catch (_) {}
        throw new Error(detail);
    }
    return res.json();
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
    const res = await fetch(API_BASE + path, { method: 'DELETE', headers });
    if (res.status === 401) { throw new AuthError('Sesi tidak valid'); }
    if (!res.ok) {
        let detail = 'Gagal menghapus data (HTTP ' + res.status + ')';
        try { const j = await res.json(); if (j.detail) detail = j.detail; } catch (_) {}
        throw new Error(detail);
    }
    try { return await res.json(); } catch (_) { return { ok: true }; }
}

// Warna semantik KPI (ref: warna-reference.png):
// hijau=pemasukan, biru=finansial utama, amber=beban,
// dinamis=bersih (hijau/merah), target=kartu putih netral
const STAR_META = [
    { emoji: '💰', tint: 'kpi-green' },
    { emoji: '⚡', tint: 'kpi-blue' },
    { emoji: '💸', tint: 'kpi-amber' },
    { emoji: '🏆', tint: 'kpi-green' },
    { emoji: '🎯', tint: 'kpi-target' },
];

const kpiRupiah = v => 'Rp ' + (Number(v) || 0).toLocaleString('en-US');

// ─────────────────────────────────────────────
// RENDER: STAR CARDS (dari API overview)
// ─────────────────────────────────────────────

async function renderStarCards() {
    const data = await apiGet('/overview');
    const cards = data.star_cards.map((c, i) => {
        let m = STAR_META[i] || {};
        if (i === 3) {
            m = Number(c.value) < 0 ? { emoji: '🏆', tint: 'kpi-red' } : { emoji: '🏆', tint: 'kpi-green' };
        }
        const cvalue = typeof c.value === 'number' ? kpiRupiah(c.value) : c.value;
        if (i === 4) {
            const bersih = data.star_cards[3] ? Number(data.star_cards[3].value) || 0 : 0;
            const target = Number(c.value) || 0;
            const kurang = Math.max(0, target - bersih);
            return `
            <div class="star-card kpi-target">
                <div class="kpi-top"><span class="kpi-label-dark">🎯 ${c.label}</span>${c.change ? `<span class="kpi-pct">${c.change}</span>` : ''}</div>
                <div class="kpi-value-dark">${cvalue}</div>
                ${target > 0 ? `<div class="kpi-caption">Kurang ${kpiRupiah(kurang)} lagi</div>` : ''}
            </div>
            `;
        }
        return `
            <div class="star-card ${m.tint} kpi-solid">
                <div class="kpi-top"><span class="kpi-label">${c.label}</span><span class="kpi-emoji">${m.emoji}</span></div>
                <div class="kpi-value">${cvalue}</div>
                ${c.change ? `<span class="kpi-badge"><i class="fa-solid fa-arrow-${c.up ? 'up' : 'down'}"></i>${c.change}</span>` : ''}
            </div>
        `;
    }).join('');
    document.getElementById('starCards').innerHTML = cards;
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
        const go = i === 0 ? ' onclick="openServisBaru()"' : '';
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
        'Unit Cash': 'fa-money-bill-wave',
        'Unit Pending': 'fa-clock',
    };
    const tintMap = {
        'Unit Masuk': 'in-blue',
        'Unit Selesai': 'in-green',
        'Unit Cash': 'in-amber',
        'Unit Pending': 'in-red',
    };
    const colorMap = {
        'Unit Masuk': 'text-blue-600',
        'Unit Selesai': 'text-green-600',
        'Unit Cash': 'text-amber-600',
        'Unit Pending': 'text-red-600',
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
// Tahap UI + dummy data — backend diintegrasikan tahap berikutnya.
// ─────────────────────────────────────────────
const STATUS_TX_ORDER = ['Analisa', 'Konfirmasi', 'Wait Part', 'Repair', 'Done', 'Failed', 'Garansi', 'Refund', 'Cancel', 'Cash'];

const STATUS_TX_DUMMY = [
    { name: 'Analisa',    value: 3, color: '#64748b', cls: 'sm-slate',  icon: 'fa-magnifying-glass' },
    { name: 'Konfirmasi', value: 1, color: '#f97316', cls: 'sm-orange', icon: 'fa-clipboard-check' },
    { name: 'Wait Part',  value: 3, color: '#ca8a04', cls: 'sm-gold',   icon: 'fa-hourglass-half' },
    { name: 'Repair',     value: 6, color: '#2563eb', cls: 'sm-blue',   icon: 'fa-screwdriver-wrench' },
    { name: 'Done',       value: 6, color: '#16a34a', cls: 'sm-green',  icon: 'fa-circle-check' },
    { name: 'Failed',     value: 1, color: '#dc2626', cls: 'sm-red',    icon: 'fa-circle-xmark' },
    { name: 'Garansi',    value: 1, color: '#7c3aed', cls: 'sm-purple', icon: 'fa-shield-halved' },
    { name: 'Refund',     value: 0, color: '#0d9488', cls: 'sm-teal',   icon: 'fa-rotate-left' },
    { name: 'Cancel',     value: 0, color: '#e11d48', cls: 'sm-rose',   icon: 'fa-ban' },
    { name: 'Cash',       value: 0, color: '#059669', cls: 'sm-emerald', icon: 'fa-cash-register' },
];

const STATUS_TX_TOTAL = STATUS_TX_DUMMY.reduce((a, b) => a + b.value, 0); // 21

async function initCharts() {
    const co = getCommonOpts();

    // Statistik Status Transaksi — Smooth Line/Area per status (dummy)
    const discrete = STATUS_TX_DUMMY.map((s, i) => ({
        seriesIndex: 0,
        dataPointIndex: i,
        fillColor: s.color,
        strokeColor: isDark() ? '#111118' : '#ffffff',
        size: 5,
    }));
    statusChart = new ApexCharts(document.querySelector('#chartStatusTransaksi'), {
        ...co,
        chart: { ...co.chart, type: 'area', height: getChartHeight(), toolbar: { show: false }, zoom: { enabled: false } },
        series: [{ name: 'Transaksi', data: STATUS_TX_DUMMY.map(s => s.value) }],
        xaxis: {
            categories: STATUS_TX_ORDER,
            labels: { style: { fontSize: '9px', fontWeight: 600 }, rotate: 0, trim: false },
            axisBorder: { show: false },
            axisTicks: { show: false },
        },
        yaxis: { min: 0, max: 7, tickAmount: 7, labels: { style: { fontSize: '10px' } } },
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
    // Dummy tahap UI — backend diintegrasikan tahap berikutnya.
    const total = STATUS_TX_TOTAL;
    const pct = v => total > 0 ? (v / total * 100).toFixed(1) + '%' : '0.0%';
    grid.innerHTML = STATUS_TX_DUMMY.map(c => `
        <div class="sm-card ${c.cls}">
            <div class="sm-top"><i class="fa-solid ${c.icon}"></i>${c.name}</div>
            <div class="sm-bot"><span class="sm-num">${c.value}</span><span class="sm-pct">${pct(c.value)}</span></div>
        </div>
    `).join('');
    if (banner) {
        const top = STATUS_TX_DUMMY.slice().sort((a, b) => b.value - a.value)[0];
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
            } else if (page === 'sparepart') {
                showSparepart();
            } else if (page === 'keuangan') {
                showKeuangan();
            } else if (page === 'servisbaru') {
                showPage('receive');
            } else {
                showPage(page === 'dashboard' ? 'dashboard' : 'dashboard');
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

function setAdminUI(user) {
    const name = user.display_name || 'Administrator';
    const initial = name.charAt(0).toUpperCase();
    document.getElementById('adminName').textContent = name;
    const avatar = document.querySelector('#appSidebar .rounded-full.flex');
    if (avatar) avatar.textContent = initial;
    const welcome = document.querySelector('.app-topbar h1 span.text-brand-500');
    if (welcome) welcome.textContent = user.display_name || 'Admin';
}

async function loadDashboard() {
    await Promise.all([renderStarCards(), renderInsights(), initCharts(), renderStatusMini(), renderDamageSection()]);
}

// ─────────────────────────────────────────────
// HALAMAN TRANSAKSI
// ─────────────────────────────────────────────

const TX_STATUS_LABEL = {
    RECEIVED: 'Diterima',
    DIAGNOSIS: 'Diagnosa',
    ANALISA: 'Analisa',
    REPAIR: 'Perbaikan',
    REPARASI: 'Reparasi',
    WAITING_PART: 'Tunggu Part',
    WAITING_APPROVAL: 'Tunggu Konfirmasi',
    READY: 'Siap Diambil',
    COMPLETED: 'Selesai',
    SELESAI: 'Selesai',
    CANCELLED: 'Batal',
    BATAL: 'Batal',
    QC: 'QC',
    KONFIRMASI: 'Konfirmasi',
    REVIEW: 'Review',
    DONE: 'Selesai',
    CASH: 'Cash/Lunas',
    FILED: 'Arsip',
    CANCEL: 'Batal',
    WAIT_PART: 'Tunggu Part',
};

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

async function renderTransaksi() {
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
        <td class="tx-cell-muted">${txDate(o.service_date)}</td>
        <td><span class="tx-device">${escapeHtml(o.device || '-')}</span></td>
        <td>
            <div class="tx-user">${escapeHtml(o.customer_name || '-')}</div>
            <div class="tx-cell-muted">${escapeHtml(o.customer_phone || '')}</div>
        </td>
        <td>${txStatusBadge(o.status)}</td>
        <td class="tx-cell-muted">${escapeHtml(o.damagetype || '-')}</td>
        <td class="tx-cell-muted">${escapeHtml(o.repair_plan || '-')}</td>
        <td class="tx-cell-muted">${escapeHtml(o.technician || '-')}</td>
        <td class="tx-laba">${txLaba(o)}</td>
        <td class="tx-aksi">
            <button type="button" class="tx-view-btn" title="Detail" onclick="txDetail(${o.id})"><i class="fa-solid fa-eye"></i></button>
            <button type="button" class="tx-view-btn tx-edit-btn" title="Edit" onclick="txEdit(${o.id})"><i class="fa-solid fa-pen"></i></button>
            <button type="button" class="tx-view-btn tx-del-btn" title="Hapus" onclick="txDel(${o.id})"><i class="fa-solid fa-trash"></i></button>
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
        pagination.classList.remove('hidden');
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
        if (info) info.textContent = 'Halaman ' + _txPage + '  ' + start + ' - ' + end + '  (dari ' + _txTotal + ' transaksi)';

        const pageBtns = document.getElementById('txPageBtns');
        if (pageBtns) {
            pageBtns.innerHTML = '';
            const mkBtn = (txt, p, disabled, active) => {
                const b = document.createElement('button');
                b.type = 'button';
                b.textContent = txt;
                b.className = 'tx-page-btn' + (active ? ' active' : '') + (disabled ? ' disabled' : '');
                if (!disabled) b.addEventListener('click', () => loadTxPage(p));
                return b;
            };
            pageBtns.appendChild(mkBtn('← Sebelumnya', _txPage - 1, _txPage === 1, false));
            for (let p = 1; p <= _txTotalPages; p++) {
                pageBtns.appendChild(mkBtn(String(p), p, false, p === _txPage));
            }
            pageBtns.appendChild(mkBtn('Berikutnya →', _txPage + 1, _txPage === _txTotalPages, false));
        }
    } catch (err) {
        loading.classList.add('hidden');
        empty.classList.remove('hidden');
        empty.innerHTML = '<i class="fa-solid fa-circle-exclamation text-3xl mb-2 block opacity-40"></i>Gagal memuat data.';
    }
}

function txDetail(id) {
    alert('Detail transaksi #' + id + ' (belum diimplementasikan)');
}

let _txEditId = null;
let _txEditCustomerId = null;

async function txEdit(id) {
    let o;
    try {
        o = await apiGet('/orders/' + id);
    } catch (err) {
        alert(err.message);
        return;
    }
    openUpdateServis(o);
}

async function txDel(id) {
    if (!confirm('Hapus transaksi #' + id + '? Data yang dihapus tidak bisa dikembalikan.')) return;
    try {
        await apiDel('/orders/' + id);
        await renderTransaksi();
    } catch (err) {
        alert(err.message);
    }
}

// ─────────────────────────────────────────────
// UPDATE DATA SERVIS (edit transaksi: kiri data, kanan finance + aksi)
// Finance = dummy tahap UI (tanpa endpoint); data servis memakai PUT yang sudah ada.
// ─────────────────────────────────────────────

function usVal(id) { const el = document.getElementById(id); return el ? el.value : ''; }
function usNum(id) { return parseFloat(usVal(id)) || 0; }

let _usNo = '';
let _usTgl = '';
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
    _usTgl = (o.service_date || '').slice(0, 10) || new Date().toISOString().slice(0, 10);
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
    // Finance dummy: nilai awal dari data tersimpan
    document.getElementById('usFinFinal').value = (o.estimate !== null && o.estimate !== undefined) ? o.estimate : '';
    document.getElementById('usFinPart').value = '';
    document.getElementById('usFinPartKe').value = 'Toko';
    document.getElementById('usFinJasaMode').value = 'Manual';
    document.getElementById('usFinJasa').value = '';
    document.getElementById('usFinJasaKe').value = o.technician || '';
    document.getElementById('usFinLain').value = '';
    // Checklist awal: SELALU dari data server per No. Servis (bukan dummy,
    // bukan store lokal). Setelah refresh pun tampil sama persis.
    const _usCheck = _usServerChecklist(o);
    applyChecklist('us', _usCheck);
    _usCheckBaseline = JSON.stringify(_usCheck);
    _checkStore[_usNo] = _usCheck;
    usSetStatus(o.status || 'ANALISA');
    usFinUpdate();
    const fb = document.getElementById('usFeedback');
    if (fb) fb.classList.add('hidden');
    const txt = document.getElementById('usSaveText');
    if (txt) txt.textContent = 'Simpan Perubahan Servis';
    document.getElementById('pageUpdateServis').classList.add('open');
}

function closeUpdateServis() {
    document.getElementById('pageUpdateServis').classList.remove('open');
    _txEditId = null;
    _txEditCustomerId = null;
    _usNo = '';
    _usTgl = '';
}

// Status unit: SATU sumber tulis (usSetStatus) + SATU sumber baca (usGetStatus).
// Kedua kontrol (usStatus & usQuickStatus) hanya mirror dari state yang sama.
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
    // Tombol cetak nota selalu tampil — bisa cetak ulang kapan pun
    // (lengkapi data / update status) tanpa harus menunggu status CASH.
}

function usGetStatus() {
    const b = document.getElementById('usQuickStatus');
    const a = document.getElementById('usStatus');
    return (b && b.value) || (a && a.value) || 'ANALISA';
}

function usRupiah(v) {
    return 'Rp ' + (Number(v) || 0).toLocaleString('id-ID');
}

function usFinUpdate() {
    const est = usNum('usEstimate');
    const dp = usNum('usDp');
    let final = usNum('usFinFinal');
    const mode = usVal('usFinJasaMode');
    const jasaEl = document.getElementById('usFinJasa');
    if (mode === '40' || mode === '50') {
        const auto = Math.round(final * Number(mode) / 100);
        if (jasaEl) jasaEl.value = auto;
    }
    const part = usNum('usFinPart');
    const jasa = usNum('usFinJasa');
    const lain = usNum('usFinLain');
    const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = usRupiah(v); };
    set('usSumEstimate', est);
    set('usSumDp', dp);
    set('usSumFinal', final);
    set('usSumPart', part);
    set('usSumJasa', jasa);
    set('usSumLain', lain);
    set('usSumSisa', final - dp);
    const wrap = document.getElementById('usFinLainKeWrap');
    if (wrap) wrap.classList.toggle('hidden', !(lain > 0));
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

function initUpdateServis() {
    renderChecklist('us', 'usCheckGroups', 'Catatan kondisi awal — tidak diubah otomatis saat data servis diperbarui.');
    const techFill = (selId) => {
        const sel = document.getElementById(selId);
        if (!sel || sel.options.length > 1) return;
        const src = document.getElementById('rcTechnician');
        if (src) sel.innerHTML = src.innerHTML;
    };
    const syncTech = async () => {
        try {
            const techs = await apiGet('/orders/technicians');
            ['usTechnician', 'usFinJasaKe'].forEach(id => {
                const sel = document.getElementById(id);
                if (!sel || sel.options.length > 1) return;
                const keep = id === 'usTechnician' ? '— Pilih Teknisi —' : '— Nama Teknisi —';
                sel.innerHTML = `<option value="">${keep}</option>` + techs.map(t => `<option value="${t}">${t}</option>`).join('');
            });
        } catch (_) { techFill('usTechnician'); techFill('usFinJasaKe'); }
    };
    syncTech();
    ['usEstimate', 'usDp', 'usFinFinal', 'usFinPart', 'usFinJasa', 'usFinLain'].forEach(id => {
        const el = document.getElementById(id);
        if (el && !el.dataset.usBound) {
            el.dataset.usBound = '1';
            el.addEventListener('input', usFinUpdate);
        }
    });
    const jm = document.getElementById('usFinJasaMode');
    if (jm && !jm.dataset.usBound) { jm.dataset.usBound = '1'; jm.addEventListener('change', usFinUpdate); }
    const sa = document.getElementById('usStatus');
    if (sa && !sa.dataset.usBound) { sa.dataset.usBound = '1'; sa.addEventListener('change', () => usSetStatus(sa.value)); }
    const sb = document.getElementById('usQuickStatus');
    if (sb && !sb.dataset.usBound) { sb.dataset.usBound = '1'; sb.addEventListener('change', () => usSetStatus(sb.value)); }
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
                const _usPayload = {
                    device: usVal('usDevice').trim(),
                    device_password: usVal('usPassword'),
                    imei: usVal('usImei').trim(),
                    damagetype: usVal('usDamage').trim(),
                    repair_plan: usVal('usPlan').trim(),
                    estimate: usNum('usEstimate'),
                    payment: usNum('usDp'),
                    technician: usVal('usTechnician'),
                    status: usGetStatus(),
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
// HALAMAN GARANSI (mock data — tahap UI, tanpa backend)
// ─────────────────────────────────────────────

const GR_PER_PAGE = 10;
let _grPage = 1;
let _grQuery = '';
let _grDate = '';
let _grStatus = '';
let _grView = [];
let _grClaimIdx = -1;

// Dummy tahap UI — backend diintegrasikan tahap berikutnya.
// `klaim: null` = belum klaim (status diturunkan dari tanggal).
// `klaim: {...}` = sedang/dalam klaim (status Klaim).
const GR_MOCK = [
    { no: 'SV-20260710-001', nama: 'Ahmad Fauzi', phone: '081234567890', device: 'Samsung Galaxy A55', mulai: '2026-07-10', akhir: '2026-10-10', damage: 'Layar retak', plan: 'Ganti LCD + frame', price: 550000, klaim: null },
    { no: 'SV-20260801-002', nama: 'Siti Nurhaliza', phone: '085725566668', device: 'iPhone 13', mulai: '2026-08-01', akhir: '2026-11-01', damage: 'Baterai drop', plan: 'Ganti baterai', price: 350000, klaim: null },
    { no: 'SV-20260615-003', nama: 'Rudi Hartono', phone: '082138475690', device: 'Xiaomi Redmi Note 13', mulai: '2026-06-15', akhir: '2026-09-15', damage: 'Konektor cas longgar', plan: 'Ganti konektor cas', price: 45000, klaim: { tgl: '2026-09-03', keluhan: 'Cas kadang tidak mengisi', tindakan: 'Diagnosa ulang', status: 'Diproses' } },
    { no: 'SV-20260820-004', nama: 'Maya Sari', phone: '083856712090', device: 'iPhone 15', mulai: '2026-08-20', akhir: '2026-11-20', damage: 'Layar pecah', plan: 'Ganti LCD', price: 1500000, klaim: null },
    { no: 'SV-20260503-005', nama: 'Budi Santoso', phone: '087731209845', device: 'Realme C55', mulai: '2026-05-03', akhir: '2026-08-03', damage: 'Fleksibel robek', plan: 'Ganti fleksibel LCD', price: 50000, klaim: null },
    { no: 'SV-20260725-006', nama: 'Dewi Lestari', phone: '081112345678', device: 'Oppo Reno 11', mulai: '2026-07-25', akhir: '2026-10-25', damage: 'Backdoor pecah', plan: 'Ganti backdoor', price: 125000, klaim: null },
    { no: 'SV-20260412-007', nama: 'Andi Pratama', phone: '081904556677', device: 'Vivo Y36', mulai: '2026-04-12', akhir: '2026-07-12', damage: 'Mati total', plan: 'Servis mesin', price: 250000, klaim: null },
    { no: 'SV-20260805-008', nama: 'Putri Ayu', phone: '082221078934', device: 'Samsung Galaxy S23', mulai: '2026-08-05', akhir: '2026-11-05', damage: 'Kamera buram', plan: 'Ganti kamera belakang', price: 420000, klaim: null },
    { no: 'SV-20260628-009', nama: 'Hendra Gunawan', phone: '085643219870', device: 'Infinix Note 40', mulai: '2026-06-28', akhir: '2026-09-28', damage: 'Buzzer mati', plan: 'Ganti buzzer', price: 60000, klaim: null },
    { no: 'SV-20260730-010', nama: 'Nina Kurnia', phone: '081327654019', device: 'iPhone 12', mulai: '2026-07-30', akhir: '2026-10-30', damage: 'LCD bergaris', plan: 'Ganti LCD INCELL', price: 680000, klaim: null },
    { no: 'SV-20260812-011', nama: 'Fajar Ramadhan', phone: '082134809572', device: 'Poco X6', mulai: '2026-08-12', akhir: '2026-11-12', damage: 'LCD pecah', plan: 'Ganti LCD ORI', price: 475000, klaim: null },
    { no: 'SV-20260320-012', nama: 'Rina Marlina', phone: '083812745690', device: 'Oppo A78', mulai: '2026-03-20', akhir: '2026-06-20', damage: 'Speaker sember', plan: 'Ganti speaker', price: 300000, klaim: null },
    { no: 'SV-20260818-013', nama: 'Doni Saputra', phone: '081556677889', device: 'Samsung Galaxy A35', mulai: '2026-08-18', akhir: '2026-11-18', damage: 'Baterai boros', plan: 'Ganti baterai', price: 195000, klaim: null },
    { no: 'SV-20260605-014', nama: 'Lina Hartati', phone: '082699887766', device: 'Vivo V30', mulai: '2026-06-05', akhir: '2026-09-05', damage: 'Baterai drop', plan: 'Ganti baterai', price: 195000, klaim: { tgl: '2026-09-04', keluhan: 'Baterai cepat habis setelah ganti', tindakan: 'Perbaikan ulang', status: 'Diajukan' } },
];

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
    return GR_MOCK.filter(g => {
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
    const n = { total: GR_MOCK.length, aktif: 0, segera: 0, expired: 0, klaim: 0 };
    GR_MOCK.forEach(g => {
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
        <div><span>Tindakan Perbaikan</span><b>${escapeHtml(g.plan || '-')}</b></div>
        <div><span>Nilai Servis</span><b>${plRupiah(g.price)}</b></div>`;
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
    _grClaimIdx = GR_MOCK.indexOf(g);
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
    _grClaimIdx = -1;
}

function initClaimForm() {
    const form = document.getElementById('claimForm');
    if (!form || form.dataset.bound) return;
    form.dataset.bound = '1';
    form.addEventListener('submit', function (e) {
        e.preventDefault();
        const g = GR_MOCK[_grClaimIdx];
        if (!g) return;
        const btn = document.getElementById('claimSubmitBtn');
        const txt = document.getElementById('claimSubmitText');
        const fb = document.getElementById('claimFeedback');
        btn.disabled = true;
        txt.textContent = 'Menyimpan...';
        g.klaim = {
            tgl: document.getElementById('clTgl').value,
            keluhan: document.getElementById('clKeluhan').value.trim(),
            tindakan: document.getElementById('clTindakan').value,
            status: document.getElementById('clStatus').value,
        };
        fb.classList.remove('hidden');
        fb.classList.add('success');
        fb.innerHTML = `<i class="fa-solid fa-circle-check"></i> Klaim tercatat (lokal). Status garansi: <b>Klaim</b>.`;
        btn.disabled = false;
        txt.textContent = 'Ajukan Klaim';
        renderGaransi();
    });
}

function renderGaransi() {
    initGrToolbar();
    initClaimForm();
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
        return;
    }

    const start = (_grPage - 1) * GR_PER_PAGE;
    const rows = data.slice(start, start + GR_PER_PAGE);
    rows.forEach((g, i) => {
        const idx = start + i;
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td class="tx-num">${idx + 1}</td>
            <td><span class="tx-device">${escapeHtml(g.nama)}</span></td>
            <td class="tx-cell-muted">${escapeHtml(g.device)}</td>
            <td class="tx-cell-muted">${txDate(g.mulai)}</td>
            <td class="tx-cell-muted">${txDate(g.akhir)}</td>
            <td>${grStatusBadge(g)}</td>
            <td class="tx-aksi">
                <button type="button" class="tx-view-btn" title="Detail" onclick="grDetail(${idx})"><i class="fa-solid fa-eye"></i></button>
                <button type="button" class="tx-view-btn tx-claim-btn" title="Klaim Garansi" onclick="grClaim(${idx})"><i class="fa-solid fa-file-circle-plus"></i></button>
            </td>
        `;
        body.appendChild(tr);
    });

    const end = start + rows.length;
    if (total > GR_PER_PAGE) pagination.classList.remove('hidden');
    else pagination.classList.add('hidden');
    if (info) info.textContent = 'Halaman ' + _grPage + '  ' + start + ' - ' + end + '  (dari ' + total + ' garansi)';

    if (pageBtns) {
        pageBtns.innerHTML = '';
        const mkBtn = (txt, p, disabled, active) => {
            const b = document.createElement('button');
            b.type = 'button';
            b.textContent = txt;
            b.className = 'tx-page-btn' + (active ? ' active' : '') + (disabled ? ' disabled' : '');
            if (!disabled) b.addEventListener('click', () => { _grPage = p; renderGaransi(); });
            return b;
        };
        pageBtns.appendChild(mkBtn('← Sebelumnya', _grPage - 1, _grPage === 1, false));
        for (let p = 1; p <= totalPages; p++) {
            pageBtns.appendChild(mkBtn(String(p), p, false, p === _grPage));
        }
        pageBtns.appendChild(mkBtn('Berikutnya →', _grPage + 1, _grPage === totalPages, false));
    }
}

// ─────────────────────────────────────────────
// HALAMAN PELANGGAN (master + ringkasan servis)
// ─────────────────────────────────────────────

// ─────────────────────────────────────────────
// HALAMAN PELANGGAN (master + ringkasan servis — tahap UI: dummy data)
// Backend diintegrasikan tahap berikutnya (GET /api/customers/summary + histori).
// ─────────────────────────────────────────────

const PL_PER_PAGE = 10;
let _plPage = 1;
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

function plFiltered() {
    const q = _plQuery.trim().toLowerCase();
    return PL_DUMMY.filter(c => {
        if (_plDate && (c.last || '') !== _plDate) return false;
        if (!q) return true;
        return [c.name, c.phone, c.device, c.plan]
            .some(f => (f || '').toLowerCase().includes(q));
    });
}

const PL_DUMMY = [
    { name: 'Andi Pratama', phone: '081234567890', device: 'Samsung Galaxy A55', plan: 'Ganti LCD + frame', price: 550000, total: 3, last: '2026-09-02', hist: [
        { no: 'SV-20260902-003', tgl: '2026-09-02', device: 'Samsung Galaxy A55', plan: 'Ganti LCD + frame', price: 550000, status: 'Repair' },
        { no: 'SV-20260718-009', tgl: '2026-07-18', device: 'Samsung Galaxy A55', plan: 'Ganti baterai', price: 350000, status: 'Done' },
        { no: 'SV-20260530-002', tgl: '2026-05-30', device: 'Samsung Galaxy A55', plan: 'Flash + servis ringan', price: 150000, status: 'Done' },
    ]},
    { name: 'Siti Rahma', phone: '085725566668', device: 'iPhone 13', plan: 'Ganti baterai', price: 350000, total: 5, last: '2026-09-01', hist: [
        { no: 'SV-20260901-014', tgl: '2026-09-01', device: 'iPhone 13', plan: 'Ganti baterai', price: 350000, status: 'Done' },
        { no: 'SV-20260812-006', tgl: '2026-08-12', device: 'iPhone 13', plan: 'Ganti kamera depan', price: 290000, status: 'Done' },
        { no: 'SV-20260702-001', tgl: '2026-07-02', device: 'iPhone 13', plan: 'Servis konektor cas', price: 120000, status: 'Done' },
    ]},
    { name: 'Budi Santoso', phone: '082138475690', device: 'Xiaomi Redmi Note 13', plan: 'Ganti konektor cas', price: 45000, total: 4, last: '2026-08-28', hist: [
        { no: 'SV-20260828-007', tgl: '2026-08-28', device: 'Xiaomi Redmi Note 13', plan: 'Ganti konektor cas', price: 45000, status: 'Done' },
        { no: 'SV-20260720-002', tgl: '2026-07-20', device: 'Xiaomi Redmi Note 13', plan: 'Ganti LCD', price: 475000, status: 'Done' },
    ]},
    { name: 'Dewi Lestari', phone: '081112345678', device: 'Oppo Reno 11', plan: 'Ganti LCD OLED', price: 790000, total: 2, last: '2026-08-25', hist: [
        { no: 'SV-20260825-005', tgl: '2026-08-25', device: 'Oppo Reno 11', plan: 'Ganti LCD OLED', price: 790000, status: 'Repair' },
        { no: 'SV-20260614-003', tgl: '2026-06-14', device: 'Oppo Reno 11', plan: 'Ganti backdoor', price: 125000, status: 'Done' },
    ]},
    { name: 'Agus Wijaya', phone: '083856712090', device: 'Vivo V30', plan: 'Ganti backdoor', price: 125000, total: 1, last: '2026-08-22', hist: [
        { no: 'SV-20260822-001', tgl: '2026-08-22', device: 'Vivo V30', plan: 'Ganti backdoor', price: 125000, status: 'Done' },
    ]},
    { name: 'Rina Marlina', phone: '087731209845', device: 'Realme C55', plan: 'Ganti fleksibel LCD', price: 50000, total: 6, last: '2026-08-20', hist: [
        { no: 'SV-20260820-002', tgl: '2026-08-20', device: 'Realme C55', plan: 'Ganti fleksibel LCD', price: 50000, status: 'Done' },
        { no: 'SV-20260805-008', tgl: '2026-08-05', device: 'Realme C55', plan: 'Ganti konektor cas', price: 45000, status: 'Done' },
        { no: 'SV-20260711-004', tgl: '2026-07-11', device: 'Realme C55', plan: 'Flash ulang', price: 100000, status: 'Done' },
    ]},
    { name: 'Hendra Gunawan', phone: '081904556677', device: 'Infinix Note 40', plan: 'Ganti buzzer', price: 60000, total: 2, last: '2026-08-18', hist: [
        { no: 'SV-20260818-009', tgl: '2026-08-18', device: 'Infinix Note 40', plan: 'Ganti buzzer', price: 60000, status: 'Done' },
    ]},
    { name: 'Putri Ayu', phone: '082221078934', device: 'Samsung Galaxy S23', plan: 'Ganti kamera belakang', price: 420000, total: 3, last: '2026-08-15', hist: [
        { no: 'SV-20260815-006', tgl: '2026-08-15', device: 'Samsung Galaxy S23', plan: 'Ganti kamera belakang', price: 420000, status: 'Done' },
        { no: 'SV-20260709-002', tgl: '2026-07-09', device: 'Samsung Galaxy S23', plan: 'Ganti baterai', price: 195000, status: 'Done' },
    ]},
    { name: 'Fajar Ramadhan', phone: '085643219870', device: 'Poco X6', plan: 'Ganti LCD ORI', price: 475000, total: 1, last: '2026-08-10', hist: [
        { no: 'SV-20260810-003', tgl: '2026-08-10', device: 'Poco X6', plan: 'Ganti LCD ORI', price: 475000, status: 'Repair' },
    ]},
    { name: 'Nina Kurnia', phone: '081327654019', device: 'iPhone 12', plan: 'Ganti LCD INCELL', price: 680000, total: 4, last: '2026-08-08', hist: [
        { no: 'SV-20260808-012', tgl: '2026-08-08', device: 'iPhone 12', plan: 'Ganti LCD INCELL', price: 680000, status: 'Done' },
        { no: 'SV-20260628-005', tgl: '2026-06-28', device: 'iPhone 12', plan: 'Ganti baterai', price: 350000, status: 'Done' },
    ]},
    { name: 'Doni Saputra', phone: '082134809572', device: 'Samsung Galaxy A35', plan: 'Ganti baterai', price: 195000, total: 2, last: '2026-08-05', hist: [
        { no: 'SV-20260805-001', tgl: '2026-08-05', device: 'Samsung Galaxy A35', plan: 'Ganti baterai', price: 195000, status: 'Done' },
    ]},
    { name: 'Lina Hartati', phone: '083812745690', device: 'Vivo Y36', plan: 'Servis mati total', price: 250000, total: 1, last: '2026-08-01', hist: [
        { no: 'SV-20260801-004', tgl: '2026-08-01', device: 'Vivo Y36', plan: 'Servis mati total', price: 250000, status: 'Analisa' },
    ]},
];

function plRupiah(v) {
    if (v === null || v === undefined) return '-';
    return new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', minimumFractionDigits: 0 }).format(Number(v) || 0);
}

async function renderPelanggan() {
    initPlToolbar();
    await loadPlPage(1);
}

function plHist(idx) {
    const c = (_plView.length ? _plView : PL_DUMMY)[idx];
    if (!c) return;
    document.getElementById('histTitle').textContent = 'Histori — ' + c.name;
    document.getElementById('histSub').textContent = c.phone + ' • ' + c.total + '× servis';
    document.getElementById('histSummary').innerHTML = renderCustSummary(c);
    document.getElementById('plHistBody').innerHTML = c.hist.map((h, i) => `
        <tr>
            <td class="tx-num">${i + 1}</td>
            <td class="tx-cell-muted">${escapeHtml(h.no)}</td>
            <td class="tx-cell-muted">${txDate(h.tgl)}</td>
            <td><span class="tx-device">${escapeHtml(h.device)}</span></td>
            <td class="tx-cell-muted">${escapeHtml(h.plan)}</td>
            <td class="tx-laba">${plRupiah(h.price)}</td>
            <td>${txStatusBadge(h.status)}</td>
        </tr>
    `).join('');
    document.getElementById('pageHistory').classList.add('open');
}

function closePlHist() {
    document.getElementById('pageHistory').classList.remove('open');
}

async function loadPlPage(page) {
    const body = document.getElementById('plBody');
    const empty = document.getElementById('plEmpty');
    const loading = document.getElementById('plLoading');
    const pagination = document.getElementById('plPagination');
    if (!body) return;

    const data = plFiltered();
    _plView = data;
    const total = data.length;
    const totalPages = Math.max(1, Math.ceil(total / PL_PER_PAGE));
    _plPage = Math.min(Math.max(1, page), totalPages);
    body.innerHTML = '';
    loading.classList.add('hidden');
    empty.classList.add('hidden');

    if (total === 0) {
        empty.innerHTML = _plQuery.trim()
            ? '<i class="fa-solid fa-magnifying-glass text-3xl mb-2 block opacity-40"></i>Pelanggan tidak ditemukan.'
            : '<i class="fa-solid fa-users text-3xl mb-2 block opacity-40"></i>Belum ada pelanggan.';
        empty.classList.remove('hidden');
        pagination.classList.add('hidden');
        return;
    }

    const start = (_plPage - 1) * PL_PER_PAGE;
    data.slice(start, start + PL_PER_PAGE).forEach((c, i) => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td class="tx-num">${start + i + 1}</td>
            <td><span class="tx-device">${escapeHtml(c.name)}</span></td>
            <td class="tx-cell-muted">${escapeHtml(c.phone)}</td>
            <td class="tx-cell-muted">${escapeHtml(c.device)}</td>
            <td class="tx-cell-muted">${escapeHtml(c.plan)}</td>
            <td class="tx-laba">${plRupiah(c.price)}</td>
            <td class="tx-cell-muted text-center">${c.total}×</td>
            <td class="tx-cell-muted">${txDate(c.last)}</td>
            <td class="tx-aksi"><button type="button" class="tx-view-btn" title="Lihat Histori" onclick="plHist(${start + i})"><i class="fa-solid fa-clock-rotate-left"></i></button></td>
        `;
        body.appendChild(tr);
    });

    const end = start + Math.min(PL_PER_PAGE, total - start);
    if (total > PL_PER_PAGE) pagination.classList.remove('hidden');
    else pagination.classList.add('hidden');
    const info = document.getElementById('plInfo');
    if (info) info.textContent = 'Halaman ' + _plPage + '  ' + start + ' - ' + end + '  (dari ' + total + ' pelanggan)';

    const pageBtns = document.getElementById('plPageBtns');
    if (pageBtns) {
        pageBtns.innerHTML = '';
        const mkBtn = (txt, p, disabled, active) => {
            const b = document.createElement('button');
            b.type = 'button';
            b.textContent = txt;
            b.className = 'tx-page-btn' + (active ? ' active' : '') + (disabled ? ' disabled' : '');
            if (!disabled) b.addEventListener('click', () => loadPlPage(p));
            return b;
        };
        pageBtns.appendChild(mkBtn('← Sebelumnya', _plPage - 1, _plPage === 1, false));
        for (let p = 1; p <= totalPages; p++) {
            pageBtns.appendChild(mkBtn(String(p), p, false, p === _plPage));
        }
        pageBtns.appendChild(mkBtn('Berikutnya →', _plPage + 1, _plPage === totalPages, false));
    }
}

// ─────────────────────────────────────────────
// HALAMAN SPAREPART (mock data — tahap UI, tanpa backend)
// ─────────────────────────────────────────────

const SP_PER_PAGE = 10;
let _spPage = 1;
let _spQuery = '';

const SP_MOCK = [
    { tgl: '2026-08-10', kategori: 'LCD', merek: 'Samsung', jenis: 'LCD Samsung A55 ORI', device: 'Galaxy A55', qty: 12, beli: 385000, jual: 550000 },
    { tgl: '2026-08-08', kategori: 'Baterai', merek: 'Apple', jenis: 'Baterai iPhone 13', device: 'iPhone 13', qty: 8, beli: 210000, jual: 350000 },
    { tgl: '2026-08-05', kategori: 'Konektor', merek: 'Xiaomi', jenis: 'Konektor Cas Redmi Note 13', device: 'Redmi Note 13', qty: 3, beli: 15000, jual: 45000 },
    { tgl: '2026-08-01', kategori: 'Kamera', merek: 'Samsung', jenis: 'Kamera Belakang S23', device: 'Galaxy S23', qty: 5, beli: 275000, jual: 420000 },
    { tgl: '2026-07-28', kategori: 'LCD', merek: 'Apple', jenis: 'LCD iPhone 12 INCELL', device: 'iPhone 12', qty: 6, beli: 450000, jual: 680000 },
    { tgl: '2026-07-25', kategori: 'Baterai', merek: 'Oppo', jenis: 'Baterai Oppo A78', device: 'Oppo A78', qty: 0, beli: 95000, jual: 175000 },
    { tgl: '2026-07-20', kategori: 'IC', merek: 'Universal', jenis: 'IC Power PMI632', device: 'All Xiaomi', qty: 20, beli: 25000, jual: 75000 },
    { tgl: '2026-07-18', kategori: 'Casing', merek: 'Vivo', jenis: 'Backdoor Vivo V30', device: 'Vivo V30', qty: 4, beli: 65000, jual: 125000 },
    { tgl: '2026-07-15', kategori: 'LCD', merek: 'Xiaomi', jenis: 'LCD Poco X6 ORI', device: 'Poco X6', qty: 9, beli: 310000, jual: 475000 },
    { tgl: '2026-07-10', kategori: 'Fleksibel', merek: 'Realme', jenis: 'Fleksibel LCD Realme C55', device: 'Realme C55', qty: 15, beli: 18000, jual: 50000 },
    { tgl: '2026-07-05', kategori: 'Baterai', merek: 'Samsung', jenis: 'Baterai Galaxy A35', device: 'Galaxy A35', qty: 2, beli: 110000, jual: 195000 },
    { tgl: '2026-07-01', kategori: 'Kamera', merek: 'Apple', jenis: 'Kamera Depan iPhone 13', device: 'iPhone 13', qty: 7, beli: 185000, jual: 290000 },
    { tgl: '2026-06-25', kategori: 'Speaker', merek: 'Infinix', jenis: 'Buzzer Note 40', device: 'Note 40', qty: 11, beli: 22000, jual: 60000 },
    { tgl: '2026-06-20', kategori: 'LCD', merek: 'Oppo', jenis: 'LCD Reno 11 OLED', device: 'Reno 11', qty: 1, beli: 520000, jual: 790000 },
];

function spRupiah(v) {
    return new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', minimumFractionDigits: 0 }).format(Number(v) || 0);
}

function spQtyCell(qty) {
    if (qty <= 0) return '<span class="qty-out">0</span> <span class="qty-flag out">Habis</span>';
    if (qty <= 5) return `<span class="qty-low">${qty}</span> <span class="qty-flag low">Menipis</span>`;
    return `<span class="qty-ok">${qty}</span>`;
}

function spEdit(i) {
    const s = SP_MOCK[i];
    if (!s) return;
    _spEditIdx = i;
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

function spDel(i) {
    const s = SP_MOCK[i];
    if (!s) return;
    if (!confirm('Hapus sparepart "' + s.jenis + '"? (lokal, hilang permanen setelah refresh tidak berpengaruh)')) return;
    SP_MOCK.splice(i, 1);
    renderSparepart();
}

let _spEditIdx = -1;

function spAdd() {
    _spEditIdx = -1;
    document.getElementById('spfTitle').textContent = 'Tambah Sparepart';
    document.getElementById('spareForm').reset();
    const fb = document.getElementById('spfFeedback');
    fb.classList.add('hidden');
    fb.classList.remove('success');
    document.getElementById('pageSpare').classList.add('open');
}

function closeSpare() {
    document.getElementById('pageSpare').classList.remove('open');
    _spEditIdx = -1;
}

function renderSpKpi() {
    const el = document.getElementById('spKpi');
    if (!el) return;
    const total = SP_MOCK.length;
    const habis = SP_MOCK.filter(s => (s.qty || 0) <= 0).length;
    const tipis = SP_MOCK.filter(s => (s.qty || 0) > 0 && (s.qty || 0) <= 5).length;
    const nilai = SP_MOCK.reduce((a, s) => a + (Number(s.qty) || 0) * (Number(s.jual) || 0), 0);
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
    if (!q) return SP_MOCK.slice();
    return SP_MOCK.filter(s => [s.jenis, s.merek, s.device, s.kategori]
        .some(f => (f || '').toLowerCase().includes(q)));
}

function renderSparepart() {
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
        return;
    }

    const start = (_spPage - 1) * SP_PER_PAGE;
    const rows = data.slice(start, start + SP_PER_PAGE);
    rows.forEach((s, i) => {
        const idx = SP_MOCK.indexOf(s);
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td class="tx-num">${start + i + 1}</td>
            <td class="tx-cell-muted">${txDate(s.tgl)}</td>
            <td class="tx-cell-muted">${escapeHtml(s.kategori)}</td>
            <td class="tx-cell-muted">${escapeHtml(s.merek)}</td>
            <td><span class="tx-device">${escapeHtml(s.jenis)}</span></td>
            <td class="tx-cell-muted">${escapeHtml(s.device)}</td>
            <td class="text-center">${spQtyCell(s.qty)}</td>
            <td class="tx-laba-muted">${spRupiah(s.beli)}</td>
            <td class="tx-laba">${spRupiah(s.jual)}</td>
            <td class="tx-aksi">
                <button type="button" class="tx-view-btn tx-edit-btn" title="Edit" onclick="spEdit(${idx})"><i class="fa-solid fa-pen"></i></button>
                <button type="button" class="tx-view-btn tx-del-btn" title="Hapus" onclick="spDel(${idx})"><i class="fa-solid fa-trash"></i></button>
            </td>
        `;
        body.appendChild(tr);
    });

    const end = start + rows.length;
    if (total > SP_PER_PAGE) pagination.classList.remove('hidden');
    else pagination.classList.add('hidden');
    if (info) info.textContent = 'Halaman ' + _spPage + '  ' + start + ' - ' + end + '  (dari ' + total + ' sparepart)';

    if (pageBtns) {
        pageBtns.innerHTML = '';
        const mkBtn = (txt, p, disabled, active) => {
            const b = document.createElement('button');
            b.type = 'button';
            b.textContent = txt;
            b.className = 'tx-page-btn' + (active ? ' active' : '') + (disabled ? ' disabled' : '');
            if (!disabled) b.addEventListener('click', () => { _spPage = p; renderSparepart(); });
            return b;
        };
        pageBtns.appendChild(mkBtn('← Sebelumnya', _spPage - 1, _spPage === 1, false));
        for (let p = 1; p <= totalPages; p++) {
            pageBtns.appendChild(mkBtn(String(p), p, false, p === _spPage));
        }
        pageBtns.appendChild(mkBtn('Berikutnya →', _spPage + 1, _spPage === totalPages, false));
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
        form.addEventListener('submit', function (e) {
            e.preventDefault();
            const jenis = document.getElementById('spfJenis').value.trim();
            if (!jenis) return;
            const item = {
                tgl: new Date().toISOString().slice(0, 10),
                kategori: document.getElementById('spfKategori').value.trim() || '-',
                merek: document.getElementById('spfMerek').value.trim() || '-',
                jenis: jenis,
                device: document.getElementById('spfDevice').value.trim() || '-',
                qty: Math.max(0, parseInt(document.getElementById('spfQty').value, 10) || 0),
                beli: Math.max(0, Number(document.getElementById('spfBeli').value) || 0),
                jual: Math.max(0, Number(document.getElementById('spfJual').value) || 0),
            };
            if (_spEditIdx >= 0 && SP_MOCK[_spEditIdx]) {
                item.tgl = SP_MOCK[_spEditIdx].tgl;
                SP_MOCK[_spEditIdx] = item;
            } else {
                SP_MOCK.unshift(item);
                _spPage = 1;
            }
            renderSparepart();
            const fb = document.getElementById('spfFeedback');
            fb.classList.remove('hidden');
            fb.classList.add('success');
            fb.innerHTML = `<i class="fa-solid fa-circle-check"></i> Tersimpan (lokal, hilang setelah refresh).`;
        });
    }
}

// ─────────────────────────────────────────────
// HALAMAN KEUANGAN (mock data — tahap UI, tanpa backend)
// ─────────────────────────────────────────────

const KU_PER_PAGE = 10;
let _kuPage = 1;
let _profitChart = null;

const KU_KAS = [
    { uraian: 'Kas Aset Awal', debit: 5000000, kredit: null, saldo: 5000000 },
    { uraian: 'Total Penjualan Service', debit: 3250000, kredit: null, saldo: 8250000 },
    { uraian: 'Total Modal (Part + Jasa)', debit: null, kredit: 1100000, saldo: 7150000 },
    { uraian: 'Total Beban (Gaji + Ops)', debit: null, kredit: 900000, saldo: 6250000 },
];

const KU_ALLOC = [
    { nama: 'Bonus Karyawan', pct: 10, color: '#f59e0b' },
    { nama: 'Pengelola', pct: 30, color: '#dc2626' },
    { nama: 'Investor', pct: 30, color: '#2563eb' },
    { nama: 'Kas Aset', pct: 30, color: '#16a34a' },
];

const KU_RIWAYAT = [
    { tgl: '2026-09-03', jenis: 'Masuk', kategori: 'Penjualan Service', ket: 'Servis ganti LCD A55', nominal: 550000 },
    { tgl: '2026-09-02', jenis: 'Keluar', kategori: 'Modal Part', ket: 'Beli LCD A55', nominal: 385000 },
    { tgl: '2026-09-02', jenis: 'Masuk', kategori: 'Penjualan Service', ket: 'Ganti baterai iPhone 13', nominal: 350000 },
    { tgl: '2026-09-01', jenis: 'Keluar', kategori: 'Beban Operasional', ket: 'Listrik & wifi', nominal: 450000 },
    { tgl: '2026-08-30', jenis: 'Masuk', kategori: 'Penjualan Service', ket: 'Service ringan + flash', nominal: 150000 },
    { tgl: '2026-08-29', jenis: 'Keluar', kategori: 'Beban Gaji', ket: 'Gaji teknisi paruh waktu', nominal: 1500000 },
    { tgl: '2026-08-28', jenis: 'Masuk', kategori: 'Penjualan Service', ket: 'Ganti konektor cas', nominal: 120000 },
    { tgl: '2026-08-27', jenis: 'Keluar', kategori: 'Modal Jasa', ket: 'Jasa pasang ke mitra', nominal: 200000 },
    { tgl: '2026-08-26', jenis: 'Masuk', kategori: 'Lainnya', ket: 'Jual HP second', nominal: 900000 },
    { tgl: '2026-08-25', jenis: 'Keluar', kategori: 'Modal Part', ket: 'Stok baterai & fleksibel', nominal: 640000 },
    { tgl: '2026-08-24', jenis: 'Masuk', kategori: 'Penjualan Service', ket: 'Ganti kamera S23', nominal: 420000 },
    { tgl: '2026-08-23', jenis: 'Keluar', kategori: 'Beban Operasional', ket: 'Sewa tempat', nominal: 2000000 },
];

function kuRupiah(v) {
    return new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', minimumFractionDigits: 0 }).format(Number(v) || 0);
}

function renderKeuangan() {
    kuShowMain(true);
    renderBukuKas();
    renderAlloc();
    renderRiwayat();
    initProfitChart();
    initKuKasForm();
}

// ── Keuangan: pusat kontrol (main) vs arsip (riwayat) ──
// Riwayat tetap dirender (data/fitur utuh), hanya disembunyikan dari tampilan utama.
function kuShowMain(silent) {
    const main = document.getElementById('kuMainView');
    const riw = document.getElementById('kuRiwayatView');
    if (main) main.classList.remove('hidden');
    if (riw) riw.classList.add('hidden');
    if (!silent && riw) {
        const page = document.getElementById('pageKeuangan');
        if (page) page.scrollIntoView({ block: 'start' });
    }
}

function kuShowRiwayat() {
    const main = document.getElementById('kuMainView');
    const riw = document.getElementById('kuRiwayatView');
    if (main) main.classList.add('hidden');
    if (riw) {
        riw.classList.remove('hidden');
        riw.scrollIntoView({ block: 'start' });
    }
    renderRiwayat();
}

// Aksi utama Buku Kas — konfirmasi UI saja, tanpa mengubah data/logika bisnis.
function kuTutupKas() {
    if (!confirm('Proses Tutup Kas & Pindah Arsip (jam 16.00)? Pastikan seluruh transaksi kas sudah tercatat.')) return;
    alert('Tutup kas diproses & arsip dipindahkan. (konfirmasi lokal — data & perhitungan tidak diubah)');
}

function renderBukuKas() {
    const body = document.getElementById('kuKasBody');
    if (body) {
        body.innerHTML = KU_KAS.map(k => `
            <tr>
                <td><span class="tx-device">${escapeHtml(k.uraian)}</span></td>
                <td class="tx-debit numeric-c">${k.debit ? kuRupiah(k.debit) : '<span class="text-green-500">-</span>'}</td>
                <td class="tx-kredit numeric-c">${k.kredit ? kuRupiah(k.kredit) : '<span class="text-red-500">-</span>'}</td>
                <td class="tx-saldo numeric-r">${kuRupiah(k.saldo)}</td>
            </tr>
        `).join('');
    }
    const sum = document.getElementById('kuKasSummary');
    if (sum) {
        const masuk = KU_KAS.reduce((a, k) => a + (Number(k.debit) || 0), 0);
        const keluar = KU_KAS.reduce((a, k) => a + (Number(k.kredit) || 0), 0);
        const saldo = KU_KAS.length ? KU_KAS[KU_KAS.length - 1].saldo : 0;
        const cards = [
            { label: 'Total Masuk', value: kuRupiah(masuk), icon: 'fa-arrow-trend-up', cls: 'sm-green' },
            { label: 'Total Keluar', value: kuRupiah(keluar), icon: 'fa-arrow-trend-down', cls: 'sm-red' },
            { label: 'Saldo Kas', value: kuRupiah(saldo), icon: 'fa-wallet', cls: 'sm-blue' },
        ];
        sum.innerHTML = cards.map(c => `
            <div class="sm-card ${c.cls}">
                <div class="sm-top"><i class="fa-solid ${c.icon}"></i>${c.label}</div>
                <div class="sm-bot"><span class="sm-num ku-num">${c.value}</span></div>
            </div>
        `).join('');
    }
}

let _kuSelAlloc = -1;

function renderAlloc() {
    const list = document.getElementById('kuAllocList');
    const totalEl = document.getElementById('kuTotalProfit');
    const total = 6250000;
    if (totalEl) totalEl.textContent = kuRupiah(total);
    if (!list) return;
    list.innerHTML = KU_ALLOC.map((a, i) => {
        const nom = Math.round(total * a.pct / 100);
        return `
        <div class="al-row${i === _kuSelAlloc ? ' is-sel' : ''}" data-alloc="${i}">
            <span class="al-dot" style="background:${a.color}"></span>
            <span class="al-name">${escapeHtml(a.nama)}</span>
            <span class="al-pct">${a.pct}%</span>
            <span class="al-nom">${kuRupiah(nom)}</span>
        </div>`;
    }).join('');
}

function initProfitChart() {
    const el = document.querySelector('#kuDonut');
    if (!el || typeof ApexCharts === 'undefined') return;
    if (_profitChart) { _profitChart.updateOptions({ theme: { mode: isDark() ? 'dark' : 'light' } }); return; }
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
        series: KU_ALLOC.map(a => a.pct),
        labels: KU_ALLOC.map(a => a.nama),
        colors: KU_ALLOC.map(a => a.color),
        theme: { mode: isDark() ? 'dark' : 'light' },
        legend: { show: false },
        dataLabels: { enabled: true, formatter: v => Math.round(v) + '%' },
        plotOptions: { pie: { donut: { size: '62%', labels: { show: false } } } },
        stroke: { width: 2 },
        tooltip: { y: { formatter: v => v + '%' } },
    });
    _profitChart.render();
}

function initKuKasForm() {
    const form = document.getElementById('kuKasForm');
    if (!form || form.dataset.bound) return;
    form.dataset.bound = '1';
    form.addEventListener('submit', (e) => {
        e.preventDefault();
        const jenis = document.getElementById('kuKasJenis').value;
        const kategori = document.getElementById('kuKasKategori').value;
        const nominal = Number(document.getElementById('kuKasNominal').value) || 0;
        if (nominal <= 0) return;
        const last = KU_KAS.length ? KU_KAS[KU_KAS.length - 1].saldo : 0;
        const masuk = jenis === 'Masuk';
        KU_KAS.push({
            uraian: kategori,
            debit: masuk ? nominal : null,
            kredit: masuk ? null : nominal,
            saldo: last + (masuk ? nominal : -nominal),
        });
        renderBukuKas();
        document.getElementById('kuKasNominal').value = '';
    });
}

let _kuQuery = '';
let _kuJenis = '';
let _kuDate = '';
let _kuView = [];
let _kuEditIdx = -1;

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

function kuFiltered() {
    const q = _kuQuery.trim().toLowerCase();
    return KU_RIWAYAT.filter(r => {
        if (_kuJenis && r.jenis !== _kuJenis) return false;
        if (_kuDate && (r.tgl || '') !== _kuDate) return false;
        if (!q) return true;
        return [r.ket, r.kategori, r.jenis].some(f => (f || '').toLowerCase().includes(q));
    });
}

function kuEdit(i) {
    const r = _kuView[i];
    if (!r) return;
    _kuEditIdx = KU_RIWAYAT.indexOf(r);
    document.getElementById('keJenis').value = r.jenis || 'Masuk';
    document.getElementById('keKategori').value = r.kategori || 'Lainnya';
    document.getElementById('keKet').value = r.ket || '';
    document.getElementById('keTgl').value = r.tgl || '';
    document.getElementById('keNominal').value = r.nominal || '';
    const fb = document.getElementById('keuFeedback');
    fb.classList.add('hidden');
    fb.classList.remove('success');
    document.getElementById('pageKeu').classList.add('open');
}

function closeKeu() {
    document.getElementById('pageKeu').classList.remove('open');
    _kuEditIdx = -1;
}

function kuDel(i) {
    const r = _kuView[i];
    if (!r) return;
    if (!confirm('Hapus "' + (r.ket || 'transaksi') + '"? (lokal, tidak memengaruhi database)')) return;
    KU_RIWAYAT.splice(KU_RIWAYAT.indexOf(r), 1);
    renderRiwayat();
}

function initKeuForm() {
    const form = document.getElementById('keuForm');
    if (!form || form.dataset.bound) return;
    form.dataset.bound = '1';
    form.addEventListener('submit', function (e) {
        e.preventDefault();
        const ket = document.getElementById('keKet').value.trim();
        if (!ket) return;
        const item = {
            tgl: document.getElementById('keTgl').value || new Date().toISOString().slice(0, 10),
            jenis: document.getElementById('keJenis').value,
            kategori: document.getElementById('keKategori').value,
            ket: ket,
            nominal: Math.max(1, Number(document.getElementById('keNominal').value) || 0),
        };
        if (_kuEditIdx >= 0 && KU_RIWAYAT[_kuEditIdx]) {
            KU_RIWAYAT[_kuEditIdx] = item;
        } else {
            KU_RIWAYAT.unshift(item);
            _kuPage = 1;
        }
        renderRiwayat();
        const fb = document.getElementById('keuFeedback');
        fb.classList.remove('hidden');
        fb.classList.add('success');
        fb.innerHTML = `<i class="fa-solid fa-circle-check"></i> Tersimpan (lokal, hilang setelah refresh).`;
    });
}

function renderRiwayat() {
    initKuToolbar();
    initKeuForm();
    const body = document.getElementById('kuBody');
    const empty = document.getElementById('kuEmpty');
    const pagination = document.getElementById('kuPagination');
    const info = document.getElementById('kuInfo');
    const pageBtns = document.getElementById('kuPageBtns');
    if (!body) return;

    body.innerHTML = '';
    empty.classList.add('hidden');

    const data = kuFiltered();
    _kuView = data;
    const total = data.length;
    const totalPages = Math.max(1, Math.ceil(total / KU_PER_PAGE));
    if (_kuPage > totalPages) _kuPage = totalPages;
    if (_kuPage < 1) _kuPage = 1;

    if (total === 0) {
        empty.innerHTML = (_kuQuery.trim() || _kuJenis || _kuDate)
            ? '<i class="fa-solid fa-magnifying-glass text-3xl mb-2 block opacity-40"></i>Tidak ada transaksi yang cocok dengan filter.'
            : '<i class="fa-solid fa-receipt text-3xl mb-2 block opacity-40"></i>Belum ada riwayat transaksi.';
        empty.classList.remove('hidden');
        pagination.classList.add('hidden');
        return;
    }

    const start = (_kuPage - 1) * KU_PER_PAGE;
    const rows = data.slice(start, start + KU_PER_PAGE);
    rows.forEach((r, i) => {
        const idx = start + i;
        const masuk = r.jenis === 'Masuk';
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td class="tx-num">${start + i + 1}</td>
            <td class="tx-cell-muted">${txDate(r.tgl)}</td>
            <td><span class="tx-status ${masuk ? 'ku-masuk' : 'ku-keluar'}"><i class="fa-solid fa-circle"></i>${r.jenis}</span></td>
            <td class="tx-cell-muted">${escapeHtml(r.kategori)}</td>
            <td class="tx-cell-muted">${escapeHtml(r.ket)}</td>
            <td class="${masuk ? 'tx-debit' : 'tx-kredit'}">${kuRupiah(r.nominal)}</td>
            <td class="tx-aksi">
                <button type="button" class="tx-view-btn tx-edit-btn" title="Edit" onclick="kuEdit(${idx})"><i class="fa-solid fa-pen"></i></button>
                <button type="button" class="tx-view-btn tx-del-btn" title="Hapus" onclick="kuDel(${idx})"><i class="fa-solid fa-trash"></i></button>
            </td>
        `;
        body.appendChild(tr);
    });

    const end = start + rows.length;
    if (total > KU_PER_PAGE) pagination.classList.remove('hidden');
    else pagination.classList.add('hidden');
    if (info) info.textContent = 'Halaman ' + _kuPage + '  ' + start + ' - ' + end + '  (dari ' + total + ' transaksi)';

    if (pageBtns) {
        pageBtns.innerHTML = '';
        const mkBtn = (txt, p, disabled, active) => {
            const b = document.createElement('button');
            b.type = 'button';
            b.textContent = txt;
            b.className = 'tx-page-btn' + (active ? ' active' : '') + (disabled ? ' disabled' : '');
            if (!disabled) b.addEventListener('click', () => { _kuPage = p; renderRiwayat(); });
            return b;
        };
        pageBtns.appendChild(mkBtn('← Sebelumnya', _kuPage - 1, _kuPage === 1, false));
        for (let p = 1; p <= totalPages; p++) {
            pageBtns.appendChild(mkBtn(String(p), p, false, p === _kuPage));
        }
        pageBtns.appendChild(mkBtn('Berikutnya →', _kuPage + 1, _kuPage === totalPages, false));
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

// Dummy histori tahap UI (ditampilkan bila API tidak mengembalikan data).
const HISTORY_DUMMY = [
    {
        name: 'Budi Santoso', phone: '085725566668', total: 4,
        device: 'Xiaomi Redmi Note 13', plan: 'Ganti konektor cas', price: 45000,
        recent: [
            { no: 'SV-20260820-011', device: 'Xiaomi Redmi Note 13', status: 'Done', date: '2026-08-20', price: 45000 },
            { no: 'SV-20260715-004', device: 'Xiaomi Redmi Note 13', status: 'Done', date: '2026-07-15', price: 120000 },
        ],
    },
    {
        name: 'Dewi Lestari', phone: '081112345678', total: 2,
        device: 'Oppo Reno 11', plan: 'Ganti LCD', price: 680000,
        recent: [
            { no: 'SV-20260802-007', device: 'Oppo Reno 11', status: 'Repair', date: '2026-08-02', price: 680000 },
        ],
    },
];

const normPhone = p => (p || '').replace(/\D/g, '').replace(/^62/, '0');

function findDummyHistory(phone) {
    const n = normPhone(phone);
    if (!n) return null;
    return HISTORY_DUMMY.find(d => normPhone(d.phone) === n) || null;
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
            ? 'Ketik No. WhatsApp untuk auto-sync histori.'
            : 'Ketik Nama / No. WhatsApp untuk cek histori pelanggan.';
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
            const dummy = findDummyHistory(phone);
            if (dummy) {
                setBadge('Ditemukan', 'found');
                list.innerHTML = renderCustSummary(dummy)
                    + historyItemsHtml(dummy.recent.map(r => ({ no_servis: r.no, device: r.device, model: '', status: r.status, created_at: r.date, estimate: r.price })));
                return;
            }
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
// Kondisi awal per No. Servis, tahap UI (lokal, tanpa DB/API).
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

const _checkStore = {};

function renderChecklist(prefix, containerId, note) {
    const box = document.getElementById(containerId);
    if (!box) return;
    const group = (title, icon, list) => `
        <div class="rc-check-group">
            <p class="rc-check-group-head"><span class="rc-check-group-ico"><i class="fa-solid ${icon}"></i></span>${title}</p>
            <div class="rc-check-grid">
                ${list.map(it => `<label class="rc-check"><input type="checkbox" id="${prefix}-ck-${it.key}"><span>${it.label}</span></label>`).join('')}
            </div>
        </div>`;
    box.innerHTML =
        group('KONDISI FISIK SAAT DITERIMA', 'fa-mobile-screen-button', CHECK_FISIK)
        + group('KELENGKAPAN SAAT DITERIMA', 'fa-box-open', CHECK_LEN)
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

async function initReceivePage() {
    renderChecklist('rc', 'rcCheckGroups');
    applyChecklist('rc', { fisik: [], len: ['unit_saja'] });
    restoreReceiveDraft();
    try {
        const techs = await apiGet('/orders/technicians');
        const sel = document.getElementById('rcTechnician');
        if (sel && techs && techs.length) {
            const cur = (document.getElementById('rcTechnician') || {}).value || '';
            sel.innerHTML = '<option value="">— Pilih Teknisi —</option>' + techs.map(t => `<option value="${t}">${t}</option>`).join('');
            // Kembalikan pilihan teknisi dari draft setelah option async tersedia.
            try {
                const d = JSON.parse(localStorage.getItem(RECEIVE_DRAFT_KEY) || 'null');
                const want = (d && d.rcTechnician) || cur;
                if (want && Array.from(sel.options).some(o => o.value === want)) sel.value = want;
            } catch (_) { if (cur) sel.value = cur; }
        }
    } catch (_) {}

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
    form.addEventListener('input', () => { updateReceiveSteps(); scheduleReceiveDraft(); });
    form.addEventListener('change', () => { updateReceiveSteps(); scheduleReceiveDraft(); });
    initReceiveShortcuts();
    restoreReceiveDraft();
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
                technician: document.getElementById('rcTechnician').value,
                status: document.getElementById('rcStatus').value,
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
                technician: (document.getElementById('rcTechnician').selectedOptions[0] || {}).textContent || '',
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
            txt.textContent = 'Terima dan Daftarkan Unit Servis';
        }
    });
}

// ─────────────────────────────────────────────
// NOTA PENERIMAAN SERVICE (tahap UI: dummy, tanpa DB/API)
// ─────────────────────────────────────────────

let _lastNota = null;

const NOTA_DUMMY = {
    no: 'SV-20260908-2525',
    tgl: '2026-09-08',
    nama: 'Andi Pratama',
    phone: '081234567890',
    device: 'Samsung Galaxy A55',
    damage: 'Layar retak, touch sebagian tidak berfungsi',
    plan: 'Ganti LCD + frame, tes fungsi',
    estimate: 550000,
    dp: 100000,
    technician: 'Teknisi 1',
    status: 'ANALISA',
    estimasi_selesai: '2026-09-11',
    garansi: 'Garansi pengerjaan 30 hari untuk penggantian part yang sama.',
    imei: '-',
    password: '-',
};

function notaData() { return _lastNota || NOTA_DUMMY; }

function notaRupiah(v) {
    return 'Rp ' + (Number(v) || 0).toLocaleString('id-ID');
}

function notaTgl(t) {
    const p = String(t || '').split('-');
    return (p.length === 3) ? p[2] + '-' + p[1] + '-' + p[0] : String(t || '-');
}

function openNota() {
    renderNotaPreview(notaData());
    renderNotaDigital(notaData());
    const fb = document.getElementById('notaFeedback');
    if (fb) fb.classList.add('hidden');
    const win = document.getElementById('pageNota');
    // Nota harus selalu di depan (mis. saat dibuka dari Update Data Servis
    // yang juga float-window). appendChild menaikkan urutan tumpuk,
    // zIndex memastikan menang dari #pageUpdateServis.
    try { document.body.appendChild(win); } catch (_) {}
    win.style.zIndex = '9600';
    win.classList.add('open');
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
        ${row('Konsumen', d.nama)}
        ${row('No. WA', d.phone)}
        ${row('Device', d.device)}
        <div class="nt-sep"></div>
        <div class="nt-label">Kerusakan:</div>
        <div class="nt-val">${escapeHtml(d.damage)}</div>
        <div class="nt-label">Tindakan:</div>
        <div class="nt-val">${escapeHtml(d.plan)}</div>
        <div class="nt-sep"></div>
        ${row('Estimasi', notaRupiah(d.estimate))}
        ${row('DP', notaRupiah(d.dp))}
        ${row('Teknisi', (d.technician || '').trim() || '-')}
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
    kv('Konsumen', d.nama);
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
    kv('Teknisi', (d.technician || '').trim() || '-');
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
    const d = notaData();
    const w = window.open('', '_blank', 'width=360,height=640');
    if (!w) {
        notaFlash('Popup diblokir browser — izinkan popup untuk mencetak.', true);
        return;
    }
    w.document.write('<!DOCTYPE html><html><head><meta charset="utf-8"><title>Nota ' +
        escapeHtml(d.no) + '</title><style>' + notaPrintCSS() + '</style></head><body>' +
        '<div class="nota">' + escapeHtml(notaText(d)) + '</div>' +
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
    const d = notaData();
    const msg = 'Halo ' + (d.nama || 'Kak') + ', unit Anda sudah terdaftar di SUKABUMI FLASHER.\n\n' + notaText(d);
    try {
        if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(msg);
    } catch (_) {}
    const num = notaWaNumber(d.phone);
    if (!num) { notaFlash('No. WA kosong — teks nota sudah disalin.', true); return; }
    notaFlash('Teks nota disalin — membuka WhatsApp customer...');
    window.open('https://wa.me/' + num + '?text=' + encodeURIComponent(msg), '_blank');
}

function notaSaveImage() {
    const d = notaData();
    const lines = notaText(d).split('\n');
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

// ── Nota Digital: modern, visual, untuk smartphone/WA (tahap UI, tanpa DB/API) ──

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
    if (isD) renderNotaDigital(notaData());
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
    if (v === 'DONE' || v === 'CASH' || v === 'SELESAI') return 'nd-green';
    if (v === 'CANCEL' || v === 'BATAL') return 'nd-red';
    if (v === 'ANALISA' || v === 'KONFIRMASI' || v === 'WAIT PART') return 'nd-amber';
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

function renderNotaDigital(d) {
    const el = document.getElementById('notaDigital');
    if (!el) return;
    const teknisi = (d.technician || '').trim() || '-';
    const tgl = notaTglSlash(d.tgl);
    const jam = notaJam();
    const selesai = notaTglSlash(notaEstimasiSelesai(d));
    const imei = (d.imei || '').trim() || '-';
    const qrUrl = 'https://api.qrserver.com/v1/create-qr-code/?size=132x132&margin=6&data='
        + encodeURIComponent('SUKABUMI FLASHER ' + (d.no || ''));
    const stCls = notaStatusClass(d.status).replace('nd-', '');
    el.innerHTML = `
    <div class="ndr-sheet">
        <div class="ndr-head">
            <div class="ndr-brand">
                <span class="ndr-logo"><img src="/static/assets/logo.png" alt="SUKABUMI FLASHER" onerror="this.style.display='none'"><i class="fa-solid fa-bolt"></i></span>
                <div><b>SUKABUMI FLASHER</b><span>BUSINESS OPERATING SYSTEM</span></div>
            </div>
            <div class="ndr-contact">
                <div><i class="fa-regular fa-calendar"></i>${escapeHtml(tgl)}</div>
                <div><i class="fa-regular fa-clock"></i>Jam: ${escapeHtml(jam)}</div>
            </div>
        </div>
        <div class="ndr-title-row">
            <div class="ndr-title">
                <h3>NOTA <em>PENERIMAAN</em> SERVICE</h3>
                <div class="ndr-state ndr-${stCls}">
                    <i class="fa-solid fa-shield-halved"></i>
                    <div><b>STATUS: ${escapeHtml(d.status || '-')}</b><span>Simpan nota ini sebagai bukti penerimaan &amp; pengambilan unit Anda.</span></div>
                </div>
            </div>
            <div class="ndr-nonum">
                <span>NOMOR SERVIS</span>
                <b>${escapeHtml(d.no || '-')}</b>
                <div class="ndr-strip"><i class="fa-solid fa-shield-halved"></i>Simpan nota ini sebagai bukti servis Anda</div>
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
                <div class="ndr-kv">IMEI <span>${escapeHtml(imei)}</span></div>
                <div class="ndr-kv">No. Servis <span>${escapeHtml(d.no || '-')}</span></div>
            </div>
            <div class="ndr-card">
                <div class="ndr-cap"><i class="fa-solid fa-hashtag"></i>PENERIMAAN</div>
                <div class="ndr-name">${escapeHtml(d.no || '-')}</div>
                <div class="ndr-line"><i class="fa-regular fa-calendar"></i>${escapeHtml(tgl)}</div>
                <div class="ndr-line"><i class="fa-regular fa-clock"></i>${escapeHtml(jam)}</div>
            </div>
        </div>
        <div class="ndr-grid3">
            <div class="ndr-card">
                <div class="ndr-cap"><i class="fa-solid fa-wrench"></i>DETAIL PERBAIKAN</div>
                <div class="ndr-sec"><span>Keluhan</span><p>${escapeHtml(d.damage)}</p></div>
                <div class="ndr-sec"><span>Pekerjaan / Tindakan</span><p class="ndr-check"><i class="fa-solid fa-check"></i>${escapeHtml(d.plan)}</p></div>
                <div class="ndr-sec"><span>Teknisi</span><p>${escapeHtml(teknisi)}</p></div>
                <div class="ndr-sec"><span>Estimasi Biaya</span><p class="ndr-price">${escapeHtml(notaRupiah(d.estimate))}</p></div>
                <div class="ndr-sec"><span>DP Masuk</span><p>${escapeHtml(notaRupiah(d.dp))}</p></div>
            </div>
            <div class="ndr-card is-green">
                <div class="ndr-cap"><i class="fa-solid fa-shield-halved"></i>JADWAL SERVIS</div>
                <div class="ndr-sched">
                    <div class="ndr-srow"><span class="ndr-ico"><i class="fa-regular fa-calendar"></i></span><div><span>Diterima</span><b>${escapeHtml(tgl)}</b></div></div>
                    <div class="ndr-srow"><span class="ndr-ico"><i class="fa-regular fa-calendar-check"></i></span><div><span>Estimasi Selesai</span><b>${escapeHtml(selesai)}</b></div></div>
                    <div class="ndr-srow"><span class="ndr-ico"><i class="fa-regular fa-clock"></i></span><div><span>Status</span><b>${escapeHtml(d.status || '-')}</b></div></div>
                </div>
                <div class="ndr-note"><i class="fa-solid fa-circle-info"></i><span>${d.garansi ? escapeHtml(d.garansi) : 'Estimasi dapat berubah sesuai hasil diagnosa teknisi.'}</span></div>
            </div>
            <div class="ndr-card">
                <div class="ndr-cap is-green-t"><i class="fa-solid fa-shield-halved"></i>SYARAT PENGAMBILAN</div>
                <ul class="ndr-yes">
                    <li><i class="fa-solid fa-check"></i><span>Tunjukkan nota / No. Servis</span></li>
                    <li><i class="fa-solid fa-check"></i><span>Pelunasan sisa biaya servis</span></li>
                    <li><i class="fa-solid fa-check"></i><span>Cek kondisi unit saat pengambilan</span></li>
                </ul>
                <div class="ndr-nohead"><i class="fa-solid fa-triangle-exclamation"></i>TIDAK TERMASUK</div>
                <ul class="ndr-no">
                    <li><i class="fa-regular fa-circle-xmark"></i><span>Kehilangan data / password</span></li>
                    <li><i class="fa-regular fa-circle-xmark"></i><span>Kerusakan akibat kelalaian pemilik</span></li>
                    <li><i class="fa-regular fa-circle-xmark"></i><span>Aksesoris yang tidak dititipkan</span></li>
                </ul>
            </div>
        </div>
        <div class="ndr-grid3 ndr-row3">
            <div class="ndr-card">
                <div class="ndr-cap"><i class="fa-solid fa-shield-halved"></i>VERIFIKASI SERVIS</div>
                <p class="ndr-desc">Scan QR untuk verifikasi nota dan melihat status servis Anda.</p>
                <div class="ndr-pill"><i class="fa-solid fa-globe"></i>boss-sf.id/lacak/${escapeHtml(d.no || '')}</div>
            </div>
            <div class="ndr-qrwrap">
                <img src="${qrUrl}" alt="QR servis" loading="lazy" onerror="this.style.display='none';var f=this.parentNode.querySelector('.ndr-kode-fallback');if(f)f.style.display='flex';">
                <div class="ndr-kode-fallback" style="display:none"><span>KODE SERVIS</span><b>${escapeHtml(d.no || '-')}</b></div>
            </div>
            <div class="ndr-pink">
                <span class="ndr-shield"><i class="fa-solid fa-shield-halved"></i></span>
                <p>Nota ini hanya berlaku di<br><b>SUKABUMI FLASHER<br>BUSINESS OPERATING SYSTEM</b></p>
                <div class="ndr-thanks">Terima kasih telah mempercayakan perbaikan perangkat Anda kepada kami.</div>
            </div>
        </div>
        <div class="ndr-terms">
            <div class="ndr-terms-head">KETENTUAN SERVIS<span></span></div>
            <div class="ndr-terms-grid">
                <div><span><i class="fa-regular fa-file-lines"></i></span><p><b>1.</b> Nota ini wajib dibawa saat pengambilan unit.</p></div>
                <div><span><i class="fa-solid fa-shield-halved"></i></span><p><b>2.</b> Estimasi dapat berubah sesuai hasil diagnosa teknisi.</p></div>
                <div><span><i class="fa-solid fa-mobile-screen-button"></i></span><p><b>3.</b> Data penting harap di-backup sebelum servis.</p></div>
                <div><span><i class="fa-solid fa-triangle-exclamation"></i></span><p><b>4.</b> Keputusan teknisi adalah yang utama dalam penentuan perbaikan.</p></div>
            </div>
        </div>
        <div class="ndr-foot">
            <div class="ndr-foot-l"><i class="fa-regular fa-circle-check"></i><span>Terima kasih telah mempercayakan perbaikan perangkat Anda kepada kami.</span></div>
            <div class="ndr-foot-r"><b>Powered by <em>SUKABUMI FLASHER</em></b><span>BUSINESS OPERATING SYSTEM</span></div>
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
        + 'Teknisi : ' + ((d.technician || '').trim() || '-') + '\n'
        + 'Tgl Terima : ' + notaTgl(d.tgl) + '\n'
        + 'Estimasi Selesai : ' + notaTgl(notaEstimasiSelesai(d)) + '\n'
        + (d.garansi ? d.garansi + '\n' : '')
        + '--------------------------\n'
         + 'Simpan nota ini sebagai bukti pengambilan unit. Terima kasih! - *SUKABUMI FLASHER*';
}

function notaDigitalShareWA() {
    const d = notaData();
    const msg = 'Halo ' + (d.nama || 'Kak') + ', berikut nota digital servis Anda di SUKABUMI FLASHER.\n\n' + notaDigitalText(d);
    try {
        if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(msg);
    } catch (_) {}
    const num = notaWaNumber(d.phone);
    if (!num) { notaFlash('No. WA kosong — teks nota sudah disalin.', true); return; }
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
    const node = document.getElementById('notaDigital');
    if (node && typeof html2canvas !== 'undefined') {
        try {
            notaFlash('Menyiapkan gambar nota...');
            // Export optimal untuk WhatsApp: target lebar ±1080px, tajam, ringan.
            // Scale dinamis dari lebar aktual node; tinggi mengikuti proporsional.
            const targetWidth = 1080;
            const rect = node.getBoundingClientRect();
            const actualWidth = (rect && rect.width) || node.offsetWidth || 0;
            const scale = actualWidth > 0 ? Math.min(targetWidth / actualWidth, 2) : 2;
            const canvas = await html2canvas(node, { backgroundColor: '#eef1f5', scale: scale, useCORS: true, logging: false });
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
        ['TEKNISI', (d.technician || '').trim() || '-'],
        ['ESTIMASI SELESAI', notaTglSlash(notaEstimasiSelesai(d))],
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
    c.fillStyle = '#b91c1c';
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

document.addEventListener('DOMContentLoaded', async function () {
    initTheme();
    updateClock();
    setInterval(updateClock, 1000);
    initNav();
    renderQuickActions();
    initReceivePage();
    initUpdateServis();
    initFloatDrag();
    initSparepart();
    initLogin();

    window.addEventListener('hashchange', () => {
        if (!getToken()) return;
        if (isReceiveHash()) { openServisBaru(); return; }
        const k = pageFromHash();
        if (k) navigateTo(k);
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
