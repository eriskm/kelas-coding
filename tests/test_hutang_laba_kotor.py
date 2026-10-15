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


def _skenario_dengan_dp(s, nama, omset, modal, beban_gaji, beban_ops, dp=0):
    """Skenario dengan DP: uang DP ikut masuk Laci tapi BUKAN bagian Omzet.

    Efeknya Laci = Laba Kotor + DP, jadi Laci TIDAK sama dengan Laba Kotor.
    Inilah yang membuat test bisa membedakan "hutang dari Laba Kotor" dari
    "hutang dari sisa Laci".
    """
    import models as m
    import cash

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

    if dp:
        pay_dp = m.Payment(service_order_id=o.id, kind="DP", amount=to_decimal(dp),
                           method="CASH", created_at=mulai)
        s.add(pay_dp)
        s.flush()
        cash.catat_penerimaan(s, pay_dp)

    pay = m.Payment(service_order_id=o.id, kind="PELUNASAN",
                    amount=to_decimal(omset), method="CASH", created_at=mulai)
    s.add(pay)
    s.flush()
    cash.catat_penerimaan(s, pay)
    cash.catat_modal(s, o)
    s.commit()
    s.expire_all()
    return s.query(m.KasPeriod).order_by(m.KasPeriod.id.desc()).first()


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
    assert to_decimal(expense_debt.saldo_hutang(db)) == to_decimal(330000), (
        "605.000 - 275.000 = 330.000 harus menjadi Hutang Beban")


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

    assert to_decimal(expense_debt.saldo_hutang(db)) == to_decimal(1500000), (
        "3 x 500.000 harus menumpuk, bukan saling menggantikan")


def test_hutang_lama_tidak_ditimpa_periode_baru(db):
    """Owner: hutang yang sudah tercatat dibiarkan, bukan direset."""
    import finance
    import models as m
    import expense_debt
    from expense_debt import TIPE_HUTANG

    mulai = datetime(2026, 8, 1, 9, 0, 0)
    s = db
    # Hutang lama dari "uji sebelumnya", tanpa baris rincian per periode.
    s.add(m.ExpenseDebtEntry(tipe=TIPE_HUTANG, nominal=to_decimal(1147000),
                             saldo_setelah=to_decimal(1147000),
                             periode="lama-sebelum-perubahan",
                             expense_debt_period_id=None, oleh="UAT Admin"))
    s.commit()

    p = _skenario(s, "SETELAH-LAMA", 600000, 325000, 405000, 200000)
    finance.compute_finance_core(s, p.start_at, p.end_at, freeze=True)
    s.commit()

    assert to_decimal(expense_debt.saldo_hutang(s)) == to_decimal(1147000 + 330000), \
        "hutang lama 1.147.000 harus tetap utuh lalu nambah 330.000"


def test_aturannya_bukan_cara_lama_bayar_kurang_di_laci(db):
    """Pemisah yang wajib ada: Laci harus TIDAK sama dengan Laba Kotor.

    Kalau Laci persis sama dengan Laba Kotor (penjualan dibayar penuh),
    maka "cara lama" (hutang = beban yang tidak kebayar dari Laci) dan "cara
    baru" (hutang = beban yang tidak ditutup Laba Kotor) menghasilkan angka
    yang sama -- sehingga test tidak akan pernah membedakan keduanya.

    Di sini Laci 375.000 tapi Laba Kotor hanya 275.000 (ada DP 100.000 yang
    ikut masuk laci). Dua aturan harus memberi jawaban BERBEDA:
        cara lama -> hutang 605.000 - 375.000 = 230.000   (SALAH)
        cara baru -> hutang 605.000 - 275.000 = 330.000   (BENAR)
    """
    import finance
    import expense_debt
    import cash

    p = _skenario_dengan_dp(db, "DP-DI-LACI", 600000, 325000, 405000, 200000,
                            dp=100000)
    # Diperiksa SEBELUM Beban dibayar: di titik ini Laci masih 375.000.
    assert to_decimal(cash.saldo_laci(db)) == to_decimal(375000), \
        "Laci harus 375.000 supaya berbeda dari Laba Kotor 275.000"

    core = finance.compute_finance_core(db, p.start_at, p.end_at, freeze=True)
    db.commit()

    assert to_decimal(core["laba_kotor"]) == to_decimal(275000)
    assert to_decimal(core["total_beban"]) == to_decimal(605000)
    assert to_decimal(expense_debt.saldo_hutang(db)) == to_decimal(330000), \
        "hutang harus dihitung dari Laba Kotor (330.000), bukan sisa Laci (230.000)"


def test_laba_kotor_cukup_tetap_tanpa_hutang_walau_laci_kurang(db):
    """Laba Kotor >= Beban = target CTO tercapai, walau uangnya belum cukup.

    Cara lama akan mencatat hutang di sini karena Laci tidak cukup. Aturan
    Owner menyatakan Laba Kotor cukup berarti target tercapai, jadi hutang
    harus nol; sisa yang belum terbayar dilaporkan lewat `kekurangan` untuk
    diputuskan manual oleh user, bukan dicatat sebagai Hutang Beban.

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