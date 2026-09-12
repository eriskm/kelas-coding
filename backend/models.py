"""SQLAlchemy models (database tables)."""
from datetime import datetime

from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    DateTime,
    ForeignKey,
    Text,
    Date,
    JSON,
)
from sqlalchemy.orm import relationship

from database import Base


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
    created_at = Column(DateTime, default=datetime.utcnow)


class AuthToken(Base):
    __tablename__ = "auth_tokens"

    id = Column(Integer, primary_key=True, index=True)
    token = Column(String(64), unique=True, index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)

    user = relationship("User")


class Customer(Base):
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    phone = Column(String(30))
    email = Column(String(120))
    address = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    service_orders = relationship("ServiceOrder", back_populates="customer")


class ServiceOrder(Base):
    __tablename__ = "service_orders"

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
    status = Column(String(30), default="RECEIVED")
    estimate = Column(Float, default=0)
    payment = Column(Float, default=0)
    service_date = Column(Date, default=datetime.utcnow().date)
    # Syarat CASH: harga final + modal part dicatat; cash_date = awal masa garansi.
    # warranty_months: 1/3/6 bulan pilihan toko, 0 = tidak garansi, NULL = legacy (30 hari).
    # Modal (part/jasa/lainnya) = atribut transaksi (diisi di Update Data Servis).
    # cash_at = jam penetapan CASH (scope periode kas 16:00; cash_date hanya info tanggal).
    final_price = Column(Float)
    part_cost = Column(Float, default=0)
    modal_jasa = Column(Float, default=0)
    modal_lainnya = Column(Float, default=0)
    cash_date = Column(Date)
    cash_at = Column(DateTime)
    warranty_months = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)

    customer = relationship("Customer", back_populates="service_orders")
    payments = relationship("Payment", back_populates="service_order", cascade="all, delete-orphan")


class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, index=True)
    service_order_id = Column(Integer, ForeignKey("service_orders.id"), nullable=False)
    amount = Column(Float, nullable=False)
    method = Column(String(30), default="CASH")
    note = Column(String(200))
    created_at = Column(DateTime, default=datetime.utcnow)

    service_order = relationship("ServiceOrder", back_populates="payments")


class Expense(Base):
    """Beban toko (Gaji/Operasional/lainnya). Dicatat per periode kas.
    Sumber: popup Beban Harian (dulu localStorage) dan/atau input Keuangan.
    """

    __tablename__ = "expenses"

    id = Column(Integer, primary_key=True, index=True)
    kategori = Column(String(40), nullable=False, index=True)  # Gaji | Operasional | ...
    uraian = Column(String(200), nullable=False)
    nilai = Column(Float, nullable=False, default=0)
    tanggal = Column(Date)  # info tanggal beban
    created_at = Column(DateTime, default=datetime.utcnow)


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
    created_at = Column(DateTime, default=datetime.utcnow)


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

    # Biaya (customer bisa Rp0 bila ditanggung garansi; internal tetap dicatat)
    customer_cost = Column(Float, default=0)
    internal_cost = Column(Float, default=0)

    created_at = Column(DateTime, default=datetime.utcnow)

    service_order = relationship("ServiceOrder", backref="warranty_claims")
    customer = relationship("Customer", backref="warranty_claims")
