"""Dashboard endpoints - data untuk star cards & charts."""
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from dependencies import get_db_session
from models import ServiceOrder, Expense, KasPeriod
import schemas

router = APIRouter(prefix="/api", tags=["dashboard"])

# Batas periode kas (WIB, jam server). Periode TIDAK auto-tutup;
# baris OPEN terakhir selalu dianggap periode aktif.
PERIOD_HOUR = 16


def _period_bounds(now: datetime):
    """Batas [start, end) periode kas yang memuat `now`."""
    start = now.replace(hour=PERIOD_HOUR, minute=0, second=0, microsecond=0)
    if now < start:
        start -= timedelta(days=1)
    return start, start + timedelta(days=1)


def get_active_period(db: Session) -> KasPeriod:
    """Ambil periode OPEN terakhir; bootstrap bila belum ada sama sekali."""
    p = (
        db.query(KasPeriod)
        .filter(KasPeriod.status == "OPEN")
        .order_by(KasPeriod.id.desc())
        .first()
    )
    if p:
        return p
    now = datetime.now()
    start, end = _period_bounds(now)
    p = KasPeriod(start_at=start, end_at=end, status="OPEN")
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _cash_moment(o) -> Optional[datetime]:
    """Jam penetapan CASH untuk scope periode. Legacy tanpa cash_at
    diperlakukan sebagai tengah hari cash_date (asumsi terdokumentasi)."""
    if getattr(o, "cash_at", None):
        return o.cash_at
    if getattr(o, "cash_date", None):
        return datetime(o.cash_date.year, o.cash_date.month, o.cash_date.day, 12, 0, 0)
    if getattr(o, "created_at", None):
        return o.created_at
    return None


def _expense_moment(e) -> Optional[datetime]:
    if getattr(e, "created_at", None):
        return e.created_at
    if getattr(e, "tanggal", None):
        return datetime(e.tanggal.year, e.tanggal.month, e.tanggal.day, 12, 0, 0)
    return None


def compute_finance(db: Session, start: datetime, end: datetime) -> dict:
    """Satu-satunya sumber hitungan keuangan (dipakai overview & kelak Tutup Kas).

    Scope = periode kas aktif. cash_date hanya info, bukan scope.
    """
    orders = db.query(ServiceOrder).filter(ServiceOrder.status == "CASH").all()
    in_orders = []
    for o in orders:
        m = _cash_moment(o)
        if m is not None and start <= m < end:
            in_orders.append(o)

    def num(v):
        try:
            return float(v or 0)
        except (TypeError, ValueError):
            return 0.0

    omset = sum(num(o.final_price if o.final_price not in (None,) else o.estimate) for o in in_orders)
    modal_part = sum(num(o.part_cost) for o in in_orders)
    modal_jasa = sum(num(getattr(o, "modal_jasa", 0)) for o in in_orders)
    modal_lain = sum(num(getattr(o, "modal_lainnya", 0)) for o in in_orders)
    total_modal = modal_part + modal_jasa + modal_lain
    laba_kotor = omset - total_modal

    expenses = db.query(Expense).all()
    in_exp = []
    for e in expenses:
        m = _expense_moment(e)
        if m is not None and start <= m < end:
            in_exp.append(e)
    beban_gaji = sum(num(e.nilai) for e in in_exp if (e.kategori or "").strip().lower() == "gaji")
    beban_ops = sum(num(e.nilai) for e in in_exp if (e.kategori or "").strip().lower() == "operasional")
    beban_lain = sum(num(e.nilai) for e in in_exp if (e.kategori or "").strip().lower() not in ("gaji", "operasional"))
    total_beban = beban_gaji + beban_ops + beban_lain

    cts_target = beban_gaji
    cts_progress = (laba_kotor / cts_target * 100) if cts_target > 0 else (100.0 if laba_kotor > 0 else 0.0)
    cts_ok = bool(laba_kotor >= cts_target) if cts_target > 0 else True

    cto_target = beban_gaji + beban_ops
    cto_progress = (laba_kotor / cto_target * 100) if cto_target > 0 else (100.0 if laba_kotor > 0 else 0.0)
    cto_ok = bool(laba_kotor >= cto_target) if cto_target > 0 else True

    laba_bersih = laba_kotor - total_beban

    # Trigger §8: alokasi TERBENTUK hanya saat CTO tercapai & laba bersih > 0.
    alokasi_ok = bool(cto_ok and laba_bersih > 0)
    if alokasi_ok:
        karyawan = round(laba_bersih * 0.10)
        pengelola = round(laba_bersih * 0.30)
        investor = round(laba_bersih * 0.30)
        kas_aset = round(laba_bersih - karyawan - pengelola - investor)  # sisa pembulatan
    else:
        karyawan = pengelola = investor = kas_aset = 0

    return {
        "n_cash": len(in_orders),
        "omset": omset,
        "modal_part": modal_part,
        "modal_jasa": modal_jasa,
        "modal_lainnya": modal_lain,
        "total_modal": total_modal,
        "laba_kotor": laba_kotor,
        "beban_gaji": beban_gaji,
        "beban_operasional": beban_ops,
        "beban_lainnya": beban_lain,
        "total_beban": total_beban,
        "cts_target": cts_target,
        "cts_progress": round(cts_progress, 2),
        "cts_tercapai": cts_ok,
        "cto_target": cto_target,
        "cto_progress": round(cto_progress, 2),
        "cto_tercapai": cto_ok,
        "laba_bersih": laba_bersih,
        "alokasi_terbentuk": alokasi_ok,
        "alokasi": {
            "karyawan": karyawan,
            "pengelola": pengelola,
            "investor": investor,
            "kas_aset": kas_aset,
        },
    }


@router.get("/period", response_model=schemas.KasPeriodOut)
def get_period(db: Session = Depends(get_db_session)):
    """Periode kas aktif (bootstrap otomatis bila belum ada)."""
    return get_active_period(db)


@router.get("/overview")
def get_overview(db: Session = Depends(get_db_session)):
    """Data untuk star cards + insight. Finansial = agregat periode kas aktif."""
    period = get_active_period(db)
    fin = compute_finance(db, period.start_at, period.end_at)

    orders = db.query(ServiceOrder).all()
    total = len(orders)
    done = sum(1 for o in orders if o.status == "COMPLETED")
    active = sum(1 for o in orders if o.status in ("REPAIR", "QC", "RECEIVED", "DIAGNOSIS"))
    pending = sum(1 for o in orders if o.status in ("WAITING_PART", "WAITING_APPROVAL"))
    ready = sum(1 for o in orders if o.status == "READY")
    cash = sum(1 for o in orders if o.payment and o.payment > 0)

    def pct_txt(p, ok):
        return "TERCAPAI" if ok else (str(p).replace(".", ",") + "%")

    return {
        "period": {
            "id": period.id,
            "start_at": period.start_at.isoformat(),
            "end_at": period.end_at.isoformat(),
        },
        "finance": fin,
        "star_cards": [
            {"key": "omset", "label": "Omset Hari Ini", "value": fin["omset"],
             "sub": str(fin["n_cash"]) + " transaksi CASH • periode 16:00–16:00"},
            {"key": "laba_kotor", "label": "Laba Kotor", "value": fin["laba_kotor"],
             "sub": "Omset − modal (Part+Jasa+Lain)"},
            {"key": "beban", "label": "Total Beban", "value": fin["total_beban"],
             "sub": "Gaji + operasional + lainnya"},
            {"key": "laba_bersih", "label": "Laba Bersih", "value": fin["laba_bersih"],
             "sub": "Kotor − total beban" + (" • alokasi terbentuk" if fin["alokasi_terbentuk"] else "")},
            {"key": "cts", "label": "Target Gaji (CTS)", "value": fin["cts_target"],
             "progress": fin["cts_progress"], "tercapai": fin["cts_tercapai"],
             "sub": pct_txt(fin["cts_progress"], fin["cts_tercapai"]) + " dari beban gaji"},
            {"key": "cto", "label": "Target Operasional (CTO)", "value": fin["cto_target"],
             "progress": fin["cto_progress"], "tercapai": fin["cto_tercapai"],
             "sub": pct_txt(fin["cto_progress"], fin["cto_tercapai"]) + " dari gaji+ops"},
        ],
        "insight": [
            {"value": total, "label": "Unit Masuk", "color": "text-cyan-600"},
            {"value": done, "label": "Unit Selesai", "color": "text-green-600"},
            {"value": cash, "label": "Unit Cash", "color": "text-emerald-600"},
            {"value": pending, "label": "Unit Pending", "color": "text-amber-600"},
        ],
        "stats": {"total": total, "done": done, "active": active, "pending": pending, "ready": ready},
    }


@router.get("/statistics/status")
def get_status_stats(db: Session = Depends(get_db_session)):
    """Data untuk smooth line chart - tren status transaksi minggu ini."""
    days = [d.strftime("%a") for d in (datetime.now() - timedelta(days=i) for i in range(6, -1, -1))]
    # dummy volume per hari
    masuk = [12, 10, 14, 13, 16, 15, 18]
    selesai = [8, 9, 11, 10, 12, 13, 12]
    pending = [4, 3, 5, 6, 5, 4, 7]
    return {
        "categories": days,
        "series": [
            {"name": "Masuk", "data": masuk},
            {"name": "Selesai", "data": selesai},
            {"name": "Pending", "data": pending},
        ],
    }


@router.get("/statistics/damage")
def get_damage_stats(db: Session = Depends(get_db_session)):
    """Data untuk horizontal bar chart - tren kerusakan minggu ini."""
    return {
        "categories": ["Layar Pecah", "Baterai", "Charging", "Speaker", "Kamera", "Water"],
        "data": [14, 9, 7, 5, 4, 3],
    }
