# -*- coding: utf-8 -*-
"""FIN-MIRROR-7 — Tutup Kas sebagai PENYELESAIAN PERIODE.

Aturan Owner yang dikunci di sini:

  1. Omzet = nilai transaksi yang SUDAH LUNAS.
  2. Laba Kotor = Nilai Transaksi − Modal Part − Modal Jasa.
  3. Laba Bersih = Laba Kotor − Beban.
  4. Laba Bersih didistribusikan 100% dengan komposisi 10/30/30/30.
  5. Pelunasan, Modal, Beban, dan seluruh distribusi tercatat sebagai
     pergerakan Kas Perputaran; 30% Kas Aset pindah ke pos Kas Aset.
  6. Setelah kewajiban kas periode diselesaikan, Saldo Kas Perputaran kembali
     ke Rp 0 — karena
         pelunasan = modal + beban + laba_bersih
     dan laba_bersih keluar 100% (70% cash-out + 30% ke Kas Aset).
  7. Kalau Laba Kotor tidak menutup Beban: TIDAK memaksa distribusi, TIDAK
     memakai DP titipan, TIDAK membuat saldo nol artifisial —而是 Hutang Beban.
  8. Tutup Kas aman dari duplikasi (idempoten) dan tidak merusak Financial SSOT.

Setiap test memakai DB SQLite terisolasi karena angkanya harus PERSIS dan
sandbox utama dipakai bersama test lain.
"""
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

import cash
import closing
from money import ZERO, quantize, to_decimal
from models import KasEntry
from routers.dashboard import batas_periode
from routers.dashboard import compute_finance as _CF


def _isolated():
    import os
    import tempfile
    from database import Base
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    folder = tempfile.mkdtemp(prefix="finmirror7_")
    eng = create_engine("sqlite:///%s" % os.path.join(folder, "iso.db"))
    Base.metadata.create_all(bind=eng)
    return sessionmaker(bind=eng)()


def _setup(s):
    """Periode kas + modal awal 0 (kas kosong, jadi hasil akhir harus 0)."""
    from models import KasPeriod
    p = KasPeriod(start_at=datetime(2026, 9, 1, 16), end_at=datetime(2026, 9, 2, 16),
                  status="OPEN", created_at=datetime(2026, 9, 1, 8))
    s.add(p)
    s.commit()
    s.refresh(p)
    return p


def _pelunasan(s, order_id, nominal, kind="PELUNASAN"):
    from models import Payment
    s.add(Payment(service_order_id=order_id, kind=kind, amount=to_decimal(nominal),
                  method="CASH", note="uji",
                  created_at=datetime.now()))
    s.commit()




def _transaksi(s, p, no, harga, modal_part, modal_jasa, lunas=True):
    """Order CASH lengkap dengan modal yang SUDAH tercatat di Laci.

    Modal dicatat lewat `cash.catat_modal` supaya simulasi sama dengan jalur
    aplikasi (bukan hanya mengisi kolom order).
    """
    import models
    c = s.query(models.Customer).filter(models.Customer.name == "FM7").first()
    if c is None:
        c = models.Customer(name="FM7", phone="0800", created_at=datetime.now())
        s.add(c)
        s.commit()
        s.refresh(c)
    o = models.ServiceOrder(
        no_servis=no, customer_id=c.id, device="PY", status="CASH",
        unit_status="DIAMBIL", service_date=p.start_at.date(),
        taken_at=datetime.now(), final_price=to_decimal(harga),
        estimate=to_decimal(harga), repair_plan="x", technician="B",
        warranty_months=1, created_at=datetime.now(),
        part_cost=to_decimal(modal_part), modal_jasa=to_decimal(modal_jasa),
        modal_lainnya=to_decimal(0))
    s.add(o)
    s.commit()
    s.refresh(o)
    if lunas:
        _pelunasan(s, o.id, harga)
        cash.catat_penerimaan(s, s.query(models.Payment).filter(
            models.Payment.service_order_id == o.id).first(), actor="pytest")
        s.commit()
    cash.catat_modal(s, o, actor="pytest")
    s.commit()
    return o


def _beban(s, p, gaji=0, operasional=0):
    import models
    t = ZERO
    for nama, kat, nilai in (("Gaji", "Gaji", gaji), ("Ops", "Operasional", operasional)):
        if nilai <= 0:
            continue
        e = models.Expense(kategori=kat, uraian=nama, nilai=to_decimal(nilai),
                           created_at=p.start_at + timedelta(hours=2), recurring=True)
        s.add(e)
        s.commit()
        s.refresh(e)
        t += to_decimal(nilai)
    s.commit()
    return t


# ── Aturan 1–4 + 6: kasus、印刷 normal, Laci kembali 0 ─────────────────────
def test_period_surplus_laci_kembali_nol():
    """Pelunasan 900rb - modal 455rb - beban 405rb -> laba 40rb -> Laci 0.

    Ini persis contoh audit Owner. Yang dibuktikan bukan cuma angka akhirnya,
    tapi IDENTITAS matematisnya:
        pelunasan = modal + beban + laba_bersih
    karena Laba Bersih keluar 100% (70% cash-out + 30% Kas Aset), maka
        Laci_akhir = Laci_awal + pelunasan - modal - beban - laba_bersih
                  = Laci_awal
    Kalau ada salah satu arus yang tidak tercatat, Laci TIDAK akan kembali 0 --
    jadi test ini sekaligus membuktikan tidak adaDistribution yang hilang.
    """
    s = _isolated()
    p = _setup(s)
    pelunasan = 0
    for harga, mp, mj in ((600000, 50000, 275000), (200000, 0, 80000),
                          (100000, 0, 50000)):
        _transaksi(s, p, "FM7-A%s" % harga, harga, mp, mj)
        pelunasan += harga
    _beban(s, p, gaji=300000, operasional=105000)        # 405.000
    s.commit()

    modal_tercatat = quantize(sum((to_decimal(e.nominal) for e in
                                   s.query(KasEntry).filter(
                                       KasEntry.sumber == cash.SUMBER_MODAL)), ZERO))
    fin = _CF(s, *batas_periode(p), lihat_kas_besar=True)
    assert fin["omset"] == to_decimal(pelunasan) == to_decimal(900000)
    assert fin["total_modal"] == to_decimal(modal_tercatat) == to_decimal(455000)
    assert fin["laba_kotor"] == to_decimal(900000 - 455000) == to_decimal(445000)
    assert fin["total_beban"] == to_decimal(405000)
    assert fin["laba_bersih"] == to_decimal(40000)

    out = closing.tutup_periode(s, p, counted=None, oleh="pytest", compute_finance=_CF)
    s.commit()

    # Distribusi 10/30/30/30 dari 40.000, seluruhnya tercatat di ledger.
    al = out["snapshot"]["distribusi"]["alokasi"]
    assert quantize(to_decimal(al["karyawan"])) == to_decimal(4000)
    assert quantize(to_decimal(al["pengelola"])) == to_decimal(12000)
    assert quantize(to_decimal(al["investor"])) == to_decimal(12000)
    assert quantize(to_decimal(al["kas_aset"])) == to_decimal(12000)
    assert (quantize(to_decimal(al["karyawan"])) + quantize(to_decimal(al["pengelola"]))
            + quantize(to_decimal(al["investor"])) + quantize(to_decimal(al["kas_aset"]))
            ) == to_decimal(40000), "distribusi harus 100% dari Laba Bersih"

    # Beban benar-benar KELUAR dari Laci (bukan hanya memotong angka laba).
    # OD-LOCK-06: dibayar saat periode dibekukan, jadi Tutup Kas menambah NOL.
    # Yang diperiksa di sini adalah TOTAL Beban yang keluar dari ledger.
    import beban_bayar as _beb
    total_beban_lucas = _beb._total_dibayar(
        s, __import__("finance").period_key(*batas_periode(p)))
    assert total_beban_lucas == to_decimal(405000), \
        "Total Beban harus keluar dari Laci: %s" % total_beban_lucas
    assert quantize(to_decimal(
        out["snapshot"]["penyelesaian"]["beban_dibayar_dari_laci"])) == to_decimal(0), \
        "Tutup Kas tidak boleh membayar lagi Beban yang sudah terbayar"

    # ATURAN 6: Kas Perputaran kembali ke Rp 0.
    assert cash.saldo_laci(s) == to_decimal(0), \
        "Laci harus kembali 0, tapi = %s" % cash.saldo_laci(s)
    # 30% pindah ke pos Kas Aset, tidak tinggal di Laci.
    assert cash.saldo_kas_aset(s) == to_decimal(12000)
    # Dan identitasnya benar-benar tertutup di ledger.
    masuk = sum((to_decimal(e.nominal) for e in s.query(KasEntry).filter(
        KasEntry.layer == cash.LAYER_LACI, KasEntry.jenis == "Masuk")), ZERO)
    keluar = sum((to_decimal(e.nominal) for e in s.query(KasEntry).filter(
        KasEntry.layer == cash.LAYER_LACI, KasEntry.jenis == "Keluar")), ZERO)
    assert masuk - keluar == to_decimal(0)
    assert masuk == pelunasan
    assert keluar == (modal_tercatat + quantize(to_decimal(405000))
                      + quantize(to_decimal(28000)) + quantize(to_decimal(12000)))
    s.close()


def test_beban_dibayar_dari_laci_bukan_hanya_dihitung():
    """Beban harus KELUAR dari Laci, bukan cuma memotong angka laba.

    OD-LOCK-06: pembayarannya terjadi saat periode DIBEKUKAN, bukan menunggu
    Tutup Kas. Tutup Kas hanya pays SISA -- jadi angka yang diperiksa di sini
    adalah TOTAL yang benar-benar keluar dari Laci, dan Tutup Kas harus
    menambah NOL.
    """
    s = _isolated()
    p = _setup(s)
    _transaksi(s, p, "FM7-B1", 900000, 455000, 0)
    _beban(s, p, gaji=300000, operasional=105000)
    s.commit()

    # Hitung pertama kali = bekukan periode = Beban langsung dibayar (OD-LOCK-06).
    _CF(s, *batas_periode(p), lihat_kas_besar=True)
    s.commit()
    saldo_setelah_beku = cash.saldo_laci(s)
    dibayar_awal = to_decimal(900000 - 455000) - saldo_setelah_beku
    assert dibayar_awal == to_decimal(405000), (
        "Beban harus dibayar saat periode dibekukan: %s" % dibayar_awal)

    out = closing.tutup_periode(s, p, counted=None, oleh="pytest", compute_finance=_CF)
    s.commit()
    peny = out["snapshot"]["penyelesaian"]
    assert to_decimal(peny["beban_dibayar_dari_laci"]) == to_decimal(0), (
        "Tutup Kas tidak boleh membayar lagi Beban yang sudah dibayar")
    assert cash.saldo_laci(s) == to_decimal(0)
    s.close()


# ── Aturan 1: Omzet hanya LUNAS ────────────────────────────────────────────
def test_transaksi_belum_lunas_tidak_masuk_omzet_nilai_tetap_utuh():
    s = _isolated()
    p = _setup(s)
    lunas = _transaksi(s, p, "FM7-LUNAS", 600000, 50000, 275000)
    belum = _transaksi(s, p, "FM7-BELUM", 400000, 0, 200000, lunas=False)
    s.commit()

    fin = _CF(s, *batas_periode(p), lihat_kas_besar=True)
    assert fin["omset"] == to_decimal(600000), "hanya transaksi LUNAS yang dihitung"
    assert fin["n_settled"] == 1
    # Order yang belum lunas tetap ada di data (tidak dihapus).
    assert s.get(models_ServiceOrder(), belum.id) is not None
    s.close()


def models_ServiceOrder():
    from models import ServiceOrder
    return ServiceOrder


# ── Aturan 7: defisit -> bukan distribusi paksa ────────────────────────────
def test_defisit_tidak_ada_distribusi_paksa():
    s = _isolated()
    p = _setup(s)
    _transaksi(s, p, "FM7-DEF2", 100000, 0, 0)
    _beban(s, p, gaji=200000, operasional=50000)
    s.commit()

    fin = _CF(s, *batas_periode(p), lihat_kas_besar=True)
    assert fin["laba_bersih"] < ZERO, "defisit harus menghasilkan laba negatif"

    out = closing.tutup_periode(s, p, counted=None, oleh="pytest", compute_finance=_CF)
    s.commit()
    # Tidak ada distribution sama sekali
    assert out["snapshot"]["distribusi"]["terbentuk"] is False
    assert to_decimal(out["distribusi_uang"]["cash_out"]) == ZERO
    # Kas Aset tidak bertambah dari distribution
    assert cash.saldo_kas_aset(s) == ZERO
    # Tercatat sebagai defisit (Kas Aset + Hutang Beban), bukan saldo nol paksa
    assert out["snapshot"]["penyelesaian"]["defisit"] is not None
    s.close()


# ── Aturan 8: idempoten & Financial SSOT utuh ─────────────────────────────
def test_tutup_kas_tidak_menggandakan_distribusi_maupun_beban():
    s = _isolated()
    p = _setup(s)
    _transaksi(s, p, "FM7-IDEM", 900000, 455000, 0)
    _beban(s, p, gaji=300000, operasional=105000)
    s.commit()
    closing.tutup_periode(s, p, counted=None, oleh="pytest", compute_finance=_CF)
    s.commit()
    n_cash_out = _n(s, cash.SUMBER_CASH_OUT)
    n_beban_periode = _n(s, cash.SUMBER_BEBAN)
    master = cash.master_kas(s)
    laci = cash.saldo_laci(s)

    # Panggil gatekeeper penyelesaian yang sama lagi -> harus tidak menambah apa pun.
    closing.selesaikan_periode(s, p, _CF(s, *batas_periode(p), lihat_kas_besar=True),
                              oleh="pytest")
    s.commit()
    assert _n(s, cash.SUMBER_CASH_OUT) == n_cash_out, "cash-out terdup"
    assert _n(s, cash.SUMBER_BEBAN) == n_beban_periode, "beban periode terdup"
    assert cash.master_kas(s) == master
    assert cash.saldo_laci(s) == laci
    s.close()


def test_periode_sudah_closed_ditolak():
    from models import KasPeriod
    s = _isolated()
    p = _setup(s)
    p.status = "CLOSED"
    s.commit()
    with pytest.raises(closing.PeriodAlreadyClosed):
        closing.tutup_periode(s, p, counted=None, oleh="pytest", compute_finance=_CF)
    s.close()


def _n(s, sumber):
    from models import KasEntry
    return s.query(KasEntry).filter(KasEntry.layer == cash.LAYER_LACI,
                                    KasEntry.sumber == sumber).count()