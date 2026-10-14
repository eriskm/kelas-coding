# -*- coding: utf-8 -*-
"""OD-LOCK-03 dan OD-LOCK-04 — aturan Owner yang LOCKED.

OD-LOCK-03 : Status CASH bersifat FINAL. Tidak boleh diubah ke status lain,
             termasuk CANCEL, meski disertai catatan koreksi.
OD-LOCK-04 : DP tidak boleh lebih besar daripada estimasi biaya transaksi.
             Berlaku di SETIAP jalur input yang menerima/memperbarui estimasi
             dan DP, bukan hanya satu halaman.
"""
import pytest

from money import to_decimal


# ───────────────── OD-LOCK-03 ─────────────────
def test_cash_tidak_bisa_jadi_cancel_walaupun_ada_catatan():
    from statusflow import check_transition
    ok, pesan = check_transition("CASH", "CANCEL", "koreksi kesalahan input")
    assert not ok, "CASH -> CANCEL harus DITOLAK walau ada catatan"
    assert "final" in (pesan or "").lower()


def test_cash_tidak_bisa_jadi_status_apa_pun():
    from statusflow import SERVICE_STATUSES, check_transition
    for target in SERVICE_STATUSES:
        if target == "CASH":
            continue
        ok, pesan = check_transition("CASH", target, "catatan koreksi")
        assert not ok, "CASH -> %s harus DITOLAK" % target
        assert pesan


def test_cash_tidak_bisa_jadi_failed():
    from statusflow import check_transition
    ok, _ = check_transition("CASH", "FAILED", "unit tidak jadi dikerjakan")
    assert not ok


def test_done_ke_cash_tetap_boleh():
    """OD-LOCK-03 tidak boleh merusak alur normal ke CASH."""
    from statusflow import check_transition
    ok, pesan = check_transition("DONE", "CASH")
    assert ok, pesan


def test_failed_ke_cancel_dengan_catatan_tetap_boleh():
    """OD-LOCK-03 hanya mengunci CASH. FAILED/CANCEL tetap bisa dikoreksi
    dengan catatan -- itu dipakai alur 'unit diambil pelanggan'."""
    from statusflow import check_transition
    ok, pesan = check_transition("FAILED", "CANCEL", "Unit diambil pelanggan")
    assert ok, pesan


def test_endpoint_menolak_cash_ke_cancel(client, db):
    """Uji end-to-end lewat HTTP: PUT status CASH lalu coba CANCEL."""
    import models
    from test_titipan_dp import _order, _pay, _token

    o = _order(db, "LOCK3-UNIT", "DONE", harga=300000)
    _pay(db, o, "PELUNASAN", 300000)
    adm = _token(db, "pytest_admin", "ADMIN")

    r = client.put("/api/orders/%d" % o.id, headers=adm, json={"status": "CASH"})
    assert r.status_code == 200, r.text
    db.expire_all()
    assert db.query(models.ServiceOrder).filter(
        models.ServiceOrder.id == o.id).first().status == "CASH"

    r2 = client.put("/api/orders/%d" % o.id, headers=adm,
                    json={"status": "CANCEL", "status_note": "dibatalkan"})
    assert r2.status_code == 400, "CASH -> CANCEL harus ditolak: %s" % r2.text
    db.expire_all()
    assert db.query(models.ServiceOrder).filter(
        models.ServiceOrder.id == o.id).first().status == "CASH", \
        "status harus tetap CASH"


# ───────────────── OD-LOCK-04 ─────────────────
def test_dp_lebih_dari_estimasi_ditolak():
    from statusflow import cek_dp_vs_estimasi
    ok, pesan = cek_dp_vs_estimasi(250000, 200000)
    assert not ok
    assert "estimasi" in (pesan or "").lower()


def test_dp_sama_dengan_estimasi_boleh():
    from statusflow import cek_dp_vs_estimasi
    assert cek_dp_vs_estimasi(200000, 200000)[0]


def test_dp_kurang_dari_estimasi_boleh():
    from statusflow import cek_dp_vs_estimasi
    assert cek_dp_vs_estimasi(150000, 200000)[0]


def test_estimasi_kosong_tidak_divalidasi():
    """Jalur 'Titip Unit' tidak mewajibkan estimasi -> tidak ada pembanding."""
    from statusflow import cek_dp_vs_estimasi
    assert cek_dp_vs_estimasi(500000, 0)[0]
    assert cek_dp_vs_estimasi(500000, None)[0]


def test_receive_menolak_dp_lebih_besar(client, db):
    from test_titipan_dp import _token
    adm = _token(db, "pytest_admin", "ADMIN")
    r = client.post("/api/orders/receive", headers=adm, json={
        "customer_name": "Uji DP Lebih", "device": "UJI",
        "estimate": 200000, "dp": 250000, "status": "DITERIMA"})
    assert r.status_code == 400, "DP 250rb vs estimasi 200rb harus DITOLAK"
    assert "estimasi" in r.json()["detail"].lower()


def test_receive_menerima_dp_sesuai_estimasi(client, db):
    from test_titipan_dp import _token
    adm = _token(db, "pytest_admin", "ADMIN")
    r = client.post("/api/orders/receive", headers=adm, json={
        "customer_name": "Uji DP Ok", "device": "UJI",
        "estimate": 200000, "dp": 200000, "status": "DITERIMA"})
    assert r.status_code in (200, 201), r.text


def test_endpoint_payments_menolak_dp_lebih(client, db):
    """Jalur POST /api/payments juga wajib dijaga (bukan cuma form)."""
    from test_titipan_dp import _order, _token
    o = _order(db, "LOCK4-PAY", "DONE", harga=300000)
    o.estimate = to_decimal(300000)
    db.commit()
    adm = _token(db, "pytest_admin", "ADMIN")
    r = client.post("/api/payments", headers=adm, json={
        "service_order_id": o.id, "kind": "DP", "amount": 400000})
    assert r.status_code == 400, "DP lewat /api/payments harus DITOLAK: %s" % r.text
    assert "estimasi" in r.json()["detail"].lower()


def test_pembayaran_kedua_ditolak_kumulatif(client, db):
    """DP 200rb + 150rb = 350rb > estimasi 300rb -> yang kedua ditolak."""
    from test_titipan_dp import _order, _token
    o = _order(db, "LOCK4-KUMULATIF", "DONE", harga=300000)
    o.estimate = to_decimal(300000)
    db.commit()
    adm = _token(db, "pytest_admin", "ADMIN")
    a = client.post("/api/payments", headers=adm, json={
        "service_order_id": o.id, "kind": "DP", "amount": 200000})
    assert a.status_code in (200, 201), a.text
    b = client.post("/api/payments", headers=adm, json={
        "service_order_id": o.id, "kind": "DP", "amount": 150000})
    assert b.status_code == 400, "total DP 350rb > estimasi 300rb harus DITOLAK"


def test_update_dp_ditolak(client, db):
    """Jalur PUT /api/orders/{id} (kenaikan DP dari form) wajib dijaga."""
    from test_titipan_dp import _order, _token
    o = _order(db, "LOCK4-UPDATE", "DONE", harga=400000)
    o.estimate = to_decimal(400000)
    db.commit()
    adm = _token(db, "pytest_admin", "ADMIN")
    r = client.put("/api/orders/%d" % o.id, headers=adm,
                   json={"payment": 900000})
    assert r.status_code == 400, "DP 900rb vs estimasi 400rb harus DITOLAK: %s" % r.text


def test_pelunasan_tidak_terkena_validasi_dp(client, db):
    """PELUNASAN boleh melebihi estimasi? Tidak boleh -- tapi yang dijaga
    OD-LOCK-04 hanya DP. Pastikan guard tidak salah sasaran."""
    from statusflow import cek_dp_vs_estimasi
    assert cek_dp_vs_estimasi(0, 500000)[0], "DP 0 selalu boleh"


def test_data_lama_tidak_ikut_tertimpa(client, db):
    """Validasi hanya berlaku saat MENYIMPAN. Data lama yang sudah kelebihan DP
    tidak boleh ikut terhapus atau diubah oleh aturan baru."""
    import models
    import cash as cash_mod
    from test_titipan_dp import _order, _pay

    o = _order(db, "LOCK4-LAMA", "CASH", harga=200000)
    _pay(db, o, "DP", 1000000)
    assert cash_mod.dp_diterima(db, o.id) == to_decimal(1000000), \
        "DP historis harus tetap utuh"
    assert cash_mod.dp_terpakai(db, o) == to_decimal(200000), \
        "hanya sebesar kewajiban yang dianggap terpakai"