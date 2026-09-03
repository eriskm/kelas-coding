/* ============================================
   BOSS SF — Dashboard Logic (fetch dari FastAPI)
   ============================================ */

const API_BASE = '/api';

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
    const res = await fetch(API_BASE + path);
    if (!res.ok) throw new Error('API error ' + res.status);
    return res.json();
}

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
    document.getElementById('insightCards').innerHTML = items.map(it => `
        <div class="insight-card">
            <div class="insight-val ${it.color}">${it.value}</div>
            <div class="insight-label">${it.label}</div>
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
// INIT
// ─────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', async function () {
    initTheme();
    updateClock();
    setInterval(updateClock, 1000);
    initNav();
    renderQuickActions();

    try {
        await Promise.all([renderStarCards(), renderInsights(), initCharts()]);
    } catch (err) {
        console.error('Gagal memuat data dari API:', err);
    }
});
