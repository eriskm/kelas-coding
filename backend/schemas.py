"""Pydantic schemas (request/response models)."""
from datetime import datetime, date
from decimal import Decimal
from money import MoneyOut
from pydantic import BaseModel, ConfigDict
from typing import Optional, List


# ---------- Customer ----------
class CustomerBase(BaseModel):
    name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None


class CustomerCreate(CustomerBase):
    pass


class CustomerUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None


class CustomerOut(CustomerBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime


class CustomerSummary(BaseModel):
    id: int
    name: str
    phone: Optional[str] = None
    last_device: Optional[str] = None
    last_action: Optional[str] = None
    last_price: Optional[MoneyOut] = None
    total_servis: int
    last_at: Optional[datetime] = None


class CustomerSummaryPage(BaseModel):
    total: int
    page: int
    limit: int
    total_pages: int
    items: List[CustomerSummary]


# ---------- ServiceOrder ----------
class ServiceOrderBase(BaseModel):
    no_servis: str
    customer_id: int
    device: str
    brand: Optional[str] = None
    model: Optional[str] = None
    damagetype: Optional[str] = None
    device_password: Optional[str] = None
    imei: Optional[str] = None
    check_fisik: Optional[List[str]] = None
    check_len: Optional[List[str]] = None
    repair_plan: Optional[str] = None
    technician: Optional[str] = None
    status: Optional[str] = "DITERIMA"
    unit_status: Optional[str] = "DI TOKO"
    taken_at: Optional[datetime] = None
    estimate: Optional[MoneyOut]
    payment: Optional[MoneyOut]
    service_date: Optional[date] = None
    final_price: Optional[MoneyOut] = None
    part_cost: Optional[MoneyOut] = None
    modal_jasa: Optional[MoneyOut] = None
    modal_lainnya: Optional[MoneyOut] = None
    # laba_bersih = derive backend (diisi router, bukan input user).
    laba_bersih: Optional[MoneyOut]
    lunas_date: Optional[date] = None
    lunas_at: Optional[datetime] = None
    warranty_months: Optional[int] = None
    # Ringkasan pembayaran (derive, diisi router — bukan kolom DB).
    payment_status: Optional[str] = None
    total_bayar: Optional[MoneyOut] = None
    sisa: Optional[MoneyOut] = None


class ServiceReceiveIn(BaseModel):
    """Payload lengkap pendaftaran unit servis baru."""
    customer_name: str
    customer_phone: Optional[str] = None
    device: str
    device_password: Optional[str] = None
    imei: Optional[str] = None
    check_fisik: Optional[List[str]] = None
    check_len: Optional[List[str]] = None
    damagetype: Optional[str] = None
    repair_plan: Optional[str] = None
    estimate: Optional[MoneyOut]
    dp: Optional[MoneyOut]
    technician: Optional[str] = None
    status: Optional[str] = "DITERIMA"
    final_price: Optional[MoneyOut] = None  # wajib terdefinisi (boleh 0) untuk path TUNGGU
    initial_path: Optional[str] = None  # TITIP | PERBAIKAN | SPAREPART | TUNGGU


class ServiceOrderCreate(ServiceOrderBase):
    pass


class ServiceOrderUpdate(BaseModel):
    customer_id: Optional[int] = None
    device: Optional[str] = None
    brand: Optional[str] = None
    model: Optional[str] = None
    damagetype: Optional[str] = None
    device_password: Optional[str] = None
    imei: Optional[str] = None
    check_fisik: Optional[List[str]] = None
    check_len: Optional[List[str]] = None
    repair_plan: Optional[str] = None
    technician: Optional[str] = None
    status: Optional[str] = None
    status_note: Optional[str] = None  # catatan wajib untuk GAGAL/BATAL/lompat-mundur/koreksi
    estimate: Optional[MoneyOut] = None
    payment: Optional[MoneyOut] = None
    final_price: Optional[MoneyOut] = None
    part_cost: Optional[MoneyOut] = None
    modal_jasa: Optional[MoneyOut] = None
    modal_lainnya: Optional[MoneyOut] = None
    warranty_months: Optional[int] = None


class ServiceOrderOut(ServiceOrderBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    customer: Optional[CustomerOut] = None


class ServiceOrderList(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    no_servis: str
    customer_id: int
    device: str
    brand: Optional[str] = None
    model: Optional[str] = None
    damagetype: Optional[str] = None
    device_password: Optional[str] = None
    imei: Optional[str] = None
    check_fisik: Optional[List[str]] = None
    check_len: Optional[List[str]] = None
    repair_plan: Optional[str] = None
    technician: Optional[str] = None
    status: str
    estimate: MoneyOut
    payment: MoneyOut
    service_date: Optional[date] = None
    final_price: Optional[MoneyOut] = None
    part_cost: Optional[MoneyOut] = None
    modal_jasa: Optional[MoneyOut] = None
    modal_lainnya: Optional[MoneyOut] = None
    laba_bersih: Optional[MoneyOut] = None
    lunas_date: Optional[date] = None
    lunas_at: Optional[datetime] = None
    warranty_months: Optional[int] = None
    unit_status: Optional[str] = None
    taken_at: Optional[datetime] = None
    payment_status: Optional[str] = None
    total_bayar: Optional[MoneyOut] = None
    sisa: Optional[MoneyOut] = None
    created_at: datetime
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None


class ServiceOrderPage(BaseModel):
    total: int
    page: int
    limit: int
    total_pages: int
    items: List[ServiceOrderList]


# ---------- Payment ----------
class PaymentBase(BaseModel):
    service_order_id: int
    kind: Optional[str] = "PELUNASAN"  # DP | PELUNASAN
    amount: MoneyOut
    method: Optional[str] = "CASH"
    note: Optional[str] = None


class PaymentCreate(PaymentBase):
    pass


class PaymentOut(PaymentBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime


class PaymentHistoryOut(BaseModel):
    kewajiban: MoneyOut
    total_bayar: MoneyOut
    sisa: MoneyOut
    payment_status: str
    items: List[PaymentOut]


# ---------- StatusHistory ----------
class StatusHistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    service_order_id: int
    dari_status: Optional[str] = None
    ke_status: str
    oleh: Optional[str] = None
    waktu: Optional[datetime] = None
    catatan: Optional[str] = None


# ---------- Expense (beban toko per periode kas) ----------
class ExpenseCreate(BaseModel):
    kategori: str  # Gaji | Operasional | ...
    uraian: str
    nilai: Optional[MoneyOut]
    tanggal: Optional[date] = None
    # FIN-MIRROR: beban permanen (default True = sama dengan Proyek A `beban`).
    # False = beban satu-off, hanya periode di mana moment-nya jatuh.
    recurring: Optional[bool] = None


class ExpenseUpdate(BaseModel):
    kategori: Optional[str] = None
    uraian: Optional[str] = None
    nilai: Optional[MoneyOut] = None
    tanggal: Optional[date] = None
    # FIN-MIRROR: lihat ExpenseCreate.recurring.
    recurring: Optional[bool] = None


class ExpenseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    kategori: str
    uraian: str
    nilai: MoneyOut
    tanggal: Optional[date] = None
    created_at: datetime
    # FIN-MIRROR: true = dipotong setiap periode (perilaku Proyek A).
    recurring: bool = True


class ExpensePage(BaseModel):
    total: int
    page: int
    limit: int
    total_pages: int
    items: List[ExpenseOut]


# ---------- KasPeriod (minimal fondasi; close flow tahap Tutup Kas) ----------
class KasPeriodOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    start_at: datetime
    end_at: datetime
    status: str
    closed_by: Optional[str] = None
    closed_at: Optional[datetime] = None
    created_at: datetime


# ---------- WarrantyClaim ----------
# Status proses: MASUK|VERIFIKASI|CEK|DITERIMA|DITOLAK|PROSES|SELESAI|DITUTUP
# Status garansi: VALID|EXPIRED (periode) — bukan keputusan claim.
# Hasil claim: BELUM_DIPUTUSKAN|DITERIMA|DITOLAK — bukan status proses.
CLAIM_STATUSES = ["MASUK", "VERIFIKASI", "CEK", "DITERIMA", "DITOLAK", "PROSES", "SELESAI", "DITUTUP"]
WARRANTY_STATUSES = ["VALID", "EXPIRED"]
CLAIM_DECISIONS = ["BELUM_DIPUTUSKAN", "DITERIMA", "DITOLAK"]
# P2-09: resolusi klaim. Uang untuk REFUND = tahap P2-10.
CLAIM_RESOLUSI = ["REPAIR", "REPLACE", "REFUND"]


class ClaimReceiveIn(BaseModel):
    """Buat record claim baru dari servis asal (tidak mengubah servis lama)."""
    service_order_id: int
    complaint: Optional[str] = None
    physical_condition: Optional[str] = None
    completeness: Optional[str] = None
    cs_note: Optional[str] = None
    check_fisik: Optional[List[str]] = None
    check_len: Optional[List[str]] = None
    warranty_days: Optional[int] = 30
    received_by: Optional[str] = None
    claim_date: Optional[date] = None


class ClaimUpdate(BaseModel):
    complaint: Optional[str] = None
    physical_condition: Optional[str] = None
    completeness: Optional[str] = None
    cs_note: Optional[str] = None
    check_fisik: Optional[List[str]] = None
    check_len: Optional[List[str]] = None
    inspection_result: Optional[str] = None
    cause: Optional[str] = None
    matches_previous: Optional[str] = None
    drop_indication: Optional[int] = None
    liquid_indication: Optional[int] = None
    third_party_work: Optional[int] = None
    action_needed: Optional[str] = None
    tech_note: Optional[str] = None
    technician: Optional[str] = None
    tech_recommendation: Optional[str] = None
    decision: Optional[str] = None
    reject_reason: Optional[str] = None
    claim_status: Optional[str] = None
    customer_cost: Optional[MoneyOut] = None
    internal_cost: Optional[MoneyOut] = None
    # P2-09
    resolusi: Optional[str] = None


class ClaimOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    claim_no: str
    service_order_id: int
    customer_id: int
    claim_date: Optional[date] = None
    received_by: Optional[str] = None
    warranty_days: Optional[int] = None
    warranty_start: Optional[date] = None
    warranty_end: Optional[date] = None
    warranty_status: Optional[str] = None
    complaint: Optional[str] = None
    physical_condition: Optional[str] = None
    completeness: Optional[str] = None
    cs_note: Optional[str] = None
    check_fisik: Optional[List[str]] = None
    check_len: Optional[List[str]] = None
    inspection_result: Optional[str] = None
    cause: Optional[str] = None
    matches_previous: Optional[str] = None
    drop_indication: Optional[int] = None
    liquid_indication: Optional[int] = None
    third_party_work: Optional[int] = None
    action_needed: Optional[str] = None
    tech_note: Optional[str] = None
    technician: Optional[str] = None
    tech_recommendation: Optional[str] = None
    decision: Optional[str] = None
    reject_reason: Optional[str] = None
    claim_status: Optional[str] = None
    customer_cost: Optional[MoneyOut] = None
    internal_cost: Optional[MoneyOut] = None
    # P2-09
    resolusi: Optional[str] = None
    origin_payment_status: Optional[str] = None
    origin_warranty_months: Optional[int] = None
    created_at: datetime
    # Info servis asal (read-only, untuk tampilan tanpa join tambahan)
    origin_no_servis: Optional[str] = None
    origin_device: Optional[str] = None
    origin_damage: Optional[str] = None
    origin_plan: Optional[str] = None
    origin_service_date: Optional[date] = None
    origin_technician: Optional[str] = None
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    origin_imei: Optional[str] = None


class ClaimPage(BaseModel):
    total: int
    page: int
    limit: int
    total_pages: int
    items: List[ClaimOut]


class ClaimLookupItem(BaseModel):
    """Hasil pencarian servis asal + validasi garansi + histori claim."""
    id: int
    no_servis: str
    service_date: Optional[date] = None
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    device: Optional[str] = None
    imei: Optional[str] = None
    damagetype: Optional[str] = None
    repair_plan: Optional[str] = None
    technician: Optional[str] = None
    status: Optional[str] = None
    warranty_days: int = 30
    warranty_months: Optional[int] = None
    warranty_start: Optional[date] = None
    warranty_end: Optional[date] = None
    warranty_status: str = "VALID"
    claim_count: int = 0
    claims: List[dict] = []


# ---------- Dashboard Overview ----------
class OverviewItem(BaseModel):
    label: str
    value: MoneyOut


class DashboardOverview(BaseModel):
    omset: MoneyOut
    laba_kotor: MoneyOut
    total_beban: MoneyOut
    laba_bersih: MoneyOut
    target_gaji: MoneyOut
    insight: List[dict]
    star_cards: List[dict]


# ---------- KasPeriod detail (arsip tutup kas) ----------
class KasPeriodDetailOut(KasPeriodOut):
    snapshot: Optional[str] = None


class KasCloseIn(BaseModel):
    cash_counted: Optional[MoneyOut] = None  # hasil hitung uang laci (audit kas)
    # P2-08: target periode tertentu (default periode OPEN aktif). Memungkinkan
    # eksekusi kedua pada periode sama dijawab 409, bukan menutup periode baru.
    kas_period_id: Optional[int] = None


# ---------- KasEntry (jurnal kas manual) ----------
class KasEntryCreate(BaseModel):
    jenis: str  # Masuk | Keluar
    kategori: str
    keterangan: str
    nominal: Optional[MoneyOut]
    tanggal: Optional[date] = None
    # P2-06 / SSOT-7: opsional; kosong = Kas Perputaran (Laci).
    layer: Optional[str] = None


class KasEntryUpdate(BaseModel):
    jenis: Optional[str] = None
    kategori: Optional[str] = None
    keterangan: Optional[str] = None
    nominal: Optional[MoneyOut] = None
    tanggal: Optional[date] = None


class KasEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    jenis: str
    kategori: str
    keterangan: str
    nominal: MoneyOut
    tanggal: Optional[date] = None
    created_at: datetime
    # P2-06 / SSOT-7
    layer: str = "LACI"
    saldo_setelah: Optional[MoneyOut] = None


class KasEntryPage(BaseModel):
    total: int
    page: int
    limit: int
    total_pages: int
    items: List[KasEntryOut]


class KasAsetMutasiIn(BaseModel):
    """Input mutasi Kas Aset (injection / pengeluaran aktual).

    v4 #6: `posisi` wajib untuk injection — LACI (Kas Aset Kecil) atau
    KAS_ASET (Kas Aset Besar / Pengelola).
    """
    kategori: Optional[str] = None
    keterangan: str
    nominal: MoneyOut
    tanggal: Optional[date] = None
    posisi: Optional[str] = None  # LACI | KAS_ASET


class KasAsetTransferIn(BaseModel):
    """v4 #5: transfer fisik Laci <-> Aset (Master Kas tetap)."""
    dari: str
    ke: str
    nominal: MoneyOut
    keterangan: str
    ref_type: Optional[str] = None
    ref_id: Optional[str] = None


class KasRiwayatItem(BaseModel):
    tgl: Optional[str] = None
    jenis: str
    kategori: Optional[str] = None
    ket: Optional[str] = None
    nominal: MoneyOut
    saldo: MoneyOut
    source: str  # order | expense | manual
    ref_id: Optional[int] = None


class KasRiwayatPage(BaseModel):
    total: int
    page: int
    limit: int
    total_pages: int
    opening: MoneyOut
    #: Total SELURUH baris yang lolos filter (bukan hanya halaman ini) supaya
    #: footer tabel bisa mencocokkan angkanya dengan kartu ringkasanConditions
    #: Kas. Tanpa ini user hanya melihat total satu halaman dan mengira rumusnya
    #: salah saat halaman > 1.
    total_masuk: MoneyOut = Decimal("0")
    total_keluar: MoneyOut = Decimal("0")
    items: List[KasRiwayatItem]


# ---------- Sparepart ----------
class SparepartCreate(BaseModel):
    kategori: Optional[str] = None
    merek: Optional[str] = None
    jenis: str
    device: Optional[str] = None
    qty: Optional[int] = 0
    harga_beli: Optional[MoneyOut]
    harga_jual: Optional[MoneyOut]
    tanggal: Optional[date] = None


class SparepartUpdate(BaseModel):
    kategori: Optional[str] = None
    merek: Optional[str] = None
    jenis: Optional[str] = None
    device: Optional[str] = None
    qty: Optional[int] = None
    harga_beli: Optional[MoneyOut] = None
    harga_jual: Optional[MoneyOut] = None
    tanggal: Optional[date] = None


class SparepartOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    kategori: Optional[str] = None
    merek: Optional[str] = None
    jenis: str
    device: Optional[str] = None
    qty: int
    harga_beli: MoneyOut
    harga_jual: MoneyOut
    tanggal: Optional[date] = None
    created_at: datetime


class SparepartPage(BaseModel):
    total: int
    page: int
    limit: int
    total_pages: int
    items: List[SparepartOut]


# ---------- Refund (P2-10) ----------
REFUND_JENIS = ["DP", "GARANSI", "FAILED_CANCEL"]


class RefundDPIn(BaseModel):
    """Refund DP: nominal berbasis DP diterima (default = seluruh DP)."""
    service_order_id: int
    nominal: Optional[MoneyOut] = None
    alasan: Optional[str] = None


class RefundGaransiIn(BaseModel):
    """Refund Klaim Garansi: nominal kesepakatan; default = biaya pelanggan klaim."""
    warranty_claim_id: int
    nominal: Optional[MoneyOut] = None
    alasan: Optional[str] = None


class RefundFailedCancelIn(BaseModel):
    """Failed -> Cancel: dana dari Laci, bukan refund garansi (Q9 titik 3)."""
    service_order_id: int
    nominal: Optional[MoneyOut] = None  # default = DP diterima
    alasan: Optional[str] = None


class RefundOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    refund_no: str
    jenis: str
    service_order_id: Optional[int] = None
    warranty_claim_id: Optional[int] = None
    nominal: MoneyOut
    sumber_dana: str
    alasan: Optional[str] = None
    kas_entry_id: Optional[int] = None
    oleh: Optional[str] = None
    created_at: datetime


class RefundPage(BaseModel):
    total: int
    page: int
    limit: int
    total_pages: int
    items: List[RefundOut]
