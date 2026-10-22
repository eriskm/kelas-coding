# -*- coding: utf-8 -*-
"""OD-LOCK-13: Karantina Uang Titipan DP & Larangan Menutup Beban dari DP.

Aturan bisnis:
1. Uang DP adalah dana titipan pelanggan (bukan kas operasional toko).
2. DP tidak boleh dipakai untuk menutup Beban periode berjalan maupun periode lalu.
3. Pembayaran Beban dari Laci hanya boleh memakai Kas Bebas Milik Toko
   (saldo_laci - saldo_titipan_dp).
4. Jika Kas Bebas Milik Toko = 0, pembayaran Beban dari Laci adalah 0,
   dan 100% Beban dicatat sebagai Hutang Beban.
"""
import os
import tempfile
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from money import ZERO, to_decimal


@pytest.fixture
def fresh_db():
    """Database terisolasi kosong untuk pengujian karantina DP."""
    folder = tempfile.mkdtemp(prefix="od13_")
    eng = create_engine("sqlite:///%s" % os.path.join(folder, "od13.db"))
    Base.metadata.create_all(bind=eng)
    session = sessionmaker(bind=eng)()
    try:
        yield session
    finally:
        session.close()


def test_beban_tidak_boleh_memakai_uang_dp_murni(fresh_db):
    """Skenario 1: Laci hanya berisi uang DP (500rb).

    Beban 300rb harus menolak mengambil dari Laci:
    - dari_laci == 0
    - hutang == 300rb
    - saldo fisik laci tetap 500rb utuh
    - saldo titipan DP tetap 500rb utuh
    """
    db = fresh_db
    import models as m
    import cash as cash_mod
    import beban_bayar

    mulai = datetime(2026, 9, 1, 10, 0, 0)
    p = m.KasPeriod(start_at=mulai, end_at=mulai + timedelta(days=1), status="OPEN")
    db.add(p)
    cust = m.Customer(name="Cust DP Only", phone="081111", created_at=mulai)
    db.add(cust)
    db.flush()

    # Buat order dengan DP 500.000 (belum lunas, status KONFIRMASI)
    order = m.ServiceOrder(
        no_servis="SV-DP-TEST-1", customer_id=cust.id, device="Test Phone",
        status="KONFIRMASI", unit_status="DIPROSES", service_date=mulai.date(),
        estimate=Decimal("1000000"), final_price=Decimal("1000000"),
        part_cost=ZERO, modal_jasa=ZERO, modal_lainnya=ZERO,
        created_at=mulai
    )
    db.add(order)
    db.flush()

    # Buat payment DP 500.000 tunai (masuk laci)
    pay = m.Payment(
        service_order_id=order.id, amount=Decimal("500000"),
        kind="DP", method="CASH", created_at=mulai
    )
    db.add(pay)
    db.flush()
    cash_mod.catat_penerimaan(db, pay, actor="kasir")
    db.flush()

    # Pastikan di laci ada 500.000 fisik dan 500.000 titipan DP
    assert cash_mod.saldo_laci(db) == Decimal("500000.00")
    assert cash_mod.saldo_titipan_dp(db) == Decimal("500000.00")
    assert cash_mod.saldo_laci_milik_toko(db) == Decimal("0.00")

    # Beban 300.000
    res = beban_bayar.bayar_beban_periode(
        db, mulai, mulai + timedelta(days=1), f"kas_period:{p.id}",
        Decimal("300000"), oleh="test", kas_period_id=p.id
    )

    # Uang DP tidak boleh disentuh sepeser pun!
    assert res["dari_laci"] == Decimal("0.00"), "Beban dilarang menyedot uang DP di laci!"
    assert res["hutang"] == Decimal("300000.00"), "Sisa beban harus menjadi Hutang Beban!"
    assert cash_mod.saldo_laci(db) == Decimal("500000.00"), "Saldo fisik laci harus tetap utuh 500rb titipan DP!"
    assert cash_mod.saldo_titipan_dp(db) == Decimal("500000.00")


def test_beban_hanya_memakai_kas_bebas_toko(fresh_db):
    """Skenario 2: Laci ada 500rb (300rb DP + 200rb uang operasional toko).

    Beban 350rb:
    - dari_laci == 200rb (hanya uang milik toko yang boleh terserap)
    - hutang == 150rb (sisanya jadi hutang, tidak boleh merambah ke 300rb DP)
    - saldo fisik laci setelah bayar == 300rb (DP utuh tersisa di laci)
    """
    db = fresh_db
    import models as m
    import cash as cash_mod
    import beban_bayar

    mulai = datetime(2026, 9, 2, 10, 0, 0)
    p = m.KasPeriod(start_at=mulai, end_at=mulai + timedelta(days=1), status="OPEN")
    db.add(p)
    cust = m.Customer(name="Cust Campur", phone="082222", created_at=mulai)
    db.add(cust)
    db.flush()

    # 1. DP 300.000 masuk laci
    order1 = m.ServiceOrder(
        no_servis="SV-DP-CAMPUR", customer_id=cust.id, device="Phone A",
        status="KONFIRMASI", unit_status="DIPROSES", service_date=mulai.date(),
        estimate=Decimal("800000"), final_price=Decimal("800000"),
        part_cost=ZERO, modal_jasa=ZERO, modal_lainnya=ZERO,
        created_at=mulai
    )
    db.add(order1)
    db.flush()
    pay1 = m.Payment(
        service_order_id=order1.id, amount=Decimal("300000"),
        kind="DP", method="CASH", created_at=mulai
    )
    db.add(pay1)
    db.flush()
    cash_mod.catat_penerimaan(db, pay1, actor="kasir")

    # 2. Uang toko 200.000 masuk laci (misal pelunasan order lunas tanpa modal)
    order2 = m.ServiceOrder(
        no_servis="SV-PELUNASAN", customer_id=cust.id, device="Phone B",
        status="CASH", unit_status="DIAMBIL", service_date=mulai.date(),
        estimate=Decimal("200000"), final_price=Decimal("200000"),
        part_cost=ZERO, modal_jasa=ZERO, modal_lainnya=ZERO,
        tanpa_modal=True, created_at=mulai
    )
    db.add(order2)
    db.flush()
    pay2 = m.Payment(
        service_order_id=order2.id, amount=Decimal("200000"),
        kind="PELUNASAN", method="CASH", created_at=mulai
    )
    db.add(pay2)
    db.flush()
    cash_mod.catat_penerimaan(db, pay2, actor="kasir")
    db.flush()

    # Total laci: 500rb, titipan DP: 300rb, milik toko: 200rb
    assert cash_mod.saldo_laci(db) == Decimal("500000.00")
    assert cash_mod.saldo_titipan_dp(db) == Decimal("300000.00")
    assert cash_mod.saldo_laci_milik_toko(db) == Decimal("200000.00")

    # Beban 350.000
    res = beban_bayar.bayar_beban_periode(
        db, mulai, mulai + timedelta(days=1), f"kas_period:{p.id}",
        Decimal("350000"), oleh="test", kas_period_id=p.id
    )

    # Hanya boleh menyerap 200.000 dari laci!
    assert res["dari_laci"] == Decimal("200000.00"), "Hanya uang toko 200rb yang boleh terpakai!"
    assert res["hutang"] == Decimal("150000.00"), "Kekurangan 150rb wajib jadi Hutang Beban!"
    assert cash_mod.saldo_laci(db) == Decimal("300000.00"), "Sisa laci harus 300rb pas sebesar uang DP!"
    assert cash_mod.saldo_titipan_dp(db) == Decimal("300000.00")


def test_dp_pelunasan_tidak_dobel_di_kas_awal_operasional(fresh_db):
    """Skenario 3: Unit dengan DP di-pelunasan di periode berjalan.

    DP 200rb masuk di periode lalu.
    Saat periode baru dibuka, kas fisik laci 200rb, tapi titipan DP juga 200rb,
    sehingga kas operasional awal toko adalah 0.

    Ketika unit tersebut di-CASH/LUNAS di periode baru:
    - omset menjadi 500rb (Harga Final penuh, memuat DP 200rb + Pelunasan 300rb).
    - kas_aset_awal_operasional HARUS TETAP 0 (tidak boleh melompat jadi 200rb).
    - Uang DP 200rb tidak boleh terhitung ganda (di kas awal DAN di omzet).
    """
    db = fresh_db
    import models as m
    import cash as cash_mod
    from routers.dashboard import compute_finance, batas_periode

    t0 = datetime(2026, 9, 1, 10, 0, 0)
    p_lama = m.KasPeriod(start_at=t0, end_at=t0 + timedelta(days=1), status="CLOSED")
    db.add(p_lama)
    cust = m.Customer(name="Cust Dobel", phone="083333", created_at=t0)
    db.add(cust)
    db.flush()

    # Order dengan DP 200rb di periode lama
    order = m.ServiceOrder(
        no_servis="SV-DOBEL-1", customer_id=cust.id, device="Phone C",
        status="KONFIRMASI", unit_status="DIPROSES", service_date=t0.date(),
        estimate=Decimal("500000"), final_price=Decimal("500000"),
        part_cost=ZERO, modal_jasa=ZERO, modal_lainnya=ZERO,
        tanpa_modal=True,
        created_at=t0
    )
    db.add(order)
    db.flush()
    pay_dp = m.Payment(
        service_order_id=order.id, amount=Decimal("200000"),
        kind="DP", method="CASH", created_at=t0
    )
    db.add(pay_dp)
    db.flush()
    mut_dp = cash_mod.catat_penerimaan(db, pay_dp, actor="kasir")
    # Pastikan kas_entry tercatat sebelum periode baru dimulai
    entry_dp = db.query(m.KasEntry).get(mut_dp["id"])
    entry_dp.created_at = t0
    db.flush()

    # Buka periode baru
    t1 = t0 + timedelta(days=1)
    p_baru = m.KasPeriod(start_at=t1, end_at=t1 + timedelta(days=1), status="OPEN")
    db.add(p_baru)
    db.flush()

    # Sebelum pelunasan: kas_aset_awal_operasional harus 0
    fin1 = compute_finance(db, *batas_periode(p_baru))
    assert fin1["kas_aset_awal_operasional"] == Decimal("0.00")

    # Pelunasan terjadi di periode baru
    t_lunas = t1 + timedelta(hours=2)
    order.status = "CASH"
    order.unit_status = "DIAMBIL"
    order.taken_at = t_lunas
    pay_lunas = m.Payment(
        service_order_id=order.id, amount=Decimal("300000"),
        kind="PELUNASAN", method="CASH", created_at=t_lunas
    )
    db.add(pay_lunas)
    db.flush()
    cash_mod.catat_penerimaan(db, pay_lunas, actor="kasir")
    db.flush()

    # Hitung finance periode baru setelah pelunasan
    fin2 = compute_finance(db, *batas_periode(p_baru))
    assert fin2["omset"] == Decimal("500000.00"), "Omzet memuat keseluruhan nilai transaksi 500rb"
    # KAS AWAL OPERASIONAL HARUS TETAP 0 (tidak boleh melonjak jadi 200rb)!
    assert fin2["kas_aset_awal_operasional"] == Decimal("0.00"), (
        "kas_aset_awal_operasional tidak boleh melonjak jadi 200rb karena DP sudah masuk di Omzet!"
    )
