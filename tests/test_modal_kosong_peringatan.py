# -*- coding: utf-8 -*-
"""Peringatan modal kosong sebelum Tutup Kas (GET /api/kas/modal-kosong).

Owner bertanya: kalau ada order CASH yang modalnya belum diisi, Tutup Kas masih
bisa jalan? Jawabannya BISA (modal 0 itu sah untuk servis tanpa ganti part),
tapi konsekuensinya tidak cuma angka laba:

  - modal yang tidak tercatat TIDAK PERNAH keluar dari Laci;
  - laba terhitung terlalu besar, CTO bisa tercapai lebih awal, dan distribution
    ikut lebih besar -- sehingga bagian modal yang belum dibayar ikut dibagikan;
  - saat Tutup Kas, uang fisik laci justru LEBIH BESAR dari sistem, dan
    selisihnya muncul seolah-olah uang hilang.

Jadi ditambahkan pengingat, BUKAN pemblokiran. Test ini mengunci:
  - hanya order CASH di periode berjalan yang dihitung;
  - order dengan modal > 0 tidak ikut;
  - order DONE tidak dihitung (modalnya belum menarik dari Laci);
  - unit CANCEL/FAIL tidak dihitung.
"""
from datetime import datetime
from decimal import Decimal

import pytest


def _bersihkan(db):
    """Hapus order milik test ini saja -- BUKAN seluruh order di periode.

    Dulu test ini menghapus order berdasarkan `lunas_at >= awal`. Itu tidak
    menangkap order yang `lunas_at`-nya NULL (order Harga Final 0 tanpa
    payment), sehingga order milik test lain ikut terhitung dan test gagal
    bukan karena salahnya fitur. Kuncinya pakai prefix no_servis.
    """
    import models
    db.query(models.ServiceOrder).filter(
        models.ServiceOrder.no_servis.like("MK-%")).delete(synchronize_session=False)
    db.query(models.Payment).filter(
        models.Payment.service_order_id.in_(
            db.query(models.ServiceOrder.id).filter(
                models.ServiceOrder.no_servis.like("MK-%")))).delete(
        synchronize_session=False)
    db.commit(); db.expunge_all()


def _order(db, no, status="CASH", part=0, jasa=0, lain=0, harga=500000, lunas=None):
    import models
    c = db.query(models.Customer).filter(
        models.Customer.name == "MK").first()
    if c is None:
        c = models.Customer(name="MK", phone="0800", created_at=datetime.now())
        db.add(c)
        db.flush()
    o = models.ServiceOrder(
        no_servis=no, customer_id=c.id, device="MK", status=status,
        unit_status="DIAMBIL" if status == "CASH" else "DI TOKO",
        service_date=datetime.now().date(), created_at=datetime.now(),
        taken_at=datetime.now(), final_price=Decimal(harga),
        estimate=Decimal(harga), repair_plan="x", technician="B", warranty_months=1,
        part_cost=Decimal(part), modal_jasa=Decimal(jasa),
        modal_lainnya=Decimal(lain), laba_bersih=Decimal(0),
        lunas_at=lunas or datetime.now(), lunas_date=datetime.now().date())
    db.add(o)
    db.flush()
    return o


def _client(client, db):
    import models
    from datetime import timedelta
    u = db.query(models.User).filter(models.User.username == "pytest_admin").first()
    if u is None:
        u = models.User(username="pytest_admin", display_name="Pytest Admin", role="ADMIN",
                        passcode_hash="x", passcode_salt="y", active=True)
        db.add(u); db.commit(); db.refresh(u)
    t = db.query(models.AuthToken).filter(
        models.AuthToken.token == "pytest-token-admin").first()
    if t is None:
        db.add(models.AuthToken(token="pytest-token-admin", user_id=u.id,
                                expires_at=datetime.now() + timedelta(days=2)))
        db.commit()
    db.expunge_all()
    return {"Authorization": "Bearer pytest-token-admin"}


def test_modal_kosong_terdeteksi(client, db):
    auth = _client(client, db)
    # Bersihkan order periode ini supaya angka(test) tidak dipengaruhi test lain.
    _bersihkan(db)

    _order(db, "MK-KOSONG-1", part=0, jasa=0)
    _order(db, "MK-KOSONG-2", part=0, jasa=0)
    db.commit(); db.expunge_all()

    r = client.get("/api/kas/modal-kosong?period=current", headers=auth)
    assert r.status_code == 200, r.text
    d = r.json()
    # Hanya order milik test ini yang diperiksa: sandbox adalah SALINAN DB
    # produksi, jadi bisa ada order modal-0 lain yang sah dari sebelumnya.
    punya = set(x["no_servis"] for x in d["items"])
    assert {"MK-KOSONG-1", "MK-KOSONG-2"} <= punya, d
    assert d["jumlah"] >= 2, d
    # Keterangan harus menyatakan ini PERINGATAN KERAS dengan alasan yang benar.
    # Dulu berbunyi "modal 0 itu sah" -- itu tidak lagi sesuai aturan Owner.
    ket = d["keterangan"].lower()
    assert "belum masuk omzet" in ket, d["keterangan"]
    # Harus menyebut jalan keluarnya, bukan cuma Authenticating masalah.
    assert "tanpa modal (sengaja 0)" in ket, d["keterangan"]


def test_order_bermodal_tidak_ikut(client, db):
    auth = _client(client, db)
    _bersihkan(db)

    _order(db, "MK-AMAN-1", part=200000, jasa=0)
    _order(db, "MK-AMAN-2", part=0, jasa=150000)
    _order(db, "MK-AMAN-3", part=0, jasa=0, lain=50000)
    db.commit(); db.expunge_all()

    d = client.get("/api/kas/modal-kosong?period=current", headers=auth).json()
    assert not any(x["no_servis"].startswith("MK-") for x in d["items"]), d


def test_hanya_status_cash_yang_dihitung(client, db):
    auth = _client(client, db)
    _bersihkan(db)

    _order(db, "MK-DONE", status="DONE", part=0, jasa=0)
    _order(db, "MK-CANCEL", status="CANCEL", part=0, jasa=0)
    _order(db, "MK-FAILED", status="FAILED", part=0, jasa=0)
    _order(db, "MK-CASH", status="CASH", part=0, jasa=0)
    db.commit(); db.expunge_all()

    d = client.get("/api/kas/modal-kosong?period=current", headers=auth).json()
    punya = set(x["no_servis"] for x in d["items"])
    assert "MK-CASH" in punya, d
    assert not ({"MK-DONE", "MK-CANCEL", "MK-FAILED"} & punya), d
    # DONE belum menarik modal dari Laci sama sekali -> belum masalah.
    # CANCEL/FAILED bukan event realisasi -> tidak relevan untuk laba.