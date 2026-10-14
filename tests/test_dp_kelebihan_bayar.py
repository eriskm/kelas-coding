# -*- coding: utf-8 -*-
"""Dua perbaikan Owner atas temuan DP.

1. KELAMPAHAN BAYAR. DP Rp1.000.000 pada unit kewajiban Rp200.000 tidak boleh
   dianggap habis seluruhnya. Yang jadi pembayaran hanya sebesar kewajiban;
   sisanya tetap TITIPAN karena uang customer itu wajib dikembalikan.

2. PEMISAHAN TAMPILAN KAS. Uang DP secara fisik ada di dalam laci, jadi angka
   fisiknya tetap dipakai untuk Declare saat Tutup Kas. Tapi angka yang
   DITAMPILKAN ke Owner sebagai "Kas Aset Kecil (Laci)" dan "Master Kas"
   harus bebas DP, supaya uang customer tidak terbaca sebagai uang usaha.
"""
from datetime import datetime

from money import to_decimal

from test_titipan_dp import _order, _pay, _titipan


def _titipan_owner(db, no):
    t = _titipan(db)
    rows = [r for r in t["live"] if r["no_servis"] == no]
    return t, sum(to_decimal(r["masuk"]) - to_decimal(r["keluar"]) for r in rows)


# ───────────────── 1. Kelebihan bayar tetap ditahan ─────────────────
def test_dp_lebih_dari_kewajiban_bukan_sepenuhnya_terpakai(client, db):
    """Kasus nyata SV-20261014-5337: DP 1jt, kewajiban 200rb."""
    o = _order(db, "OVER-001", "CASH", harga=200000)
    _pay(db, o, "DP", 1000000)

    import statusflow
    rows = _pay_rows(db, o)
    assert statusflow.payment_summary(o, rows)["payment_status"] == "LUNAS"

    import cash as cash_mod
    # Terpakai hanya sebesar kewajiban.
    assert cash_mod.dp_terpakai(db, o, rows) == to_decimal(200000)

    # Sisanya 800rb masih ditahan -> harus tetap muncul di Laporan Titipan DP.
    t, ditahan = _titipan_owner(db, "OVER-001")
    assert ditahan == to_decimal(800000), \
        "kelebihan bayar milik customer, tidak boleh hilang dari laporan"


def _pay_rows(db, order):
    import models
    return db.query(models.Payment).filter(
        models.Payment.service_order_id == order.id).all()


def test_kelebihan_bayar_kembali_dikembalikan(client, db):
    """Begitu kelebihan bayar dikembalikan, sisanya habis -> keluar dari panel."""
    import models
    o = _order(db, "OVER-002", "CASH", harga=200000)
    _pay(db, o, "DP", 1000000)
    db.add(models.Refund(refund_no="RF-OVER-002", jenis="DP",
                         service_order_id=o.id, nominal=to_decimal(800000),
                         sumber_dana="LACI", created_at=datetime.now()))
    db.commit()

    _t, ditahan = _titipan_owner(db, "OVER-002")
    assert ditahan == to_decimal(0), "tidak ada yang tertahan setelah dikembalikan"
    assert "OVER-002" not in [r["no_servis"] for r in _titipan(db)["live"]]


def test_dp_normal_tidak_berubah(client, db):
    """DP di bawah kewajiban (kasus biasa) tidak boleh terpengaruh aturan baru."""
    import cash as cash_mod
    o = _order(db, "OVER-003", "CASH", harga=800000)
    _pay(db, o, "DP", 500000)
    _pay(db, o, "PELUNASAN", 300000)
    rows = _pay_rows(db, o)
    assert cash_mod.dp_terpakai(db, o, rows) == to_decimal(500000)
    _t, ditahan = _titipan_owner(db, "OVER-003")
    assert ditahan == to_decimal(0), "DP <= kewajiban -> tidak ada sisa"


def test_dp_belum_lunas_tidak_terpakai(client, db):
    import cash as cash_mod
    o = _order(db, "OVER-004", "DONE", harga=800000)
    _pay(db, o, "DP", 500000)
    rows = _pay_rows(db, o)
    assert cash_mod.dp_terpakai(db, o, rows) == to_decimal(0)
    _t, ditahan = _titipan_owner(db, "OVER-004")
    assert ditahan == to_decimal(500000)


# ───────────────── 2. Pemisahan tampilan kas ─────────────────
def test_ringkasan_pisah_dp_dan_milik_toko(client, db):
    import cash as cash_mod
    r = cash_mod.ringkasan(db, termasuk_aset=True)

    assert "titipan_dp" in r, "titipan harus dilaporkan supaya bisa dipisahkan"
    assert r["laci"] == cash_mod.saldo_laci(db), "angka FISIK tetap utuh"
    assert r["laci_milik_toko"] == r["laci"] - r["titipan_dp"]
    assert r["master_kas"] == r["laci"] + r["aset"], "angka FISIK Master tetap utuh"
    assert r["master_kas_milik_toko"] == r["laci_milik_toko"] + r["aset"]


def test_angka_fisik_tidak_berubah_oleh_pemisahan(client, db):
    """Pemisahan hanya tampilan: saldo Laci & Master Kas versi lama tetap sama."""
    import cash as cash_mod
    laci_mentah = cash_mod.saldo_laci(db)
    aset = cash_mod.saldo_kas_aset(db)
    r = cash_mod.ringkasan(db, termasuk_aset=True)
    assert r["laci"] == laci_mentah
    assert r["aset"] == aset
    assert r["master_kas"] == laci_mentah + aset


def test_role_tanpa_authority_tetap_tidak_lihat_aset(client, db):
    """SSOT-7: role biasa tidak boleh menerima key Aset/Master sama sekali."""
    import cash as cash_mod
    r = cash_mod.ringkasan(db, termasuk_aset=False)
    assert "aset" not in r
    assert "master_kas" not in r
    assert "master_kas_milik_toko" not in r
    assert "laci" in r and "laci_milik_toko" in r


def test_endpoint_saldo_mengirim_kedua_versi(client, db):
    """Kartu di layar memakai versi milik-toko; Declare tetap memakai fisik."""
    adm = _token_admin(db)
    r = client.get("/api/kas/saldo", headers=adm)
    assert r.status_code == 200, r.text
    b = r.json()
    assert "laci" in b and "laci_milik_toko" in b
    assert "titipan_dp" in b
    assert b["laci_milik_toko"] == b["laci"] - b["titipan_dp"]


def _token_admin(db):
    import models
    from test_titipan_dp import _token
    return _token(db, "pytest_admin", "ADMIN")