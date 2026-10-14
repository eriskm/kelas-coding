# -*- coding: utf-8 -*-
"""Laporan Titipan DP: panel hanya menampilkan DP yang MASIH DITAHAN.

Owner: "jika sudah tidak ada Saldo Titipan, sebaiknya data ini dikosongkan saja.
Contoh: di periode ini terjadi pelunasan atas DP dari beberapa periode sebelumnya,
maka uang DP keluar, saldo titipan menjadi 0."

Yang dikunci di sini:
  1. DP yang masih ditahan  -> muncul di `live` (dan di `mutasi` riwayat).
  2. Unit sudah LUNAS       -> TIDAK muncul di `live`; panel kosong kalau semua
                               sudah lunas. Ini terjadi otomatis begitu Tutup
                               Kas menutup periode -- tanpa menghapus apa pun.
  3. DP dikembalikan        -> ditahan berkurang; penuh -> hilang dari `live`.
  4. SAFETY: mengosongkan panel TIDAK boleh menghapus `payments`, TIDAK boleh
     mengubah `kas_entries`/saldo Laci, dan TIDAK boleh mengubah status
     pembayaran maupun Omzet. Percobaan awal membuktikan menghapus baris DP
     secara fisik membuat unit LUNAS -> BELUM LUNAS danRp800.000 lenyap dari
     Omzet padahal uangnya ada di Laci. Karena itu报告 ini hanya display.
"""
from datetime import datetime, timedelta

from money import to_decimal

from test_titipan_dp import _order, _pay, _titipan


def _live(db):
    import routers.dashboard as dash
    return dash.ringkasan_titipan_dp(db)["live"]


def _saldo_laci(db):
    """Saldo Laci = SUM entri kas layer LACI."""
    import models
    total = to_decimal(0)
    for k in db.query(models.KasEntry).filter(models.KasEntry.layer == "LACI").all():
        n = to_decimal(k.nominal)
        total += n if k.jenis == "Masuk" else -n
    return total


def _omzet(db):
    import routers.dashboard as dash
    from datetime import datetime as dt
    return dash.compute_finance(db, dt(2000, 1, 1), dt(2100, 1, 1))["omset"]


def _refund(db, order, nominal, suffix=""):
    import models
    db.add(models.Refund(refund_no="RF-TEST-%s%s" % (order.id, suffix), jenis="DP",
                         service_order_id=order.id, nominal=to_decimal(nominal),
                         sumber_dana="LACI", created_at=datetime.now()))
    db.commit()


def _net(rows):
    """Mutasi bersih milik satu unit.

    Kolom `saldo` adalah running balance GLOBAL lintas semua unit, jadi tidak
    bisa dipakai untuk memeriksa satu unit secara individual.
    """
    return sum(to_decimal(r["masuk"]) - to_decimal(r["keluar"]) for r in rows)


# ───────────────── 1. DP yang masih ditahan tampil ─────────────────
def test_dp_belum_lunas_muncul_di_live(client, db):
    o = _order(db, "LIVE-DP-001", "DONE", harga=800000)
    _pay(db, o, "DP", 500000)
    rows = [r for r in _live(db) if r["no_servis"] == "LIVE-DP-001"]
    assert rows, "DP yang belum lunas harus tampil"
    assert _net(rows) == to_decimal(500000)


# ───────────────── 2. Setelah lunas: panel kosong ─────────────────
def test_dp_lunas_kosongkan_panel(client, db):
    o = _order(db, "LIVE-DP-002", "CASH", harga=800000)
    _pay(db, o, "DP", 500000)
    assert _live(db), "DP yang belum lunas harus tampil dulu"

    # Pelunasan sisa 300rb -> unit jadi LUNAS
    _pay(db, o, "PELUNASAN", 300000)

    live = _live(db)
    assert "LIVE-DP-002" not in [r["no_servis"] for r in live], \
        "unit LUNAS tidak boleh masih tampil sebagai DP yang ditahan"

    # Riwayat (mutasi) tetap lengkap — itu arsip, tidak dihapus.
    import routers.dashboard as dash
    t = dash.ringkasan_titipan_dp(db)
    assert "LIVE-DP-002" in [r["no_servis"] for r in t["mutasi"]]
    assert to_decimal(t["dipakai"]) >= to_decimal(500000)


def test_unit_sendiri_lunas_keluar_dari_panel(client, db):
    """Kasus Owner: satu-satunya DP milik unit ini lunas -> tidak ada yang tertahan.

    Sengaja hanya memeriksa unit milik test ini, bukan seluruh isi `live`.
    Sweep "lunasi semua" di seluruh DB akan mengotori sandbox yang dipakai test
    lain (payments tanpa entri kas) dan merusak pengukuran saldo global.
    """
    import routers.dashboard as dash
    o = _order(db, "LIVE-DP-007", "CASH", harga=800000)
    _pay(db, o, "DP", 500000)
    _pay(db, o, "PELUNASAN", 300000)

    live = dash.ringkasan_titipan_dp(db)["live"]
    assert "LIVE-DP-007" not in [r["no_servis"] for r in live]

    # DP-nya jadi pembayaran, jadi masuk angka 'dipakai' (sebesar kewajiban).
    t = dash.ringkasan_titipan_dp(db)
    assert to_decimal(t["dipakai"]) >= to_decimal(500000)


# ───────────────── 3. DP dikembalikan ─────────────────
def test_dp_dikembalikan_penuh_kosong(client, db):
    o = _order(db, "LIVE-DP-003", "DONE", harga=800000)
    _pay(db, o, "DP", 500000)
    assert _live(db)
    _refund(db, o, 500000)
    assert "LIVE-DP-003" not in [r["no_servis"] for r in _live(db)]


def test_dp_dikembalikan_sebagian_menampilkan_sisa(client, db):
    o = _order(db, "LIVE-DP-004", "DONE", harga=800000)
    _pay(db, o, "DP", 500000)
    _refund(db, o, 200000)
    rows = [r for r in _live(db) if r["no_servis"] == "LIVE-DP-004"]
    assert rows, "DP yang masih disisakan harus tetap tampil"
    # 500k masuk - 200k kembali = 300k masih tertahan.
    assert _net(rows) == to_decimal(300000)
    # Tidak boleh ada baris "Dipakai untuk Pelunasan" selama unit belum LUNAS.
    assert not [r for r in rows if r["jenis"] == "DIPAKAI"]


# ───────────────── 4. SAFETY: nihil efek samping ─────────────────
def test_mengosongkan_panel_tidak_menghapus_data(client, db):
    """Inti dari keputusan ini: display-only, nol efek ke kas dan Omzet."""
    import models
    o = _order(db, "LIVE-DP-005", "CASH", harga=800000)
    _pay(db, o, "DP", 500000)
    _pay(db, o, "PELUNASAN", 300000)

    # Catat entri kas nyata, seperti alur produksi.
    import cash as cash_mod
    for p in db.query(models.Payment).filter(
            models.Payment.service_order_id == o.id).all():
        cash_mod.catat_penerimaan(db, p, actor=None)

    # Hanya baris yang MENYENTUH pembayaran unit ini yang dibandingkan --
    # bukan seluruh tabel. Pembayaran Beban otomatis (OD-LOCK-06) memang menambah
    # baris kas lain, dan itu tidak boleh dianggap sebagai "efek samping DP".
    def _entri_unit():
        pay_ids = [p.id for p in db.query(models.Payment).filter(
            models.Payment.service_order_id == o.id).all()]
        return sorted(e.id for e in db.query(models.KasEntry).filter(
            models.KasEntry.ref_type == "payment",
            models.KasEntry.ref_id.in_(pay_ids)).all())

    n_pay = db.query(models.Payment).count()

    # "Pemanasan": hitung Omzet dulu. Panggilan pertama ke financial core bisa
    # membekukan periode dan memicu pembayaran Beban otomatis (OD-LOCK-06).
    # Setelah itu saldo stabil, sehingga yang diuji murni EFEK DP.
    omset = _omzet(db)
    db.expire_all()
    laci = _saldo_laci(db)
    dari_unit = _entri_unit()
    dari = cash_mod.dp_diterima(db, o.id)
    status = __import__("statusflow").payment_summary(
        o, db.query(models.Payment).filter(
            models.Payment.service_order_id == o.id).all())["payment_status"]

    # Panel harus kosong untuk unit ini...
    assert "LIVE-DP-005" not in [r["no_servis"] for r in _live(db)]
    # ...tapi TIDAK ADA yang berubah di bawahnya:
    assert db.query(models.Payment).count() == n_pay, "baris payments tidak boleh hilang"
    assert _entri_unit() == dari_unit, "entri kas unit tidak boleh hilang"
    assert _saldo_laci(db) == laci, "saldo Laci tidak boleh bergeser"
    assert _omzet(db) == omset, "Omzet tidak boleh bergeser"
    assert cash_mod.dp_diterima(db, o.id) == dari, "DP unit harus tetap tercatat"
    assert status == "LUNAS", "unit yang sudah dibayar tidak boleh jadi BELUM LUNAS"


def test_live_stabil_antara_request(client, db):
    """Reload halaman / request berulang -> angka identik."""
    import routers.dashboard as dash
    a = dash.ringkasan_titipan_dp(db)["live"]
    b = dash.ringkasan_titipan_dp(db)["live"]
    assert [r["no_servis"] for r in a] == [r["no_servis"] for r in b]
    assert [to_decimal(r["saldo"]) for r in a] == [to_decimal(r["saldo"]) for r in b]


def test_riwayat_lama_tidak_ikut_kosong(client, db):
    """DP periode SEBELUM yang belum lunas tetap terbawa ke periode berikutnya."""
    from test_titipan_dp import _period
    p = _period(db)
    o = _order(db, "LIVE-DP-006", "DONE", harga=500000)
    dbaris = __import__("models").Payment(service_order_id=o.id, kind="DP",
                                         amount=to_decimal(250000),
                                         created_at=p.start_at - timedelta(days=1))
    db.add(dbaris)
    db.commit()
    rows = [r for r in _live(db) if r["no_servis"] == "LIVE-DP-006"]
    assert rows, "DP lama yang belum lunas harus tetap terlihat sampai dilunasi"
    assert _net(rows) == to_decimal(250000)
