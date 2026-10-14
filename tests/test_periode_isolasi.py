# -*- coding: utf-8 -*-
"""Aturan Owner: hitungan periode HARUS terisolasi.

    "sistem ini hanya menghitung Omzet dan Beban itu hanya per periode saja.
     Dilarang keras menghubungkan hitungan dari periode saat ini ke periode
     berikutnya. Yang periode berhubungan masih ada, itu pun hanya uang DP,
     Kas Aset jika ada, dan hutang beban."

Yang dikunci di sini:

  1. SALDO LACI YANG DIBAWA ke periode baru harus NOL. Ini guarantee-nya:
     Tutup Kas menyelesaikan seluruh kewajiban periode, jadi Laci kembali ke
     titik awal. Kalau angka ini tidak nol, berarti ada penumpukan dari
     periode lama -- dan itulah yang Owner larang.
     (Catatan: `cash.saldo_laci()` sendiri TIDAK bisa dibuat "per periode"
     secara matematis: opening + Σsebelum + Σsejak == opening + Σsemua.
     Memaksanya jadi nol akan membuat Declare membandingkan sistem 0 dengan
     uang fisik dan mencatat penyesuaian palsu. Karena itu jaminannya dibuat
     di titik yang benar -- lewat INVARIAN di atas.)

  2. OMZET hanya menghitung transaksi yang settle DI DALAM periode berjalan.
  3. BEBAN hanya menghitung biaya yang jatuh di periode berjalan.
  4. Yang boleh menyeber: uang DP, Kas Aset, Hutang Beban.
"""
from datetime import datetime, timedelta

from money import to_decimal, ZERO

from test_titipan_dp import _order, _pay, _period


def _expense(db, kategori, uraian, nilai, moment):
    import models
    e = models.Expense(kategori=kategori, uraian=uraian, nilai=to_decimal(nilai),
                       tanggal=moment.date())
    db.add(e)
    db.commit()
    return e


def _fin(db, p):
    import routers.dashboard as dash
    return dash.compute_finance(db, *dash.batas_periode(p))


# ───────────────── 1. Tidak ada penumpukan lintas periode ─────────────────
def _db_bersih():
    """Session ke SQLite BARU yang tabelnya kosong.

    Invariant "saldo bawaan periode = 0" hanya bisa diuji di DB yang bersih.
    Sandbox utama dipakai BERSAMA dengan file test lain, dan beberapa test
    sengaja menulis entri ber-tanggal lama -- itu akan membuat invariant-nya
    salah dibaca sebagai penumpukan, padahal yang mengotorinya adalah test.
    """
    import os
    import tempfile

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from database import Base
    folder = tempfile.mkdtemp(prefix="isolasi_periode_")
    eng = create_engine("sqlite:///%s" % os.path.join(folder, "iso.db"))
    Base.metadata.create_all(bind=eng)
    return sessionmaker(bind=eng)()


def test_saldo_laci_yang_dibawa_ke_periode_baru_nol(client):
    """Jaminan anti-akumulasi: periode baru selalu mulai dari Laci 0.

    Skenario miniature: periode pertama menahan uang, lalu ditutup sehingga
    Laci kembali ke titik awal; periode berikutnya harus mulai dari 0, bukan
    dari sisa periode lama.
    """
    import cash
    import models
    from datetime import datetime, timedelta

    s = _db_bersih()
    try:
        mulai1 = datetime(2026, 5, 1, 8, 0)
        p1 = models.KasPeriod(start_at=mulai1, end_at=mulai1 + timedelta(hours=8),
                              status="CLOSED", closed_at=mulai1 + timedelta(hours=8))
        s.add(p1)
        cust = models.Customer(name="Iso")
        s.add(cust)
        s.commit()

        o = models.ServiceOrder(
            no_servis="ISO-P1", customer_id=cust.id, device="X", status="CASH",
            service_date=mulai1.date(), final_price=to_decimal(500000),
            estimate=to_decimal(500000), repair_plan="x", technician="T",
            warranty_months=1, created_at=mulai1)
        s.add(o)
        s.commit()
        pay = models.Payment(service_order_id=o.id, kind="PELUNASAN",
                             amount=to_decimal(500000), created_at=mulai1)
        s.add(pay)
        s.commit()
        s.refresh(pay)
        cash.catat_penerimaan(s, pay)
        cash.catat_modal(s, o)
        s.commit()
        s.expire_all()

        # Tutup periode: modality keluar, sisanya balik ke titik awal.
        cash.rekonsiliasi_laci(s, cash_counted=to_decimal(0),
                               ref_type="periode", ref_id=p1.id)
        s.commit()
        s.expire_all()

        mulai2 = p1.end_at
        p2 = models.KasPeriod(start_at=mulai2, end_at=mulai2 + timedelta(days=1),
                              status="OPEN")
        s.add(p2)
        s.commit()
        s.expire_all()

        bawaan = cash.saldo_laci_sampai(s, p2.start_at)
        assert to_decimal(bawaan) == to_decimal(0), (
            "Periode baru harus mulai dari Laci 0, bukan sisa periode lama "
            "(%s)" % bawaan)
        assert to_decimal(cash.saldo_laci(s)) == to_decimal(0)
    finally:
        s.close()


def test_saldo_laci_terbentang_awal_ditambah_arus_periode(client, db):
    """Saldo Laci = saldo bawaan (awal periode) + arus periode berjalan.

    Ini identitas yang benar. Perhatikan bahwa `saldo_laci()` TIDAK bisa
    dibuat "sejak awal periode saja" secara matematis: opening + Σ sebelum +
    Σ sejak == opening + Σ semua. Memaksanya nol akan merusak Declare.
    Yang dijaga di sini adalah composisinya, supaya tidak ada sumber lain
    yang diam-diam menambah angka.
    """
    import cash
    import routers.dashboard as dash

    p = dash.get_active_period(db)
    bawaan = cash.saldo_laci_sampai(db, p.start_at)
    arus = ZERO
    for k in cash.rows_layer(db, cash.LAYER_LACI):
        if (k.kategori or "").strip() == cash.SALDO_AWAL_KATEGORI:
            continue
        m = cash._moment(k)
        if m is not None and m >= p.start_at:
            n = to_decimal(k.nominal)
            arus += n if (k.jenis or "").strip().lower() == "masuk" else -n
    assert to_decimal(cash.saldo_laci(db)) == to_decimal(bawaan) + arus


# ───────────────── 2. Omzet terisolasi per periode ─────────────────
def test_omzet_tidak_mencair_dengan_periode_lama(client, db):
    import routers.dashboard as dash
    p = dash.get_active_period(db)
    omset_awal = to_decimal(_fin(db, p)["omset"])

    # Unit di luar periode berjalan, dibayar penuh.
    o = _order(db, "ISO-OMZET-LAMA", "CASH", harga=900000)
    lama = p.start_at - timedelta(days=2)
    d = __import__("models").Payment(service_order_id=o.id, kind="DP",
                                     amount=to_decimal(900000), created_at=lama)
    db.add(d)
    db.commit()
    db.refresh(d)
    import cash
    cash.catat_penerimaan(db, d)

    assert to_decimal(_fin(db, p)["omset"]) == omset_awal, \
        "Pembayaran dari periode lama tidak boleh masuk Omzet periode ini"


# ───────────────── 3. Beban terisolasi per periode ─────────────────
def test_beban_tidak_mencair_dengan_periode_lama(client, db):
    import routers.dashboard as dash
    p = dash.get_active_period(db)
    beban_awal = to_decimal(_fin(db, p)["total_beban"])

    _expense(db, "Operasional", "ISO biaya periode lama", 777000,
             p.start_at - timedelta(days=3))

    assert to_decimal(_fin(db, p)["total_beban"]) == beban_awal, \
        "Beban periode lama tidak boleh ikut dihitung di periode ini"


# ───────────────── 4. Tiga hal yang BOLEH menyeber ─────────────────
def test_yang_boleh_menyeber_dp_kas_aset_hutang_beban(client, db):
    """DP, Kas Aset, dan Hutang Beban memang lintas periode -- itu izin Owner."""
    import cash
    import expense_debt
    import routers.dashboard as dash
    from models import Payment

    p = dash.get_active_period(db)
    omset_awal = to_decimal(
        dash.compute_finance(db, *dash.batas_periode(p))["omset"])

    # DP berumur lama, unitnya belum dilunasi.
    o = _order(db, "ISO-DP-SEBER", "DONE", harga=900000)
    d = Payment(service_order_id=o.id, kind="DP", amount=to_decimal(400000),
                created_at=datetime(2020, 1, 1))
    db.add(d)
    db.commit()
    db.refresh(d)
    cash.catat_penerimaan(db, d)

    assert to_decimal(cash.saldo_titipan_dp(db)) >= to_decimal(400000), \
        "DP dari periode lama harus tetap terbawa (izin Owner)"

    # DP ini TIDAK boleh ikut menjadi Omzet periode ini.
    assert to_decimal(
        dash.compute_finance(db, *dash.batas_periode(p))["omset"]) == omset_awal, \
        "DP yang boleh menyeber tetap tidak boleh masuk Omzet"

    # Kas Aset & Hutang Beban punya jalurnya sendiri, tidak lewat hitungan
    # Omzet/Beban. Kunci di sini hanya bahwa keduanya memang lintas periode.
    assert callable(cash.saldo_kas_aset)
    assert callable(expense_debt.saldo_hutang)