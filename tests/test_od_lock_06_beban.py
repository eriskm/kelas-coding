# -*- coding: utf-8 -*-
"""OD-LOCK-06 (Owner, LOCKED) — Pembayaran Beban, Kas Aset, dan Hutang Beban.

Urutan dana: LACI -> KAS ASET (dipindah sungguhan) -> HUTANG BEBAN.

Skenario yang diminta Owner:
    Penjualan 600.000 | Modal 325.000 | Sisa Laci 275.000
    Total Beban 605.000 | Kekurangan 330.000

    A. Kas Aset 500.000 -> Laci 275.000, Kas Aset 330.000, sisa aset 170.000, hutang 0
    B. Kas Aset 200.000 -> Laci 275.000, Kas Aset 200.000, hutang 130.000
    C. Kas Aset       0 -> Laci 275.000, hutang 330.000
"""
from datetime import datetime, timedelta
from decimal import Decimal

from money import to_decimal, ZERO

OMZET = to_decimal(600000)
MODAL = to_decimal(325000)
BEBAN = to_decimal(605000)
LACI_AWAL_SEJAK_MENJUAL = OMZET - MODAL          # 275.000
KEKURANGAN = BEBAN - LACI_AWAL_SEJAK_MENJUAL     # 330.000


def _skenario(s, kas_aset_awal):
    """Bangun kondisi persis seperti contoh Owner.

    Mengembalikan dict berisi session, periode, dan id yang dibutuhkan.
    """
    import models as m
    import cash as cash_mod

    mulai = datetime(2026, 8, 1)
    s.add(m.KasPeriod(start_at=mulai, end_at=mulai + timedelta(days=1),
                      status="OPEN"))
    s.add(m.Customer(name="OD6", phone="0800", created_at=mulai))
    s.commit()
    s.expire_all()
    pid = s.query(m.KasPeriod).first().id
    cid = s.query(m.Customer).first().id

    # Beban 605.000: gaji 405.000 + operasional 200.000.
    for nama, kat, nilai in (("Gaji", "Gaji", 405000),
                             ("Ops", "Operasional", 200000)):
        s.add(m.Expense(kategori=kat, uraian=nama, nilai=to_decimal(nilai),
                        created_at=mulai))
    s.flush()

    # Penjualan 600.000, Modal 325.000 keluar.
    o = m.ServiceOrder(
        no_servis="OD6-1", customer_id=cid, device="PY", status="CASH",
        unit_status="DIAMBIL", service_date=mulai.date(), taken_at=mulai,
        final_price=OMZET, estimate=OMZET, repair_plan="x", technician="T",
        warranty_months=1, created_at=mulai,
        part_cost=to_decimal(225000), modal_jasa=to_decimal(100000),
        modal_lainnya=to_decimal(0))
    s.add(o)
    s.flush()
    pay = m.Payment(service_order_id=o.id, kind="PELUNASAN", amount=OMZET,
                    method="CASH", created_at=mulai)
    s.add(pay)
    s.flush()
    cash_mod.catat_penerimaan(s, pay)
    cash_mod.catat_modal(s, o)
    s.commit()
    s.expire_all()

    # Kas Aset awal.
    if kas_aset_awal > ZERO:
        cash_mod.catat_mutasi(
            s, cash_mod.LAYER_ASET, "Masuk", "Saldo Awal Kas Aset",
            "Modal awal", to_decimal(kas_aset_awal),
            sumber=cash_mod.SUMBER_INJEKSI, check_saldo=False)
    s.commit()
    s.expire_all()
    return {"pid": pid, "mulai": mulai}


def _isi(s, pid):
    """Jalankan financial core (memicu beku + pembayaran OD-LOCK-06)."""
    from finance import compute_finance_core
    p = s.query(__import__("models").KasPeriod).get(pid)
    from routers.dashboard import batas_periode
    return compute_finance_core(s, *batas_periode(p))


def _stok(kas_aset_awal):
    """DB terisolasi kosong untuk satu skenario."""
    import os
    import tempfile
    from database import Base
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    folder = tempfile.mkdtemp(prefix="od6_")
    eng = create_engine("sqlite:///%s" % os.path.join(folder, "od6.db"))
    Base.metadata.create_all(bind=eng)
    return sessionmaker(bind=eng)()


# ───────────────────────────── SKENARIO A ─────────────────────────────
def _input_hutang_admin(db, period, nominal=None, oleh="pytest"):
    """OD-LOCK-12: simulasi Admin mencatat Hutang Beban manual, 1x per periode."""
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


def test_skenario_a_kas_aset_tidak_disentuh_otomatis():
    """OD-LOCK-06 (revisi): Kas Aset TIDAK pernah menutup otomatis.

    Owner: "keputusan untuk menutup dari Kas Aset dilakukan secara
    manual oleh user". Jadi хотя Kas Aset 500.000 tersedia, sistem tetap hanya
    membayar dari Laci dan mencatat sisanya sebagai Hutang Beban.
    """
    import cash as cash_mod
    import expense_debt as debt_mod

    s = _stok(0)
    ctx = _skenario(s, to_decimal(500000))
    _isi(s, ctx["pid"])
    s.commit()
    s.expire_all()

    assert to_decimal(cash_mod.saldo_laci(s)) == ZERO, "Laci dibayar sampai habis"
    assert to_decimal(cash_mod.saldo_kas_aset(s)) == to_decimal(500000), \
        "Kas Aset TIDAK boleh tersentuh otomatis -- tetap 500.000"
    # OD-LOCK-12: kekurangan TIDAK boleh otomatis jadi Hutang Beban. Menunggu
    # Admin yang menginput manual saat Tutup Kas.
    assert to_decimal(debt_mod.saldo_hutang(s)) == ZERO, \
        "kekurangan 330.000 tidak boleh otomatis jadi Hutang Beban"
    s.close()


# ───────────────────────────── SKENARIO B ─────────────────────────────
def test_skenario_b_kas_aset_tidak_disentuh_otomatis():
    import cash as cash_mod
    import expense_debt as debt_mod

    s = _stok(0)
    ctx = _skenario(s, to_decimal(200000))
    _isi(s, ctx["pid"])
    s.commit()
    s.expire_all()

    assert to_decimal(cash_mod.saldo_kas_aset(s)) == to_decimal(200000), \
        "Kas Aset tetap 200.000 meski cukup menutup kekurangan"
    assert to_decimal(debt_mod.saldo_hutang(s)) == ZERO, \
        "Kas Aset cukup menutup kekurangan, tapi hutang tetap TIDAK otomatis"
    assert to_decimal(cash_mod.saldo_laci(s)) == ZERO
    s.close()


# ───────────────────────────── SKENARIO C ─────────────────────────────
def test_skenario_c_tanpa_kas_aset():
    import cash as cash_mod
    import expense_debt as debt_mod

    s = _stok(0)
    ctx = _skenario(s, ZERO)
    _isi(s, ctx["pid"])
    s.commit()
    s.expire_all()

    assert to_decimal(debt_mod.saldo_hutang(s)) == ZERO, \
        "Tanpa Kas Aset -> TIDAK ada Hutang Beban otomatis (OD-LOCK-12)"
    assert to_decimal(cash_mod.saldo_laci(s)) == ZERO
    assert to_decimal(cash_mod.saldo_kas_aset(s)) == ZERO
    s.close()


def test_keputusan_cover_manual_ditawarkan_bukan_dijalankan():
    """Sistem memberi tahu berapa yang BISA ditutup manual -- tidak memindahkan."""
    import cash as cash_mod
    import beban_bayar as bb

    s = _stok(0)
    ctx = _skenario(s, to_decimal(500000))
    p = s.query(__import__("models").KasPeriod).get(ctx["pid"])
    from finance import period_key
    from routers.dashboard import batas_periode
    key = period_key(s, *batas_periode(p))
    aset_awal = to_decimal(cash_mod.saldo_kas_aset(s))
    res = bb.bayar_beban_periode(s, *batas_periode(p), key, BEBAN)
    s.commit()
    s.expire_all()

    assert to_decimal(res["dari_kas_aset"]) == ZERO, "cover otomatis harus nol"
    assert to_decimal(res["hutang"]) == KEKURANGAN
    assert to_decimal(res["bisa_ditutup_manual"]) == KEKURANGAN, \
        "sistem harus memberi tahu jumlah yang bisa ditutup manual"
    assert to_decimal(res["saldo_kas_aset_tersedia"]) == aset_awal
    assert "manual" in (res["cara_cover"] or "").lower()
    assert to_decimal(cash_mod.saldo_kas_aset(s)) == aset_awal, \
        "saldo Kas Aset tidak boleh bergerak"
    s.close()


# ────────────────────── KONSISTENSI & KETATAN ──────────────────────
def test_laci_tidak_pernah_negatif():
    """OD-LOCK-06: jangan paksa Laci negatif walau Beban lebih besar."""
    import cash as cash_mod
    s = _stok(0)
    ctx = _skenario(s, ZERO)
    _isi(s, ctx["pid"])
    s.commit()
    s.expire_all()
    assert to_decimal(cash_mod.saldo_laci(s)) >= ZERO, "Laci tidak boleh negatif"
    s.close()


def test_beban_dibayar_tepat_sekali():
    """Pembayaran berulang (beku dipanggil lagi) tidak boleh menambah lagi."""
    import cash as cash_mod
    import expense_debt as debt_mod
    s = _stok(0)
    ctx = _skenario(s, to_decimal(200000))
    _isi(s, ctx["pid"])
    s.commit()
    s.expire_all()
    aset_1 = to_decimal(cash_mod.saldo_kas_aset(s))
    hutang_1 = to_decimal(debt_mod.saldo_hutang(s))
    for _ in range(3):
        _isi(s, ctx["pid"])
        s.commit()
        s.expire_all()
    assert to_decimal(cash_mod.saldo_kas_aset(s)) == aset_1, \
        "Kas Aset tidak boleh berkurang lagi"
    assert to_decimal(debt_mod.saldo_hutang(s)) == hutang_1, \
        "Hutang Beban tidak boleh bertambah lagi"
    s.close()


def test_tutup_kas_tidak_membayar_ulang():
    """OD-LOCK-06: Tutup Kas tidak boleh membayar ulang."""

    import cash as cash_mod
    import closing
    import expense_debt as debt_mod
    import routers.dashboard as dash
    import models as m

    s = _stok(0)
    ctx = _skenario(s, to_decimal(200000))
    _isi(s, ctx["pid"])
    s.commit()
    s.expire_all()
    aset_1 = to_decimal(cash_mod.saldo_kas_aset(s))
    hutang_1 = to_decimal(debt_mod.saldo_hutang(s))
    laci_1 = to_decimal(cash_mod.saldo_laci(s))

    p = s.query(m.KasPeriod).get(ctx["pid"])
    closing.selesaikan_periode(s, p, dash.compute_finance(s, *dash.batas_periode(p)),
                               oleh="pytest")
    s.commit()
    s.expire_all()

    assert to_decimal(cash_mod.saldo_kas_aset(s)) == aset_1, \
        "Tutup Kas tidak boleh memakai Kas Aset lagi"
    assert to_decimal(debt_mod.saldo_hutang(s)) == hutang_1, \
        "Tutup Kas tidak boleh menambah Hutang Beban lagi"
    assert to_decimal(cash_mod.saldo_laci(s)) == laci_1
    s.close()


def test_beban_tidak_dibayar_dua_kali():
    """Regresi: jalur lama `catat_beban` per-baris + Tutup Kas = bayar 2x."""
    import cash as cash_mod
    import models as m
    import routers.dashboard as dash

    s = _stok(0)
    ctx = _skenario(s, ZERO)
    # Simulasikan jalur LAMA: catat_beban dipanggil per baris Beban.
    for e in s.query(m.Expense).all():
        cash_mod.catat_beban(s, e)
    s.commit()
    s.expire_all()
    n_legacy = s.query(m.KasEntry).filter(
        m.KasEntry.sumber == cash_mod.SUMBER_BEBAN,
        m.KasEntry.ref_type == "expense").count()

    _isi(s, ctx["pid"])
    s.commit()
    s.expire_all()

    # Yang dihitung mesin OD-LOCK-06 harus memotong sisa yang BELUM dibayar
    # lewat jalur legacy, bukan mengulang semuanya.
    import beban_bayar as bb
    from finance import period_key
    dari_mesin = bb._total_dibayar(
        s, period_key(s, *dash.batas_periode(s.query(m.KasPeriod).get(ctx["pid"]))))
    if n_legacy > 0:
        assert dari_mesin <= BEBAN, (
            "total dibayar %s tidak boleh melebihi Total Beban %s"
            % (dari_mesin, BEBAN))
    s.close()


def test_hutang_punya_rincian_periode():
    """OD-LOCK-06: Hutang Beban harus ada rincian + periode asalnya."""
    import expense_debt as debt_mod
    import models as m

    s = _stok(0)
    ctx = _skenario(s, ZERO)
    _isi(s, ctx["pid"])
    s.commit()
    s.expire_all()

    row = s.query(m.ExpenseDebtPeriod).filter(
        m.ExpenseDebtPeriod.kas_period_id == ctx["pid"]).first()
    # OD-LOCK-12: tanpa perintah Admin, TIDAK ada baris rincian sama sekali.
    assert row is None, "Hutang Beban tidak boleh ada sebelum Admin menginput"
    # Setelah Admin menginput manual, baris rinciannya terbentuk.
    _input_hutang_admin(s, s.query(m.KasPeriod).get(ctx["pid"]))
    s.commit()
    row = s.query(m.ExpenseDebtPeriod).filter(
        m.ExpenseDebtPeriod.kas_period_id == ctx["pid"]).first()
    assert row is not None, "harus ada baris rincian Hutang Beban"
    assert to_decimal(row.defisit) == KEKURANGAN, "rincian sisa kewajiban"
    assert to_decimal(row.cover_kas_aset) == ZERO, "rincian cover Kas Aset"
    assert to_decimal(row.hutang_baru) == KEKURANGAN
    assert row.periode, "harus ada periode asal"

    entry = s.query(m.ExpenseDebtEntry).filter(
        m.ExpenseDebtEntry.expense_debt_period_id == row.id).first()
    assert entry is not None, "harus ada jejak hutang yang terakumulasi"
    assert to_decimal(entry.nominal) == KEKURANGAN
    assert entry.periode == row.periode, "riwayat harus menunjuk periode asal"
    s.close()


def test_hutang_terakumulasi_saat_periode_berganti():
    """OD-LOCK-06: Hutang Beban tidak hilang, tapi MENUMPUH.

    Periode berikutnya punya kewajiban Beban sendiri. Karena Laci & Kas Aset
    kosong, kekurangannya ditambahkan — itulah "terakumulasi sampai benar-benar
    dibayar", bukan "direset tiap periode".
    """
    import expense_debt as debt_mod
    import models as m

    s = _stok(0)
    ctx = _skenario(s, ZERO)
    _isi(s, ctx["pid"])
    s.commit()
    s.expire_all()
    hutang_1 = to_decimal(debt_mod.saldo_hutang(s))
    # OD-LOCK-12: periode pertama belum otomatis jadi hutang.
    assert hutang_1 == ZERO, "Hutang Beban tidak boleh otomatis muncul"
    p = s.query(m.KasPeriod).get(ctx["pid"])
    _input_hutang_admin(s, p)
    s.commit()
    hutang_1 = to_decimal(debt_mod.saldo_hutang(s))
    assert hutang_1 == KEKURANGAN

    nxt = m.KasPeriod(start_at=p.end_at, end_at=p.end_at + timedelta(days=1),
                      status="OPEN")
    s.add(nxt)
    s.commit()
    s.expire_all()
    nxt_id = nxt.id

    _isi(s, nxt_id)
    s.commit()
    s.expire_all()
    # Periode kedua juga harus menunggu Admin.
    assert to_decimal(debt_mod.saldo_hutang(s)) == hutang_1, \
        "periode kedua TIDAK boleh otomatis menambah hutang"
    _input_hutang_admin(s, s.query(m.KasPeriod).get(nxt_id))
    s.commit()

    hutang_2 = to_decimal(debt_mod.saldo_hutang(s))
    assert hutang_2 > hutang_1, (
        "Hutang Beban periode lama harus UTUH dan bertambah, bukan hilang "
        "atau direset: %s -> %s" % (hutang_1, hutang_2))

    # Baris hutang periode PERTAMA masih ada dan tidak diubah.
    row_1 = s.query(m.ExpenseDebtPeriod).filter(
        m.ExpenseDebtPeriod.kas_period_id == ctx["pid"]).first()
    assert row_1 is not None, "rincian hutang periode pertama harus tersimpan"
    assert to_decimal(row_1.defisit) == KEKURANGAN, \
        "rincian periode pertama tidak boleh ditimpa periode berikutnya"
    s.close()


def test_tidak_ada_entri_kas_aset_dari_pembayaran_beban():
    """OD-LOCK-06 (revisi): pembayaran Beban tidak boleh menyentuh Kas Aset.

    Penutupan dari Kas Aset adalah keputusan manual user lewat
    `POST /api/kas/aset/keluar` -- bukan konsekuensi otomatis pembayaran Beban.
    """
    import cash as cash_mod
    import models as m

    s = _stok(0)
    ctx = _skenario(s, to_decimal(500000))
    _isi(s, ctx["pid"])
    s.commit()
    s.expire_all()

    mut = s.query(m.KasEntry).filter(
        m.KasEntry.layer == cash_mod.LAYER_ASET,
        m.KasEntry.jenis == "Keluar",
        m.KasEntry.ref_type == "beban_periode").all()
    assert not mut, \
        "pembayaran Beban tidak boleh membuat entri Kas Aset keluar otomatis"
    assert to_decimal(cash_mod.saldo_kas_aset(s)) == to_decimal(500000)

    # Entri Laci untuk Beban tetap ada -- pembayaran dari Laci itu wajib.
    n_laci = s.query(m.KasEntry).filter(
        m.KasEntry.layer == cash_mod.LAYER_LACI,
        m.KasEntry.sumber == cash_mod.SUMBER_BEBAN,
        m.KasEntry.ref_type == "beban_periode").count()
    assert n_laci == 1, "harus ada satu pencatatan pembayaran Beban di Laci"
    s.close()