/* ============================================
   BOSS SF — Dashboard Logic (fetch dari FastAPI)
   ============================================ */

const API_BASE = '/api';

// Auth helpers
function getToken() { return localStorage.getItem('bsf_token'); }
function setToken(t) { localStorage.setItem('bsf_token', t); }
function clearToken() { localStorage.removeItem('bsf_token'); }

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

// Ikon & warna untuk tiap kartu statistik
const STAR_META = [
    { icon: 'fa-coins',                 bg: 'bg-indigo-50',   color: 'text-indigo-600' },
    { icon: 'fa-chart-line',            bg: 'bg-green-50',    color: 'text-green-600' },
    { icon: 'fa-receipt',               bg: 'bg-red-50',      color: 'text-red-600' },
    { icon: 'fa-sack-dollar',           bg: 'bg-emerald-50',  color: 'text-emerald-600' },
    { icon: 'fa-bullseye',              bg: 'bg-amber-50',    color: 'text-amber-600' },
];

// ─────────────────────────────────────────────
// RENDER: STAR CARDS (dari API overview)
// ─────────────────────────────────────────────

async function renderStarCards() {
    const data = await apiGet('/overview');
    const cards = data.star_cards.map((c, i) => {
        const m = STAR_META[i] || {};
        const cvalue = typeof c.value === 'number' && c.value >= 1000 ? formatRupiah(c.value) : c.value;
        return `
            <div class="star-card">
                <div class="icon-wrap ${m.bg} ${m.color}"><i class="fa-solid ${m.icon}"></i></div>
                <div>
                    <div class="value">${cvalue}</div>
                    <div class="label">${c.label}</div>
                    ${c.change ? `<div class="change ${c.up ? 'up' : 'down'}"><i class="fa-solid fa-arrow-${c.up ? 'up' : 'down'}" style="font-size:9px;margin-right:2px"></i>${c.change}</div>` : ''}
                </div>
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
        { icon: 'fa-solid fa-plus',                label: 'Servis Baru', bg: 'bg-indigo-500',  color: 'text-indigo-600' },
        { icon: 'fa-solid fa-cash-register',       label: 'Input Kas',   bg: 'bg-emerald-500', color: 'text-emerald-600' },
        { icon: 'fa-solid fa-money-check-dollar',  label: 'Input Beban', bg: 'bg-amber-500',   color: 'text-amber-600' },
        { icon: 'fa-solid fa-microchip',           label: 'Sparepart',   bg: 'bg-cyan-600',    color: 'text-cyan-600' },
    ];

    document.getElementById('quickActions').innerHTML = actions.map(a => `
        <button class="qa-card" style="border:none">
            <span class="qa-card-icon ${a.bg}">
                <i class="${a.icon}"></i>
            </span>
            <span class="qa-card-label ${a.color}">${a.label}</span>
        </button>
    `).join('');
}
// ─────────────────────────────────────────────
// RENDER: INSIGHT CARDS (dari API overview)
// ─────────────────────────────────────────────

async function renderInsights() {
    const data = await apiGet('/overview');
    const items = data.insight;
    const iconMap = {
        'Dikerjakan': 'fa-wrench',
        'Terlambat': 'fa-clock',
        'Menunggu Acc': 'fa-hourglass-half',
        'Piutang': 'fa-hand-holding-dollar',
    };
    document.getElementById('insightCards').innerHTML = items.map(it => `
        <div class="insight-card">
            <span class="insight-icon ${it.color}">
                <i class="fa-solid ${iconMap[it.label] || 'fa-chart-simple'}"></i>
            </span>
            <div class="insight-body">
                <div class="insight-val ${it.color}">${it.value}</div>
                <div class="insight-label">${it.label}</div>
            </div>
        </div>
    `).join('');
}

// ─────────────────────────────────────────────
// CHARTS
// ─────────────────────────────────────────────

let statusChart, kerusakanChart;

function getChartHeight() {
    return window.innerWidth < 640 ? 220 : 270;
}

function getCommonOpts() {
    return {
        chart: { fontFamily: 'Inter, system-ui, sans-serif', toolbar: { show: false } },
        grid: { borderColor: chartGridColor() },
        theme: { mode: isDark() ? 'dark' : 'light' },
    };
}

async function initCharts() {
    const co = getCommonOpts();
    const [statusData, damageData] = await Promise.all([
        apiGet('/statistics/status'),
        apiGet('/statistics/damage'),
    ]);

    // Statistik Status Transaksi — Smooth Line Chart
    statusChart = new ApexCharts(document.querySelector('#chartStatusTransaksi'), {
        ...co,
        chart: { ...co.chart, type: 'area', height: getChartHeight(), toolbar: { show: false } },
        series: statusData.series,
        xaxis: { categories: statusData.categories, labels: { style: { fontSize: '10px' } } },
        yaxis: { labels: { style: { fontSize: '10px' } } },
        colors: ['#3b82f6', '#22c55e', '#f59e0b'],
        fill: { type: 'gradient', gradient: { shadeIntensity: 1, opacityFrom: 0.35, opacityTo: 0.02 } },
        stroke: { curve: 'smooth', width: 3 },
        dataLabels: { enabled: false },
        legend: { position: 'top', fontSize: '10.5px', horizontalAlign: 'left' },
        tooltip: { y: { formatter: v => v + ' unit' } },
        responsive: [{
            breakpoint: 640,
            options: { chart: { height: 220 }, legend: { fontSize: '9px' } },
        }],
    });
    statusChart.render();

    // Tren Kerusakan Minggu Ini — Horizontal Bar
    kerusakanChart = new ApexCharts(document.querySelector('#chartKerusakan'), {
        ...co,
        chart: { ...co.chart, type: 'bar', height: getChartHeight(), toolbar: { show: false } },
        series: [{ name: 'Unit', data: damageData.data }],
        xaxis: { categories: damageData.categories },
        yaxis: { labels: { style: { fontSize: '10px' } } },
        colors: ['#ef4444', '#f97316', '#f59e0b', '#22c55e', '#06b6d4', '#8b5cf6'],
        plotOptions: { bar: { borderRadius: 6, columnWidth: '55%', horizontal: true, distributed: true } },
        dataLabels: { enabled: true, formatter: v => v + 'x', style: { fontSize: '10px', fontWeight: 700 } },
        grid: { borderColor: chartGridColor(), xaxis: { lines: { show: true } } },
        legend: { show: false },
        stroke: { show: false },
        fill: { opacity: 1 },
        tooltip: { y: { formatter: v => v + ' unit' } },
        responsive: [{
            breakpoint: 640,
            options: {
                xaxis: { labels: { style: { fontSize: '9px' } } },
                yaxis: { labels: { style: { fontSize: '9px' } } },
                dataLabels: { style: { fontSize: '8px' } },
            }
        }],
    });
    kerusakanChart.render();
}

function updateChartTheme() {
    [statusChart, kerusakanChart].forEach(c => {
        if (c) c.updateOptions({ theme: { mode: isDark() ? 'dark' : 'light' }, grid: { borderColor: chartGridColor() } });
    });
}

// ─────────────────────────────────────────────
// SIDEBAR NAV
// ─────────────────────────────────────────────

function initNav() {
    const links = document.querySelectorAll('.nav-link');
    links.forEach(link => {
        link.addEventListener('click', function (e) {
            e.preventDefault();
            links.forEach(l => l.classList.remove('active'));
            this.classList.add('active');
            if (window.innerWidth < 640) toggleSidebar(false);
        });
    });

    const mobileItems = document.querySelectorAll('.mobile-nav-item');
    mobileItems.forEach(item => {
        item.addEventListener('click', function () {
            mobileItems.forEach(i => i.classList.remove('active'));
            this.classList.add('active');
        });
    });
}

// ─────────────────────────────────────────────
// LOGIN FLOW
// ─────────────────────────────────────────────

function showLogin() {
    document.getElementById('loginScreen').classList.remove('hidden-login');
}

function hideLogin() {
    document.getElementById('loginScreen').classList.add('hidden-login');
}

function setLoginError(msg) {
    const box = document.getElementById('loginError');
    document.getElementById('loginErrorText').textContent = msg;
    box.classList.remove('hidden');
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
    await Promise.all([renderStarCards(), renderInsights(), initCharts()]);
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
        setToken(data.token);
        setAdminUI(data.user);
        hideLogin();
        await loadDashboard();
    } catch (err) {
        setLoginError(err.message);
    } finally {
        btn.disabled = false;
        btnText.textContent = 'Masuk';
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
    location.reload();
}

function initLogin() {
    const form = document.getElementById('loginForm');
    const pwToggle = document.getElementById('pwToggle');
    const pwInput = document.getElementById('loginPasscode');
    const logoutLink = document.getElementById('logoutLink');

    form.addEventListener('submit', handleLogin);
    logoutLink.addEventListener('click', handleLogout);

    pwToggle.addEventListener('click', () => {
        const show = pwInput.type === 'password';
        pwInput.type = show ? 'text' : 'password';
        pwToggle.innerHTML = `<i class="fa-solid ${show ? 'fa-eye-slash' : 'fa-eye'}"></i>`;
    });
}

// ─────────────────────────────────────────────
// INIT
// ─────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', async function () {
    initTheme();
    updateClock();
    setInterval(updateClock, 1000);
    initNav();
    renderQuickActions();
    initLogin();

    const user = await checkSession();
    if (user) {
        setAdminUI(user);
        hideLogin();
        try {
            await loadDashboard();
        } catch (err) {
            console.error('Gagal memuat data dari API:', err);
        }
    } else {
        showLogin();
    }
});
