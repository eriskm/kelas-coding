# -*- coding: utf-8 -*-
"""Owner (Kelola Akun) -- koreksi aturan:

  1. "Nonaktifkan, bukan hapus."
  2. "Teknisi nonaktif tidak bisa login atau menerima penugasan baru."
  3. "Histori servis, garansi, laporan kinerja, dan audit transaksi lama
      tidak boleh ikut terhapus."
  4. "Jika ada koreksi data teknisi, perubahan harus tercatat dan tidak boleh
      diam-diam mengubah histori lama."
  5. "Penghapusan permanen hanya boleh dipertimbangkan jika tidak melanggar
      kebutuhan audit, retensi data, dan aturan yang berlaku."

Jadi fitur HAPUS PERMANEN dibatalkan. Yang ada hanya Nonaktifkan, dan setiap
perubahan akun harus masuk journal.
"""
from datetime import datetime, timedelta

import pytest


def _akun(db, username, nama, role="TEKNISI", aktif=1):
    import models

    u = db.query(models.User).filter(models.User.username == username).first()
    if u is None:
        u = models.User(username=username, display_name=nama, role=role,
                        passcode_hash="x", passcode_salt="y", active=aktif,
                        created_at=datetime.now())
        db.add(u)
        db.commit()
        db.expire_all()
        u = db.query(models.User).filter(models.User.username == username).one()
    tok = "pytest-token-akun-" + username
    t = db.query(models.AuthToken).filter(models.AuthToken.token == tok).first()
    if t is None:
        db.add(models.AuthToken(token=tok, user_id=u.id,
                                expires_at=datetime.now() + timedelta(days=2)))
        db.commit()
    return u, {"Authorization": "Bearer " + tok}


def _unit_baru(client, hdr, telepon, estimate=100000):
    """Buat unit lewat endpoint receive (payload mengikuti schema aslinya)."""
    r = client.post("/api/orders/receive", headers=hdr, json={
        "customer_name": "Pelanggan " + telepon,
        "phone": telepon,
        "device": "PX",
        "keluhan": "k",
        "estimate": estimate,
        "dp": 0,
    })
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


# ────────────── (1) HAPUS PERMANEN HANYA SUPERADMIN ──────────────
def test_backend_punya_endpoint_hapus_akun_superadmin():
    """Owner: SUPERADMIN boleh hapus akun lain (non-superadmin)."""
    import inspect

    import routers.auth as auth_router

    assert hasattr(auth_router, "delete_user"), \
        "fungsi hapus akun harus ada untuk SUPERADMIN"
    src = inspect.getsource(auth_router)
    assert "@router.delete(\"/users" in src, \
        "harus ada DELETE /users/{id}"


def test_frontend_tidak_punya_tombol_hapus_untuk_non_superadmin():
    src = open(r"D:\PRAKTEK MJPRO\frontend\script.js", encoding="utf-8").read()
    # Frontend tetap tidak punya tombol hapus untuk non-superadmin
    assert "function akHapus" not in src
    assert "akBolehHapus" not in src
    assert "Hapus Akun permanen" not in src
    assert "fa-trash-can" not in src


def test_superadmin_bisa_hapus_akun_lain(client, db):
    """SUPERADMIN boleh hapus akun non-superadmin."""
    import models

    superadmin, super_hdr = _akun(db, "del_super", "Super Admin", "SUPERADMIN")
    target, _ = _akun(db, "del_target", "Teknisi Target", "TEKNISI", aktif=1)
    uid, uname = target.id, target.username

    # Journal AKUN_DIHAPUS tercatat (pakai delta karena DB shared antar test)
    before = len(_jurnal(db, "AKUN_DIHAPUS"))

    r = client.delete("/api/auth/users/%d" % uid, headers=super_hdr)
    assert r.status_code == 200, r.text
    db.expire_all()

    # Akun terhapus permanen
    assert db.query(models.User).filter(models.User.username == uname).first() is None

    # Journal AKUN_DIHAPUS tercatat (pakai delta karena DB shared antar test)
    rows = _jurnal(db, "AKUN_DIHAPUS")
    assert len(rows) >= before + 1
    entry = rows[-1]
    assert entry.actor == "del_super"
    assert entry.entity_id == uid
    detail = entry.details or {}
    assert "perubahan" in detail
    # Journal mencatat field yang berubah: username/display_name/role/active -> None
    assert "username" in detail["perubahan"]
    assert detail["perubahan"]["username"][0] == uname
    assert detail["perubahan"]["username"][1] is None


def test_superadmin_tidak_boleh_hapus_sendiri(client, db):
    """SUPERADMIN tidak boleh hapus akun sendiri."""
    import models

    superadmin, super_hdr = _akun(db, "del_self", "Super Admin Self", "SUPERADMIN")
    uid = superadmin.id

    r = client.delete("/api/auth/users/%d" % uid, headers=super_hdr)
    assert r.status_code == 400, r.text
    assert "sendiri" in (r.json().get("detail") or "").lower()

    # Akun masih ada
    db.expire_all()
    assert db.query(models.User).filter(models.User.id == uid).first() is not None


def test_admin_tidak_boleh_hapus_akun(client, db):
    """ADMIN tidak punya ROLE_CONFIG, tidak boleh hapus."""
    import models

    admin, hdr = _akun(db, "del_admin", "Admin Toko", "ADMIN")
    superadmin, super_hdr = _akun(db, "del_admin_super", "Super Admin", "SUPERADMIN")
    target, _ = _akun(db, "del_target2", "Teknisi Target 2", "TEKNISI", aktif=1)
    uid = target.id

    r = client.delete("/api/auth/users/%d" % uid, headers=hdr)
    assert r.status_code == 403, r.text

    # Akun masih ada
    db.expire_all()
    assert db.query(models.User).filter(models.User.id == uid).first() is not None


def test_nonaktifkan_tetap_ada_dan_bisa_dibalik(client, db):
    import models

    admin, hdr = _akun(db, "akun_admin", "Admin Toko", "ADMIN")
    superadmin, super_hdr = _akun(db, "akun_super", "Super Admin", "SUPERADMIN")
    target, _ = _akun(db, "akun_target", "Teknisi Satu")
    uid, uname = target.id, target.username

    r = client.put("/api/auth/users/%d" % uid, headers=super_hdr, json={"active": 0})
    assert r.status_code == 200, r.text
    db.expire_all()
    row = db.query(models.User).filter(models.User.username == uname).one()
    assert row.active == 0, "harus nonaktif"
    assert row.display_name == "Teknisi Satu", "histori data harus utuh"

    r = client.put("/api/auth/users/%d" % uid, headers=super_hdr, json={"active": 1})
    assert r.status_code == 200, r.text
    db.expire_all()
    assert db.query(models.User).filter(
        models.User.username == uname).one().active == 1


# ────────────── (2) TEKNISI NONAKTIF ──────────────
def test_akun_nonaktif_tidak_bisa_login(client, db):
    _akun(db, "akun_login", "Teknisi Login", "TEKNISI", aktif=0)
    r = client.post("/api/auth/login",
                    json={"username": "akun_login", "passcode": "apa saja"})
    assert r.status_code in (400, 401), r.text


def test_teknisi_nonaktif_tidak_masuk_daftar_pilihan(client, db):
    import models

    admin, hdr = _akun(db, "akun_pilihan_admin", "Admin Pilihan", "ADMIN")
    _akun(db, "akun_pilihan_aktif", "Teknisi Aktif", "TEKNISI", aktif=1)
    _akun(db, "akun_pilihan_off", "Teknisi Nonaktif", "TEKNISI", aktif=0)

    r = client.get("/api/orders/technicians", headers=hdr)
    assert r.status_code == 200, r.text
    nama = r.json()
    assert "Teknisi Aktif" in nama
    assert "Teknisi Nonaktif" not in nama, \
        "teknisi nonaktif tidak boleh muncul sebagai pilihan penugasan baru"


def test_unit_lama_tidak_ikut_terhapus(client, db):
    """Aturan (3): histori servis tidak boleh ikut terhapus."""
    import models

    _akun(db, "akun_historis_admin", "Admin Historis", "ADMIN")
    tech, _ = _akun(db, "akun_historis", "Teknisi Historis", "TEKNISI", aktif=1)
    admin, hdr = _akun(db, "akun_historis_admin", "Admin Historis", "ADMIN")
    superadmin, super_hdr = _akun(db, "akun_historis_super", "Super Admin", "SUPERADMIN")
    tech, _ = _akun(db, "akun_historis", "Teknisi Historis", "TEKNISI", aktif=1)
    oid = _unit_baru(client, hdr, "08000000777")
    r = client.put("/api/orders/%d" % oid, headers=hdr,
                   json={"status": "REPAIR", "status_note": "diterima", "technician": "Teknisi Historis",
                         "repair_plan": "x", "estimate": 100000})
    assert r.status_code == 200, r.text

    uid = tech.id
    client.put("/api/auth/users/%d" % uid, headers=super_hdr, json={"active": 0})
    db.expire_all()
    o = db.query(models.ServiceOrder).filter(models.ServiceOrder.id == oid).one()
    assert o.technician == "Teknisi Historis", \
        "riwayat penugasan di unit lama harus tetap utuh"


def test_penugasan_baru_ke_teknisi_nonaktif_ditolak(client, db):
    """Aturan (2): penugasan BARU ke teknisi nonaktif harus ditolak.
    
    User management (nonaktifkan) hanya SUPERADMIN.
    """
    import models

    admin, hdr = _akun(db, "akun_penugasan_admin", "Admin Penugasan", "ADMIN")
    superadmin, super_hdr = _akun(db, "akun_penugasan_super", "Super Admin", "SUPERADMIN")
    _akun(db, "akun_penugasan", "Teknisi Di Liburkan", "TEKNISI", aktif=1)

    oid = _unit_baru(client, hdr, "08000000778")


    client.put("/api/auth/users/%d" %
               db.query(models.User).filter(
                   models.User.username == "akun_penugasan").one().id,
               headers=super_hdr, json={"active": 0})
    db.expire_all()

    r = client.put("/api/orders/%d" % oid, headers=hdr,
                   json={"status": "REPAIR", "status_note": "diterima",
                         "technician": "Teknisi Di Liburkan",
                         "repair_plan": "x", "estimate": 100000})
    assert r.status_code == 400, "harus 400, dapat %s" % r.status_code
    assert "dinonaktifkan" in (r.json().get("detail") or "").lower()


def test_teknisi_aktif_tetas_bisa_ditugaskan(client, db):
    """Penjaga baru tidak boleh merusak alur normal."""
    import models

    admin, hdr = _akun(db, "akun_normal_admin", "Admin Normal", "ADMIN")
    _akun(db, "akun_normal", "Teknisi Normal", "TEKNISI", aktif=1)
    oid = _unit_baru(client, hdr, "08000000779")

    r = client.put("/api/orders/%d" % oid, headers=hdr,
                   json={"status": "REPAIR", "status_note": "diterima", "technician": "Teknisi Normal",
                         "repair_plan": "x", "estimate": 100000})
    assert r.status_code == 200, r.text


def test_nama_bebas_yang_bukan_akun_masih_diterima(client, db):
    """Teknisi yang hanya ada di data lama (nama bebas) tidak boleh terkunci."""
    admin, hdr = _akun(db, "akun_bebas_admin", "Admin Bebas", "ADMIN")
    oid = _unit_baru(client, hdr, "08000000780")

    r = client.put("/api/orders/%d" % oid, headers=hdr,
                   json={"status": "REPAIR", "status_note": "diterima", "technician": "Mandor Pabrik",
                         "repair_plan": "x", "estimate": 100000})
    assert r.status_code == 200, r.text


# ────────────── (4) KOREKSI HARUS TERCATAT ──────────────
def _jurnal(db, event):
    import models

    return (db.query(models.JournalEntry)
            .filter(models.JournalEntry.event == event).all())


def test_menonaktifkan_akun_tercatat_di_jurnal(client, db):
    """Owner: koreksi tidak boleh diam-diam.
    
    User management hanya SUPERADMIN.
    """
    import models

    admin, hdr = _akun(db, "akun_jurnal_admin", "Admin Jurnal", "ADMIN")
    superadmin, super_hdr = _akun(db, "akun_jurnal_super", "Super Admin", "SUPERADMIN")
    target, _ = _akun(db, "akun_jurnal", "Teknisi Jurnal", "TEKNISI", aktif=1)
    uid, uname = target.id, target.username

    before = len(_jurnal(db, "AKUN_DIUBAH"))
    r = client.put("/api/auth/users/%d" % uid, headers=super_hdr, json={"active": 0})
    assert r.status_code == 200, r.text
    db.expire_all()

    rows = _jurnal(db, "AKUN_DIUBAH")
    assert len(rows) == before + 1, "perubahan akun harus tercatat di journal"
    entry = rows[-1]
    detail = entry.details or {}
    assert "perubahan" in detail, "journal harus menyimpan nilai sebelum/sesudah"
    assert "active" in detail["perubahan"], "perubahan status harus tercatat"
    assert detail["perubahan"]["active"] == [1, 0], \
        "harus menyimpan nilai SEBELUM dan SESUDAH, got %r" % (
            detail["perubahan"]["active"],)


def test_membuat_akun_tercatat_di_jurnal(client, db):
    """User management hanya SUPERADMIN."""
    admin, hdr = _akun(db, "akun_buat_admin", "Admin Buat", "ADMIN")
    superadmin, super_hdr = _akun(db, "akun_buat_super", "Super Admin", "SUPERADMIN")
    before = len(_jurnal(db, "AKUN_DIBUAT"))
    r = client.post("/api/auth/users", headers=super_hdr,
                    json={"username": "akun_baru", "display_name": "Akun Baru",
                          "passcode": "1234", "role": "TEKNISI", "active": 1})
    assert r.status_code == 201, r.text
    db.expire_all()
    assert len(_jurnal(db, "AKUN_DIBUAT")) == before + 1


def test_jurnal_akun_menyimpan_aktor(client, db):
    """User management hanya SUPERADMIN. Actor di jurnal adalah SUPERADMIN."""
    import models

    admin, hdr = _akun(db, "akun_aktor", "Admin Aktor", "ADMIN")
    superadmin, super_hdr = _akun(db, "akun_aktor_super", "Super Admin", "SUPERADMIN")
    target, _ = _akun(db, "akun_aktor_t", "Teknisi Aktor", "TEKNISI", aktif=1)
    uid = target.id
    client.put("/api/auth/users/%d" % uid, headers=super_hdr, json={"active": 0})
    db.expire_all()
    entry = _jurnal(db, "AKUN_DIUBAH")[-1]
    assert entry.actor == "akun_aktor_super", \
        "jurnal harus tahu siapa yang mengubah (SUPERADMIN), got %r" % entry.actor


def test_perubahan_nama_tercatat(client, db):
    """User management hanya SUPERADMIN."""
    import models

    admin, hdr = _akun(db, "akun_nama_admin", "Admin Nama", "ADMIN")
    superadmin, super_hdr = _akun(db, "akun_nama_super", "Super Admin", "SUPERADMIN")
    target, _ = _akun(db, "akun_nama", "Nama Lama", "TEKNISI", aktif=1)
    uid = target.id
    r = client.put("/api/auth/users/%d" % uid, headers=super_hdr,
                   json={"display_name": "Nama Baru"})
    assert r.status_code == 200, r.text
    db.expire_all()
    entry = _jurnal(db, "AKUN_DIUBAH")[-1]
    perubahan = (entry.details or {}).get("perubahan", {})
    assert "display_name" in perubahan, \
        "koreksi nama harus tercatat, got %r" % list(perubahan)
