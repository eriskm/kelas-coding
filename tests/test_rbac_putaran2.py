# -*- coding: utf-8 -*-
"""RBAC putaran 2 - lima keputusan Owner.

1. SUPERADMIN: akun lama TIDAK diubah; Super Admin baru dibuat lewat mekanisme
   aman di luar aplikasi. Password/token tidak pernah disalin atau ditampilkan.
2. TEKNISI / ORDER_CREATE: diaudit dulu, lalu dicabut karena penerimaan unit
   adalah tugas Kasir/CS.
3. INVESTOR: boleh melihat RINGKASAN Kas Aset + Hutang Beban (read-only).
4. ADMIN SPAREPART: permission sparepart dipisah dari laporan keuangan.
5. EKSPOR LAPORAN: endpoint CSV untuk Pengelola dan Investor, dengan
   pembatasan data yang sama dengan tampilan.
"""
from datetime import datetime, timedelta

import pytest


def _tok(db, username, role):
    """Buat akun + token. Mengembalikan `(objek_user, header)`.

   mengembalikan user juga penting supaya test bisa memakai `.id`-nya tanpa
   query ulang.
    """
    import models

    u = db.query(models.User).filter(models.User.username == username).first()
    if u is None:
        u = models.User(username=username, display_name=username.title(),
                        role=role, passcode_hash="x", passcode_salt="y",
                        active=1, created_at=datetime.now())
        db.add(u)
        db.commit()
        db.expire_all()
        u = db.query(models.User).filter(models.User.username == username).one()
    tok = "pytest-token-rbac2-" + username
    if db.query(models.AuthToken).filter(models.AuthToken.token == tok).first() is None:
        db.add(models.AuthToken(token=tok, user_id=u.id,
                                expires_at=datetime.now() + timedelta(days=2)))
        db.commit()
    return u, {"Authorization": "Bearer " + tok}


def _hdr(db, username, role):
    """Shortcut kalau test hanya butuh header."""
    return _tok(db, username, role)[1]


def _u(role):
    class _U:
        pass
    u = _U()
    u.role = role
    u.display_name = role
    u.username = role
    return u


# ───────────────── (1) SUPER ADMIN baru ─────────────────
def test_akun_lama_tidak_diubah_otomatis():
    """Tidak boleh ada kode yang menaikkan role akun yang sudah ada."""
    import inspect

    import routers.auth as a

    src = inspect.getsource(a)
    for jahat in ("auto_promote", "ensure_superadmin", "promote(",
                  "upgrade_role"):
        assert jahat not in src, "dilarang auto-promote: %s" % jahat


def test_admin_tidak_bisa_buat_akun_superadmin(client, db):
    """Privilege escalation lewat pembuatan akun harus tertutup."""
    hdr = _hdr(db, "rbac2_admin", "ADMIN")
    r = client.post("/api/auth/users", headers=hdr,
                    json={"username": "selfmade", "display_name": "Self",
                          "passcode": "rahasia123", "role": "SUPERADMIN"})
    assert r.status_code == 403, "Admin tidak boleh membuat Super Admin: %s" % r.status_code
    import models
    assert db.query(models.User).filter(
        models.User.username == "selfmade").count() == 0


def test_admin_tidak_bisa_tingkatkan_akun_ke_superadmin(client, db):
    import models

    admin, hdr = _tok(db, "rbac2_admin_prom", "ADMIN")
    target, _ = _tok(db, "rbac2_biasa", "KASIR")
    r = client.put("/api/auth/users/%d" % target.id, headers=hdr,
                   json={"role": "SUPERADMIN"})
    assert r.status_code == 403, r.text


def test_superadmin_boleh_bikin_akun_superadmin_lain(client, db):
    """Setelah ada, mekanisme normal: Super Admin sendiri yang menambah."""
    _tok(db, "rbac2_super", "SUPERADMIN")
    hdr = _hdr(db, "rbac2_super", "SUPERADMIN")
    r = client.post("/api/auth/users", headers=hdr,
                    json={"username": "super2", "display_name": "Super 2",
                          "passcode": "rahasia123", "role": "SUPERADMIN"})
    assert r.status_code == 201, r.text


def test_skrip_bootstrap_ada_dan_aman():
    """Mekanisme pembuatan akun Super Admin pertama."""
    import inspect
    import os

    import bootstrap_superadmin as bs

    src = inspect.getsource(bs)
    assert "getpass.getpass" in src, "passcode harus diketik, bukan dicetak"
    assert "print(passcode" not in src, "passcode tidak boleh dicetak"
    assert "passcode_hash" in src, "harus di-hash"
    # Tidak boleh mengubah akun yang ada.
    assert "db.delete" not in src, "skrip tidak boleh menghapus akun"
    assert ".active = 0" not in src, "skrip tidak boleh menonaktifkan akun"
    # Satu kali saja.
    assert "_sudah_ada_superadmin" in src


def test_skrip_berhenti_kalau_sudah_ada_superadmin():
    import bootstrap_superadmin as bs

    assert bs._sudah_ada_superadmin.__doc__ is None or True

    class _S:
        def query(self, *a, **k):
            return self

        def all(self):
            class _U:
                def __init__(self, role):
                    self.role = role
            return [_U("ADMIN"), _U("SUPERADMIN")]

    assert bs._sudah_ada_superadmin(_S()) is True

    class _S2:
        def query(self, *a, **k):
            return self

        def all(self):
            class _U:
                role = "ADMIN"
            return [_U(), _U()]

    assert bs._sudah_ada_superadmin(_S2()) is False


# ───────────────── (2) ORDER_CREATE ─────────────────
def test_teknisi_tidak_bisa_terima_unit(client, db):
    hdr = _hdr(db, "rbac2_teknisi", "TEKNISI")
    r = client.post("/api/orders/receive", headers=hdr,
                    json={"customer_name": "X", "customer_phone": "0800",
                          "device": "PX", "estimate": 1000, "dp": 0})
    assert r.status_code == 403, "penerimaan unit adalah tugas Kasir/CS: %s" % r.status_code


def test_teknisi_tetap_bisa_kerja_unit():
    """Alur servis TIDAK boleh beku."""
    import authority as A

    assert A.can(_u("TEKNISI"), A.Action.ORDER_UPDATE) is True
    assert A.can(_u("TEKNISI"), A.Action.ORDER_HANDOVER) is True


def test_kasir_tetap_bisa_terima_unit(client, db):
    hdr = _hdr(db, "rbac2_kasir", "KASIR")
    r = client.post("/api/orders/receive", headers=hdr,
                    json={"customer_name": "Uji", "customer_phone": "0800123",
                          "device": "PX", "estimate": 1000, "dp": 0})
    assert r.status_code in (200, 201), r.text


# ───────────────── (3) INVESTOR ringkasan kas aset ─────────────────
def test_investor_bisa_lihat_ringkasan_investasi(client, db):
    hdr = _hdr(db, "rbac2_investor", "INVESTOR")
    r = client.get("/api/laporan/investasi", headers=hdr)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "kas_aset" in data and "saldo" in data["kas_aset"]
    assert "hutang_beban" in data and "saldo" in data["hutang_beban"]
    assert data["hak_bagi_hasil"]["rate"] == "30%"


def test_ringkasan_investasi_tidak_bocor_data_pelanggan(client, db):
    """Investor tidak boleh melihat data pribadi pelanggan."""
    hdr = _hdr(db, "rbac2_investor2", "INVESTOR")
    r = client.get("/api/laporan/investasi", headers=hdr)
    assert r.status_code == 200
    teks = r.text.lower()
    for terlarang in ("no_servis", "no servis", "customer", "telepon", "phone",
                      "nama_pelanggan", "device"):
        assert terlarang not in teks, \
            "ringkasan investasi membocorkan '%s'" % terlarang


@pytest.mark.parametrize("role", ["PENGELOLA", "TEKNISI", "KASIR",
                                  "ADMIN SPAREPART"])
def test_endpoint_investasi_batasi_role(client, db, role):
    hdr = _hdr(db, "rbac2_inv_" + role.replace(" ", "_").lower(), role)
    r = client.get("/api/laporan/investasi", headers=hdr)
    # PENGELOLA punya REPORT_FULL tapi bukan REPORT_INVESTOR -> tetap 403.
    assert r.status_code == 403, "%s seharusnya 403, dapat %s" % (role, r.status_code)


def test_investor_tidak_bisa_menutup_kas(client, db):
    hdr = _hdr(db, "rbac2_inv_tutup", "INVESTOR")
    r = client.post("/api/kas/close", headers=hdr, json={})
    assert r.status_code == 403


def test_investor_tidak_bisa_ubah_saldo_kas_aset(client, db):
    hdr = _hdr(db, "rbac2_inv_ubah", "INVESTOR")
    r = client.post("/api/kas/aset/masuk", headers=hdr,
                    json={"nominal": 1000, "keterangan": "x", "posisi": "KAS_ASET"})
    assert r.status_code == 403
    r = client.post("/api/kas/aset/keluar", headers=hdr,
                    json={"nominal": 1000, "keterangan": "x"})
    assert r.status_code == 403


# ───────────────── (4) ADMIN SPAREPART ─────────────────
def test_admin_sparepart_tidak_punya_laporan_keuangan():
    import authority as A

    assert A.can(_u("ADMIN SPAREPART"), A.Action.REPORT_FULL) is False
    assert A.can(_u("ADMIN SPAREPART"), A.Action.REPORT_INVESTOR) is False
    assert A.can(_u("ADMIN SPAREPART"), A.Action.REPORT_SPAREPART) is True
    assert A.can(_u("ADMIN SPAREPART"), A.Action.SPAREPART_WRITE) is True


def test_admin_sparepart_tidak_bisa_buka_laporan_bisnis(client, db):
    hdr = _hdr(db, "rbac2_spare", "ADMIN SPAREPART")
    r = client.get("/api/laporan/bisnis", headers=hdr)
    assert r.status_code == 403, r.text


def test_admin_sparepart_tidak_bisa_ekspor_laba(client, db):
    hdr = _hdr(db, "rbac2_spare2", "ADMIN SPAREPART")
    r = client.get("/api/laporan/export?jenis=laba-bersih", headers=hdr)
    assert r.status_code == 403, r.text


def test_admin_sparepart_tidak_bisa_tutup_kas(client, db):
    hdr = _hdr(db, "rbac2_spare3", "ADMIN SPAREPART")
    r = client.post("/api/kas/close", headers=hdr, json={})
    assert r.status_code == 403


# ───────────────── (5) EKSPOR LAPORAN ─────────────────
def test_pengelola_bisa_ekspor_laba(client, db):
    hdr = _hdr(db, "rbac2_peng", "PENGELOLA")
    r = client.get("/api/laporan/export?jenis=laba-bersih", headers=hdr)
    assert r.status_code == 200, r.text
    assert "attachment" in r.headers.get("content-disposition", "")
    assert "text/csv" in r.headers.get("content-type", "")
    assert "Laba Kotor" in r.text


def test_pengelola_bisa_ekspor_bagi_hasil(client, db):
    hdr = _hdr(db, "rbac2_peng2", "PENGELOLA")
    r = client.get("/api/laporan/export?jenis=bagi-hasil", headers=hdr)
    assert r.status_code == 200, r.text


def test_investor_bisa_ekspor_hanya_bagian_investor(client, db):
    """Investor hanya boleh laporan investasinya, tidak laporan bisnis."""
    hdr = _hdr(db, "rbac2_inv_exp", "INVESTOR")
    r = client.get("/api/laporan/export?jenis=bagian-investor", headers=hdr)
    assert r.status_code == 200, r.text
    assert "Hak Bagi Hasil Investor" in r.text

    # Laporan bisnis DITOLAK untuk Investor.
    r = client.get("/api/laporan/export?jenis=laba-bersih", headers=hdr)
    assert r.status_code == 403, "Investor tidak boleh ekspor laba-bersih"


@pytest.mark.parametrize("jenis", ["laba-bersih", "bagi-hasil"])
def test_investor_ditolak_laporan_bisnis(client, db, jenis):
    hdr = _hdr(db, "rbac2_inv_" + jenis.replace("-", "_"), "INVESTOR")
    r = client.get("/api/laporan/export?jenis=%s" % jenis, headers=hdr)
    assert r.status_code == 403


@pytest.mark.parametrize("role", ["TEKNISI", "KASIR", "ADMIN SPAREPART"])
def test_role_operasional_tidak_bisa_ekspor(client, db, role):
    hdr = _hdr(db, "rbac2_exp_" + role.replace(" ", "_").lower(), role)
    r = client.get("/api/laporan/export?jenis=laba-bersih", headers=hdr)
    assert r.status_code == 403, "%s tidak boleh ekspor laporan" % role


def test_pengelola_bisa_ekspor_laporan_bisnis(client, db):
    hdr = _hdr(db, "rbac2_peng3", "PENGELOLA")
    r = client.get("/api/laporan/bisnis", headers=hdr)
    assert r.status_code == 200, r.text
    assert r.json()["untuk"] == "PENGELOLA"


def test_jenis_laporan_asing_ditolak(client, db):
    hdr = _hdr(db, "rbac2_peng4", "PENGELOLA")
    r = client.get("/api/laporan/export?jenis=sql-ini", headers=hdr)
    assert r.status_code == 400, r.text


def test_ekspor_tanpa_token_ditolak(client, db):
    r = client.get("/api/laporan/export?jenis=laba-bersih")
    assert r.status_code == 401
    r = client.get("/api/laporan/investasi")
    assert r.status_code == 401


def test_ekspor_tidak_bocor_data_pelanggan(client, db):
    hdr = _hdr(db, "rbac2_peng5", "PENGELOLA")
    r = client.get("/api/laporan/export?jenis=laba-bersih", headers=hdr)
    assert r.status_code == 200
    teks = r.text.lower()
    for terlarang in ("no_servis", "telepon", "phone", "nama pelanggan"):
        assert terlarang not in teks, "ekspor membocorkan '%s'" % terlarang


def test_modul_laporan_tidak_punya_endpoint_tulis():
    """Modul laporan harus baca-saja sepenuhnya."""
    from routers import laporan

    for r in laporan.router.routes:
        metode = getattr(r, "methods", set())
        assert not (metode & {"POST", "PUT", "PATCH", "DELETE"}), \
            "router laporan tidak boleh punya endpoint tulis: %s" % (metode,)


def test_modul_laporan_memakai_otorisasi_backend():
    """Semua endpoint laporan wajib dijaga `require_authority`."""
    import inspect

    from routers import laporan

    src = inspect.getsource(laporan)
    n_endpoint = src.count("@router.get(")
    n_otorisasi = (src.count("Depends(require_authority(")
                   + src.count("Depends(require_any_authority("))
    assert n_endpoint > 0
    assert n_otorisasi >= n_endpoint, \
        "semua %d endpoint laporan harus ber-require_authority" % n_endpoint
