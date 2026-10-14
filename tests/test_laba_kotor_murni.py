# -*- coding: utf-8 -*-
"""Laba Kotor MURNI: omset - modal, tanpa transaksi kas manual.

Owner: "yg benar seharusnya justru laba_kotor = omset - total_modal".

Transaksi kas manual (jurnal `sumber = MANUAL`) BUKAN hasil servis, jadi tidak
boleh ikut memengaruhi Laba Kotor. Tapi uangnya tetap nyata masuk, jadi tidak
boleh hilang juga -- ia tetap dihitung di LABA BERSIH, sesuai SSOT
`finance.compute_finance_core` (finance.py:357).
"""
from money import to_decimal


def _period():
    from test_titipan_dp import _period as _p
    return _p


def _fin(db):
    import routers.dashboard as dash
    p = dash.get_active_period(db)
    return dash.compute_finance(db, *dash.batas_periode(p))


def _tambah_kas_manual(db, nominal):
    """Buat jurnal kas manual lewat modul kas, bukan insert langsung."""
    import cash as cash_mod
    mut = cash_mod.catat_mutasi(
        db, cash_mod.LAYER_LACI, "Masuk", "Kas Masuk Manual",
        "Transaksi kas manual (uji)", to_decimal(nominal),
        sumber=cash_mod.SUMBER_MANUAL, check_saldo=False)
    db.commit()
    return mut


def test_laba_kotor_tidak_ikut_tambahan(client, db):
    """Menambah kas manual TIDAK boleh menaikkan Laba Kotor."""
    f0 = _fin(db)
    lk0 = to_decimal(f0["laba_kotor"])
    omset0 = to_decimal(f0["omset"])
    modal0 = to_decimal(f0["total_modal"])

    _tambah_kas_manual(db, 250000)
    f1 = _fin(db)

    assert to_decimal(f1["tambahan"]) > to_decimal(0), "kas manual harus tercatat"
    assert to_decimal(f1["laba_kotor"]) == lk0, \
        "Laba Kotor tidak boleh berubah karena transaksi kas manual"
    assert to_decimal(f1["laba_kotor"]) == omset0 - modal0, \
        "Laba Kotor = Omzet - Modal, tanpa tambahan"


def test_tambahan_tetap_masuk_laba_bersih(client, db):
    """Uang kas manual nyata -- jadi harus tetap muncul di Laba Bersih."""
    f0 = _fin(db)
    lb0 = to_decimal(f0["laba_bersih"])
    tam0 = to_decimal(f0["tambahan"])

    _tambah_kas_manual(db, 250000)
    f1 = _fin(db)

    assert to_decimal(f1["tambahan"]) == tam0 + to_decimal(250000)
    assert to_decimal(f1["laba_bersih"]) == lb0 + to_decimal(250000), \
        "transaksi kas manual menaikkan Laba Bersih, bukan Laba Kotor"


def test_rumus_laba_kotor_dan_bersih(client, db):
    """Kunci rumusnya langsung."""
    f = _fin(db)
    assert to_decimal(f["laba_kotor"]) == (to_decimal(f["omset"])
                                           - to_decimal(f["total_modal"]))
    assert to_decimal(f["laba_bersih"]) == (to_decimal(f["omset"])
                                            - to_decimal(f["modal_part"])
                                            - to_decimal(f["modal_jasa"])
                                            - to_decimal(f["modal_lainnya"])
                                            + to_decimal(f["tambahan"])
                                            - to_decimal(f["total_beban"]))


def test_ambang_cto_dihitung_dari_laba_kotor_murni(client, db):
    """Target tidak boleh terpenuhi oleh uang yang bukan hasil servis."""
    f0 = _fin(db)
    cto0 = f0["cto_tercapai"]

    _tambah_kas_manual(db, 9000000)
    f1 = _fin(db)

    # Omzet & modal tidak berubah, jadi ambang CTO tidak boleh ikut naik.
    assert to_decimal(f1["omset"]) == to_decimal(f0["omset"])
    assert to_decimal(f1["cto_target"]) == to_decimal(f0["cto_target"])
    assert f1["cto_tercapai"] == cto0, \
        "Kas manual tidak boleh membuat CTO tercapai"
    if not cto0:
        assert not f1["cto_tercapai"], "CTO tetap tidak tercapai"


def test_laba_kotor_tidak_pernah_negatif_dari_kas_manual(client, db):
    """Kas manual besar tidak boleh membuat Laba Kotor naik di atas Omzet."""
    f0 = _fin(db)
    _tambah_kas_manual(db, 5000000)
    f1 = _fin(db)
    assert to_decimal(f1["laba_kotor"]) <= to_decimal(f1["omset"]), \
        "Laba Kotor tidak boleh melebihi Omzet"