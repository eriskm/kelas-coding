# -*- coding: utf-8 -*-
"""P2-14 (ID-13) — regression baseline: Financial Core (SSOT-2..5) & Beban beku.

P2-15 (Owner Cash Model): Omzet/Modal/Laba direalisasikan saat status **CASH**.
"""
from datetime import date, datetime, timedelta

import finance
from money import to_decimal
from statusflow import lock_lunas_moment


def _periode_aktif(db):
    from models import KasPeriod
    now = datetime.now()
    start = now.replace(hour=16, minute=0, second=0, microsecond=0)
    if now < start:
        start -= timedelta(days=1)
    end = start + timedelta(days=1)
    p = db.query(KasPeriod).filter(KasPeriod.status == "OPEN").first()
    if p is None:
        p = KasPeriod(start_at=start, end_at=end, status="OPEN")
        db.add(p)
        db.commit()
        db.refresh(p)
    else:
        p.start_at, p.end_at = start, end
        db.commit()
    return p


def _unit(db, no, harga, modal=(0, 0, 0), settle=True, cashed=True):
    """Buat unit uji berstatus DONE.

    P2-15: `settle=True` menulis Payment Ledger (LUNAS); `cashed=True` lalu
    menandai CASH agar unit masuk kohorot Omzet.
    """
    import models
    cust = db.query(models.Customer).filter(models.Customer.name == "Pytest Customer").first()
    o = models.ServiceOrder(no_servis=no, customer_id=cust.id, device="PY", status="DONE",
                            service_date=date.today(), final_price=to_decimal(harga),
                            estimate=to_decimal(harga), warranty_months=1)
    o.part_cost, o.modal_jasa, o.modal_lainnya = [to_decimal(x) for x in modal]
    o.payment = to_decimal("0")
    db.add(o)
    db.commit()
    db.refresh(o)
    if settle:
        db.add(models.Payment(service_order_id=o.id, kind="PELUNASAN",
                              amount=to_decimal(harga), method="CASH", note="lunas"))
        db.commit()
        lock_lunas_moment(o, datetime.now())
    if cashed:
        o.status = "CASH"
        db.commit()
    return o


def _expense(kategori, uraian, nilai, moment):
    import models
    return models.Expense(kategori=kategori, uraian=uraian, nilai=to_decimal(nilai),
                          tanggal=moment.date(), created_at=moment)


def test_omzet_hanya_dari_cash_dan_modal_terpisah(db):
    p = _periode_aktif(db)
    core = finance.compute_finance_core(db, p.start_at, p.end_at)
    assert core["periode"] == p.start_at.date().isoformat()
    assert core["omset"] >= 0
    assert core["total_modal"] == (core["modal_part"] + core["modal_jasa"] + core["modal_lainnya"])
    assert core["total_beban"] == core["beban_gaji"] + core["beban_operasional"]
    assert core["laba_bersih"] == (core["omset"] - core["modal_part"]
                                   - core["modal_jasa"] - core["modal_lainnya"]
                                   - core["total_beban"])


def test_omzet_hanya_unit_cash(db):
    """P2-15: hanya unit CASH yang masuk kohorot Omzet."""
    p = _periode_aktif(db)
    import models
    o_done = _unit(db, "PY-DONE-OMZET", 111000, cashed=False)
    ids = [x.id for x in finance.settled_orders(db, p.start_at, p.end_at)]
    assert o_done.id not in ids, "unit DONE tidak boleh masuk Omzet"
    o_cash = _unit(db, "PY-CASH-OMZET", 222000, cashed=True)
    ids2 = [x.id for x in finance.settled_orders(db, p.start_at, p.end_at)]
    assert o_cash.id in ids2, "unit CASH harus masuk Omzet"


def test_dp_tidak_masuk_omzet(db):
    """DP tidak masuk Omzet; pelunasan saja belum cukup — realisasi saat CASH."""
    p = _periode_aktif(db)
    import models
    o = _unit(db, "PY-DP", 400000, modal=(100000, 50000, 10000), settle=False, cashed=False)
    db.add(models.Payment(service_order_id=o.id, kind="DP",
                          amount=to_decimal("400000"), method="CASH", note="dp"))
    db.commit()
    ids_dp = [x.id for x in finance.settled_orders(db, p.start_at, p.end_at)]
    assert o.id not in ids_dp, "DP saja tidak boleh masuk Omzet"

    db.add(models.Payment(service_order_id=o.id, kind="PELUNASAN",
                          amount=to_decimal("400000"), method="CASH", note="lunas"))
    db.commit()
    lock_lunas_moment(o, datetime.now())
    db.commit()
    db.refresh(o)
    core_lunas = finance.compute_finance_core(db, p.start_at, p.end_at)
    ids_lunas = [x.id for x in finance.settled_orders(db, p.start_at, p.end_at)]
    assert o.id not in ids_lunas, "LUNAS tapi belum CASH tidak boleh masuk Omzet"
    assert o.laba_bersih == 0

    o.status = "CASH"
    db.commit()
    db.refresh(o)
    ids_cash = [x.id for x in finance.settled_orders(db, p.start_at, p.end_at)]
    assert o.id in ids_cash, "CASH harus masuk cohort Omzet"
    core_cash = finance.compute_finance_core(db, p.start_at, p.end_at)
    assert core_cash["omset"] >= core_lunas["omset"] + to_decimal("400000")
    assert core_cash["total_modal"] >= to_decimal("160000")


def test_beban_hanya_gaji_dan_operasional(db):
    p = _periode_aktif(db)
    tengah = p.start_at + (p.end_at - p.start_at) / 2
    db.add(_expense("Gaji", "PY gaji", 100000, tengah))
    db.add(_expense("Operasional", "PY ops", 50000, tengah))
    db.add(_expense("Transport", "PY transport", 999999, tengah))
    db.commit()
    finance.freeze_expenses_for_period(db, p.start_at, p.end_at, commit=True)
    core = finance.compute_finance_core(db, p.start_at, p.end_at)
    assert core["total_beban"] == core["beban_gaji"] + core["beban_operasional"]
    assert core["total_beban"] < to_decimal("999999")