/* ============================================
   ServisKu v3 — Dashboard Logic & Dummy Data
   ============================================ */

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
    return 'Rp ' + val.toLocaleString('id-ID');
}

function isDark() {
    return document.documentElement.classList.contains('dark');
}

function chartGridColor() { return isDark() ? 'rgba(255,255,255,0.04)' : '#f1f5f9'; }

// ─────────────────────────────────────────────
// STAT CARDS (Star Cards)
// ─────────────────────────────────────────────

function renderStarCards() {
    const data = [
        {
            icon: 'fa-solid fa-coins',
            bg: 'bg-indigo-50', iconColor: 'text-indigo-600',
            value: formatRupiah(12500000),
            label: 'Omset Hari Ini',
            change: '+12% dari kemarin', up: true
        },
        {
            icon: 'fa-solid fa-chart-line',
            bg: 'bg-green-50', iconColor: 'text-green-600',
            value: formatRupiah(8750000),
            label: 'Laba Kotor',
            change: null, up: null
        },
        {
            icon: 'fa-solid fa-receipt',
            bg: 'bg-red-50', iconColor: 'text-red-600',
            value: formatRupiah(3750000),
            label: 'Total Beban',
            change: null, up: null
        },
        {
            icon: 'fa-solid fa-sack-dollar',
            bg: 'bg-emerald-50', iconColor: 'text-emerald-600',
            value: formatRupiah(5000000),
            label: 'Laba Bersih',
            change: '+8% dari bulan lalu', up: true
        },
        {
            icon: 'fa-solid fa-bullseye',
            bg: 'bg-amber-50', iconColor: 'text-amber-600',
            value: formatRupiah(15000000),
            label: 'Target Gaji (CTS)',
            change: 'Tercapai 83%', up: true
        },
    ];

    document.getElementById('starCards').innerHTML = data.map(c => `
        <div class="star-card">
            <div class="icon-wrap ${c.bg} ${c.iconColor}"><i class="${c.icon}"></i></div>
            <div>
                <div class="value">${c.value}</div>
                <div class="label">${c.label}</div>
                ${c.change ? `<div class="change ${c.up ? 'up' : 'down'}"><i class="fa-solid fa-arrow-${c.up ? 'up' : 'down'}" style="font-size:9px;margin-right:2px"></i>${c.change}</div>` : ''}
            </div>
        </div>
    `).join('');
}

// ─────────────────────────────────────────────
// QUICK ACTIONS
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
// INSIGHT CARDS
// ─────────────────────────────────────────────

function renderInsights() {
    const items = [
        { value: '18',     label: 'Dikerjakan',   color: 'text-cyan-600' },
        { value: '3',      label: 'Terlambat',     color: 'text-red-500' },
        { value: '5',      label: 'Menunggu Acc',  color: 'text-amber-600' },
        { value: formatRupiah(2650000), label: 'Piutang', color: 'text-rose-600' },
    ];

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

function initCharts() {
    const co = getCommonOpts();

    // Statistik Status Transaksi — Smooth Line Chart
    statusChart = new ApexCharts(document.querySelector('#chartStatusTransaksi'), {
        ...co,
        chart: { ...co.chart, type: 'area', height: getChartHeight(), toolbar: { show: false } },
        series: [
            { name: 'Masuk',    data: [12, 10, 14, 13, 16, 15, 18] },
            { name: 'Selesai',  data: [8, 9, 11, 10, 12, 13, 12] },
            { name: 'Pending',  data: [4, 3, 5, 6, 5, 4, 7] },
        ],
        xaxis: { categories: ['Sen', 'Sel', 'Rab', 'Kam', 'Jum', 'Sab', 'Min'], labels: { style: { fontSize: '10px' } } },
        yaxis: { labels: { style: { fontSize: '10px' } } },
        colors: ['#3b82f6', '#22c55e', '#f59e0b'],
        fill: { type: 'gradient', gradient: { shadeIntensity: 1, opacityFrom: 0.35, opacityTo: 0.02 } },
        stroke: { curve: 'smooth', width: 3 },
        dataLabels: { enabled: false },
        legend: { position: 'top', fontSize: '10.5px', horizontalAlign: 'left' },
        tooltip: { y: { formatter: v => v + ' unit' } },
        responsive: [{
            breakpoint: 640,
            options: {
                chart: { height: 220 },
                legend: { fontSize: '9px' },
            }
        }],
    });
    statusChart.render();

    // Tren Kerusakan Minggu Ini — Horizontal Bar dengan gradasi
    kerusakanChart = new ApexCharts(document.querySelector('#chartKerusakan'), {
        ...co,
        chart: { ...co.chart, type: 'bar', height: getChartHeight(), toolbar: { show: false } },
        series: [{ name: 'Unit', data: [14, 9, 7, 5, 4, 3] }],
        xaxis: { categories: ['Layar Pecah', 'Baterai', 'Charging', 'Speaker', 'Kamera', 'Water'] },
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
            // close sidebar on mobile after click
            if (window.innerWidth < 640) toggleSidebar(false);
        });
    });

    // Mobile bottom nav
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

document.addEventListener('DOMContentLoaded', function () {
    initTheme();
    updateClock();
    setInterval(updateClock, 1000);

    renderStarCards();
    renderQuickActions();
    renderInsights();
    initCharts();
    initNav();
});
