/* ============================================
   ServisKu v2 — Dashboard Logic & Dummy Data
   ============================================ */

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
        // update charts untuk dark mode
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

function chartTextColor() { return isDark() ? '#94a3b8' : '#64748b'; }
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
        { icon: 'fa-solid fa-plus',             label: 'Servis Baru',   bg: 'bg-indigo-500',  hover: 'hover:bg-indigo-600',  text: 'text-white' },
        { icon: 'fa-solid fa-user-plus',        label: 'Customer Baru', bg: 'bg-emerald-500', hover: 'hover:bg-emerald-600', text: 'text-white' },
        { icon: 'fa-solid fa-money-bill-wave',  label: 'Transaksi Baru',bg: 'bg-amber-500',   hover: 'hover:bg-amber-600',   text: 'text-white' },
        { icon: 'fa-solid fa-hand-holding-dollar', label: 'Tambahan Pembayaran', bg: 'bg-purple-500', hover: 'hover:bg-purple-600', text: 'text-white' },
        { icon: 'fa-solid fa-microchip',        label: 'Tambah Sparepart', bg: 'bg-cyan-600', hover: 'hover:bg-cyan-700',   text: 'text-white' },
    ];

    document.getElementById('quickActions').innerHTML = actions.map(a => `
        <button class="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-[13px] font-semibold ${a.bg} ${a.hover} ${a.text} transition-all hover:-translate-y-0.5 hover:shadow-lg cursor-pointer border-0">
            <i class="${a.icon}"></i> ${a.label}
        </button>
    `).join('');
}

// ─────────────────────────────────────────────
// INSIGHT CARDS
// ─────────────────────────────────────────────

function renderInsights() {
    const items = [
        { value: '18',     label: 'Sedang Dikerjakan', color: 'text-cyan-600' },
        { value: '3',      label: 'Servis Terlambat',   color: 'text-red-500' },
        { value: '5',      label: 'Menunggu Approval',  color: 'text-amber-600' },
        { value: formatRupiah(2650000), label: 'Total Piutang', color: 'text-rose-600' },
    ];

    document.getElementById('insightCards').innerHTML = items.map(it => `
        <div class="insight-card">
            <div class="insight-val ${it.color}">${it.value}</div>
            <div class="insight-label">${it.label}</div>
        </div>
    `).join('');
}

// ─────────────────────────────────────────────
// TECHNICIAN LIST
// ─────────────────────────────────────────────

const technicians = [
    { name: 'Budi Santoso',   active: 4, total: 6, color: '#3b82f6' },
    { name: 'Andi Wijaya',    active: 3, total: 5, color: '#10b981' },
    { name: 'Rizky Pratama',  active: 2, total: 4, color: '#f59e0b' },
    { name: 'Dedi Kurnia',    active: 1, total: 3, color: '#8b5cf6' },
];

function renderTechnicians() {
    document.getElementById('technicianList').innerHTML = technicians.map(t => {
        const pct = Math.round((t.active / t.total) * 100);
        return `
            <div class="flex items-center gap-3">
                <div class="w-2 h-2 rounded-full flex-shrink-0" style="background:${t.color}"></div>
                <div class="flex-1 min-w-0">
                    <div class="flex items-center justify-between mb-1">
                        <span class="text-[12.5px] font-medium text-gray-700 dark:text-gray-300 truncate">${t.name}</span>
                        <span class="text-[11px] text-gray-400 ml-2 flex-shrink-0">${t.active}/${t.total}</span>
                    </div>
                    <div class="h-[5px] bg-gray-100 dark:bg-gray-700 rounded-full overflow-hidden">
                        <div class="h-full rounded-full transition-all" style="width:${pct}%; background:${t.color}"></div>
                    </div>
                </div>
            </div>
        `;
    }).join('');
}

// ─────────────────────────────────────────────
// STATUS SUMMARY
// ─────────────────────────────────────────────

function renderStatusSummary() {
    const statuses = [
        { label: 'Masuk',           count: 12, color: '#3b82f6' },
        { label: 'Diagnosa',        count: 5,  color: '#8b5cf6' },
        { label: 'Menunggu Acc',    count: 5,  color: '#f59e0b' },
        { label: 'Menunggu Part',   count: 4,  color: '#f97316' },
        { label: 'Perbaikan',       count: 10, color: '#06b6d4' },
        { label: 'QC',              count: 4,  color: '#6366f1' },
        { label: 'Siap Diambil',    count: 7,  color: '#22c55e' },
        { label: 'Selesai',         count: 12, color: '#16a34a' },
    ];

    const total = statuses.reduce((s, x) => s + x.count, 0) || 1;

    document.getElementById('statusSummary').innerHTML = statuses.map(s => {
        const pct = Math.round((s.count / total) * 100);
        return `
            <div>
                <div class="flex items-center justify-between mb-1">
                    <span class="text-[11.5px] font-medium text-gray-600 dark:text-gray-400">${s.label}</span>
                    <span class="text-[11.5px] font-bold text-gray-800 dark:text-gray-200">${s.count}</span>
                </div>
                <div class="h-[7px] bg-gray-100 dark:bg-gray-700 rounded-full overflow-hidden">
                    <div class="h-full rounded-full" style="width:${pct}%; background:${s.color}"></div>
                </div>
            </div>
        `;
    }).join('');
}

// ─────────────────────────────────────────────
// CHARTS
// ─────────────────────────────────────────────

let omzetChart, servisChart, statusChart, kerusakanChart;

function getCommonOpts() {
    return {
        chart: { fontFamily: 'Inter, system-ui, sans-serif', toolbar: { show: false } },
        grid: { borderColor: chartGridColor() },
        theme: { mode: isDark() ? 'dark' : 'light' },
    };
}

function initCharts() {
    const co = getCommonOpts();

    // 1. Omzet 7 Hari
    omzetChart = new ApexCharts(document.querySelector('#chartOmzet'), {
        ...co,
        chart: { ...co.chart, type: 'area', height: 260 },
        series: [{ name: 'Omzet', data: [2800000, 3200000, 2500000, 4100000, 3600000, 2900000, 3800000] }],
        xaxis: { categories: ['Sen', 'Sel', 'Rab', 'Kam', 'Jum', 'Sab', 'Min'], labels: { style: { fontSize: '11px' } } },
        yaxis: { labels: { formatter: v => 'Rp' + (v / 1000000).toFixed(1) + 'jt', style: { fontSize: '11px' } } },
        colors: ['#6366f1'],
        fill: { type: 'gradient', gradient: { opacityFrom: 0.4, opacityTo: 0.05 } },
        stroke: { curve: 'smooth', width: 2.5 },
        dataLabels: { enabled: false },
        tooltip: { y: { formatter: v => 'Rp ' + v.toLocaleString('id-ID') } },
    });
    omzetChart.render();

    // 2. Servis/Hari
    servisChart = new ApexCharts(document.querySelector('#chartServis'), {
        ...co,
        chart: { ...co.chart, type: 'bar', height: 260 },
        series: [{ name: 'Servis', data: [8, 12, 6, 10, 14, 9, 12] }],
        xaxis: { categories: ['Sen', 'Sel', 'Rab', 'Kam', 'Jum', 'Sab', 'Min'], labels: { style: { fontSize: '11px' } } },
        yaxis: { labels: { style: { fontSize: '11px' } } },
        colors: ['#10b981'],
        plotOptions: { bar: { borderRadius: 6, columnWidth: '50%' } },
        dataLabels: { enabled: false },
    });
    servisChart.render();

    // 3. Status Donut
    statusChart = new ApexCharts(document.querySelector('#chartStatus'), {
        ...co,
        chart: { ...co.chart, type: 'donut', height: 270 },
        series: [12, 5, 5, 4, 10, 4, 7, 12],
        labels: ['Masuk', 'Diagnosa', 'Menunggu Acc', 'Menunggu Part', 'Perbaikan', 'QC', 'Siap Diambil', 'Selesai'],
        colors: ['#3b82f6', '#8b5cf6', '#f59e0b', '#f97316', '#06b6d4', '#6366f1', '#22c55e', '#16a34a'],
        plotOptions: { pie: { donut: { size: '62%' } } },
        legend: { position: 'bottom', fontSize: '10.5px', itemMargin: { horizontal: 6, vertical: 3 } },
        dataLabels: { enabled: false },
    });
    statusChart.render();

    // 4. Jenis Kerusakan
    kerusakanChart = new ApexCharts(document.querySelector('#chartKerusakan'), {
        ...co,
        chart: { ...co.chart, type: 'bar', height: 280 },
        series: [{ name: 'Jumlah', data: [14, 9, 7, 5, 4, 3] }],
        xaxis: { categories: ['Layar Pecah', 'Baterai', 'Charging', 'Speaker', 'Kamera', 'Water'], labels: { style: { fontSize: '11px' }, rotate: -30 } },
        yaxis: { labels: { style: { fontSize: '11px' } } },
        colors: ['#ef4444'],
        plotOptions: { bar: { borderRadius: 6, columnWidth: '50%' } },
        dataLabels: { enabled: false },
    });
    kerusakanChart.render();
}

function updateChartTheme() {
    [omzetChart, servisChart, statusChart, kerusakanChart].forEach(c => {
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
    renderTechnicians();
    renderStatusSummary();
    initCharts();
    initNav();
});
