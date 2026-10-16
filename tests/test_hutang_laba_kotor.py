# -*- coding: utf-8 -*-
"""Owner (LOCKED):

    "dalam setiap periode jika Laba Kotor tidak dapat menutup Beban maka akan
     menjadi Hutang Beban."

    "kalau Laba Kotor cukup untuk menutup beban, sama dengan Target CTO tercapai"

Jadi penentu Hutang Beban adalah LABA KOTOR, bukan "berapa yang tidak kebayar
dari Laci". Pembayaran dari Laci tetap seperti OD-LOCK-06 (seadanya, tidak
pernah negatif); yang berubah hanya PENGUKURAN hutangnya.
"""
from datetime import datetime, timedelta

import pytest
from money import to_decimal, ZERO


@pytest.fixture()
def db():
    from database import SessionLocal
    from models import Base
    from sqlalchemy import create_engine

    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = SessionLocal(bind=eng)
    try:
        yield s
    finally:
        s.close()
        eng.dispose()


def _skenario(s, nama, omset, modal, beban_gaji, beban_ops):
    """Bangun satu periode: satu unit CASH + katalog beban."""
    import models as m

    mulai = datetime(2026, 8, 1, 9, 0, 0)
    s.add(m.KasPeriod(start_at=mulai, end_at=mulai + timedelta(days=1),
                      status="OPEN"))
    s.add(m.Customer(name=nama, phone="0800", created_at=mulai))
    s.commit()
    s.expire_all()
    cid = s.query(m.Customer).filter(m.Customer.name == nama).one().id

    for kategori, nilai in (("Gaji", beban_gaji), ("Operasional", beban_ops)):
        s.add(m.Expense(kategori=kategori, uraian=nama, nilai=to_decimal(nilai),
                        created_at=mulai, recurring=True))
    s.flush()

    o = m.ServiceOrder(
        no_servis=nama, customer_id=cid, device="PY", status="CASH",
        unit_status="DIAMBIL", service_date=mulai.date(), taken_at=mulai,
        final_price=to_decimal(omset), estimate=to_decimal(omset),
        repair_plan="x", technician="T", warranty_months=1, created_at=mulai,
        part_cost=to_decimal(modal), modal_jasa=to_decimal(0),
        modal_lainnya=to_decimal(0))
    s.add(o)
    s.flush()
    s.add(m.Payment(service_order_id=o.id, kind="PELUNASAN",
                    amount=to_decimal(omset), created_at=mulai))
    s.flush()
    # Penjualan dan Modal harus masuk ledger kas, kalau tidak Laci kosong dan
    # skenario-nya tidak realistis.
    import cash

    cash.catat_penerimaan(s, s.query(m.Payment).order_by(m.Payment.id.desc()).first())
    cash.catat_modal(s, o)
    s.commit()
    s.expire_all()
    return s.query(m.KasPeriod).order_by(m.KasPeriod.id.desc()).first()


def _input_hutang_admin(db, period, nominal=None, oleh="pytest"):
    """OD-LOCK-12: simulasi Admin mencatat Hutang Began secara manual.

    Meniru `POST /api/beban-hutang/catat`: ambil nilai minus di akhir
    Kondisi Kas Operasional dari SATU sumber (`kondisi_kas_akhir`), lalu catat
    sebesar itu (atau sebesar `nominal` kalau diberikan).
    """
    import expense_debt as debt_mod
    from finance import period_key
    from routers.dashboard import batas_periode, compute_finance

    start, end = batas_periode(period)
    fin = compute_finance(db, start, end)
    kka = to_decimal(fin["kondisi_kas_akhir"])
    n = nominal if nominal is not None else max(ZERO, -kka)
    return debt_mod.catat_hutang_manual(
        db, period_key(db, start, end), n, kas_period_id=period.id,
        oleh=oleh, kondisi_kas_akhir=kka)


def test_od_lock_12_hutang_beban_tidak_lagi_otomatis(db):
    """OD-LOCK-12: Beku periode lalu Tutup Kas TIDAK boleh bikin hutang sendiri."""
    import finance
    import expense_debt

    p = _skenario(db, "OL12-OTOMATIS", 600000, 325000, 405000, 200000)
    core = finance.compute_finance_core(db, p.start_at, p.end_at, freeze=True)
    db.commit()
    # Kondisi Kas minus, tapi hutang TIDAK boleh muncul sendiri.
    assert to_decimal(core["laba_kotor"]) == to_decimal(275000)
    assert to_decimal(expense_debt.saldo_hutang(db)) == to_decimal(0), (
        "Beban beku saja TIDAK boleh membuat Hutang Beban (OD-LOCK-12)")

    import closing
    closing.tutup_periode(db, p, counted=None, oleh="pytest",
                          compute_finance=finance.compute_finance_core)
    db.commit()
    assert to_decimal(expense_debt.saldo_hutang(db)) == to_decimal(0), (
        "Tutup Kas TIDAK boleh membuat Hutang Beban tanpa perintah Admin")


def test_od_lock_12_admin_input_manual_satu_kali(db):
    """OD-LOCK-12: Admin menginput manual = nilai minus Kondisi Kas, 1x/period."""
    import finance
    import expense_debt

    p = _skenario(db, "OL12-MANUAL", 600000, 325000, 405000, 200000)
    finance.compute_finance_core(db, p.start_at, p.end_at, freeze=True)
    db.commit()
    assert to_decimal(expense_debt.saldo_hutang(db)) == to_decimal(0)

    _input_hutang_admin(db, p)
    db.commit()
    assert to_decimal(expense_debt.saldo_hutang(db)) > to_decimal(0), (
        "setelah Admin input manual, Hutang Beban harus tercatat")

    # Satu periode = satu kali. Input kedua harus DITOLAK.
    import pytest
    with pytest.raises(Exception):
        _input_hutang_admin(db, p)
    db.rollback()


def test_od_lock_12_nominal_lebih_besar_dari_minus_ditolak(db):
    """Nominal tidak boleh melebihi nilai minus yang diukur."""
    import finance
    import expense_debt
    import pytest

    p = _skenario(db, "OL12-LEBIH", 600000, 325000, 405000, 200000)
    finance.compute_finance_core(db, p.start_at, p.end_at, freeze=True)
    db.commit()
    with pytest.raises(Exception):
        _input_hutang_admin(db, p, nominal=to_decimal(99_000_000))
    db.rollback()
    assert to_decimal(expense_debt.saldo_hutang(db)) == to_decimal(0)


def test_laba_kotor_cukup_tidak_ada_hutang(db):
    """Laba Kotor >= Beban = target CTO tercapai. TIDAK ada hutang."""
    import finance
    import expense_debt

    p = _skenario(db, "LK-CUKUP", 1000000, 200000, 405000, 200000)
    core = finance.compute_finance_core(db, p.start_at, p.end_at, freeze=True)
    db.commit()

    assert to_decimal(core["laba_kotor"]) == to_decimal(800000)
    assert to_decimal(core["total_beban"]) == to_decimal(605000)
    assert to_decimal(core["laba_kotor"]) >= to_decimal(core["total_beban"])
    assert to_decimal(expense_debt.saldo_hutang(db)) == ZERO, (
        "Laba Kotor menutup Beban -> target tercapai -> tidak boleh ada hutang")


def test_laba_kotor_kurang_jadi_hutang(db):
    """Laba Kotor < Beban -> selisihnya jadi Hutang Beban."""
    import finance
    import expense_debt

    p = _skenario(db, "LK-KURANG", 600000, 325000, 405000, 200000)
    core = finance.compute_finance_core(db, p.start_at, p.end_at, freeze=True)
    db.commit()

    assert to_decimal(core["laba_kotor"]) == to_decimal(275000)
    assert to_decimal(core["total_beban"]) == to_decimal(605000)
    # OD-LOCK-12: TIDAK ada hutang sampai Admin yang input.
    assert to_decimal(expense_debt.saldo_hutang(db)) == to_decimal(0)
    _input_hutang_admin(db, p)
    db.commit()
    assert to_decimal(expense_debt.saldo_hutang(db)) == to_decimal(330000), (
        "nilai minus Conditions Kas harus menjadi Hutang Beban setelah "
        "Admin input manual")


def test_hutang_menumpuk_antar_periode(db):
    """Owner: "jika periode berikutnya masih minus, tidak apa-apa terus nambah"."""
    import finance
    import models as m
    import expense_debt

    mulai = datetime(2026, 8, 1, 9, 0, 0)
    s = db
    s.add(m.Customer(name="TUMPUK", phone="0800", created_at=mulai))
    s.commit()
    s.expire_all()
    cid = s.query(m.Customer).filter(m.Customer.name == "TUMPUK").one().id
    s.add(m.Expense(kategori="Gaji", uraian="G", nilai=to_decimal(500000),
                    created_at=mulai, recurring=True))
    s.commit()

    for i in range(3):
        p = m.KasPeriod(start_at=mulai + timedelta(hours=2 * i),
                        end_at=mulai + timedelta(hours=2 * i + 1),
                        status="OPEN")
        s.add(p)
        s.commit()
        s.expire_all()
        p = s.query(m.KasPeriod).order_by(m.KasPeriod.id.desc()).first()
        core = finance.compute_finance_core(db, p.start_at, p.end_at,
                                            freeze=True)
        s.commit()
        assert to_decimal(core["laba_kotor"]) == ZERO, "tanpa penjualan"

    # OD-LOCK-12: ketiga periode TIDAK otomatis menambah hutang.
    assert to_decimal(expense_debt.saldo_hutang(db)) == to_decimal(0), (
        "beberapa periode kosong tidak boleh otomatis menambah hutang")
    # Admin yang memutuskan, satu kali per periode.
    for pp in s.query(m.KasPeriod).order_by(m.KasPeriod.id).all():
        _input_hutang_admin(s, pp)
    s.commit()
    assert to_decimal(expense_debt.saldo_hutang(db)) == to_decimal(1500000), (
        "3 x 500.000 menumpuk karena Admin thrice input manual")


def test_hutang_lama_tidak_ditimpa_periode_baru(db):
    """Owner: hutang yang sudah tercatat dibiarkan, bukan direset."""
    import finance
    import models as m
    import expense_debt
    from expense_debt import TIPE_HUTANG

    mulai = datetime(2026, 8, 1, 9, 0, 0)
    s = db
    # Hutang Beban dari periode sebelumnya (satu-satunya yang boleh terbawa).
    s.add(m.ExpenseDebtEntry(tipe=TIPE_HUTANG, nominal=to_decimal(1147000),
                             saldo_setelah=to_decimal(1147000),
                             periode="lama-sebelum-perubahan",
                             expense_debt_period_id=None, oleh="UAT Admin"))
    s.commit()

    p = _skenario(s, "SETELAH-LAMA", 600000, 325000, 405000, 200000)
    finance.compute_finance_core(s, p.start_at, p.end_at, freeze=True)
    s.commit()

    # OD-LOCK-12 + aturan Owner: periode BARU tidak boleh membawa pengaruh
    # periode lama, KECUALI DP dan Beban Hutang. Jadi Hutang Beban lama (1.147.000)
    # boleh terbawa; sisanya (Omzet/Modal/Beban periode lama) tidak.
    assert to_decimal(expense_debt.saldo_hutang(s)) == to_decimal(1147000), \
        "Hutang Beban boleh terbawa; periode baru tidak otomatis menambah"
    _input_hutang_admin(s, p)
    s.commit()
    assert to_decimal(expense_debt.saldo_hutang(s)) == to_decimal(1147000 + 330000), \
        "Hutang Beban lama tetap utuh, lalu nambah setelah Admin input manual"


def test_laba_kotor_cukup_tetap_tanpa_hutang_walau_laci_kurang(db):
    """Laba Kotor >= Beban = target CTO tercapai, walau uangnya belum cukup.

    Sesuai OD-LOCK-12: Hutang Beban hanya muncul kalau nilai AKHIR di tabel
    "Kondisi Kas Operasional" minus DAN Admin menginputnya. Di sini Laba Kotor
    sudah menutup Beban, jadi tidak ada minus dan tidak ada hutang sama sekali.

    Cara membuat Laci < Laba Kotor: penjualan lunas 600.000 (Laba Kotor
    500.000 setelah modal 100.000), lalu keluar CASH_OUT 200.000 dari Laci.
    Sisa Laci 300.000 -- lebih kecil dari Laba Kotor.
    """
    import finance
    import models as m
    import expense_debt
    import cash

    p = _skenario(db, "CASHOUT", 600000, 100000, 500000, 0)
    cash.catat_mutasi(
        db, cash.LAYER_LACI, "Keluar", cash.KATEGORI[cash.SUMBER_CASH_OUT],
        "Cash out uji", to_decimal(200000),
        sumber=cash.SUMBER_CASH_OUT, check_saldo=False)
    db.commit()
    db.expire_all()

    assert to_decimal(cash.saldo_laci(db)) == to_decimal(300000), \
        "Laci 300.000 < Laba Kotor 500.000 -- inilah kasus pembeda"

    core = finance.compute_finance_core(db, p.start_at, p.end_at, freeze=True)
    db.commit()

    assert to_decimal(core["laba_kotor"]) == to_decimal(500000)
    assert to_decimal(core["total_beban"]) == to_decimal(500000)
    assert to_decimal(expense_debt.saldo_hutang(db)) == ZERO, \
        "Laba Kotor menutup Beban -> target CTO tercapai -> tidak ada hutang"


def test_laci_tidak_pernah_negatif(db):
    """Batas Laci tetap berlaku walau Beban besar sekali."""
    import finance
    import cash

    p = _skenario(db, "NEGATIF", 100000, 50000, 900000, 500000)
    finance.compute_finance_core(db, p.start_at, p.end_at, freeze=True)
    db.commit()
    assert to_decimal(cash.saldo_laci(db)) >= ZERO, (
        "Laci tidak boleh pernah negatif")