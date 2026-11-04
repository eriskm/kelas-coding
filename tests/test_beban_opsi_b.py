# -*- coding: utf-8 -*-
"""Test Pembayaran Beban Otomatis saat CASH - Opsi B (Owner Decision 2026-11-02).

Aturan Bisnis Opsi B:
1. Uang DP pelanggan lain di laci adalah dana titipan yang tidak boleh disentuh.
2. Ketika transaksi servis lunas (CASH), Modal Part/Jasa/Lain langsung keluar (OD-LOCK-01).
3. Laba kotor dari unit yang baru lunas (final_price - modal) otomatis dipakai mencicil
   Beban periode yang belum terbayar: min(sisa_beban, laba_unit).
4. Pemotongan beban per unit bersifat idempoten: memproses ulang order tidak boleh
   membayar beban dua kali untuk unit yang sama.
5. Jika sisa beban sudah lunas, sisa laba tetap berada di laci sebagai kas toko.
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
    folder = tempfile.mkdtemp(prefix="opsib_")
    eng = create_engine("sqlite:///%s" % os.path.join(folder, "opsib.db"))
    Base.metadata.create_all(bind=eng)
    session = sessionmaker(bind=eng)()
    try:
        yield session
    finally:
        session.close()


def test_opsi_b_beban_dicicil_dari_laba_unit_walau_ada_dp_tertahan(fresh_db):
    """Skenario:
    - DP unit lain tertahan di laci: 500.000 (titipan DP).
    - Beban periode: 400.000 (Gaji + Ops).
    - Unit baru lunas: final_price 250.000, part_cost 100.000, modal_jasa 25.000 (laba = 125.000).
    - Hasil: Modal keluar 125.000, Beban keluar 125.000 (persis sebesar laba unit).
    - DP 500.000 tetap utuh di laci. Sisa beban menjadi 275.000.
    """
    db = fresh_db
    import models as m
    import cash as cash_mod
    import beban_bayar
    from routers.orders import _bayar_beban_periode_di_cash

    now = datetime(2026, 11, 2, 10, 0, 0)
    p = m.KasPeriod(start_at=now, end_at=now + timedelta(days=1), status="OPEN")
    db.add(p)
    cust1 = m.Customer(name="Pelanggan DP", phone="08111", created_at=now)
    cust2 = m.Customer(name="Pelanggan Lunas", phone="08222", created_at=now)
    db.add_all([cust1, cust2])
    db.flush()

    # Beban periode 400.000
    db.add(m.Expense(kategori="Gaji", uraian="Gaji Teknisi", nilai=Decimal("300000"), created_at=now))
    db.add(m.Expense(kategori="Operasional", uraian="Listrik", nilai=Decimal("100000"), created_at=now))
    db.flush()

    # 1. Unit 1 menerima DP 500.000 (masih DIPROSES, belum lunas)
    order_dp = m.ServiceOrder(
        no_servis="SV-DP-HOLD", customer_id=cust1.id, device="HP Titip DP",
        status="KONFIRMASI", unit_status="DIPROSES", service_date=now.date(),
        estimate=Decimal("1000000"), final_price=Decimal("1000000"),
        part_cost=ZERO, modal_jasa=ZERO, modal_lainnya=ZERO, created_at=now
    )
    db.add(order_dp)
    db.flush()
    pay_dp = m.Payment(service_order_id=order_dp.id, amount=Decimal("500000"),
                       kind="DP", method="CASH", created_at=now)
    db.add(pay_dp)
    db.flush()
    cash_mod.catat_penerimaan(db, pay_dp, actor="kasir")
    db.flush()

    assert cash_mod.saldo_laci(db) == Decimal("500000.00")
    assert cash_mod.saldo_titipan_dp(db) == Decimal("500000.00")
    assert cash_mod.saldo_laci_milik_toko(db) == Decimal("0.00")

    # 2. Unit 2 lunas di kasir
    order_lunas = m.ServiceOrder(
        no_servis="SV-LUNAS-01", customer_id=cust2.id, device="HP Selesai",
        status="CASH", unit_status="DIAMBIL", service_date=now.date(),
        estimate=Decimal("250000"), final_price=Decimal("250000"),
        part_cost=Decimal("100000"), modal_jasa=Decimal("25000"), modal_lainnya=ZERO,
        created_at=now
    )
    db.add(order_lunas)
    db.flush()
    pay_lunas = m.Payment(service_order_id=order_lunas.id, amount=Decimal("250000"),
                          kind="PELUNASAN", method="CASH", created_at=now)
    db.add(pay_lunas)
    db.flush()
    cash_mod.catat_penerimaan(db, pay_lunas, actor="kasir")
    cash_mod.catat_modal(db, order_lunas, actor="kasir")
    db.flush()

    # Fisik laci sekarang: 500k + 250k - 125k modal = 625k
    assert cash_mod.saldo_laci(db) == Decimal("625000.00")

    # Jalankan bayar beban di CASH
    res = _bayar_beban_periode_di_cash(db, order_lunas, actor="kasir")
    db.flush()

    # Opsi B: beban dibayar dari laba unit (125.000)
    assert res["dari_laci"] == Decimal("125000.00"), "Beban harus dicicil sebesar laba kotor unit 125rb!"
    assert res["total_beban"] == Decimal("400000.00")
    assert res["sudah_dibayar"] == Decimal("0.00")

    # Saldo fisik laci setelah potong beban: 625k - 125k = 500k (pas utuh sebesar uang DP unit 1)
    assert cash_mod.saldo_laci(db) == Decimal("500000.00"), "Saldo laci harus 500rb utuh untuk titipan DP!"
    assert cash_mod.saldo_titipan_dp(db) == Decimal("500000.00")

    # Sisa beban periode menjadi 275.000
    assert beban_bayar.sisa_kewajiban_beban(db, now, now + timedelta(days=1),
                                           f"kas_period:{p.id}", Decimal("400000")) == Decimal("275000.00")


def test_opsi_b_beban_tetap_keluar_meski_ada_defisit_titipan_dp_global(fresh_db):
    """Skenario Kasus Nyata di Toko (persis kondisi servisku.db):
    - Ada DP tertahan dari order-order lain sebesar 500.000.
    - Kas fisik laci sebelum transaksi hanya 100.000 (akibat pengeluaran masa lalu).
    - Saldo_laci_milik_toko = max(0, 100k - 500k) = 0.
    - Masuk unit servis lunas: final_price 200.000, modal 50.000 (laba kotor unit = 150.000).
    - Fisik laci menjadi: 100k + 200k - 50k = 250.000.
    - Karena fisik laci (250k) masih di bawah total DP tertahan (500k), saldo_laci_milik_toko tetap 0.
    - Di aturan lama: Beban diblokir total (keluar 0).
    - Di OPSI B (Owner 2026-11-02): Beban tetap dicicil sebesar laba kotor unit ini (150.000)
      karena uang 150.000 ini adalah laba bersih baru dari unit bersangkutan!
    """
    db = fresh_db
    import models as m
    import cash as cash_mod
    import beban_bayar
    from routers.orders import _bayar_beban_periode_di_cash

    now = datetime(2026, 11, 2, 10, 0, 0)
    p = m.KasPeriod(start_at=now, end_at=now + timedelta(days=1), status="OPEN")
    db.add(p)
    cust1 = m.Customer(name="Cust DP Tertahan", phone="08111", created_at=now)
    cust2 = m.Customer(name="Cust Unit Baru", phone="08222", created_at=now)
    db.add_all([cust1, cust2])
    db.flush()

    # Beban periode 300.000
    db.add(m.Expense(kategori="Gaji", uraian="Gaji", nilai=Decimal("300000"), created_at=now))
    db.flush()

    # Unit 1 terima DP 500.000 (belum lunas)
    order_dp = m.ServiceOrder(
        no_servis="SV-DP-DEFISIT", customer_id=cust1.id, device="HP DP",
        status="KONFIRMASI", unit_status="DIPROSES", service_date=now.date(),
        estimate=Decimal("1000000"), final_price=Decimal("1000000"),
        part_cost=ZERO, modal_jasa=ZERO, modal_lainnya=ZERO, created_at=now
    )
    db.add(order_dp)
    db.flush()
    pay_dp = m.Payment(service_order_id=order_dp.id, amount=Decimal("500000"),
                       kind="DP", method="CASH", created_at=now)
    db.add(pay_dp)
    db.flush()
    cash_mod.catat_penerimaan(db, pay_dp, actor="kasir")

    # Pengeluaran masa lalu 400.000 keluar dari laci sehingga sisa fisik laci tinggal 100.000
    cash_mod.catat_mutasi(db, cash_mod.LAYER_LACI, "Keluar", "Pengeluaran Masa Lalu",
                          "Pengeluaran masa lalu", Decimal("400000"), check_saldo=False)
    db.flush()

    assert cash_mod.saldo_laci(db) == Decimal("100000.00")
    assert cash_mod.saldo_titipan_dp(db) == Decimal("500000.00")
    assert cash_mod.saldo_laci_milik_toko(db) == Decimal("0.00")

    # Unit 2 lunas: final_price 200.000, modal 50.000 -> laba kotor 150.000
    order_lunas = m.ServiceOrder(
        no_servis="SV-BARU-01", customer_id=cust2.id, device="HP Selesai Baru",
        status="CASH", unit_status="DIAMBIL", service_date=now.date(),
        estimate=Decimal("200000"), final_price=Decimal("200000"),
        part_cost=Decimal("50000"), modal_jasa=ZERO, modal_lainnya=ZERO,
        created_at=now
    )
    db.add(order_lunas)
    db.flush()
    pay_lunas = m.Payment(service_order_id=order_lunas.id, amount=Decimal("200000"),
                          kind="PELUNASAN", method="CASH", created_at=now)
    db.add(pay_lunas)
    db.flush()
    cash_mod.catat_penerimaan(db, pay_lunas, actor="kasir")
    cash_mod.catat_modal(db, order_lunas, actor="kasir")
    db.flush()

    # Fisik laci sekarang: 100k + 200k - 50k = 250k.
    # Namun saldo_laci_milik_toko = max(0, 250k - 500k) = 0!
    assert cash_mod.saldo_laci(db) == Decimal("250000.00")
    assert cash_mod.saldo_laci_milik_toko(db) == Decimal("0.00")

    # Jalankan bayar beban di CASH
    res = _bayar_beban_periode_di_cash(db, order_lunas, actor="kasir")
    db.flush()

    # OPSI B: Harus tetap keluar 150.000 dari laba unit baru ini!
    assert res["dari_laci"] == Decimal("150000.00"), (
        "Beban harus keluar 150.000 dari laba unit, tidak boleh terblokir menjadi 0!"
    )
    # Fisik laci tersisa: 250k - 150k = 100k (tetap tidak tersedot saldo awal laci)
    assert cash_mod.saldo_laci(db) == Decimal("100000.00")



def test_opsi_b_idempoten_replay_order_tidak_dobel_bayar_beban(fresh_db):
    """Replay event CASH untuk order yang sama tidak boleh memotong Beban dua kali."""
    db = fresh_db
    import models as m
    import cash as cash_mod
    from routers.orders import _bayar_beban_periode_di_cash

    now = datetime(2026, 11, 2, 10, 0, 0)
    p = m.KasPeriod(start_at=now, end_at=now + timedelta(days=1), status="OPEN")
    db.add(p)
    cust = m.Customer(name="Cust Replay", phone="08333", created_at=now)
    db.add(cust)
    db.flush()

    db.add(m.Expense(kategori="Operasional", uraian="Beban", nilai=Decimal("500000"), created_at=now))
    db.flush()

    order = m.ServiceOrder(
        no_servis="SV-REPLAY-1", customer_id=cust.id, device="HP Replay",
        status="CASH", unit_status="DIAMBIL", service_date=now.date(),
        estimate=Decimal("200000"), final_price=Decimal("200000"),
        part_cost=Decimal("50000"), modal_jasa=ZERO, modal_lainnya=ZERO,
        created_at=now
    )
    db.add(order)
    db.flush()
    pay = m.Payment(service_order_id=order.id, amount=Decimal("200000"),
                    kind="PELUNASAN", method="CASH", created_at=now)
    db.add(pay)
    db.flush()
    cash_mod.catat_penerimaan(db, pay, actor="kasir")
    cash_mod.catat_modal(db, order, actor="kasir")
    db.flush()

    # Panggilan 1
    res1 = _bayar_beban_periode_di_cash(db, order, actor="kasir")
    db.flush()
    assert res1["dari_laci"] == Decimal("150000.00")
    assert cash_mod.saldo_laci(db) == Decimal("0.00")

    # Panggilan 2 (replay)
    res2 = _bayar_beban_periode_di_cash(db, order, actor="kasir")
    db.flush()
    assert res2["dari_laci"] == Decimal("0.00"), "Replay tidak boleh memotong beban lagi!"
    assert cash_mod.saldo_laci(db) == Decimal("0.00")


def test_opsi_b_beban_terpenuhi_sisa_laba_tetap_di_laci(fresh_db):
    """Jika sisa beban periode lebih kecil dari laba unit, hanya dipotong sebesar sisa beban."""
    db = fresh_db
    import models as m
    import cash as cash_mod
    from routers.orders import _bayar_beban_periode_di_cash

    now = datetime(2026, 11, 2, 10, 0, 0)
    p = m.KasPeriod(start_at=now, end_at=now + timedelta(days=1), status="OPEN")
    db.add(p)
    cust = m.Customer(name="Cust Laba Besar", phone="08444", created_at=now)
    db.add(cust)
    db.flush()

    # Beban hanya 50.000
    db.add(m.Expense(kategori="Operasional", uraian="Beban Kecil", nilai=Decimal("50000"), created_at=now))
    db.flush()

    # Laba unit = 200.000 - 50.000 = 150.000
    order = m.ServiceOrder(
        no_servis="SV-LABA-BESAR", customer_id=cust.id, device="HP Big Profit",
        status="CASH", unit_status="DIAMBIL", service_date=now.date(),
        estimate=Decimal("200000"), final_price=Decimal("200000"),
        part_cost=Decimal("50000"), modal_jasa=ZERO, modal_lainnya=ZERO,
        created_at=now
    )
    db.add(order)
    db.flush()
    pay = m.Payment(service_order_id=order.id, amount=Decimal("200000"),
                    kind="PELUNASAN", method="CASH", created_at=now)
    db.add(pay)
    db.flush()
    cash_mod.catat_penerimaan(db, pay, actor="kasir")
    cash_mod.catat_modal(db, order, actor="kasir")
    db.flush()

    res = _bayar_beban_periode_di_cash(db, order, actor="kasir")
    db.flush()

    # Hanya bayar 50.000 (sesuai sisa beban)
    assert res["dari_laci"] == Decimal("50000.00")

    # Saldo laci: 200k masuk - 50k modal - 50k beban = 100k sisa laba tetap di laci!
    assert cash_mod.saldo_laci(db) == Decimal("100000.00")


def test_opsi_b_unit_tanpa_laba_tidak_bayar_beban(fresh_db):
    """Unit servis impas/tanpa laba (laba = 0) tidak mengeluarkan uang untuk beban."""
    db = fresh_db
    import models as m
    import cash as cash_mod
    from routers.orders import _bayar_beban_periode_di_cash

    now = datetime(2026, 11, 2, 10, 0, 0)
    p = m.KasPeriod(start_at=now, end_at=now + timedelta(days=1), status="OPEN")
    db.add(p)
    cust = m.Customer(name="Cust Impas", phone="08555", created_at=now)
    db.add(cust)
    db.flush()

    db.add(m.Expense(kategori="Operasional", uraian="Beban", nilai=Decimal("100000"), created_at=now))
    db.flush()

    # final_price 100k, part_cost 100k -> laba = 0
    order = m.ServiceOrder(
        no_servis="SV-IMPAS", customer_id=cust.id, device="HP Modal Penuh",
        status="CASH", unit_status="DIAMBIL", service_date=now.date(),
        estimate=Decimal("100000"), final_price=Decimal("100000"),
        part_cost=Decimal("100000"), modal_jasa=ZERO, modal_lainnya=ZERO,
        created_at=now
    )
    db.add(order)
    db.flush()
    pay = m.Payment(service_order_id=order.id, amount=Decimal("100000"),
                    kind="PELUNASAN", method="CASH", created_at=now)
    db.add(pay)
    db.flush()
    cash_mod.catat_penerimaan(db, pay, actor="kasir")
    cash_mod.catat_modal(db, order, actor="kasir")
    db.flush()

    res = _bayar_beban_periode_di_cash(db, order, actor="kasir")
    db.flush()

    assert res["dari_laci"] == Decimal("0.00")
    assert cash_mod.saldo_laci(db) == Decimal("0.00")


def test_tutup_kas_settles_beban_from_laba_kotor_when_dp_present(fresh_db):
    """Saat Tutup Kas, sisa laba kotor periode yang belum terserap beban otomatis
    digunakan untuk melunasi Beban toko, sehingga saldo kas toko kembali ke 0
    (tidak tertinggal di laci sebagai saldo sistem yang membingungkan).
    """
    db = fresh_db
    import models as m
    import cash as cash_mod
    import closing
    from routers.dashboard import compute_finance

    now = datetime(2026, 11, 2, 10, 0, 0)
    p = m.KasPeriod(start_at=now, end_at=now + timedelta(days=1), status="OPEN")
    db.add(p)
    cust1 = m.Customer(name="Cust DP Tertahan", phone="08111", created_at=now)
    cust2 = m.Customer(name="Cust Selesai", phone="08222", created_at=now)
    db.add_all([cust1, cust2])
    db.flush()

    # Beban periode 500.000
    db.add(m.Expense(kategori="Operasional", uraian="Beban Toko", nilai=Decimal("500000"), created_at=now))
    db.flush()

    # 1. Order DP 500.000 (belum lunas)
    order_dp = m.ServiceOrder(
        no_servis="SV-DP-CLOSING", customer_id=cust1.id, device="HP DP",
        status="KONFIRMASI", unit_status="DIPROSES", service_date=now.date(),
        estimate=Decimal("1000000"), final_price=Decimal("1000000"),
        part_cost=ZERO, modal_jasa=ZERO, modal_lainnya=ZERO, created_at=now
    )
    db.add(order_dp)
    db.flush()
    pay_dp = m.Payment(service_order_id=order_dp.id, amount=Decimal("500000"),
                       kind="DP", method="CASH", created_at=now)
    db.add(pay_dp)
    db.flush()
    cash_mod.catat_penerimaan(db, pay_dp, actor="kasir")

    # 2. Order 2 selesai di periode ini: final_price 200k, modal 50k -> laba kotor 150k
    # Anggap saat CASH beban belum terbayar (misal order dibuat lewat jalur lama)
    order2 = m.ServiceOrder(
        no_servis="SV-DONE-CLOSING", customer_id=cust2.id, device="HP Done",
        status="CASH", unit_status="DIAMBIL", service_date=now.date(),
        estimate=Decimal("200000"), final_price=Decimal("200000"),
        part_cost=Decimal("50000"), modal_jasa=ZERO, modal_lainnya=ZERO,
        created_at=now
    )
    db.add(order2)
    db.flush()
    pay2 = m.Payment(service_order_id=order2.id, amount=Decimal("200000"),
                     kind="PELUNASAN", method="CASH", created_at=now)
    db.add(pay2)
    db.flush()
    cash_mod.catat_penerimaan(db, pay2, actor="kasir")
    cash_mod.catat_modal(db, order2, actor="kasir")
    db.flush()

    # Total laci: 500k DP + 150k laba = 650k
    assert cash_mod.saldo_laci(db) == Decimal("650000.00")
    # Kas bebas toko (setelah karantina DP) = 150k
    assert cash_mod.saldo_laci_milik_toko(db) == Decimal("150000.00")

    # Jalankan Tutup Kas
    import beban_bayar
    res = closing.tutup_periode(db, p, counted=None, oleh="Admin", compute_finance=compute_finance)
    db.flush()

    # Beban terbayar dari laci harus menyerap 150.000 laba kotor toko
    penyelesaian = res["snapshot"]["penyelesaian"]
    assert beban_bayar._total_dibayar(db, f"kas_period:{p.id}") == Decimal("150000.00"), "Total beban keluar dari laci harus 150k menyerap laba kotor toko!"
    assert penyelesaian["beban_belum_terbayar"] == "350000.00", "Sisa beban 350k menjadi defisit/hutang beban"

    # Saldo fisik laci tersisa persis 500.000 (utuh uang DP titipan pelanggan!)
    assert cash_mod.saldo_laci(db) == Decimal("500000.00")
    # Kas toko di laci kembali ke NOL pas
    assert cash_mod.saldo_laci_milik_toko(db) == Decimal("0.00")


def test_buka_kas_auto_inits_attendance_and_beban(fresh_db):
    """Ketika periode kas dibuka (Buka Kas), seluruh karyawan aktif otomatis
    berstatus 'Hadir' dan Beban Gaji otomatis dibekukan ke ExpensePeriod.
    """
    db = fresh_db
    import models as m
    import closing
    from routers.dashboard import compute_finance, batas_periode
    from finance import compute_finance_core

    now = datetime(2026, 11, 2, 10, 0, 0)
    # Tambah karyawan aktif dengan gaji_harian
    u1 = m.User(username="tech1", display_name="Teknisi Satu", role="TEKNISI",
                passcode_hash="h1", passcode_salt="s1",
                active=1, gaji_harian=Decimal("150000"))
    u2 = m.User(username="tech2", display_name="Teknisi Dua", role="TEKNISI",
                passcode_hash="h2", passcode_salt="s2",
                active=1, gaji_harian=Decimal("100000"))
    db.add_all([u1, u2])
    db.flush()

    # Buka periode baru lewat closing
    p = m.KasPeriod(start_at=now, end_at=now + timedelta(days=1), status="OPEN")
    db.add(p)
    db.flush()

    # Tutup periode 1 dan buka periode 2
    res = closing.tutup_periode(db, p, counted=None, oleh="Admin", compute_finance=compute_finance)
    db.flush()

    new_pid = res["new_period"]["id"]
    p2 = db.query(m.KasPeriod).filter(m.KasPeriod.id == new_pid).first()
    assert p2 is not None
    assert p2.status == "OPEN"

    # Periksa kehadiran otomatis terbentuk untuk periode 2
    atts = db.query(m.UserAttendance).filter(m.UserAttendance.kas_period_id == p2.id).all()
    assert len(atts) == 2, "Harus ada 2 entri presensi untuk periode baru"
    assert all(a.hadir for a in atts), "Semua karyawan harus default Hadir saat Buka Kas"

    # Periksa Beban Gaji otomatis terhitung di compute_finance_core
    st, en = batas_periode(p2)
    fin = compute_finance_core(db, st, en)
    assert fin["beban_gaji"] == Decimal("250000.00"), "Beban gaji harus otomatis 250k (150k + 100k) saat Buka Kas!"


def test_ubah_manual_absensi_mengubah_beban_secara_otomatis(fresh_db):
    """Jika ada karyawan yang tidak hadir dan diubah manual oleh Admin,
    Beban Gaji toko otomatis berkurang sesuai kehadiran aktual.
    """
    db = fresh_db
    import models as m
    from routers.attendance import init_period_attendance, toggle_attendance, AttendanceToggleIn
    from routers.dashboard import batas_periode
    from finance import compute_finance_core

    now = datetime(2026, 11, 2, 10, 0, 0)
    admin = m.User(username="admin1", display_name="Admin Toko", role="ADMIN",
                   passcode_hash="ha", passcode_salt="sa", active=1)
    u1 = m.User(username="tech1", display_name="Teknisi A", role="TEKNISI",
                passcode_hash="h1", passcode_salt="s1", active=1, gaji_harian=Decimal("150000"))
    u2 = m.User(username="tech2", display_name="Teknisi B", role="TEKNISI",
                passcode_hash="h2", passcode_salt="s2", active=1, gaji_harian=Decimal("100000"))
    db.add_all([admin, u1, u2])
    db.flush()

    p = m.KasPeriod(start_at=now, end_at=now + timedelta(days=1), status="OPEN")
    db.add(p)
    db.flush()

    # Inisialisasi awal Buka Kas: dua-duanya Hadir (Total Gaji = 250k)
    init_period_attendance(db, p.id)
    st, en = batas_periode(p)
    fin1 = compute_finance_core(db, st, en)
    assert fin1["beban_gaji"] == Decimal("250000.00")

    # Admin ubah manual: Teknisi B Libur / Tidak Masuk (gaji_harian 100k dinonaktifkan)
    toggle_attendance(
        payload=AttendanceToggleIn(user_id=u2.id, hadir=False, keterangan="Izin Sakit"),
        db=db,
        admin=admin
    )
    db.flush()

    # Beban Gaji otomatis menyesuaikan menjadi hanya 150k (hanya Teknisi A yang hadir)!
    fin2 = compute_finance_core(db, st, en)
    assert fin2["beban_gaji"] == Decimal("150000.00"), "Beban gaji harus otomatis turun ke 150k setelah diubah manual!"


def test_buka_kas_membekukan_operasional_dan_gaji_tanpa_duplikat(fresh_db):
    """Saat Tutup Kas membuka periode baru, baik Beban Operasional (katalog Expense)
    maupun Beban Gaji (presensi UserAttendance) wajib ikut terbawa ke ExpensePeriod
    periode baru tanpa menggandakan baris gaji.
    """
    db = fresh_db
    import models as m
    import closing
    from routers.dashboard import compute_finance, batas_periode
    from finance import compute_finance_core

    now = datetime(2026, 11, 3, 10, 0, 0)
    u1 = m.User(username="tech_op1", display_name="Teknisi Satu", role="TEKNISI",
                passcode_hash="h1", passcode_salt="s1",
                active=1, gaji_harian=Decimal("150000"))
    exp_ops = m.Expense(kategori="Operasional", uraian="Listrik & Wifi Harian",
                        nilai=Decimal("55000"), recurring=True)
    db.add_all([u1, exp_ops])
    db.flush()

    p = m.KasPeriod(start_at=now, end_at=now + timedelta(days=1), status="OPEN")
    db.add(p)
    db.flush()

    res = closing.tutup_periode(db, p, counted=None, oleh="Admin", compute_finance=compute_finance)
    db.flush()

    new_pid = res["new_period"]["id"]
    p2 = db.query(m.KasPeriod).filter(m.KasPeriod.id == new_pid).first()
    st, en = batas_periode(p2)
    fin = compute_finance_core(db, st, en)

    assert fin["beban_gaji"] == Decimal("150000.00"), "Beban gaji 150k wajib tercatat tepat 1x (tidak terduplikasi)"
    assert fin["beban_operasional"] == Decimal("55000.00"), "Beban operasional 55k wajib ikut terbawa ke periode baru"
    assert fin["total_beban"] == Decimal("205000.00")


def test_perubahan_beban_periode_open_otomatis_rekonsiliasi_distribusi(fresh_db):
    """Jika di tengah periode OPEN distribusi sudah terbentuk (CTO tercapai),
    lalu Admin menambah/mengubah/menghapus Beban Operasional di periode berjalan,
    maka ExpensePeriod dan Distribution otomatis tersinkronisasi (topdown/topup).
    """
    db = fresh_db
    import models as m
    import cash as cash_mod
    import distribution as dist_mod
    from routers.dashboard import batas_periode
    from finance import compute_finance_core, sync_open_period_expense_item

    now = datetime(2026, 11, 4, 10, 0, 0)
    p = m.KasPeriod(start_at=now, end_at=now + timedelta(days=1), status="OPEN")
    cust = m.Customer(name="Budi", phone="08123", created_at=now)
    db.add_all([p, cust])
    db.flush()

    # Order 1: Omzet 1.000.000, Modal 200.000 -> Laba Kotor 800.000
    o = m.ServiceOrder(
        no_servis="SRV-SYNC-1", customer_id=cust.id, device="A55", status="CASH",
        unit_status="DIAMBIL", service_date=now.date(), taken_at=now + timedelta(hours=1),
        final_price=Decimal("1000000"), estimate=Decimal("1000000"),
        part_cost=Decimal("150000"), modal_jasa=Decimal("50000"), modal_lainnya=Decimal("0"),
        created_at=now
    )
    db.add(o)
    db.flush()
    pay = m.Payment(service_order_id=o.id, kind="PELUNASAN", amount=Decimal("1000000"),
                    method="CASH", created_at=now + timedelta(hours=1))
    db.add(pay)
    db.flush()
    cash_mod.catat_penerimaan(db, pay)
    cash_mod.catat_modal(db, o)

    # Beban awal: Operasional 100.000
    exp1 = m.Expense(kategori="Operasional", uraian="Sewa", nilai=Decimal("100000"), recurring=True)
    db.add(exp1)
    db.flush()

    st, en = batas_periode(p)
    core1 = compute_finance_core(db, st, en)
    assert core1["laba_bersih"] == Decimal("700000.00")

    # Bentuk distribusi awal (Laba Bersih 700.000)
    res_dist1 = dist_mod.pastikan_otomatis(
        db, core1["periode"], core1["laba_bersih"], cto_tercapai=True, kas_period_id=p.id, oleh="Admin"
    )
    assert res_dist1["dibentuk"] is True
    assert res_dist1["distribution"].laba_bersih == Decimal("700000.00")

    # Admin menambah beban operasional baru Rp 200.000 di tengah periode OPEN
    exp2 = m.Expense(kategori="Operasional", uraian="Token Listrik", nilai=Decimal("200000"), recurring=False)
    db.add(exp2)
    db.flush()
    sync_open_period_expense_item(db, exp2, action="upsert", oleh="Admin")

    core2 = compute_finance_core(db, st, en)
    assert core2["total_beban"] == Decimal("300000.00")
    assert core2["laba_bersih"] == Decimal("500000.00")

    dist_row = dist_mod.sudah_ada(db, core2["periode"], p.id)
    assert dist_row.laba_bersih == Decimal("500000.00"), "Alokasi distribusi wajib otomatis turun (topdown) mengikuti Laba Bersih 500k!"
    assert dist_row.pengelola == Decimal("150000.00")


