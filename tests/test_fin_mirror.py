# -*- coding: utf-8 -*-
"""FIN-MIRROR — regression: kesetaraan Financial Logic Project B vs Project A.

Menguji aturan yang DIMIRROR dari Proyek A:

FIN-MIRROR-1 (Beban permanen)
    A `app.py:983-984,1017` memakai `SUM(nilai) FROM beban` TANPA filter tanggal.
    Beban yang sama dipotong dari setiap siklus, setiap hari.
    Test ini mengunci: periode tanpa expense BARU tetap membawa beban katalog.

FIN-MIRROR-2 (Gate Omzet = CASH)
    A `app.py:1715` - `laba_final = h_jual - m_part - m_jasa - m_lain if
    stat == 'Cash' else 0`. Pengakuan laba murni bergantung pada status Cash;
    tidak ada syarat LUNAS.

FIN-MIRROR-3 (kewajiban sebagai satu sumber omzet)
    `finance.compute_finance_core` memakai `kewObligation()`, bukan `or` yang
    membuat `final_price = 0` diam-diam jatuh ke `estimate`.

Semua test TIDAK melakukan `commit()` supaya `rollback()` pada fixture `db`
(conftest.py:96-97) membersihkan seluruh data uji - tidak mencemari test lain.
"""
from datetime import date, datetime, timedelta

import finance
import models
import statusflow
from money import to_decimal
from statusflow import lock_lunas_moment

BEBAN_KATEGORI = ("gaji", "operasional")


def _periode(offset=0):
    """Batas [start, end) periode kas 16:00->16:00 pada hari ke-`offset`."""
    now = datetime.now() + timedelta(days=offset)
    start = now.replace(hour=16, minute=0, second=0, microsecond=0)
    if now < start:
        start -= timedelta(days=1)
    return start, start + timedelta(days=1)


def _katalog_beban(db):
    """Total beban `recurring` yang ada di katalog saat ini."""
    total = to_decimal(0)
    for e in db.query(models.Expense).all():
        if (e.kategori or "").strip().lower() in BEBAN_KATEGORI:
            if bool(getattr(e, "recurring", True)):
                total += to_decimal(e.nilai)
    return total


def _unit(db, cust, no, harga, modal=(0, 0, 0), status="CASH", moment=None):
    o = models.ServiceOrder(no_servis=no, customer_id=cust.id, device="PY",
                            status=status, service_date=date.today(),
                            final_price=to_decimal(harga),
                            estimate=to_decimal(harga),
                            warranty_months=1, payment=to_decimal("0"))
    o.part_cost, o.modal_jasa, o.modal_lainnya = [to_decimal(x) for x in modal]
    if moment is not None:
        o.taken_at = moment
    db.add(o)
    db.flush()
    db.refresh(o)
    return o


def _expense(db, kategori, uraian, nilai, moment, recurring):
    db.add(models.Expense(kategori=kategori, uraian=uraian, nilai=to_decimal(nilai),
                          tanggal=moment.date(), created_at=moment,
                          recurring=recurring))
    db.flush()


def _customer(db):
    c = db.query(models.Customer).filter(models.Customer.name == "FIN-MIRROR").first()
    if c is None:
        c = models.Customer(name="FIN-MIRROR")
        db.add(c)
        db.flush()
        db.refresh(c)
    return c


def _reset_periode(db, *offsets):
    """Hapus baris beku beban pada periode yang akan dipakai test.

    DB sandbox adalah salinan DB produksi, jadi bisa saja sudah punya snapshot
    `expense_periods` untuk periode tertentu. Beku bersifat one-shot, jadi test
    harus relieved dari snapshot lama agar bisa menguji aturan dari nol.
    """
    for off in offsets:
        s, e = _periode(off)
        db.query(models.ExpensePeriod).filter(
            models.ExpensePeriod.periode == finance.period_key(s, e)).delete(
                synchronize_session=False)
    db.flush()


def _bersihkan(db):
    """Buang sisa uji FIN-MIRROR (berguna bila suite dijalankan ulang)."""
    for o in db.query(models.ServiceOrder).filter(
            models.ServiceOrder.no_servis.like("FIN-MIRROR%")).all():
        db.query(models.Payment).filter(
            models.Payment.service_order_id == o.id).delete(synchronize_session=False)
        db.delete(o)
    db.query(models.ExpensePeriod).filter(
        models.ExpensePeriod.nama_beban.like("FIN-MIRROR%")).delete(synchronize_session=False)
    db.query(models.Expense).filter(
        models.Expense.uraian.like("FIN-MIRROR%")).delete(synchronize_session=False)
    db.query(models.KasEntry).filter(
        models.KasEntry.keterangan.like("FIN-MIRROR%")).delete(synchronize_session=False)
    db.flush()


# ---------------------------------------------------------------- FIN-MIRROR-1

def test_beban_katalog_dipotong_di_setiap_periode(db):
    """FIN-MIRROR-1: periode tanpa expense BARU tetap membawa beban katalog.

    Regresi untuk bug yang ditemukan saat mirroring: sebelumnya
    `freeze_expenses_for_period` hanya membekukan expense yang `created_at`-nya
    jatuh di periode itu, sehingga periode berikutnya punya beban 0 ->
    laba_bersih = laba_kotor -> distribusi 10/30/30/30 berjalan dari laba kotor.
    """
    _bersihkan(db)
    _reset_periode(db, -1, 0, 1)
    # Katalog dari DB salinan ikut terhitung; expected dihitung relatif.
    baseline = _katalog_beban(db)
    tengah = _periode(-1)[0] + timedelta(hours=6)
    _expense(db, "Gaji", "FIN-MIRROR gaji", 400000, tengah, True)
    _expense(db, "Operasional", "FIN-MIRROR ops", 205000, tengah, True)
    diharapkan = baseline + to_decimal(605000)

    # Periode 1: beku seperti biasa.
    s0, e0 = _periode(-1)
    finance.freeze_expenses_for_period(db, s0, e0, commit=False)
    assert to_decimal(finance.compute_finance_core(db, s0, e0)["total_beban"]) == diharapkan

    # Periode 2 & 3: TIDAK ada expense baru sama sekali.
    for offset in (0, 1):
        s, e = _periode(offset)
        finance.freeze_expenses_for_period(db, s, e, commit=False)
        core = finance.compute_finance_core(db, s, e)
        assert to_decimal(core["total_beban"]) == diharapkan, \
            "beban katalog harus tetap dipotong di periode %s (perilaku A)" % s.date()


def test_beban_recurring_default_true_dan_not_null(db):
    """FIN-MIRROR-1: expense baru default permanen, seperti tabel `beban` A."""
    kolom = models.Expense.__table__.c.recurring
    assert kolom.nullable is False
    row = models.Expense(kategori="Gaji", uraian="FIN-MIRROR default", nilai=to_decimal(1))
    db.add(row)
    db.flush()
    db.refresh(row)
    assert bool(row.recurring) is True


def test_beban_one_off_hanya_satu_periode(db):
    """Beban `recurring=False` tetap terbatas ke periodenya (kapabilitas lama B)."""
    _bersihkan(db)
    _reset_periode(db, -2, -1)
    s0, e0 = _periode(-2)
    tengah = s0 + timedelta(hours=6)
    baseline_gaji = sum((to_decimal(e.nilai) for e in db.query(models.Expense).all()
                        if (e.kategori or "").strip().lower() == "gaji"
                        and bool(getattr(e, "recurring", True))), to_decimal(0))
    _expense(db, "Gaji", "FIN-MIRROR one-off", 50000, tengah, False)

    finance.freeze_expenses_for_period(db, s0, e0, commit=False)
    assert to_decimal(finance.compute_finance_core(db, s0, e0)["beban_gaji"]) \
        == baseline_gaji + to_decimal(50000)

    s1, e1 = _periode(-1)
    finance.freeze_expenses_for_period(db, s1, e1, commit=False)
    assert to_decimal(finance.compute_finance_core(db, s1, e1)["beban_gaji"]) == baseline_gaji, \
        "beban one-off tidak boleh ikut ke periode berikutnya"


def test_freeze_beban_idempoten_dan_tidak_menggandakan(db):
    """SSOT-4: pemanggilan berulang tidak menambah baris beku baru."""
    _bersihkan(db)
    _reset_periode(db, -1)
    baseline = _katalog_beban(db)
    tengah = _periode(-1)[0] + timedelta(hours=6)
    _expense(db, "Gaji", "FIN-MIRROR gaji", 400000, tengah, True)
    _expense(db, "Operasional", "FIN-MIRROR ops", 205000, tengah, True)
    s0, e0 = _periode(-1)
    a = finance.freeze_expenses_for_period(db, s0, e0, commit=False)
    b = finance.freeze_expenses_for_period(db, s0, e0, commit=False)
    c = finance.freeze_expenses_for_period(db, s0, e0, commit=False)
    assert a["dibekukan"] >= 2
    assert b["dibekukan"] == 0 and c["dibekukan"] == 0
    assert c["sudah_ada"] == a["dibekukan"]
    assert to_decimal(finance.compute_finance_core(db, s0, e0)["total_beban"]) \
        == baseline + to_decimal(605000)


def test_periode_lama_yang_sudah_beku_tidak_berubah(db):
    """Histori produksi terlindungi: periode yang sudah beku tetap angkanya."""
    _bersihkan(db)
    _reset_periode(db, -3)
    s0, e0 = _periode(-3)
    tengah = s0 + timedelta(hours=6)
    _expense(db, "Gaji", "FIN-MIRROR gaji", 400000, tengah, True)
    _expense(db, "Operasional", "FIN-MIRROR ops", 205000, tengah, True)
    finance.freeze_expenses_for_period(db, s0, e0, commit=False)
    sebelum = to_decimal(finance.compute_finance_core(db, s0, e0)["total_beban"])

    # Beban recurring BARU muncul setelah periode itu dihitung.
    _expense(db, "Gaji", "FIN-MIRROR belakangan", 999999, datetime.now(), True)
    finance.freeze_expenses_for_period(db, s0, e0, commit=False)
    sesudah = to_decimal(finance.compute_finance_core(db, s0, e0)["total_beban"])
    assert sesudah == sebelum, "periode yang sudah beku tidak boleh berubah karena beban baru"


def test_kategori_di_luar_beban_kategori_tidak_dihitung(db):
    """SSOT-4 (A `app.py:983-984`): hanya gaji & operasional yang jadi Beban."""
    _bersihkan(db)
    _reset_periode(db, -1)
    tengah = _periode(-1)[0] + timedelta(hours=6)
    _expense(db, "Transport", "FIN-MIRROR transport", 999999, tengah, True)
    s0, e0 = _periode(-1)
    finance.freeze_expenses_for_period(db, s0, e0, commit=False)
    core = finance.compute_finance_core(db, s0, e0)
    assert core["total_beban"] == core["beban_gaji"] + core["beban_operasional"]
    assert to_decimal(core["total_beban"]) < to_decimal(999999)


# ---------------------------------------------------------------- FIN-MIRROR-2

def test_cash_tanpa_lunas_TIDAK_diakui(db):
    """FIN-MIRROR-6 (keputusan Owner terbaru): Omzet HANYA transaksi yang LUNAS.

    Aturan lama (FIN-MIRROR-2, mirror Proyek A) menyatakan unit CASH
    tetap diakui walau belum lunas. Owner sekarang justru mengunci aturan yang
    lebih ketat: "Omzet = nilai transaksi yang sudah LUNAS."

    Alasan: pelunasan dicatat terpisah dari status CASH dan bisa bolong --
    misalnya harga diubah setelah unit diambil, atau pelunasan baru dicatat
    kemudian. Kalau unit seperti itu ikut dihitung, Omzet lebih besar dari uang
    yang benar-benar diterima, Laba Kotor ikut membesar, dan distribusi bisa
    keluar dari uang yang belum masuk.
    """
    _bersihkan(db)
    cust = _customer(db)
    s0, e0 = _periode(0)
    o = _unit(db, cust, "FIN-MIRROR-CASH-NOT-LUNAS", 500000,
              modal=(200000, 100000, 0), status="CASH", moment=datetime.now())
    assert o.lunas_at is None, "order ini sengaja tidak LUNAS"
    ids = [x.id for x in finance.settled_orders(db, s0, e0)]
    assert o.id not in ids, "unit CASH yang belum LUNAS TIDAK boleh masuk cohort Omzet"
    # `order_profit` per-order tetap boleh positif; yang diexclude adalah
    # pengakuan OMZET periode, bukan penghitungan laba unit.
    assert to_decimal(statusflow.order_profit(o, [])) == to_decimal(200000)


def test_cash_lunas_dan_tidak_lunas_hanya_lunas_yang_diakui(db):
    """Control: begitu dilunasi, unit yang sama langsung masuk cohort."""
    _bersihkan(db)
    cust = _customer(db)
    s0, e0 = _periode(0)
    o = _unit(db, cust, "FIN-MIRROR-JADI-LUNAS", 500000,
              modal=(200000, 100000, 0), status="CASH", moment=datetime.now())
    oid = o.id
    ids = [x.id for x in finance.settled_orders(db, s0, e0)]
    assert oid not in ids
    db.add(models.Payment(service_order_id=oid, kind="PELUNASAN",
                          amount=to_decimal(500000), method="CASH", note="lunas"))
    db.flush()
    db.commit()
    db.expunge_all()
    ids2 = [x.id for x in finance.settled_orders(db, s0, e0)]
    assert oid in ids2, "setelah dilunasi, unit harus masuk cohort Omzet"


def test_non_cash_nol_meski_lunas(db):
    """FIN-MIRROR-2: hanya status CASH yang diakui; REFUND bernilai 0."""
    _bersihkan(db)
    cust = _customer(db)
    s0, e0 = _periode(0)
    o = _unit(db, cust, "FIN-MIRROR-REFUND", 500000, modal=(200000, 100000, 0),
              status="REFUND")
    db.add(models.Payment(service_order_id=o.id, kind="PELUNASAN",
                          amount=to_decimal(500000), method="CASH", note="lunas"))
    db.flush()
    lock_lunas_moment(o, datetime.now())
    db.flush()
    db.refresh(o)
    pays = db.query(models.Payment).filter(models.Payment.service_order_id == o.id).all()
    # LUNAS tapi bukan CASH -> di luar cohort dan laba 0 (A: `else 0`).
    ids = [x.id for x in finance.settled_orders(db, s0, e0)]
    assert o.id not in ids
    assert to_decimal(statusflow.order_profit(o, pays)) == to_decimal(0)


def test_cash_momen_dipakai_bukan_lunas(db):
    """Unit CASH yang belum LUNAS diatribusikan lewat `taken_at`."""
    _bersihkan(db)
    cust = _customer(db)
    o = _unit(db, cust, "FIN-MIRROR-MOMEN", 100000, status="CASH",
              moment=datetime(2020, 1, 1, 10, 0, 0))
    assert statusflow.cash_moment(o) == datetime(2020, 1, 1, 10, 0, 0)


def test_lunas_tanpa_cash_tidak_masuk_omzet(db):
    """Unit LUNAS tapi belum CASH tetap di luar Omzet (A: hanya 'Cash')."""
    _bersihkan(db)
    cust = _customer(db)
    s0, e0 = _periode(0)
    o = _unit(db, cust, "FIN-MIRROR-LUNAS-BELUM-CASH", 300000, status="DONE",
              moment=None)
    db.add(models.Payment(service_order_id=o.id, kind="PELUNASAN",
                          amount=to_decimal(300000), method="CASH", note="lunas"))
    db.flush()
    lock_lunas_moment(o, datetime.now())
    db.flush()
    db.refresh(o)
    assert o.lunas_at is not None
    assert o.id not in [x.id for x in finance.settled_orders(db, s0, e0)]


# ---------------------------------------------------------------- FIN-MIRROR-3

def test_final_price_nol_tidak_jatuh_ke_estimate(db):
    """FIN-MIRROR-3: `final_price = 0` berarti kewajiban 0, bukan `estimate`."""
    _bersihkan(db)
    cust = _customer(db)
    o = _unit(db, cust, "FIN-MIRROR-FP-NOL", 0, modal=(0, 0, 0), status="CASH",
              moment=datetime.now())
    o.final_price = to_decimal(0)
    o.estimate = to_decimal(999999)
    db.flush()
    db.refresh(o)
    assert statusflow.kewajiban(o) == to_decimal(0), \
        "final_price 0 harus dihormati, bukan diganti estimate"


def test_omset_konsisten_antara_core_dan_order_profit(db):
    """FIN-MIRROR-3: penjumlahan cohort core == jumlah kewajiban per-order."""
    _bersihkan(db)
    cust = _customer(db)
    s0, e0 = _periode(0)
    for i, harga in enumerate((300000, 450000, 120000)):
        _unit(db, cust, "FIN-MIRROR-CONS-%d" % i, harga,
              modal=(100000, 50000, 25000), status="CASH", moment=datetime.now())
    cohort = finance.settled_orders(db, s0, e0)
    assert len(cohort) >= 3
    total_core = to_decimal(finance.compute_finance_core(db, s0, e0)["omset"])
    total_order = sum((to_decimal(statusflow.kewajiban(o)) for o in cohort), to_decimal(0))
    assert total_core == total_order


def test_laba_bersih_empat_pengurang(db):
    """SSOT-5 + FIN-MIRROR-4: 4 pengurang, + `tambahan`, - Beban."""
    _bersihkan(db)
    _reset_periode(db, 0)
    cust = _customer(db)
    s0, e0 = _periode(0)
    tengah = s0 + timedelta(hours=6)
    baseline = _katalog_beban(db)
    _expense(db, "Gaji", "FIN-MIRROR gaji", 400000, tengah, True)
    _expense(db, "Operasional", "FIN-MIRROR ops", 205000, tengah, True)
    _unit(db, cust, "FIN-MIRROR-LB", 1000000, modal=(400000, 200000, 50000),
          status="CASH", moment=datetime.now())
    core = finance.compute_finance_core(db, s0, e0)
    assert to_decimal(core["laba_bersih"]) == (
        to_decimal(core["omset"]) - to_decimal(core["modal_part"])
        - to_decimal(core["modal_jasa"]) - to_decimal(core["modal_lainnya"])
        + to_decimal(core["tambahan"]) - to_decimal(core["total_beban"]))

    beban = baseline + to_decimal(605000)
    assert to_decimal(core["total_beban"]) == beban
    assert to_decimal(core["tambahan"]) == to_decimal(0)

    # Laba dihitung dari kohorot yang benar-benar masuk periode ini (test lain
    # bisa saja sudah commit unit CASH, jadi expected diturunkan dari kohorot).
    cohort = finance.settled_orders(db, s0, e0)
    expect = sum((to_decimal(statusflow.kewajiban(o))
                  - to_decimal(o.part_cost)
                  - to_decimal(o.modal_jasa)
                  - to_decimal(o.modal_lainnya) for o in cohort), to_decimal(0))
    assert to_decimal(core["laba_bersih"]) == expect - beban


# ---------------------------------------------------------------- FIN-MIRROR-4

def _kas_manual(db, nominal, jenis="Masuk", kategori="Penjualan Service",
                moment=None, layer="LACI", sumber="MANUAL"):
    row = models.KasEntry(tanggal=None, kategori=kategori, jenis=jenis,
                          nominal=to_decimal(nominal), layer=layer,
                          sumber=sumber, keterangan="FIN-MIRROR kas manual",
                          created_at=moment or datetime.now())
    db.add(row)
    db.flush()
    return row


def test_tambahan_manual_masuk_laba_bersih(db):
    """FIN-MIRROR-4 (A-1 `app.py:372-376`): kas manual Masuk menambah laba."""
    _bersihkan(db)
    _reset_periode(db, 0)
    s0, e0 = _periode(0)
    sebelum = to_decimal(finance.compute_finance_core(db, s0, e0)["laba_bersih"])
    _kas_manual(db, 100000, "Masuk", moment=s0 + timedelta(hours=1))
    core = finance.compute_finance_core(db, s0, e0)
    assert to_decimal(core["tambahan"]) == to_decimal(100000)
    assert to_decimal(core["laba_bersih"]) == sebelum + to_decimal(100000)


def test_tambahan_manual_keluar_mengurangi_laba(db):
    """FIN-MIRROR-4: kas manual Keluar mengurangi laba (sama seperti A)."""
    _bersihkan(db)
    _reset_periode(db, 0)
    s0, e0 = _periode(0)
    sebelum = to_decimal(finance.compute_finance_core(db, s0, e0)["laba_bersih"])
    _kas_manual(db, 30000, "Keluar", moment=s0 + timedelta(hours=1))
    core = finance.compute_finance_core(db, s0, e0)
    assert to_decimal(core["tambahan"]) == to_decimal(-30000)
    assert to_decimal(core["laba_bersih"]) == sebelum - to_decimal(30000)


def test_tambahan_tidak_ganda_dengan_tiga_suku_lain(db):
    """FIN-MIRROR-4: hanya `sumber=MANUAL`; PAYMENT/MODAL/BEBAN/CASH_OUT bukan."""
    _bersihkan(db)
    _reset_periode(db, 0)
    s0, e0 = _periode(0)
    m = s0 + timedelta(hours=1)
    # Semua sumber lain TIDAK boleh masuk `tambahan`.
    _kas_manual(db, 111, "Masuk", moment=m, sumber="PAYMENT")
    _kas_manual(db, 222, "Keluar", moment=m, sumber="MODAL")
    _kas_manual(db, 333, "Keluar", moment=m, sumber="BEBAN")
    _kas_manual(db, 444, "Keluar", moment=m, sumber="CASH_OUT")
    _kas_manual(db, 555, "Masuk", moment=m, sumber="REFUND_DP")
    # Baris float kas fisik = padanan 'MODAL KAS KECIL (LACI)' A -> dikecualikan.
    _kas_manual(db, 999999, "Masuk", kategori="Saldo Awal", moment=m, sumber="MANUAL")
    # Kas Aset bukan arus Laci.
    _kas_manual(db, 888888, "Masuk", moment=m, layer="KAS_ASET", sumber="MANUAL")
    core = finance.compute_finance_core(db, s0, e0)
    assert to_decimal(core["tambahan"]) == to_decimal(0)


def test_tambahan_hanya_dalam_periode(db):
    """Batas periode dipatuhi (A tidak punya batas; B tetap_periodisasi)."""
    _bersihkan(db)
    _reset_periode(db, -1, 0)
    s0, e0 = _periode(0)
    # Di luar periode -> tidak boleh masuk.
    _kas_manual(db, 50000, "Masuk", moment=s0 - timedelta(hours=1))
    assert to_decimal(finance.compute_finance_core(db, s0, e0)["tambahan"]) == to_decimal(0)
    _kas_manual(db, 70000, "Masuk", moment=s0 + timedelta(hours=1))
    assert to_decimal(finance.compute_finance_core(db, s0, e0)["tambahan"]) == to_decimal(70000)


def test_tambahan_ikut_menaikkan_ambang_milestone(db):
    """FIN-MIRROR-4 (A-1 `app.py:376`): ambang CTS/CTO memakai laba_kotor+tambahan."""
    import cash as cash_mod
    _bersihkan(db)
    _reset_periode(db, 0)
    s0, e0 = _periode(0)
    core0 = finance.compute_finance_core(db, s0, e0)
    lk0 = to_decimal(core0["omset"]) - to_decimal(core0["total_modal"])
    _kas_manual(db, 400000, "Masuk", moment=s0 + timedelta(hours=1))
    core1 = finance.compute_finance_core(db, s0, e0)
    lk1 = (to_decimal(core1["omset"]) - to_decimal(core1["total_modal"])
           + to_decimal(core1["tambahan"]))
    assert lk1 == lk0 + to_decimal(400000)
    # CASH_OUT tidak boleh masuk (A: bagi hasil tak pernah jadi transaksi_tambahan)
    _kas_manual(db, 400000, "Keluar", moment=s0 + timedelta(hours=1), sumber="CASH_OUT")
    core2 = finance.compute_finance_core(db, s0, e0)
    assert to_decimal(core2["tambahan"]) == to_decimal(400000)