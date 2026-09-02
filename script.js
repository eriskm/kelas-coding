/* ============================================
   ServisKu — Dashboard Logic & Dummy Data
   ============================================ */

// ─────────────────────────────────────────────
// DUMMY DATA
// ─────────────────────────────────────────────

const STATUS = {
    RECEIVED:          { label: 'Masuk',          class: 'badge-received' },
    DIAGNOSIS:         { label: 'Diagnosa',       class: 'badge-diagnosis' },
    WAITING_APPROVAL:  { label: 'Menunggu Acc',   class: 'badge-waiting-approval' },
    WAITING_PART:      { label: 'Menunggu Part',  class: 'badge-waiting-part' },
    REPAIR:            { label: 'Perbaikan',       class: 'badge-repair' },
    QC:                { label: 'QC',              class: 'badge-qc' },
    READY:             { label: 'Siap Diambil',    class: 'badge-ready' },
    COMPLETED:         { label: 'Selesai',         class: 'badge-completed' },
    CANCELLED:         { label: 'Batal',           class: 'badge-cancelled' },
};

const technicians = [
    { id: 1, name: 'Budi Santoso',   active: 4, total: 6, color: '#3b82f6' },
    { id: 2, name: 'Andi Wijaya',    active: 3, total: 5, color: '#10b981' },
    { id: 3, name: 'Rizky Pratama',  active: 2, total: 4, color: '#f59e0b' },
    { id: 4, name: 'Dedi Kurnia',    active: 1, total: 3, color: '#8b5cf6' },
];

const customers = [
    { id: 'C001', name: 'Ahmad Fauzi',     phone: '081234567890' },
    { id: 'C002', name: 'Siti Nurhaliza',   phone: '085678901234' },
    { id: 'C003', name: 'Rudi Hartono',     phone: '087890123456' },
    { id: 'C004', name: 'Maya Sari',        phone: '082345678901' },
    { id: 'C005', name: 'Dedi Kurniawan',   phone: '083456789012' },
    { id: 'C006', name: 'Rina Wati',        phone: '084567890123' },
    { id: 'C007', name: 'Hendra Gunawan',   phone: '085678901235' },
    { id: 'C008', name: 'Putri Rahayu',     phone: '086789012345' },
    { id: 'C009', name: 'Fajar Nugroho',    phone: '087890123457' },
    { id: 'C010', name: 'Lestari Dewi',     phone: '088901234567' },
];

const serviceOrders = [
    { id: 'SV-20260901-001', customer: customers[0], device: 'Samsung Galaxy A54',    brand: 'Samsung',  model: 'A54',     tech: technicians[0], status: 'REPAIR',          estimate: 450000,  payment: 0,           time: '08:30' },
    { id: 'SV-20260901-002', customer: customers[1], device: 'iPhone 14 Pro',         brand: 'Apple',    model: '14 Pro',   tech: technicians[1], status: 'WAITING_PART',    estimate: 1200000, payment: 0,           time: '09:15' },
    { id: 'SV-20260901-003', customer: customers[2], device: 'Xiaomi Redmi Note 12',  brand: 'Xiaomi',   model: 'Note 12',  tech: technicians[2], status: 'QC',              estimate: 350000,  payment: 0,           time: '09:45' },
    { id: 'SV-20260901-004', customer: customers[3], device: 'OPPO Reno 8',           brand: 'OPPO',     model: 'Reno 8',   tech: technicians[0], status: 'READY',           estimate: 500000,  payment: 500000,      time: '10:00' },
    { id: 'SV-20260901-005', customer: customers[4], device: 'Samsung Galaxy S23',    brand: 'Samsung',  model: 'S23',      tech: technicians[1], status: 'COMPLETED',       estimate: 800000,  payment: 800000,      time: '10:30' },
    { id: 'SV-20260901-006', customer: customers[5], device: 'Vivo V27',              brand: 'Vivo',     model: 'V27',      tech: technicians[3], status: 'RECEIVED',        estimate: 0,       payment: 0,           time: '11:00' },
    { id: 'SV-20260901-007', customer: customers[6], device: 'iPhone 13',             brand: 'Apple',    model: '13',       tech: technicians[2], status: 'DIAGNOSIS',       estimate: 0,       payment: 0,           time: '11:30' },
    { id: 'SV-20260901-008', customer: customers[7], device: 'Realme C55',            brand: 'Realme',   model: 'C55',      tech: technicians[0], status: 'WAITING_APPROVAL', estimate: 280000,  payment: 0,           time: '12:00' },
    { id: 'SV-20260901-009', customer: customers[8], device: 'Samsung Galaxy A34',    brand: 'Samsung',  model: 'A34',      tech: technicians[1], status: 'REPAIR',          estimate: 400000,  payment: 0,           time: '13:00' },
    { id: 'SV-20260901-010', customer: customers[9], device: 'Xiaomi Poco X5',        brand: 'Xiaomi',   model: 'Poco X5',  tech: technicians[3], status: 'READY',           estimate: 320000,  payment: 320000,      time: '13:30' },
    { id: 'SV-20260901-011', customer: customers[0], device: 'OPPO A78',              brand: 'OPPO',     model: 'A78',      tech: technicians[2], status: 'REPAIR',          estimate: 300000,  payment: 0,           time: '14:00' },
    { id: 'SV-20260901-012', customer: customers[3], device: 'iPhone 15',             brand: 'Apple',    model: '15',       tech: technicians[0], status: 'COMPLETED',       estimate: 1500000, payment: 1500000,     time: '14:30' },
];

const piutangData = [
    { customer: 'Ahmad Fauzi',     amount: 450000,  serviceId: 'SV-20260901-001' },
    { customer: 'Siti Nurhaliza',  amount: 1200000, serviceId: 'SV-20260901-002' },
    { customer: 'Rudi Hartono',    amount: 350000,  serviceId: 'SV-20260901-003' },
    { customer: 'Putri Rahayu',    amount: 280000,  serviceId: 'SV-20260901-008' },
    { customer: 'Fajar Nugroho',   amount: 400000,  serviceId: 'SV-20260901-009' },
];

// ─────────────────────────────────────────────
// HELPER
// ─────────────────────────────────────────────

function formatCurrency(val) {
    if (val === 0) return '-';
    return 'Rp ' + val.toLocaleString('id-ID');
}

function getStatusBadge(status) {
    const s = STATUS[status];
    return `<span class="badge ${s.class}">${s.label}</span>`;
}

// ─────────────────────────────────────────────
// RENDER: STAT CARDS
// ─────────────────────────────────────────────

function renderStatCards() {
    const count = {};
    serviceOrders.forEach(o => {
        count[o.status] = (count[o.status] || 0) + 1;
    });

    const totalOmzet = serviceOrders.reduce((s, o) => s + o.estimate, 0);
    const totalBayar = serviceOrders.reduce((s, o) => s + o.payment, 0);
    const totalPiutang = piutangData.reduce((s, p) => s + p.amount, 0);

    const cards = [
        { icon: 'fa-clipboard-list', bg: 'bg-blue-50',  color: 'text-blue-600',  value: serviceOrders.length,   label: 'Total Servis Hari Ini',  change: '+3 dari kemarin', up: true },
        { icon: 'fa-inbox',         bg: 'bg-cyan-50',   color: 'text-cyan-600',  value: count['RECEIVED'] || 0,  label: 'Servis Masuk',           change: null, up: null },
        { icon: 'fa-wrench',        bg: 'bg-indigo-50', color: 'text-indigo-600',value: (count['REPAIR'] || 0) + (count['DIAGNOSIS'] || 0), label: 'Sedang Dikerjakan', change: null, up: null },
        { icon: 'fa-clock-rotate-left', bg: 'bg-orange-50', color: 'text-orange-600', value: (count['WAITING_PART'] || 0) + (count['WAITING_APPROVAL'] || 0), label: 'Menunggu', change: null, up: null },
        { icon: 'fa-circle-check',  bg: 'bg-green-50',  color: 'text-green-600', value: (count['READY'] || 0) + (count['COMPLETED'] || 0), label: 'Siap Diambil', change: null, up: null },
        { icon: 'fa-coins',         bg: 'bg-emerald-50',color: 'text-emerald-600', value: formatCurrency(totalOmzet), label: 'Omzet Hari Ini', change: '+12% dari kemarin', up: true },
    ];

    const container = document.getElementById('statCards');
    container.innerHTML = cards.map(c => `
        <div class="stat-card">
            <div class="flex items-center justify-between mb-3">
                <div class="stat-icon ${c.bg} ${c.color}">
                    <i class="fa-solid ${c.icon}"></i>
                </div>
            </div>
            <div class="stat-value">${c.value}</div>
            <div class="stat-label">${c.label}</div>
            ${c.change ? `<div class="stat-change ${c.up ? 'up' : 'down'}"><i class="fa-solid fa-arrow-${c.up ? 'up' : 'down'} mr-1"></i>${c.change}</div>` : ''}
        </div>
    `).join('');
}

// ─────────────────────────────────────────────
// RENDER: SERVICE TABLE
// ─────────────────────────────────────────────

function renderServiceTable() {
    const tbody = document.getElementById('serviceTableBody');
    tbody.innerHTML = serviceOrders.map(o => `
        <tr>
            <td class="px-5 py-3 font-mono text-xs text-gray-600">${o.id}</td>
            <td class="px-5 py-3">
                <div class="font-medium text-gray-800">${o.customer.name}</div>
                <div class="text-xs text-gray-400">${o.customer.phone}</div>
            </td>
            <td class="px-5 py-3 text-gray-700">${o.device}</td>
            <td class="px-5 py-3 text-gray-600">${o.tech.name.split(' ')[0]}</td>
            <td class="px-5 py-3">${getStatusBadge(o.status)}</td>
            <td class="px-5 py-3 text-right text-gray-700">${formatCurrency(o.estimate)}</td>
            <td class="px-5 py-3 text-right text-gray-400 text-xs">${o.time}</td>
        </tr>
    `).join('');
}

// ─────────────────────────────────────────────
// RENDER: TECHNICIAN LIST
// ─────────────────────────────────────────────

function renderTechnicians() {
    const container = document.getElementById('technicianList');
    container.innerHTML = technicians.map(t => {
        const pct = Math.round((t.active / t.total) * 100);
        return `
            <div>
                <div class="flex items-center justify-between mb-1">
                    <div class="flex items-center gap-2">
                        <div class="w-2 h-2 rounded-full" style="background:${t.color}"></div>
                        <span class="text-sm font-medium text-gray-700">${t.name}</span>
                    </div>
                    <span class="text-xs text-gray-500">${t.active} / ${t.total} job</span>
                </div>
                <div class="tech-progress">
                    <div class="tech-progress-bar" style="width:${pct}%; background:${t.color}"></div>
                </div>
            </div>
        `;
    }).join('');
}

// ─────────────────────────────────────────────
// RENDER: STATUS SUMMARY
// ─────────────────────────────────────────────

function renderStatusSummary() {
    const count = {};
    serviceOrders.forEach(o => {
        count[o.status] = (count[o.status] || 0) + 1;
    });

    const items = [
        { status: 'RECEIVED',        color: '#3b82f6' },
        { status: 'DIAGNOSIS',       color: '#8b5cf6' },
        { status: 'WAITING_APPROVAL',color: '#f59e0b' },
        { status: 'WAITING_PART',    color: '#f97316' },
        { status: 'REPAIR',          color: '#06b6d4' },
        { status: 'QC',              color: '#6366f1' },
        { status: 'READY',           color: '#22c55e' },
        { status: 'COMPLETED',       color: '#16a34a' },
    ];

    const total = serviceOrders.length || 1;
    const container = document.getElementById('statusSummary');

    container.innerHTML = items.map(it => {
        const n = count[it.status] || 0;
        const pct = Math.round((n / total) * 100);
        return `
            <div>
                <div class="flex items-center justify-between mb-1">
                    <span class="text-xs text-gray-600">${STATUS[it.status].label}</span>
                    <span class="text-xs font-semibold text-gray-800">${n}</span>
                </div>
                <div class="status-bar-track">
                    <div class="status-bar-fill" style="width:${pct}%; background:${it.color}"></div>
                </div>
            </div>
        `;
    }).join('');
}

// ─────────────────────────────────────────────
// RENDER: PIUTANG
// ─────────────────────────────────────────────

function renderPiutang() {
    const container = document.getElementById('piutangList');
    container.innerHTML = piutangData.map(p => `
        <div class="piutang-item">
            <div>
                <div class="text-sm font-medium text-gray-800">${p.customer}</div>
                <div class="text-xs text-gray-400">${p.serviceId}</div>
            </div>
            <div class="text-sm font-bold text-red-600">${formatCurrency(p.amount)}</div>
        </div>
    `).join('');
}

// ─────────────────────────────────────────────
// CHARTS
// ─────────────────────────────────────────────

const chartColors = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4'];

function initCharts() {
    // 1. Omzet 7 Hari
    new ApexCharts(document.querySelector('#chartOmzet'), {
        chart: { type: 'area', height: 260, toolbar: { show: false }, fontFamily: 'Inter, sans-serif' },
        series: [{ name: 'Omzet', data: [2800000, 3200000, 2500000, 4100000, 3600000, 2900000, 3800000] }],
        xaxis: { categories: ['Sen', 'Sel', 'Rab', 'Kam', 'Jum', 'Sab', 'Min'], labels: { style: { fontSize: '11px' } } },
        yaxis: { labels: { formatter: v => 'Rp ' + (v / 1000000).toFixed(1) + 'jt', style: { fontSize: '11px' } } },
        colors: ['#3b82f6'],
        fill: { type: 'gradient', gradient: { opacityFrom: 0.4, opacityTo: 0.05 } },
        stroke: { curve: 'smooth', width: 2 },
        dataLabels: { enabled: false },
        grid: { borderColor: '#f1f5f9' },
        tooltip: { y: { formatter: v => 'Rp ' + v.toLocaleString('id-ID') } },
    }).render();

    // 2. Jumlah Servis / Hari
    new ApexCharts(document.querySelector('#chartServis'), {
        chart: { type: 'bar', height: 260, toolbar: { show: false }, fontFamily: 'Inter, sans-serif' },
        series: [{ name: 'Servis', data: [8, 12, 6, 10, 14, 9, 12] }],
        xaxis: { categories: ['Sen', 'Sel', 'Rab', 'Kam', 'Jum', 'Sab', 'Min'], labels: { style: { fontSize: '11px' } } },
        yaxis: { labels: { style: { fontSize: '11px' } } },
        colors: ['#10b981'],
        plotOptions: { bar: { borderRadius: 6, columnWidth: '50%' } },
        dataLabels: { enabled: false },
        grid: { borderColor: '#f1f5f9' },
    }).render();

    // 3. Status Pie
    const countStatus = {};
    serviceOrders.forEach(o => {
        const lbl = STATUS[o.status].label;
        countStatus[lbl] = (countStatus[lbl] || 0) + 1;
    });
    new ApexCharts(document.querySelector('#chartStatus'), {
        chart: { type: 'donut', height: 260, fontFamily: 'Inter, sans-serif' },
        series: Object.values(countStatus),
        labels: Object.keys(countStatus),
        colors: chartColors,
        plotOptions: { pie: { donut: { size: '65%' } } },
        legend: { position: 'bottom', fontSize: '11px', itemMargin: { horizontal: 8, vertical: 4 } },
        dataLabels: { enabled: false },
    }).render();

    // 4. Teknisi Bar
    new ApexCharts(document.querySelector('#chartTeknisi'), {
        chart: { type: 'bar', height: 260, toolbar: { show: false }, fontFamily: 'Inter, sans-serif' },
        series: [
            { name: 'Selesai', data: technicians.map(t => t.total - t.active) },
            { name: 'Aktif',   data: technicians.map(t => t.active) },
        ],
        xaxis: { categories: technicians.map(t => t.name.split(' ')[0]), labels: { style: { fontSize: '11px' } } },
        yaxis: { labels: { style: { fontSize: '11px' } } },
        colors: ['#22c55e', '#3b82f6'],
        plotOptions: { bar: { borderRadius: 4, columnWidth: '55%', horizontal: false } },
        stroke: { show: true, width: 0 },
        legend: { position: 'top', fontSize: '11px' },
        dataLabels: { enabled: false },
        grid: { borderColor: '#f1f5f9' },
        fill: { opacity: 1 },
    }).render();

    // 5. Merk HP
    const brandCount = {};
    serviceOrders.forEach(o => { brandCount[o.brand] = (brandCount[o.brand] || 0) + 1; });
    new ApexCharts(document.querySelector('#chartMerk'), {
        chart: { type: 'pie', height: 260, fontFamily: 'Inter, sans-serif' },
        series: Object.values(brandCount),
        labels: Object.keys(brandCount),
        colors: ['#3b82f6', '#22c55e', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4'],
        legend: { position: 'bottom', fontSize: '11px', itemMargin: { horizontal: 8, vertical: 4 } },
        dataLabels: { enabled: false },
    }).render();

    // 6. Jenis Kerusakan
    const damageTypes = {
        'Layar Rusak': 4,
        'Baterai Boros': 3,
        'Charging Error': 2,
        'Speaker Mati': 1,
        'Kamera Error': 1,
        'Water Damage': 1,
    };
    new ApexCharts(document.querySelector('#chartKerusakan'), {
        chart: { type: 'bar', height: 280, toolbar: { show: false }, fontFamily: 'Inter, sans-serif' },
        series: [{ name: 'Jumlah', data: Object.values(damageTypes) }],
        xaxis: { categories: Object.keys(damageTypes), labels: { style: { fontSize: '11px' }, rotate: -30, rotateAlways: false } },
        yaxis: { labels: { style: { fontSize: '11px' } } },
        colors: ['#ef4444'],
        plotOptions: { bar: { borderRadius: 6, columnWidth: '55%', horizontal: false } },
        dataLabels: { enabled: false },
        grid: { borderColor: '#f1f5f9' },
    }).render();
}

// ─────────────────────────────────────────────
// SIDEBAR NAVIGATION
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
    renderStatCards();
    renderServiceTable();
    renderTechnicians();
    renderStatusSummary();
    renderPiutang();
    initCharts();
    initNav();
});
