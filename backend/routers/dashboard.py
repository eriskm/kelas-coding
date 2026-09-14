"""Dashboard endpoints - data untuk star cards & charts."""
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from dependencies import get_db_session
from models import Expense, KasEntry, KasPeriod, Payment, ServiceOrder
from statusflow import kewajiban, lunas_moment, payment_summary
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


def _expense_moment(e) -> Optional[datetime]:
    if getattr(e, "created_at", None):
        return e.created_at
    if getattr(e, "tanggal", None):
        return datetime(e.tanggal.year, e.tanggal.month, e.tanggal.day, 12, 0, 0)
    return None


def compute_finance(db: Session, start: datetime, end: datetime) -> dict:
    """Satu-satunya sumber hitungan keuangan (dipakai overview & Tutup Kas).

    Pemasukan servis = jurnal payments (DP/PELUNASAN) dalam periode.
    Modal diatribusikan ke order yang menerima pembayaran dalam periode.
    """

    def num(v):
        try:
            return float(v or 0)
        except (TypeError, ValueError):
            return 0.0

    pays = db.query(Payment).all()
    in_pays = [p for p in pays
               if p.created_at is not None and start <= p.created_at < end]
    omset = sum(num(p.amount) for p in in_pays)
    paid_order_ids = {p.service_order_id for p in in_pays}
    in_orders = []
    if paid_order_ids:
        in_orders = db.query(ServiceOrder).filter(ServiceOrder.id.in_(paid_order_ids)).all()
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

    # Jurnal kas manual periode aktif (di luar servis & beban).
    # 'Saldo Awal' dikecualikan dari baris (dihitung lintas periode sebagai opening).
    def _kas_moment(k) -> Optional[datetime]:
        if getattr(k, "created_at", None):
            return k.created_at
        if getattr(k, "tanggal", None):
            return datetime(k.tanggal.year, k.tanggal.month, k.tanggal.day, 12, 0, 0)
        return None

    kas_masuk = 0.0
    kas_keluar = 0.0
    opening = 0.0
    for k in db.query(KasEntry).all():
        is_opening = (k.kategori or "") == "Saldo Awal"
        val = num(k.nominal)
        signed = val if (k.jenis or "").strip().lower() == "masuk" else -val
        if is_opening:
            opening += signed
            continue
        m = _kas_moment(k)
        if m is not None and start <= m < end:
            if (k.jenis or "").strip().lower() == "masuk":
                kas_masuk += val
            else:
                kas_keluar += val

    total_masuk = omset + kas_masuk
    total_keluar = total_modal + total_beban + kas_keluar
    saldo = opening + total_masuk - total_keluar

    return {
        "n_bayar": len(in_pays),
        "n_order_bayar": len(in_orders),
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
        "kas_masuk_manual": kas_masuk,
        "kas_keluar_manual": kas_keluar,
        "opening": opening,
        "total_masuk": total_masuk,
        "total_keluar": total_keluar,
        "saldo": saldo,
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
    selesai = sum(1 for o in orders if o.status == "SELESAI")
    aktif = sum(1 for o in orders if o.status in ("DITERIMA", "ANALISA", "DIAGNOSA",
                                                 "KONFIRMASI", "MENUNGGU SPAREPART", "PERBAIKAN"))
    gagal_batal = sum(1 for o in orders if o.status in ("GAGAL", "BATAL"))
    _all_pays = db.query(Payment).all()
    _by_order = {}
    for _p in _all_pays:
        _by_order.setdefault(_p.service_order_id, []).append(_p)
    lunas = sum(1 for o in orders
                if payment_summary(o, _by_order.get(o.id, []))["payment_status"] == "LUNAS")

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
             "sub": str(fin["n_bayar"]) + " pembayaran • periode 16:00–16:00"},
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
            {"value": selesai, "label": "Unit Selesai", "color": "text-green-600"},
            {"value": lunas, "label": "Unit Lunas", "color": "text-emerald-600"},
            {"value": aktif, "label": "Unit Aktif", "color": "text-amber-600"},
        ],
        "stats": {"total": total, "selesai": selesai, "aktif": aktif,
                  "gagal_batal": gagal_batal, "lunas": lunas},
    }


@router.get("/statistics/status")
def get_status_stats(db: Session = Depends(get_db_session)):
    """Tren 7 hari real + hitungan per status saat ini (pengganti dummy)."""
    today = datetime.now().date()
    days = [today - timedelta(days=i) for i in range(6, -1, -1)]
    categories = [d.strftime("%a") for d in days]
    orders = db.query(ServiceOrder).all()
    _pay_rows = db.query(Payment).all()
    _pay_by_order = {}
    for _p in _pay_rows:
        _pay_by_order.setdefault(_p.service_order_id, []).append(_p)
    lunas_days = []
    for o in orders:
        m = lunas_moment(o, _pay_by_order.get(o.id, []))
        s = payment_summary(o, _pay_by_order.get(o.id, []))
        if s["payment_status"] == "LUNAS" and m is not None:
            lunas_days.append(m.date())
    masuk, selesai, pending = [], [], []
    pending_set = {"DITERIMA", "ANALISA", "DIAGNOSA", "KONFIRMASI",
                   "MENUNGGU SPAREPART", "PERBAIKAN"}
    for d in days:
        created = [o for o in orders
                   if o.created_at is not None and o.created_at.date() == d]
        masuk.append(len(created))
        selesai.append(sum(1 for cd in lunas_days if cd == d))
        pending.append(sum(1 for o in created if (o.status or "") in pending_set))
    by_status = []
    for name in ["DITERIMA", "ANALISA", "DIAGNOSA", "KONFIRMASI", "MENUNGGU SPAREPART",
                 "PERBAIKAN", "SELESAI", "GAGAL", "BATAL"]:
        by_status.append({"name": name,
                          "value": db.query(ServiceOrder).filter(ServiceOrder.status == name).count()})
    return {
        "categories": categories,
        "series": [
            {"name": "Masuk", "data": masuk},
            {"name": "Selesai", "data": selesai},
            {"name": "Pending", "data": pending},
        ],
        "by_status": by_status,
    }


@router.get("/statistics/damage")
def get_damage_stats(db: Session = Depends(get_db_session)):
    """Tren kerusakan real: agregat damagetype 6 teratas (pengganti angka statis)."""
    counts: dict = {}
    for (dt,) in db.query(ServiceOrder.damagetype).all():
        name = (dt or "").strip()
        if not name:
            continue
        counts[name] = counts.get(name, 0) + 1
    top = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:6]
    return {
        "categories": [k for k, _ in top],
        "data": [v for _, v in top],
    }
