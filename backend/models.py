"""SQLAlchemy models (database tables).

Basis waktu: waktu server lokal (datetime.now / date.today) di semua default.
Periode kas, histori, dan jurnal memakai waktu lokal yang sama sehingga
perbandingan rentang tanggal konsisten (sebelumnya campur UTC & lokal).
"""
from datetime import date, datetime

from decimal import Decimal

from sqlalchemy import (
    Numeric,
    Column,
    Integer,
    String,
    DateTime,
    ForeignKey,
    Text,
    Date,
    JSON,
    Boolean,
)
from sqlalchemy.orm import relationship

from database import Base


MONEY = Numeric(18, 2)  # P2-02 / Q10: nilai uang = Numeric/Decimal, bukan Float

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(80), unique=True, index=True, nullable=False)
    display_name = Column(String(120), nullable=False)
    role = Column(String(40), default="ADMIN")
    passcode_hash = Column(String(255), nullable=False)
    passcode_salt = Column(String(64), nullable=False)
    active = Column(Integer, default=1)
    last_login = Column(DateTime)
    created_at = Column(DateTime, default=datetime.now)


class AuthToken(Base):
    __tablename__ = "auth_tokens"

    id = Column(Integer, primary_key=True, index=True)
    token = Column(String(64), unique=True, index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.now)
    expires_at = Column(DateTime, nullable=False)

    user = relationship("User")


class Customer(Base):
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    phone = Column(String(30))
    email = Column(String(120))
    address = Column(Text)
    created_at = Column(DateTime, default=datetime.now)

    service_orders = relationship("ServiceOrder", back_populates="customer")


class ServiceOrder(Base):
    __tablename__ = "service_orders"

    # Status servis kanonis (FINAL LOCK, Bahasa Indonesia).
    # Payment: BELUM LUNAS/LUNAS (derive dari payments, tidak disimpan).
    # Unit: DI TOKO/DIAMBIL (kolom unit_status + taken_at).
    id = Column(Integer, primary_key=True, index=True)
    no_servis = Column(String(50), unique=True, index=True, nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    device = Column(String(120), nullable=False)
    brand = Column(String(60))
    model = Column(String(60))
    damagetype = Column(String(120))
    device_password = Column(String(120))
    imei = Column(String(80))
    check_fisik = Column(JSON, default=list)
    check_len = Column(JSON, default=list)
    repair_plan = Column(Text)
    technician = Column(String(60))
    status = Column(String(30), default="DITERIMA")
    unit_status = Column(String(10), default="DI TOKO")
    taken_at = Column(DateTime)
    estimate = Column(MONEY, default=Decimal("0"))
    payment = Column(MONEY, default=Decimal("0"))  # DP era legacy; read-only arsip (sumber baru: payments)
    service_date = Column(Date, default=date.today)
    # lunas_date/lunas_at = momen LUNAS pertama (dikunci sekali, rename dari cash_*).
    # warranty_months: 1/3/6 bulan pilihan toko, 0 = tidak garansi, NULL = legacy (30 hari).
    # Modal (part/jasa/lainnya) = atribut transaksi (diisi di Update Data Servis).
    # lunas_at = jam pelunasan (scope periode kas 16:00; lunas_date hanya info tanggal).
    final_price = Column(MONEY)
    part_cost = Column(MONEY, default=Decimal("0"))
    modal_jasa = Column(MONEY, default=Decimal("0"))
    modal_lainnya = Column(MONEY, default=Decimal("0"))
    # Owner menyatakan unit ini memang TANPA modal (mis. hanya jasa software,
    # tanpa ganti part). Bezakan ini dari unit yang modalnya belum sempat diisi:
    # yang ditandai tetap masuk Omzet, yang tidak ditandai dianggap belum lengkap
    # dan memicu peringatan keras saat Tutup Kas. Tidak menambah angka apa pun.
    tanpa_modal = Column(Boolean, default=False, nullable=False, server_default="0")
    # laba_bersih per-order (alur keuangan): kewajiban − modal_* bila
    # SELESAI+LUNAS, selain itu 0. Dihitung backend, bukan input user.
    laba_bersih = Column(MONEY, default=Decimal("0"))
    lunas_date = Column(Date)
    lunas_at = Column(DateTime)
    warranty_months = Column(Integer)
    created_at = Column(DateTime, default=datetime.now)

    customer = relationship("Customer", back_populates="service_orders")
    payments = relationship("Payment", back_populates="service_order", cascade="all, delete-orphan")
    order_parts = relationship("ServiceOrderPart", back_populates="service_order", cascade="all, delete-orphan")
    status_history = relationship("StatusHistory", back_populates="service_order",
                                  cascade="all, delete-orphan")


class Payment(Base):
    """Jurnal pembayaran per service order (SOURCE OF TRUTH pembayaran).
    kind: DP | PELUNASAN. Append-only: tanpa PUT/DELETE baris.
    """

    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, index=True)
    service_order_id = Column(Integer, ForeignKey("service_orders.id"), nullable=False)
    kind = Column(String(10), default="PELUNASAN")  # DP | PELUNASAN
    amount = Column(MONEY, nullable=False)
    method = Column(String(30), default="CASH")
    note = Column(String(200))
    created_at = Column(DateTime, default=datetime.now)

    service_order = relationship("ServiceOrder", back_populates="payments")


class Expense(Base):
    """Beban toko (Gaji/Operasional/lainnya).
    Sumber: popup Beban Harian (dulu localStorage) dan/atau input Keuangan.

    FIN-MIRROR (mirror Project A `tabel beban`):
    - `recurring=True` (default) = beban PERMANEN. Mirip Proyek A yang tabel
      `beban` tidak punya dimensi tanggal: nilai yang sama dipotong dari setiap
      siklus, setiap hari, selamanya (mis. gaji 400rb + operasional 205rb).
    - `recurring=False` = beban SATU-OFF bertanggal, hanya dibebankan ke periode
      di mana `created_at`/`tanggal`-nya jatuh (kapabilitas lama Project B).

    Nichta: A memakai `INSERT OR REPLACE` dengan `nama_beban` UNIQUE, jadi
    memperbarui nilai = menimpa entri yang sama (bukan menambah). Flag ini
    menjaga makna itu tanpa menghapus histori.
    """

    __tablename__ = "expenses"

    id = Column(Integer, primary_key=True, index=True)
    kategori = Column(String(40), nullable=False, index=True)  # Gaji | Operasional | ...
    uraian = Column(String(200), nullable=False)
    nilai = Column(MONEY, nullable=False, default=Decimal("0"))
    tanggal = Column(Date)  # info tanggal beban
    created_at = Column(DateTime, default=datetime.now)
    # FIN-MIRROR: beban permanen (default True = sama dengan Proyek A).
    recurring = Column(Boolean, nullable=False, default=True, server_default="1")


class KasPeriod(Base):
    """Periode kas 16:00→16:00. Tetap aktif sampai Admin/Superadmin Tutup Kas.
    CLEAR tampilan ≠ DELETE data (arsip via flag/is_arsip di tabel lain, tahap berikutnya).
    """

    __tablename__ = "kas_periods"

    id = Column(Integer, primary_key=True, index=True)
    start_at = Column(DateTime, nullable=False)
    end_at = Column(DateTime, nullable=False)
    status = Column(String(20), default="OPEN", index=True)  # OPEN | CLOSED
    snapshot = Column(Text)  # JSON snapshot saat Tutup Kas (tahap Tutup Kas)
    closed_by = Column(String(120))
    closed_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.now)


class WarrantyClaim(Base):
    """Klaim Garansi: record/proses BARU yang mengacu ke servis lama.

    Prinsip: servis lama = histori (tidak diubah). Claim punya Claim ID
    sendiri + relasi ke servis asal. Status garansi (VALID/EXPIRED),
    hasil claim (BELUM_DIPUTUSKAN/DITERIMA/DITOLAK), dan status proses
    (MASUK..DITUTUP) disimpan terpisah dan tidak dicampur.
    """

    __tablename__ = "warranty_claims"

    id = Column(Integer, primary_key=True, index=True)
    claim_no = Column(String(50), unique=True, index=True, nullable=False)
    service_order_id = Column(Integer, ForeignKey("service_orders.id"), nullable=False, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False, index=True)

    # Identitas claim
    claim_date = Column(Date, nullable=False)
    received_by = Column(String(120))

    # Snapshot garansi saat claim dibuat (servis asal tidak diubah)
    warranty_days = Column(Integer, default=30)
    warranty_start = Column(Date)
    warranty_end = Column(Date)
    warranty_status = Column(String(20), default="VALID")  # VALID | EXPIRED

    # Keluhan baru (data claim, bukan data servis lama)
    complaint = Column(Text)
    physical_condition = Column(Text)
    completeness = Column(String(200))
    cs_note = Column(Text)
    check_fisik = Column(JSON, default=list)
    check_len = Column(JSON, default=list)

    # Pemeriksaan teknisi
    inspection_result = Column(Text)
    cause = Column(Text)
    matches_previous = Column(String(20))  # YA | TIDAK | SEBAGIAN
    drop_indication = Column(Integer, default=0)
    liquid_indication = Column(Integer, default=0)
    third_party_work = Column(Integer, default=0)
    action_needed = Column(Text)
    tech_note = Column(Text)
    technician = Column(String(60))
    tech_recommendation = Column(String(20))  # DITERIMA | DITOLAK | null

    # Keputusan + status proses (tiga konsep terpisah, lihat docstring)
    decision = Column(String(20), default="BELUM_DIPUTUSKAN")  # BELUM_DIPUTUSKAN | DITERIMA | DITOLAK
    reject_reason = Column(Text)
    claim_status = Column(String(20), default="MASUK")  # MASUK|VERIFIKASI|CEK|DITERIMA|DITOLAK|PROSES|SELESAI|DITUTUP
    # P2-09: RESOLUSI klaim (roadmap P2-08 d): REPAIR | REPLACE | REFUND.
    # Dampak uang untuk REFUND dikerjakan pada P2-10 (belum di sini).
    resolusi = Column(String(20))
    # P2-09: snapshot kondisi unit ASAL saat claim dibuat (audit; servis lama
    # tidak diubah). Melanjutkan aturan "garansi hanya dari transaksi settled".
    origin_payment_status = Column(String(20))
    origin_warranty_months = Column(Integer)

    # Biaya (customer bisa Rp0 bila ditanggung garansi; internal tetap dicatat)
    customer_cost = Column(MONEY, default=Decimal("0"))
    internal_cost = Column(MONEY, default=Decimal("0"))

    created_at = Column(DateTime, default=datetime.now)

    service_order = relationship("ServiceOrder", backref="warranty_claims")
    customer = relationship("Customer", backref="warranty_claims")


class Sparepart(Base):
    """Stok sparepart toko. Satu-satunya sumber halaman Sparepart."""

    __tablename__ = "spareparts"

    id = Column(Integer, primary_key=True, index=True)
    kategori = Column(String(60))
    merek = Column(String(60))
    jenis = Column(String(120), nullable=False)
    device = Column(String(120))
    qty = Column(Integer, default=0)
    harga_beli = Column(MONEY, default=Decimal("0"))
    harga_jual = Column(MONEY, default=Decimal("0"))
    tanggal = Column(Date)
    created_at = Column(DateTime, default=datetime.now)

    batches = relationship("SparepartBatch", back_populates="sparepart", cascade="all, delete-orphan")
    sale_items = relationship("PartSaleItem", back_populates="sparepart")
    order_parts = relationship("ServiceOrderPart", back_populates="sparepart")


class SparepartBatch(Base):
    """P2-15 — Batch Lot stok sparepart (FIFO inventory tracking).

    Setiap pengadaan barang masuk dicatat sebagai batch tersendiri.
    Pengurangan stok memprioritaskan batch tertua dengan qty_sisa > 0.
    """
    __tablename__ = "sparepart_batches"

    id = Column(Integer, primary_key=True, index=True)
    sparepart_id = Column(Integer, ForeignKey("spareparts.id"), nullable=False, index=True)
    supplier = Column(String(120))
    harga_beli = Column(MONEY, default=Decimal("0"), nullable=False)
    harga_jual = Column(MONEY, default=Decimal("0"), nullable=False)
    qty_masuk = Column(Integer, nullable=False, default=0)
    qty_sisa = Column(Integer, nullable=False, default=0)
    tanggal_masuk = Column(Date, default=date.today)
    status = Column(String(20), default="ACTIVE", index=True)  # ACTIVE | DEPLETED
    created_at = Column(DateTime, default=datetime.now)

    sparepart = relationship("Sparepart", back_populates="batches")
    sale_items = relationship("PartSaleItem", back_populates="batch")
    order_parts = relationship("ServiceOrderPart", back_populates="batch")


class PartSale(Base):
    """P2-15 — Transaksi penjualan sparepart / aksesoris langsung (Kasir POS)."""
    __tablename__ = "part_sales"

    id = Column(Integer, primary_key=True, index=True)
    no_transaksi = Column(String(50), unique=True, index=True, nullable=False)
    customer_name = Column(String(120), default="Pelanggan Umum")
    customer_phone = Column(String(60))
    total_omzet = Column(MONEY, default=Decimal("0"), nullable=False)
    total_modal = Column(MONEY, default=Decimal("0"), nullable=False)
    laba = Column(MONEY, default=Decimal("0"), nullable=False)
    payment_method = Column(String(30), default="CASH")
    kasir_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    oleh = Column(String(80))
    created_at = Column(DateTime, default=datetime.now, index=True)

    items = relationship("PartSaleItem", back_populates="part_sale", cascade="all, delete-orphan")
    kasir = relationship("User")


class PartSaleItem(Base):
    """P2-15 — Rincian item per transaksi penjualan part langsung."""
    __tablename__ = "part_sale_items"

    id = Column(Integer, primary_key=True, index=True)
    part_sale_id = Column(Integer, ForeignKey("part_sales.id"), nullable=False, index=True)
    sparepart_id = Column(Integer, ForeignKey("spareparts.id"), nullable=False, index=True)
    batch_id = Column(Integer, ForeignKey("sparepart_batches.id"), nullable=True, index=True)
    qty = Column(Integer, nullable=False, default=1)
    harga_beli = Column(MONEY, default=Decimal("0"), nullable=False)
    harga_jual = Column(MONEY, default=Decimal("0"), nullable=False)
    subtotal = Column(MONEY, default=Decimal("0"), nullable=False)

    part_sale = relationship("PartSale", back_populates="items")
    sparepart = relationship("Sparepart", back_populates="sale_items")
    batch = relationship("SparepartBatch", back_populates="sale_items")


class KasEntry(Base):
    """Jurnal kas manual: pemasukan non-servis (cth. jual second, saldo awal)
    dan penyesuaian kas yang tidak punya rumah di service_orders/expenses.
    BUKAN duplikat order/expense — hanya untuk arus kas di luar keduanya."""

    __tablename__ = "kas_entries"

    id = Column(Integer, primary_key=True, index=True)
    jenis = Column(String(10), nullable=False)  # Masuk | Keluar
    kategori = Column(String(60), nullable=False)  # 'Saldo Awal' = modal awal (dihitung lintas periode)
    keterangan = Column(String(200), nullable=False)
    nominal = Column(MONEY, nullable=False, default=Decimal("0"))
    tanggal = Column(Date)  # info tanggal kas
    created_at = Column(DateTime, default=datetime.now)
    # Owner Cash Model v4 / SSOT-7: Laci = "Kas Aset Kecil (Laci)",
    # Aset = "Kas Aset Besar (Pengelola)". Dua posisi dari MASTER KAS yang sama.
    layer = Column(String(20), nullable=False, default="LACI", index=True)
    # Saldo layer terkait SESUDAH baris ini tercatat (jejak audit, bukan sumber hitung).
    saldo_setelah = Column(MONEY)
    # P2-15 / Cash Model v4: asal mutasi. Dipakai untuk (a) idempotensi mutasi
    # turunan lewat ref_type/ref_id dan (b) mencegah double count dengan Buku Kas.
    sumber = Column(String(30), nullable=False, default="MANUAL", index=True)
    # Pelaku mutasi posisi Master Kas (audit).
    oleh = Column(String(120))
    ref_type = Column(String(30), index=True)
    ref_id = Column(Integer, index=True)


class StatusHistory(Base):
    """Jejak perubahan status servis (FINAL LOCK §10). Append-only."""

    __tablename__ = "status_history"

    id = Column(Integer, primary_key=True, index=True)
    service_order_id = Column(Integer, ForeignKey("service_orders.id"), nullable=False, index=True)
    dari_status = Column(String(30))  # NULL = awal (saat receive)
    ke_status = Column(String(30), nullable=False)
    oleh = Column(String(60))
    waktu = Column(DateTime, default=datetime.now, index=True)
    catatan = Column(Text)

    service_order = relationship("ServiceOrder", back_populates="status_history")


class JournalEntry(Base):
    """Journal audit append-only lintas domain (P2-03).

    Infrastruktur murni: tidak memuat business rule. Monetary opsional dan
    bertipe Numeric/Decimal (P2-02 / Q10). Tidak memakai ForeignKey ke tabel
    domain supaya jurnal tetap utuh dan tidak pernah terhapus cascade.
    """

    __tablename__ = "journal_entries"

    id = Column(Integer, primary_key=True, index=True)
    ts = Column(DateTime, default=datetime.now, index=True)
    domain = Column(String(30), nullable=False, index=True)
    event = Column(String(60), nullable=False, index=True)
    entity_type = Column(String(40), index=True)
    entity_id = Column(Integer, index=True)
    ref_type = Column(String(30))
    ref_code = Column(String(80), index=True)
    amount = Column(MONEY)
    actor = Column(String(60), index=True)
    source = Column(String(20), default="SYSTEM")
    details = Column(JSON)


class ExpensePeriod(Base):
    """Beban beku per periode kas (SSOT-4 / OD-001).

    Snapshot satu kali per periode: mengubah/menambah expenses setelah periode
    dibekukan TIDAK mengubah beban periode tersebut (idempotent, historis utuh).
    """

    __tablename__ = "expense_periods"

    id = Column(Integer, primary_key=True, index=True)
    periode = Column(String(20), nullable=False, index=True)
    kategori = Column(String(40), index=True)
    nama_beban = Column(String(200))
    nilai = Column(MONEY, nullable=False, default=Decimal("0"))
    dibebankan_pada = Column(DateTime, default=datetime.now)
    expense_id = Column(Integer, index=True)


class Distribution(Base):
    """P2-07 / SSOT-6: Distribusi 10% Karyawan | 30% Pengelola | 30% Investor |
    30% Hak Kas Aset — dipicu Tutup Kas, bukan CTO.

    Satu baris per periode kas (idempotent). `kas_aset_hak` dicatat sebagai
    mutasi Kas Aset (layer KAS_ASET, P2-06); 70% cash-out dieksekusi saat
    pengeluaran nyata (P2-08), bukan mengurangi saldo di sini.
    """

    __tablename__ = "distributions"

    id = Column(Integer, primary_key=True, index=True)
    periode = Column(String(20), nullable=False, unique=True, index=True)
    kas_period_id = Column(Integer, index=True)
    laba_bersih = Column(MONEY, nullable=False, default=Decimal("0"))
    karyawan_pct = Column(MONEY, nullable=False, default=Decimal("0.10"))
    pengelola_pct = Column(MONEY, nullable=False, default=Decimal("0.30"))
    investor_pct = Column(MONEY, nullable=False, default=Decimal("0.30"))
    kas_aset_pct = Column(MONEY, nullable=False, default=Decimal("0.30"))
    bonus_karyawan = Column(MONEY, nullable=False, default=Decimal("0"))
    pengelola = Column(MONEY, nullable=False, default=Decimal("0"))
    investor = Column(MONEY, nullable=False, default=Decimal("0"))
    hak_kas_aset = Column(MONEY, nullable=False, default=Decimal("0"))
    cash_out = Column(MONEY, nullable=False, default=Decimal("0"))
    # P2-08: id baris kas_entries (layer LACI) untuk eksekusi cash-out 70%.
    # NULL = belum dieksekusi. Menjaga Tutup Kas tidak dobel bayar.
    cash_out_entry_id = Column(Integer, index=True)
    # P2-08: id baris 'Saldo Awal' penyesuaian Laci = uang fisik (bila ada).
    laci_adjust_entry_id = Column(Integer, index=True)
    oleh = Column(String(120))
    created_at = Column(DateTime, default=datetime.now, index=True)


class Refund(Base):
    """P2-10 — Refund (Q9 / OD-016 / FIX-17b). TIGA jenis, TIGA sumber dana.

    - `DP`             : authority Admin/Kasir, dana dari LACI (Kas Perputaran);
    - `GARANSI`        : authority Admin, dana dari KAS_ASET (pre-check);
    - `FAILED_CANCEL`  : authority Admin/Kasir, dana dari LACI (bukan refund garansi).

    Q9: **satu efek finansial per refund** — `kas_entry_id` menunjuk satu-satunya
    baris kas yang dihasilkan. Tidak ada debit ganda.
    Append-only: tidak ada helper update/delete (Q14).
    """

    __tablename__ = "refunds"

    id = Column(Integer, primary_key=True, index=True)
    refund_no = Column(String(50), unique=True, index=True, nullable=False)
    jenis = Column(String(20), nullable=False, index=True)  # DP | GARANSI | FAILED_CANCEL
    service_order_id = Column(Integer, ForeignKey("service_orders.id"), index=True)
    warranty_claim_id = Column(Integer, ForeignKey("warranty_claims.id"), index=True)
    nominal = Column(MONEY, nullable=False, default=Decimal("0"))
    sumber_dana = Column(String(20), nullable=False)  # LACI | KAS_ASET
    alasan = Column(Text)
    kas_entry_id = Column(Integer, index=True)  # SATU-satunya efek saldo
    oleh = Column(String(120))
    created_at = Column(DateTime, default=datetime.now, index=True)

    service_order = relationship("ServiceOrder")
    warranty_claim = relationship("WarrantyClaim")


class ExpenseDebtPeriod(Base):
    """P2-11 / SSOT-8: hasil proses defisit Beban satu periode kas.

    Alur LOCKED (Q8/Q18): defisit terhadap Beban → Kas Aset menutup (sepenuhnya
    yang bisa) → sisa = Hutang Beban (carry forward sampai diselesaikan).

    `hutang_awal` hanya informatif (saldo hutang yang terbawa dari periode
    sebelumnya); tidak ada baris/konsep hutang di Buku Kas.
    """

    __tablename__ = "expense_debt_periods"

    id = Column(Integer, primary_key=True, index=True)
    periode = Column(String(20), nullable=False, unique=True, index=True)
    kas_period_id = Column(Integer, index=True)
    beban = Column(MONEY, nullable=False, default=Decimal("0"))
    laba_kotor = Column(MONEY, nullable=False, default=Decimal("0"))
    defisit = Column(MONEY, nullable=False, default=Decimal("0"))
    cover_kas_aset = Column(MONEY, nullable=False, default=Decimal("0"))
    hutang_baru = Column(MONEY, nullable=False, default=Decimal("0"))
    hutang_awal = Column(MONEY, nullable=False, default=Decimal("0"))
    hutang_akhir = Column(MONEY, nullable=False, default=Decimal("0"))
    oleh = Column(String(120))
    created_at = Column(DateTime, default=datetime.now, index=True)


class ExpenseDebtEntry(Base):
    """P2-11: ledger Hutang Beban (append-only). TIDAK bagian dari Buku Kas."""

    __tablename__ = "expense_debt_entries"

    id = Column(Integer, primary_key=True, index=True)
    tipe = Column(String(20), nullable=False, index=True)  # HUTANG | PELUNASAN
    nominal = Column(MONEY, nullable=False, default=Decimal("0"))
    saldo_setelah = Column(MONEY, nullable=False, default=Decimal("0"))
    periode = Column(String(20), index=True)   # periode asal hutang / pelunasan
    expense_debt_period_id = Column(Integer, index=True)
    kas_entry_id = Column(Integer, index=True)  # mutasi Kas Aset (bukan Buku Kas)
    oleh = Column(String(120))
    created_at = Column(DateTime, default=datetime.now, index=True)


class StockMove(Base):
    """P2-12 — jurnal pergerakan stok (ADAPT dari `stock_moves` Project A).

    AKSI:
      MASUK  — barang masuk (pembelian/pemasok stok), qty bertambah;
      PAKAI  — pemakaian sparepart untuk unit (decrement ATOMIK bila qty cukup);
      BATAL  — pembatalan pemakaian (qty kembali; idempoten).

    Append-only (Q14): tidak ada update/hapus baris movement.
    `qty_sebelum`/`qty_sesudah`/`selisih` menyimpan jejak, `pakai_move_id`
    menunjuk movement PAKAI yang dibatalkan (agar restore tidak dobel).
    """

    __tablename__ = "stock_moves"

    id = Column(Integer, primary_key=True, index=True)
    sparepart_id = Column(Integer, ForeignKey("spareparts.id"), nullable=False, index=True)
    aksi = Column(String(20), nullable=False, index=True)  # MASUK | PAKAI | BATAL
    qty = Column(Integer, nullable=False)
    qty_sebelum = Column(Integer, nullable=False, default=0)
    qty_sesudah = Column(Integer, nullable=False, default=0)
    selisih = Column(Integer, nullable=False, default=0)
    service_order_id = Column(Integer, ForeignKey("service_orders.id"), index=True)
    service_order_part_id = Column(Integer, index=True)
    pakai_move_id = Column(Integer, index=True)  # untuk BATAL: movement asal
    keterangan = Column(String(200))
    oleh = Column(String(120))
    waktu = Column(DateTime, default=datetime.now, index=True)

    sparepart = relationship("Sparepart")


class ServiceOrderPart(Base):
    """P2-12 — pemakaian sparepart per unit (ADAPT dari `servis_part` Project A).

    Memotong link part ↔ ServiceOrder. Status pemakaian: DIPAKAI | DIBATALKAN.
    """

    __tablename__ = "service_order_parts"

    id = Column(Integer, primary_key=True, index=True)
    service_order_id = Column(Integer, ForeignKey("service_orders.id"), nullable=False, index=True)
    sparepart_id = Column(Integer, ForeignKey("spareparts.id"), nullable=True, index=True)
    batch_id = Column(Integer, ForeignKey("sparepart_batches.id"), nullable=True, index=True)
    part_name = Column(String(150), nullable=True)
    qty = Column(Integer, nullable=False, default=1)
    modal_beli = Column(MONEY, default=Decimal("0"), nullable=False)
    harga_satuan = Column(MONEY, default=Decimal("0"))
    is_external = Column(Boolean, default=False, nullable=False, server_default="0")
    note = Column(String(200), nullable=True)
    status = Column(String(20), nullable=False, default="DIPAKAI", index=True)
    stock_move_id = Column(Integer, index=True)      # movement PAKAI
    cancel_move_id = Column(Integer, index=True)    # movement BATAL
    oleh = Column(String(120))
    created_at = Column(DateTime, default=datetime.now, index=True)

    service_order = relationship("ServiceOrder", back_populates="order_parts")
    sparepart = relationship("Sparepart", back_populates="order_parts")
    batch = relationship("SparepartBatch", back_populates="order_parts")


class Notification(Base):
    """P2-13 — log notifikasi (WA/Telegram). Anti-duplikat berbasis jendela waktu.

    Baris ini adalah OUTBOX + audit: notifikasi dicatat di sini dan di journal
    (P2-03) **sebelum** pengiriman. Pengiriman ke provider eksternal TIDAK terjadi
    saat provider nonaktif (default) — termasuk saat production test.
    """

    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    event = Column(String(40), nullable=False, index=True)
    ref_type = Column(String(40))
    ref_code = Column(String(60), index=True)
    dedup_key = Column(String(160), nullable=False, index=True)
    provider = Column(String(20), nullable=False, default="TELEGRAM")
    tujuan = Column(String(200))
    pesan = Column(Text)
    status = Column(String(20), nullable=False, default="DIANTREKAN", index=True)
    actor = Column(String(120))
    created_at = Column(DateTime, default=datetime.now, index=True)


class IdempotencyRecord(Base):
    """P2-14 — catatan idempotency untuk endpoint money/closing.

    Menyimpan key + hash request + response, sehingga retry dengan key yang sama
    mengembalikan hasil pertama (tanpa menggandakan efek). Append-only: record
    tidak diedit/delete oleh alur request (Q14).
    """

    __tablename__ = "idempotency_keys"

    id = Column(Integer, primary_key=True, index=True)
    scope = Column(String(60), nullable=False, index=True)
    key = Column(String(120), nullable=False, index=True)
    request_hash = Column(String(64), nullable=False)
    status = Column(String(20), nullable=False, default="IN_PROGRESS", index=True)
    response_json = Column(Text)
    actor = Column(String(120))
    created_at = Column(DateTime, default=datetime.now, index=True)
