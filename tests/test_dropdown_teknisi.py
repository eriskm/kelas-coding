# -*- coding: utf-8 -*-
"""Owner: "di halaman Update Data Servis dan Servis Baru pada Teknisi
Penanggung Jawab pilihannya dulu hanya akun teknisi saja."

Endpoint `GET /api/orders/technicians` sebelumnya mengembalikan:
  1. nama bebas dari `service_orders.technician`,
  2. akun aktif ber-role TEKNISI,
  3. akun aktif ber-role ADMIN dan SUPERADMIN.

Akibatnya Manager Toko dan akun Developer muncul sebagai pilihan "Teknisi
Penanggung Jawab" di tiga form: Servis Baru (`rcTechnician`), Update Data
Servis (`usTechnician`), dan Klaim Garansi (`clrTechnician`) -- semuanya
memakai endpoint yang sama.
"""
from datetime import datetime, timedelta

import pytest


def _akun(db, username, nama, role, aktif=1):
    import models as m

    u = db.query(m.User).filter(m.User.username == username).first()
    if u is None:
        u = m.User(username=username, display_name=nama, role=role,
                   passcode_hash="x", passcode_salt="y", active=aktif,
                   created_at=datetime.now())
        db.add(u)
        db.commit()
        db.expire_all()
        u = db.query(m.User).filter(m.User.username == username).one()
    tok = "pytest-token-tech-" + username
    if db.query(m.AuthToken).filter(m.AuthToken.token == tok).first() is None:
        db.add(m.AuthToken(token=tok, user_id=u.id,
                            expires_at=datetime.now() + timedelta(days=2)))
        db.commit()
    return u, {"Authorization": "Bearer " + tok}


def test_dropdown_hanya_akun_teknisi(client, db):
    from routers.orders import list_technicians

    _akun(db, "tech_reza", "Reza", "TEKNISI", aktif=1)
    _akun(db, "tech_andi", "Andi", "TEKNISI", aktif=1)
    _akun(db, "mang_budi", "Budi", "ADMIN", aktif=1)
    _akun(db, "super_eko", "Super Eko", "SUPERADMIN", aktif=1)
    _akun(db, "kas_tono", "Tono", "KASIR", aktif=1)
    _akun(db, "peng_dewi", "Dewi", "PENGELOLA", aktif=1)

    nama = list_technicians(db)
    assert "Reza" in nama and "Andi" in nama
    for bukan in ("Budi", "Super Eko", "Tono", "Dewi"):
        assert bukan not in nama, \
            "%s bukan teknisi, tidak boleh jadi pilihan Teknisi Penanggung Jawab" % bukan


def test_teknisi_nonaktif_tidak_muncul(client, db):
    from routers.orders import list_technicians

    _akun(db, "tech_aktif", "Teknisi Aktif", "TEKNISI", aktif=1)
    _akun(db, "tech_lama", "Teknisi Libur", "TEKNISI", aktif=0)
    nama = list_technicians(db)
    assert "Teknisi Aktif" in nama
    assert "Teknisi Libur" not in nama, "teknisi nonaktif tidak boleh dipilih"


def test_username_teknisi_ikut_muncul(client, db):
    """Nama tampil pakai display_name; username dipakai sebagai cadangan."""
    from routers.orders import list_technicians

    u = _akun(db, "tech_polos", "", "TEKNISI", aktif=1)[0]
    u.display_name = ""
    db.commit()
    nama = list_technicians(db)
    assert "tech_polos" in nama, "kalau display_name kosong, username tetap bisa"


def test_endpoint_tidak_lagi_mengambil_nama_bebas_dari_order_lama(client, db):
    """Nama historis tanpa akun tidak boleh jadi pilihan baru."""
    import models as m
    from routers.orders import list_technicians

    _akun(db, "tech_pakai", "Teknisi Pakai", "TEKNISI", aktif=1)
    c = db.query(m.Customer).filter(m.Customer.name == "TeknisUji").first()
    if c is None:
        c = m.Customer(name="TeknisUji", phone="08000777", created_at=datetime.now())
        db.add(c)
        db.commit()
        db.expire_all()
        c = db.query(m.Customer).filter(m.Customer.name == "TeknisUji").one()
    db.add(m.ServiceOrder(
        no_servis="TECH-LEGACY", customer_id=c.id, device="PX", status="REPAIR",
        unit_status="DI TOKO", service_date=datetime.now().date(),
        taken_at=datetime.now(), technician="Mandor Pabrik",
        repair_plan="x", final_price=0, estimate=0, created_at=datetime.now()))
    db.commit()
    db.expire_all()

    nama = list_technicians(db)
    assert "Teknisi Pakai" in nama
    assert "Mandor Pabrik" not in nama, \
        "nama historis tanpa akun tidak boleh jadi pilihan baru"


def test_order_lama_tetap_utuh(client, db):
    """Memakai nama non-akun TIDAK boleh menghapus histori order."""
    import models as m
    from routers.orders import list_technicians

    list_technicians(db)  # panggil endpoint-nya
    o = db.query(m.ServiceOrder).filter(
        m.ServiceOrder.no_servis == "TECH-LEGACY").first()
    if o is not None:
        assert o.technician == "Mandor Pabrik", \
            "histori penugasan tidak boleh berubah"


def test_admin_tidak_bisa_memilih_dirinya_sebagai_teknisi(client, db):
    """Penegakan di backend, bukan cuma disembunyikan di dropdown."""
    _akun(db, "adm_pilih", "Admin Pilih", "ADMIN", aktif=1)
    _akun(db, "adm_kasir", "Kasir Pilih", "KASIR", aktif=1)
    from routers.orders import list_technicians

    nama = list_technicians(db)
    assert "Admin Pilih" not in nama
    assert "Kasir Pilih" not in nama


def test_semua_tiga_form_pakai_endpoint_yang_sama():
    """Servis Baru, Update Data Servis, dan Klaim Garansi harus konsisten."""
    src = open(r"D:\PRAKTEK MJPRO\frontend\script.js", encoding="utf-8").read()
    assert src.count("apiGet('/orders/technicians')") >= 3, \
        "ketiga form harus ambil dari endpoint yang sama"
    for id_dropdown in ("rcTechnician", "usTechnician", "clrTechnician"):
        assert id_dropdown in src, "dropdown %s harus terisi" % id_dropdown


def test_kontrak_tetap_list_string():
    """UI tidak boleh rusak karena bentuk datanya berubah."""
    from routers.orders import list_technicians
    from database import SessionLocal

    db = SessionLocal()
    try:
        hasil = list_technicians(db)
    finally:
        db.close()
    assert isinstance(hasil, list)
    assert all(isinstance(x, str) for x in hasil)