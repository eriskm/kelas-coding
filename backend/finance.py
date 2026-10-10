"""P2-05 — FINANCIAL CORE Project B (Financial SSOT sebagai target).

Implementasi rumus Owner:
    OMZET       = total penjualan yang SETTLED/LUNAS pada periode bisnis (16:00->16:00)
                  DP BUKAN Omzet, BUKAN Laba.
    MODAL       = Modal Part + Modal Jasa + Modal Lain-lain (3 komponen cost terpisah)
    BEBAN       = Gaji + Operasional (kategori lain tidak masuk Beban)
    LABA BERSIH = OMZET - MODAL PART - MODAL JASA - MODAL LAIN-LAIN - BEBAN

Aturan tambahan Owner:
- Q4/SSOT-2: cohort Omzet = unit yang payment_status LUNAS dan momen settlement-nya
  (lunas_at) berada dalam periode. DP tidak pernah masuk Omzet.
- Q5/Q19/SSOT-3: ketiga modal adalah komponen terpisah; tidak digabung, tidak
  boleh dihitung dua kali (Laba Kotor hanya alias antara, bukan pengurangan kedua).
- SSOT-4/OD-001: Beban dibebankan SEKALI per periode kas (snapshot beku, idempotent).
- SSOT-5: Laba Bersih = 4 pengurang; tanpa double calculation.

Modul ini TIDAK menghitung distribusi secara final (P2-07) dan TIDAK menutup kas (P2-08).
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from models import ExpensePeriod, ServiceOrder
from money import ZERO, to_decimal
from statusflow import payment_summary

# Kategori beban yang Recognized Owner (SSOT-4). Kategori lain TIDAK masuk Beban.
BEBAN_KATEGORI = ("gaji", "operasional")


def period_key(start: datetime, end: datetime) -> str:
    """Kunci periode kas = tanggal mulai periode (16:00->16:00)."""
    return start.strftime("%Y-%m-%d")


def settled_orders(db: Session, start: datetime, end: datetime) -> list:
    """Cohort Omzet: unit CASH dengan momen settlement di dalam periode.

    P2-15 / Owner Cash Model: **Omzet direalisasikan saat CASH**, bukan saat LUNAS.
    Unit yang sudah LUNAS tetapi belum CASH → BELUM masuk Omzet (Payment Ledger
    boleh berstatus LUNAS). Settlement/lunas tetap dibaca dari Payment Ledger
    (P2-04 / Q17) — CASH bukan bypass, hanya titik pengakuan transaksi.
    """
    orders = db.query(ServiceOrder).all()
    cohort = []
    for o in orders:
        if (getattr(o, "status", "") or "") != "CASH":
            continue
        moment = getattr(o, "lunas_at", None) or getattr(o, "lunas_date", None)
        if moment is None:
            continue
        if isinstance(moment, datetime):
            m = moment
        else:
            m = datetime(moment.year, moment.month, moment.day, 12, 0, 0)
        if not (start <= m < end):
            continue
        pays = db.query(__import__("models").Payment).filter(
            __import__("models").Payment.service_order_id == o.id).all()
        if payment_summary(o, pays)["payment_status"] == "LUNAS":
            cohort.append(o)
    return cohort


def freeze_expenses_for_period(db: Session, start: datetime, end: datetime,
                              commit: bool = False) -> dict:
    """Bekukan beban periode ini SEKALI (idempotent, SSOT-4 / OD-001).

    Snapshot diambil dari `expenses` yang sudah bertepatan dengan periode (aturan
    yang sama seperti sebelumnya, tidak mengubah angka), lalu disimpan agar
    periode berikutnya tidak ikut berubah bila ada perubahan retroactive.
    """
    from models import Expense

    key = period_key(start, end)
    existing = db.query(ExpensePeriod).filter(ExpensePeriod.periode == key).all()
    if existing:
        return {"periode": key, "dibekukan": 0, "sudah_ada": len(existing)}

    dibuat = 0
    for e in db.query(Expense).all():
        # Aturan moment yang SAMA dengan sebelumnya (_expense_moment di dashboard):
        # created_at dipakai bila ada, jika tidak tanggal pada 12:00.
        moment = getattr(e, "created_at", None)
        if moment is None:
            tgl = getattr(e, "tanggal", None)
            if tgl is None:
                continue
            moment = datetime(tgl.year, tgl.month, tgl.day, 12, 0, 0)
        if not (start <= moment < end):
            continue
        kategori = (e.kategori or "").strip().lower()
        if kategori not in BEBAN_KATEGORI:
            # SSOT-4: kategori lain bukan Beban -> tidak dibekukan sebagai beban.
            continue
        db.add(ExpensePeriod(
            periode=key,
            kategori=(e.kategori or "").strip(),
            nama_beban=(e.uraian or e.kategori or "-").strip(),
            nilai=to_decimal(e.nilai),
            dibebankan_pada=datetime.now(),
            expense_id=e.id,
        ))
        dibuat += 1
    db.flush()
    if commit:
        db.commit()
    return {"periode": key, "dibekukan": dibuat, "sudah_ada": 0}


def beban_frozen(db: Session, start: datetime, end: datetime,
                 commit: bool = False) -> dict:
    """Baca beban beku periode; bekukan lebih dulu bila belum ada."""
    key = period_key(start, end)
    rows = db.query(ExpensePeriod).filter(ExpensePeriod.periode == key).all()
    if not rows:
        freeze_expenses_for_period(db, start, end, commit=False)
        rows = db.query(ExpensePeriod).filter(ExpensePeriod.periode == key).all()
    gaji = ZERO
    operasional = ZERO
    for r in rows:
        kategori = (r.kategori or "").strip().lower()
        if kategori == "gaji":
            gaji += to_decimal(r.nilai)
        elif kategori == "operasional":
            operasional += to_decimal(r.nilai)
    if commit:
        db.commit()
    return {"periode": key, "gaji": gaji, "operasional": operasional,
            "total": gaji + operasional}


def compute_finance_core(db: Session, start: datetime, end: datetime,
                         freeze: bool = False) -> dict:
    """SSOT financial core. Mengembalikan primitive untuk P2-05/P2-07/P2-08."""
    cohort = settled_orders(db, start, end)
    omset = ZERO
    modal_part = ZERO
    modal_jasa = ZERO
    modal_lain = ZERO
    for o in cohort:
        omset += to_decimal(getattr(o, "final_price", None)) or to_decimal(
            getattr(o, "estimate", 0))
        modal_part += to_decimal(getattr(o, "part_cost", 0))
        modal_jasa += to_decimal(getattr(o, "modal_jasa", 0))
        modal_lain += to_decimal(getattr(o, "modal_lainnya", 0))
    total_modal = modal_part + modal_jasa + modal_lain

    beban = beban_frozen(db, start, end, commit=False)
    total_beban = beban["gaji"] + beban["operasional"]

    laba_bersih = omset - modal_part - modal_jasa - modal_lain - total_beban

    return {
        "periode": period_key(start, end),
        "omset": omset,
        "n_settled": len(cohort),
        "modal_part": modal_part,
        "modal_jasa": modal_jasa,
        "modal_lainnya": modal_lain,
        "total_modal": total_modal,
        "beban_gaji": beban["gaji"],
        "beban_operasional": beban["operasional"],
        "total_beban": total_beban,
        "laba_bersih": laba_bersih,
        "laba_per_order": None,
    }


def snapshot_laba_bersih(db: Session, start: datetime, end: datetime) -> Decimal:
    """Primitive snapshot Laba Bersih untuk dipakai Tutup Kas (P2-08)."""
    return compute_finance_core(db, start, end)["laba_bersih"]


__all__ = [
    "BEBAN_KATEGORI",
    "beban_frozen",
    "compute_finance_core",
    "freeze_expenses_for_period",
    "period_key",
    "settled_orders",
    "snapshot_laba_bersih",
]