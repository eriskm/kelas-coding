# -*- coding: utf-8 -*-
"""Owner: "pakai periode, karena selama pengujian dalam satu hari bisa berkali-
kali tutup kas."

`period_key` dulu memakai tanggal (`start.strftime("%Y-%m-%d")`). Dua KasPeriod
yang jatuh di tanggal sama -- hal yang PASTI terjadi kalau Tutup Kas diulang
sehari -- menghasilkan kunci yang sama. Karena kunci itu dipakai sebagai
`ref_id` penanda idempotensi Beban, periode kedua terlihat "sudah bayar" dan
Beban-nya tidak pernah keluar dari Laci.

Bug ini nyata di DB produksi: KasPeriod 4 dan 5 sama-sama ber-key "2026-10-13",
sehingga satu entri `beban_periode/2026-10-13` memenuhi keduanya.
"""
from datetime import datetime, timedelta

import pytest
from money import to_decimal, ZERO

from money import quantize


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


def _buat_periode(s, mulai):
    import models as m

    s.add(m.KasPeriod(start_at=mulai, end_at=mulai + timedelta(days=1),
                      status="OPEN"))
    s.commit()
    s.expire_all()
    return s.query(m.KasPeriod).filter(
        m.KasPeriod.start_at == mulai).one()


def test_kunci_berbeda_walau_satu_hari(db):
    """Dua periode di hari yang sama WAJIB punya kunci berbeda."""
    import finance

    hari_yang_sama = datetime(2026, 8, 1, 9, 0, 0)
    p1 = _buat_periode(db, hari_yang_sama)
    p2 = _buat_periode(db, hari_yang_sama + timedelta(hours=2))

    k1 = finance.period_key(db, p1.start_at, p1.end_at)
    k2 = finance.period_key(db, p2.start_at, p2.end_at)

    assert k1 != k2, (
        "dua periode pada hari yang sama tidak boleh memakai kunci yang sama")
    assert k1 == "kas_period:%d" % p1.id
    assert k2 == "kas_period:%d" % p2.id


def test_kunci_cukup_banyak_meski_beruntun(db):
    import finance

    mulai = datetime(2026, 8, 1, 16, 0, 0)
    kunci = []
    for i in range(5):
        p = _buat_periode(db, mulai + timedelta(hours=2 * i))
        kunci.append(finance.period_key(db, p.start_at, p.end_at))
    assert len(set(kunci)) == 5, "tiap Tutup Kas harus punya kunci sendiri"


def test_kunci_legacy_tetap_bisa_dibaca(db):
    """Baris beku versi lama (kunci tanggal) tidak boleh terduplikasi."""
    import finance
    import models as m

    mulai = datetime(2026, 8, 1, 16, 0, 0)
    p = _buat_periode(db, mulai)
    kunci_baru = finance.period_key(db, p.start_at, p.end_at)
    kunci_lama = finance.legacy_period_key(mulai)

    db.add(m.ExpensePeriod(periode=kunci_lama, kategori="Gaji",
                           nama_beban="Lama", nilai=to_decimal(500000),
                           dibebankan_pada=datetime.now()))
    db.commit()

    hasil = finance.freeze_expenses_for_period(db, p.start_at, p.end_at,
                                              commit=False)
    assert hasil["dibekukan"] == 0, (
        "baris beku versi lama harus dikenali, bukan dibekukan ulang")
    assert kunci_baru != kunci_lama


def test_beku_versi_lama_tidak_menahan_periode_yang_masih_jalan(db):
    """Periode OPEN tidak boleh "mewarisi" beku versi lama milik periode lain.

    Kalau boleh, periode baru yang jatuh di tanggal sama dengan periode lama
    akan terlihat sudah beku -- dan Beban-nya tidak pernah dibayar. Persis
    kegagalan yang terjadi di DB produksi: KasPeriod 5 (OPEN) tertahan baris
    beku milik KasPeriod 4.
    """
    import finance
    import models as m

    mulai = datetime(2026, 8, 1, 16, 0, 0)
    p_lama = _buat_periode(db, mulai)
    p_lama.status = "CLOSED"
    db.add(m.Expense(kategori="Gaji", uraian="Gaji bulanan",
                     nilai=to_decimal(500000), created_at=mulai,
                     recurring=True))
    db.add(m.ExpensePeriod(periode=finance.legacy_period_key(mulai),
                           kategori="Gaji", nama_beban="Lama",
                           nilai=to_decimal(500000),
                           dibebankan_pada=datetime.now()))
    db.commit()

    # Periode baru, masih OPEN, DI HARI YANG SAMA (hanya jamnya beda) --
    # supaya kunci versi lamanya ikut bentrok, persis kondisi produksi.
    p_baru = _buat_periode(db, mulai + timedelta(hours=2))
    assert p_baru.status == "OPEN"
    assert finance.legacy_period_key(p_baru.start_at) == \
        finance.legacy_period_key(p_lama.start_at), \
        "kedua periode harus jatuh di tanggal yang sama agar kunci lama bentrok"

    hasil = finance.freeze_expenses_for_period(db, p_baru.start_at,
                                               p_baru.end_at, commit=True)
    assert hasil["dibekukan"] > 0, (
        "periode OPEN harus dibekukan sendiri, bukan memakai beku versi lama")

    kunci_baru = finance.period_key(db, p_baru.start_at, p_baru.end_at)
    assert db.query(m.ExpensePeriod).filter(
        m.ExpensePeriod.periode == kunci_baru).count() > 0


def test_beban_tiap_periode_dibayar_masing_masing(db):
    """Inilah bug yang ketahuan di produksi: periode kedua tidak bayar Beban."""
    import finance
    import models as m
    from expense_debt import saldo_hutang

    mulai = datetime(2026, 8, 1, 9, 0, 0)
    p1 = _buat_periode(db, mulai)
    p2 = _buat_periode(db, mulai + timedelta(hours=1))

    for kategori, nilai in (("Gaji", 300000), ("Operasional", 200000)):
        db.add(m.Expense(kategori=kategori, uraian="X", nilai=to_decimal(nilai),
                         created_at=mulai, recurring=True))
    db.commit()

    core1 = finance.compute_finance_core(db, p1.start_at, p1.end_at, freeze=True)
    core2 = finance.compute_finance_core(db, p2.start_at, p2.end_at, freeze=True)
    db.commit()

    assert to_decimal(core1["total_beban"]) == to_decimal(500000)
    assert to_decimal(core2["total_beban"]) == to_decimal(500000), (
        "periode kedua harus punya kewajiban Beban sendiri")

    # Dua periode, dua hutang terpisah.
    rows = db.query(m.ExpenseDebtPeriod).all()
    assert len(rows) == 2, (
        "tiap periode harus punya baris hutang sendiri, bukan berbagi satu")
    assert to_decimal(saldo_hutang(db)) == to_decimal(1000000)