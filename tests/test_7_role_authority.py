# -*- coding: utf-8 -*-
"""Penyesuaian hak akses 7 role BOSS SF (Owner, struktur resmi).

SUPER ADMIN  - akun Developer: akun, role, permission, konfigurasi, audit log.
ADMIN        - Manager Toko: operasional, Tutup Kas, mengawasi tim.
PENGELOLA    - Pemilik: monitoring, laporan detail + unduh. 30% bagi hasil.
INVESTOR     - Monitoring investasi: laporan relevan, dasar bagi hasil 30%.
KASIR / CS   - Terima unit, pembayaran, nota, ambil unit. BUKAN modal/laba.
TEKNISI      - Kerjakan unit, diagnosis, catatan teknis. BUKAN keuangan.
ADMIN SPAREPART - Kelola barang/stok. BUKAN transaksi pelanggan.

Yang diuji di sini:
  - matriks authority sesuai pembagian tugas;
  - lewat HTTP: role monitoring benar-benar tidak bisa menulis;
  - privilege escalation: param/session/role di luar daftar tidak memberi hak.
"""
from datetime import datetime, timedelta

import pytest


# ──────────────────────────── util ────────────────────────────
def _tok(db, username, role):
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
    tok = "pytest-token-7role-" + username
    if db.query(models.AuthToken).filter(models.AuthToken.token == tok).first() is None:
        db.add(models.AuthToken(token=tok, user_id=u.id,
                                expires_at=datetime.now() + timedelta(days=2)))
        db.commit()
    return {"Authorization": "Bearer " + tok}


SEMUA_ROLE = ["SUPERADMIN", "ADMIN", "KASIR", "TEKNISI",
              "ADMIN SPAREPART", "PENGELOLA", "INVESTOR"]

MONITORING = ["PENGELOLA", "INVESTOR"]


def _u(role):
    class _U:
        pass
    u = _U()
    u.role = role
    u.display_name = role
    u.username = str(role).lower()
    return u


# ─────────────────────── (1) Role terpisah ───────────────────────
def test_tujuh_role_terdaftar_dan_unik():
    import authority as A

    assert len(set(SEMUA_ROLE)) == 7, "role harus 7 dan tidak boleh duplikat"
    for r in SEMUA_ROLE:
        # Semua alias harus mengembalikan canonical role yang konsisten,
        # dan tiap role harus punya canonical sendiri yang unik.
        kanon = A.canonical_role(_u(r))
        assert A.ROLE_ALIASES[A.ROLE_ALIASES[kanon]] == kanon, \
            "%s tidak konsisten: %s -> %s" % (r, kanon, A.ROLE_ALIASES[kanon])
    kanon = [A.canonical_role(_u(r)) for r in SEMUA_ROLE]
    assert len(set(kanon)) == 7, \
        "tujuh role harus menghasilkan tujuh role berbeda, dapat: %s" % kanon


def test_superadmin_bukan_alias_admin():
    """Owner: Super Admin = akun Developer, BUKAN Manager Toko."""
    import authority as A

    assert A.ROLE_SUPERADMIN != A.ROLE_ADMIN
    assert A.ROLE_ALIASES["SUPERADMIN"] == A.ROLE_SUPERADMIN
    assert A.canonical_role(_u("SUPERADMIN")) == A.ROLE_SUPERADMIN


def test_tidak_ada_role_duplikat_di_alias():
    import authority as A

    # Dua alias yang menunjuk role berbeda Boleh; satu alias tidak boleh
    # di-zombikan dipakai dua nama resmi yang berbeda.
    assert A.ROLE_ALIASES["ADMIN"] == A.ROLE_ADMIN
    assert A.ROLE_ALIASES["SUPERADMIN"] != A.ROLE_ALIASES["ADMIN"]
    assert A.ROLE_ALIASES["ADMIN SPAREPART"] == A.ROLE_ADMIN_SPAREPART
    assert A.ROLE_ALIASES["ADMIN SPAREPART"] != A.ROLE_ALIASES["ADMIN"]


# ─────────────────────── (2) Pembagian tugas ───────────────────────
def test_superadmin_milik_semua_aksi():
    import authority as A

    kurang = [a for a in A.AUTHORITY_MATRIX
              if not A.can(_u("SUPERADMIN"), a)]
    assert kurang == [], "Super Admin harus punya semua aksi, kurang: %s" % kurang


def test_superadmin_memilik_role_config():
    import authority as A

    assert A.can(_u("SUPERADMIN"), A.Action.ROLE_CONFIG) is True


@pytest.mark.parametrize("role", ["ADMIN", "KASIR", "TEKNISI",
                                  "ADMIN SPAREPART", "PENGELOLA", "INVESTOR"])
def test_role_config_hanya_superadmin(role):
    import authority as A

    assert A.can(_u(role), A.Action.ROLE_CONFIG) is False, \
        "%s tidak boleh mengubah role/permission/konfigurasi" % role


def test_hanya_admin_dan_superadmin_yang_tutup_kas():
    import authority as A

    assert A.can(_u("ADMIN"), A.Action.KAS_CLOSE) is True
    assert A.can(_u("SUPERADMIN"), A.Action.KAS_CLOSE) is True
    for role in ("KASIR", "TEKNISI", "ADMIN SPAREPART", "PENGELOLA", "INVESTOR"):
        assert A.can(_u(role), A.Action.KAS_CLOSE) is False, \
            "%s tidak boleh menjalankan Tutup Kas" % role


def test_teknisi_tidak_bisa_uang():
    import authority as A

    for aksi in (A.Action.ORDER_UPDATE_FINANCE, A.Action.ORDER_UPDATE_MODAL,
                 A.Action.PAYMENT_CREATE, A.Action.PAYMENT_CANCEL,
                 A.Action.EXPENSE_WRITE, A.Action.KAS_CLOSE,
                 A.Action.ORDER_STATUS_CLOSING, A.Action.KAS_ASET_INJEKSI,
                 A.Action.REFUND_GARANSI, A.Action.CUSTOMER_WRITE):
        assert A.can(_u("TEKNISI"), aksi) is False, \
            "Teknisi tidak boleh: %s" % aksi


def test_kasir_tidak_bisa_modal_laba_beban():
    import authority as A

    assert A.can(_u("KASIR"), A.Action.ORDER_UPDATE_MODAL) is False, \
        "Kasir tidak boleh mengubah modal"
    assert A.can(_u("KASIR"), A.Action.EXPENSE_WRITE) is False, \
        "Kasir tidak boleh mencatat beban"
    assert A.can(_u("KASIR"), A.Action.KAS_CLOSE) is False, \
        "Kasir tidak boleh Tutup Kas"


def test_kasir_tetap_bisa_terima_dan_membayar():
    import authority as A

    for aksi in (A.Action.ORDER_CREATE, A.Action.PAYMENT_CREATE,
                 A.Action.ORDER_HANDOVER, A.Action.REFUND_DP,
                 A.Action.CUSTOMER_WRITE, A.Action.FAILED_CANCEL):
        assert A.can(_u("KASIR"), aksi) is True, \
            "Kasir harus bisa: %s" % aksi


def test_kasir_tidak_boleh_sparepart():
    """Sparepart adalah tugas Admin Sparepart."""
    import authority as A

    assert A.can(_u("KASIR"), A.Action.SPAREPART_WRITE) is False


def test_admin_sparepart_hanya_barang():
    import authority as A

    assert A.can(_u("ADMIN SPAREPART"), A.Action.SPAREPART_WRITE) is True
    for aksi in (A.Action.ORDER_CREATE, A.Action.ORDER_UPDATE,
                 A.Action.ORDER_UPDATE_FINANCE, A.Action.ORDER_UPDATE_MODAL,
                 A.Action.PAYMENT_CREATE, A.Action.CUSTOMER_WRITE,
                 A.Action.CUSTOMER_DELETE, A.Action.EXPENSE_WRITE,
                 A.Action.KAS_CLOSE, A.Action.KAS_ASET_INJEKSI,
                 A.Action.ORDER_DELETE, A.Action.USER_MANAGE):
        assert A.can(_u("ADMIN SPAREPART"), aksi) is False, \
            "Admin Sparepart tidak boleh: %s" % aksi


@pytest.mark.parametrize("role", MONITORING)
def test_monitoring_tidak_punya_aksi_tulis(role):
    import authority as A

    AKSI_BACA = {"REPORT_FULL", "REPORT_INVESTOR"}
    tulis = [a for a in A.AUTHORITY_MATRIX
             if str(a) not in AKSI_BACA and A.can(_u(role), a)]
    assert tulis == [], "%s tidak boleh punya operasi tulis: %s" % (role, tulis)


def test_pengelola_boleh_laporan_penuh_investor_boleh_laporan_investasi():
    import authority as A

    assert A.can(_u("PENGELOLA"), A.Action.REPORT_FULL) is True
    assert A.can(_u("PENGELOLA"), A.Action.REPORT_INVESTOR) is False, \
        "Pengelola tidak perlu hak laporan investasi khusus"
    assert A.can(_u("INVESTOR"), A.Action.REPORT_INVESTOR) is True
    assert A.can(_u("INVESTOR"), A.Action.REPORT_FULL) is False, \
        "Investor tidak boleh laporan operasional penuh"


def test_monitoring_tetap_read_only_walau_matrix_dibuka():
    """Blanket `can()` harus menahan walau matriks keliru."""
    import authority as A

    asli = A.AUTHORITY_MATRIX[A.Action.KAS_CLOSE]
    A.AUTHORITY_MATRIX[A.Action.KAS_CLOSE] = set(asli) | {"PENGELOLA"}
    try:
        assert A.can(_u("PENGELOLA"), A.Action.KAS_CLOSE) is False
        assert A.can(_u("INVESTOR"), A.Action.KAS_CLOSE) is False
    finally:
        A.AUTHORITY_MATRIX[A.Action.KAS_CLOSE] = asli


# ─────────────────────── (3) Privilege escalation ───────────────────────
def test_role_asing_jadi_custom_bukan_admin():
    import authority as A

    for aneh in ("", "   ", "Superdmin", "ADMINN", "apakah", None, "super admin 2"):
        assert A.canonical_role(_u(aneh)) == A.ROLE_CUSTOM


def test_role_kosong_tidak_dapat_hak():
    """Akun dengan role null/kosong tidak boleh dapat hak apa pun."""
    import authority as A

    for kosong in ("", "   ", None, "????"):
        assert A.can(_u(kosong), A.Action.KAS_CLOSE) is False
        assert A.can(_u(kosong), A.Action.USER_MANAGE) is False


def test_param_tidak_bisa_menaikkan_hak(client, db):
    """Ngoroll payload/param tidak boleh elevate."""
    import models

    hdr = _tok(db, "esc_pengelola", "PENGELOLA")

    # Coba paksa jadi admin lewat body.
    for payload in ({"role": "ADMIN", "active": 1},
                    {"username": "superadmin", "passcode": "1234"}):
        r = client.put("/api/auth/users/999999", headers=hdr, json=payload)
        assert r.status_code in (403, 404), \
            "payload role tidak boleh elevate: %s" % r.status_code

    # Endpoint kas-aset pun tidak boleh terbuka.
    r = client.post("/api/kas/aset/masuk", headers=hdr,
                    json={"nominal": 1000, "keterangan": "x", "posisi": "KAS_ASET"})
    assert r.status_code == 403, r.text


def test_token_tanpa_role_tidak_dapat_apa(client, db):
    import models

    u = models.User(username="esc_norole", display_name="No Role", role="",
                    passcode_hash="x", passcode_salt="y", active=1,
                    created_at=datetime.now())
    db.add(u)
    db.commit()
    db.expire_all()
    u = db.query(models.User).filter(models.User.username == "esc_norole").one()
    db.add(models.AuthToken(token="pytest-token-norole", user_id=u.id,
                            expires_at=datetime.now() + timedelta(days=1)))
    db.commit()
    hdr = {"Authorization": "Bearer pytest-token-norole"}

    r = client.post("/api/kas/close", headers=hdr, json={})
    assert r.status_code in (403, 422), r.status_code
    r = client.post("/api/kas/aset/masuk", headers=hdr,
                    json={"nominal": 1000, "keterangan": "x", "posisi": "KAS_ASET"})
    assert r.status_code == 403, r.text


def test_token_palsu_ditolak(client, db):
    r = client.post("/api/kas/aset/masuk",
                    headers={"Authorization": "Bearer token-ngawur"},
                    json={"nominal": 1000, "keterangan": "x", "posisi": "KAS_ASET"})
    assert r.status_code == 401, r.text


def test_tanpa_token_ditolak(client, db):
    r = client.post("/api/kas/aset/masuk",
                    json={"nominal": 1000, "keterangan": "x", "posisi": "KAS_ASET"})
    assert r.status_code == 401, r.text


# ─────────────────────── (4) Bukti lewat HTTP ───────────────────────
@pytest.mark.parametrize("role", ["PENGELOLA", "INVESTOR"])
def test_monitoring_tidak_bisa_menutup_kas(client, db, role):
    hdr = _tok(db, "http_tutup_" + role.lower(), role)
    r = client.post("/api/kas/close", headers=hdr, json={})
    assert r.status_code == 403, "%s harus 403, dapat %s" % (role, r.status_code)


@pytest.mark.parametrize("role", ["PENGELOLA", "INVESTOR", "TEKNISI",
                                  "ADMIN SPAREPART"])
def test_tidak_boleh_catat_beban(client, db, role):
    hdr = _tok(db, "http_beban_" + role.replace(" ", "_").lower(), role)
    r = client.post("/api/expenses", headers=hdr,
                    json={"kategori": "Operasional", "uraian": "x", "nilai": 1000})
    assert r.status_code == 403, "%s harus 403, dapat %s" % (role, r.status_code)


@pytest.mark.parametrize("role", ["PENGELOLA", "INVESTOR", "TEKNISI",
                                  "ADMIN SPAREPART", "KASIR"])
def test_tidak_boleh_suntik_kas_aset(client, db, role):
    hdr = _tok(db, "http_aset_" + role.replace(" ", "_").lower(), role)
    r = client.post("/api/kas/aset/masuk", headers=hdr,
                    json={"nominal": 1000, "keterangan": "x", "posisi": "KAS_ASET"})
    assert r.status_code == 403, "%s harus 403, dapat %s" % (role, r.status_code)


@pytest.mark.parametrize("role", ["PENGELOLA", "INVESTOR", "ADMIN SPAREPART"])
def test_tidak_boleh_buat_pelanggan(client, db, role):
    hdr = _tok(db, "http_cust_" + role.replace(" ", "_").lower(), role)
    r = client.post("/api/customers", headers=hdr,
                    json={"name": "X", "phone": "08"})
    assert r.status_code == 403, "%s harus 403, dapat %s" % (role, r.status_code)


@pytest.mark.parametrize("role", ["TEKNISI", "ADMIN SPAREPART", "KASIR"])
def test_tidak_boleh_kelola_akun(client, db, role):
    hdr = _tok(db, "http_akun_" + role.replace(" ", "_").lower(), role)
    r = client.post("/api/auth/users", headers=hdr,
                    json={"username": "baru", "display_name": "B",
                          "passcode": "1234", "role": "KASIR"})
    assert r.status_code == 403, "%s harus 403, dapat %s" % (role, r.status_code)


def test_admin_sparepart_tetap_bisa_kelola_sparepart(client, db):
    hdr = _tok(db, "http_spare_ok", "ADMIN SPAREPART")
    r = client.post("/api/spareparts", headers=hdr,
                    json={"kode": "SP-UJI-7R", "nama": "Part Uji",
                          "jenis": "UNIT", "stok": 5,
                          "harga_beli": 800, "harga_jual": 1000})
    assert r.status_code in (200, 201), r.text


def test_kasir_masih_bisa_terima_unit(client, db):
    hdr = _tok(db, "http_kasir_ok", "KASIR")
    r = client.post("/api/orders/receive", headers=hdr,
                    json={"customer_name": "Uji 7 Role", "phone": "0800009911",
                          "device": "PX", "keluhan": "k", "estimate": 100000,
                          "dp": 0})
    assert r.status_code in (200, 201), r.text
    oid = r.json()["id"]

    # Harga boleh, modal TIDAK.
    r = client.put("/api/orders/%d" % oid, headers=hdr,
                   json={"final_price": 150000, "part_cost": 99999,
                         "status_note": "koreksi"})
    assert r.status_code == 200, r.text
    import models
    db.expire_all()
    o = db.query(models.ServiceOrder).filter(models.ServiceOrder.id == oid).one()
    from money import to_decimal
    assert to_decimal(o.final_price) == to_decimal(150000), \
        "Kasir boleh mengubah harga"
    assert to_decimal(o.part_cost) != to_decimal(99999), \
        "Kasir TIDAK boleh mengubah modal"


def test_admin_boleh_ubah_modal(client, db):
    hdr = _tok(db, "http_admin_modal", "ADMIN")
    r = client.post("/api/orders/receive", headers=hdr,
                    json={"customer_name": "Uji Modal", "phone": "0800009922",
                          "device": "PX", "keluhan": "k", "estimate": 100000,
                          "dp": 0})
    assert r.status_code in (200, 201), r.text
    oid = r.json()["id"]
    r = client.put("/api/orders/%d" % oid, headers=hdr,
                   json={"part_cost": 40000, "status_note": "isi modal"})
    assert r.status_code == 200, r.text
    import models
    from money import to_decimal
    db.expire_all()
    o = db.query(models.ServiceOrder).filter(models.ServiceOrder.id == oid).one()
    assert to_decimal(o.part_cost) == to_decimal(40000)


def test_teknisi_tidak_bisa_ubah_pembayaran(client, db):
    hdr = _tok(db, "http_teknisi_bayar", "TEKNISI")
    r = client.post("/api/payments", headers=hdr,
                    json={"service_order_id": 1, "kind": "DP", "amount": 1000})
    assert r.status_code == 403, r.text


# ─────────────────────── (5) Histori aman ───────────────────────
def test_histori_teknisi_nonaktif_tetap_utuh(client, db):
    """OD-LOCK-08: nonaktif bukan hapus, dan penugasan barunya ditolak.
    
    User management (edit/nonaktifkan) hanya SUPERADMIN. ADMIN hanya operasi.
    """
    import models
    from money import to_decimal

    admin = _tok(db, "hist_admin", "ADMIN")
    superadmin = _tok(db, "hist_super", "SUPERADMIN")
    # `service_orders.technician` diisi dari `users.display_name`, jadi nama
    # teknisi di order harus PERSIS sama dengan display_name akunnya.
    _tok(db, "hist_teknisi", "TEKNISI")
    import models as _m
    _teknisi = db.query(_m.User).filter(
        _m.User.username == "hist_teknisi").one()
    _teknisi.display_name = "Teknisi Historis 7R"
    db.commit()
    db.expire_all()
    r = client.post("/api/orders/receive", headers=admin,
                    json={"customer_name": "Histori", "phone": "0800009933",
                          "device": "PX", "keluhan": "k", "estimate": 100000,
                          "dp": 0})
    assert r.status_code in (200, 201), r.text
    oid = r.json()["id"]
    r = client.put("/api/orders/%d" % oid, headers=admin,
                   json={"status": "REPAIR", "status_note": "diterima",
                         "technician": "Teknisi Historis 7R",
                         "repair_plan": "x", "estimate": 100000})
    assert r.status_code == 200, r.text

    tech = db.query(models.User).filter(
        models.User.username == "hist_teknisi").one()
    client.put("/api/auth/users/%d" % tech.id, headers=superadmin, json={"active": 0})
    db.expire_all()

    o = db.query(models.ServiceOrder).filter(models.ServiceOrder.id == oid).one()
    assert o.technician == "Teknisi Historis 7R", \
        "riwayat penugasan lama harus tetap utuh"

    # Penugasan baru ke teknisi nonaktif ditolak.
    r = client.post("/api/orders/receive", headers=admin,
                    json={"customer_name": "Histori 2", "phone": "0800009944",
                          "device": "PX", "keluhan": "k", "estimate": 100000,
                          "dp": 0})
    oid2 = r.json()["id"]
    r = client.put("/api/orders/%d" % oid2, headers=admin,
                   json={"status": "REPAIR", "status_note": "diterima",
                         "technician": "Teknisi Historis 7R",
                         "repair_plan": "x", "estimate": 100000})
    assert r.status_code == 400, r.text
    assert "dinonaktifkan" in (r.json().get("detail") or "").lower()
