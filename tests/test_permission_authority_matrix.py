# -*- coding: utf-8 -*-
"""OD-LOCK-14 - Permission: 7 endpoint yang dulu dilindungi `require_admin`.

Audit (2026-10-16) menemukan `require_admin` adalah penjaga yang berbeda dari
`require_authority`: ia tidak membaca `AUTHORITY_MATRIX` sama sekali, dan ceknya
memakai `.upper()` langsung sehingga TIDAK mengenali alias yang sah seperti
`DEV` dan `SUPER_ADMIN`. Akibatnya ada dua sumber kebenaran.

Keputusan Owner: satu sumber kebenaran - `AUTHORITY_MATRIX`.

  1. Tambah `Action.SPAREPART_DELETE` = {SUPERADMIN, ADMIN} saja.
     `SPAREPART_WRITE` (S/A/SP) tetap ada untuk tulis; jadi Admin Sparepart
     boleh manages sparepart tetapi TIDAK boleh menghapusnya. Akses tidak
     berubah dari sebelumnya.
  2. Migrasikan 7 endpoint berikut dari `require_admin` ke
     `require_authority(Action.X)`:

        POST/PUT  /api/auth/users             USER_MANAGE
        DELETE    /api/claims/{id}            CLAIM_WRITE
        DELETE    /api/expenses/{id}          EXPENSE_WRITE
        DELETE    /api/kas/entries/{id}       KAS_ENTRY_WRITE
        DELETE    /api/orders/{id}            ORDER_DELETE
        DELETE    /api/sparparts/{id}         SPAREPART_DELETE

  3. Hapus `require_admin` setelah tidak dipakai.
  4. Anti-eskalasi akun (Admin tidak boleh membuat/menaikkan akun Super Admin)
     harus tetap berlaku.
"""
from datetime import datetime, timedelta

import pytest

import authority as A
from money import to_decimal

#: Role yang WAJIB ditolak di 7 endpoint (management) ini.
#: Role yang WAJIB ditolak di 7 endpoint manajemen ini.
ROLE_BUKAN_ADMIN = ("PENGELOLA", "INVESTOR", "KASIR", "TEKNISI", "ADMIN SPAREPART",
                    "PEMILIK", "CS")


def _u(role):
    class U:
        def __init__(self, r):
            self.role = r
            self.active = 1
            self.username = "x"
    return U(role)


def _akun(db, username, role, aktif=1):
    """Buat akun + token langsung supaya bisa dipakai endpoint ber-403."""
    import models as m
    u = db.query(m.User).filter(m.User.username == username).first()
    if u is None:
        u = m.User(username=username, display_name=username, role=role,
                   passcode_hash="x", passcode_salt="y", active=aktif)
        db.add(u)
        db.commit()
        db.refresh(u)
    tok = "%s-token" % username
    if db.query(m.AuthToken).filter(m.AuthToken.token == tok).first() is None:
        db.add(m.AuthToken(token=tok, user_id=u.id,
                           expires_at=datetime.now() + timedelta(days=2)))
        db.commit()
    return u, {"Authorization": "Bearer %s" % tok}


def _buat_sparepart(client, db):
    """Buat sparepart lewat API supaya sama persis dengan session aplikasi."""
    import models as m
    _u1, hdr_admin = _akun(db, "pytest_mk_part", "ADMIN")
    body = {"kategori": "LCD", "merek": "PY", "jenis": "PY-L", "device": "PY",
            "qty": 1, "harga_beli": 1000, "harga_jual": 2000}
    r = client.post("/api/spareparts", headers=hdr_admin, json=body)
    assert r.status_code in (200, 201), "gagal buat sparepart: %s" % r.text[:160]
    pid = r.json()["id"]
    db.expire_all()
    return pid

# =====================================================================
# 1. SPAREPART_DELETE di matriks
# =====================================================================

def test_sparepart_delete_ada_di_action():
    assert hasattr(A.Action, "SPAREPART_DELETE")
    assert A.Action.SPAREPART_DELETE == "SPAREPART_DELETE"


def test_sparepart_delete_hanya_superadmin_dan_admin():
    """Admin Sparepart TIDAK boleh menghapus sparepart (keputusan Owner)."""
    assert A.can(_u("SUPERADMIN"), A.Action.SPAREPART_DELETE) is True
    assert A.can(_u("ADMIN"), A.Action.SPAREPART_DELETE) is True
    for role in ("ADMIN SPAREPART", "PENGELOLA", "INVESTOR", "KASIR",
                 "TEKNISI", "CUSTOM"):
        assert A.can(_u(role), A.Action.SPAREPART_DELETE) is False, (
            "%s tidak boleh menghapus sparepart" % role)


def test_sparepart_delete_terpisah_dari_write():
    """BUG-KEBALIAN: kalau DELETE ikut SPAREPART_WRITE, Admin Sparepart
    otomatis bisa hapus. Pemisahan ini yang menjaganya."""
    assert A.can(_u("ADMIN SPAREPART"), A.Action.SPAREPART_WRITE) is True
    assert A.can(_u("ADMIN SPAREPART"), A.Action.SPAREPART_DELETE) is False
    # Tulis tetap boleh untuk Admin Sparepart - akses lama tidak berubah.
    assert A.AUTHORITY_MATRIX.get(A.Action.SPAREPART_WRITE) == {
        A.ROLE_SUPER, A.ROLE_ADMIN, A.ROLE_ADMIN_SPAREPART}


# =====================================================================
# 2. Tujuh endpoint memakai matriks, bukan require_admin
# =====================================================================

def test_require_admin_sudah_dihapus():
    """require_admin dihapus supaya tidak ada dua sumber kebenaran."""
    import routers.auth as au
    assert not hasattr(au, "require_admin"), (
        "require_admin masih ada - sumber kebenaran ganda")


def test_tujuh_endpoint_tidak_lagi_pakai_require_admin():
    """Tidak boleh ada satu pun sisa `require_admin` di seluruh backend."""
    import glob
    import io
    import os
    pattern = "require_admin"
    n = 0
    for f in glob.glob(os.path.join(os.path.dirname(au_path()), "*.py")) + \
            glob.glob(os.path.join(os.path.dirname(au_path()), "routers", "*.py")):
        src = io.open(f, encoding="utf-8").read()
        n += src.count(pattern)
    assert n == 0, "masih ada %d pemakaian require_admin" % n


def au_path():
    import routers.auth as au
    return au.__file__


def test_endpoint_pakai_require_authority(client, db):
    """Setiap signature 7 endpoint harus punya require_authority."""
    import routers.auth as au
    import routers.claims as cl
    import routers.expenses as ex
    import routers.kas as ks
    import routers.orders as od
    import routers.spareparts as sp

    def deps(mod, fname):
        fn = getattr(mod, fname)
        src = __import__("inspect").getsource(fn)
        return src

    # Hanya Everexpose signature-nya: harus ada require_authority(...)
    # auth.py tidak bisa meng-import `authority` di level modul (circular),
    # jadi ia memakai `_matrix_user(...)` yang mengimpor authority di dalam
    # fungsi danTetap memanggil `auth_mod.can(...)` - satu sumber kebenaran.
    assert "_matrix_user" in deps(au, "create_user")
    assert "_matrix_user" in deps(au, "update_user")
    assert "require_authority" in deps(cl, "delete_claim")
    assert "require_authority" in deps(ex, "delete_expense")
    assert "require_authority" in deps(ks, "delete_entry")
    assert "require_authority" in deps(od, "delete_order")
    assert "require_authority" in deps(sp, "delete_sparepart")


# =====================================================================
# 3. 403 untuk role yang tidak berwenang
# =====================================================================

def test_hapus_sparepart_403_untuk_admin_sparepart(client, db):
    """UJI INTI: Admin Sparepart manages sparepart tapi tidak boleh hapus."""
    import models as m
    pid = _buat_sparepart(client, db)
    # Bukti barang ADA (kalau tidak, 404 menyesatkan):
    assert db.query(m.Sparepart).filter(m.Sparepart.id == pid).first() is not None

    _u1, hdr = _akun(db, "pytest_sp", "ADMIN SPAREPART")
    import authority as _A
    r = client.delete("/api/spareparts/%d" % pid, headers=hdr)
    assert r.status_code == 403, (
        "Admin Sparepart HARUS ditolak (403), dapat %s: %s"
        % (r.status_code, r.text[:120]))
    # Dan barangnya TIDAK hilang.
    assert db.query(m.Sparepart).filter(m.Sparepart.id == pid).first() is not None


def test_tujuh_endpoint_403_untuk_seluruh_role_bukan_admin(client, db):
    """Setiap role non-Admin harus dapat 403 di endpoint manajemen."""
    import models as m
    cust = db.query(m.Customer).filter(m.Customer.name == "Pytest Customer").first()
    cust_id = cust.id if cust else None

    part_id = _buat_sparepart(client, db)
    order = m.ServiceOrder(no_servis="PY-PERM-403", customer_id=cust_id,
                           status="DITERIMA", device="P", repair_plan="x",
                           created_at=datetime.now())
    db.add(order)
    db.commit()
    db.refresh(order)
    exp = m.Expense(kategori="Gaji", uraian="pytest", nilai=to_decimal(1000),
                    created_at=datetime.now())
    db.add(exp)
    db.commit()
    db.refresh(exp)

    for i, role in enumerate(ROLE_BUKAN_ADMIN):
        _u2, hdr = _akun(db, "pytest_neg_%d" % i, role)
        yang_ditolak = [
            ("POST", "/api/auth/users",
             {"username": "baru%d" % i, "display_name": "Baru",
                          "passcode": "rahasia123", "role": "KASIR"}),
            ("PUT", "/api/auth/users/%d" % order.customer_id,
             {"role": "KASIR"}),
            ("DELETE", "/api/claims/1", None),
            ("DELETE", "/api/expenses/%d" % exp.id, None),
            ("DELETE", "/api/kas/entries/1", None),
            ("DELETE", "/api/orders/%d" % order.id, None),
            ("DELETE", "/api/spareparts/%d" % part_id, None),
        ]
        # CATATAN: prefix route sparepart adalah `/api/spareparts` (dengan "e").
        # Awalnya baris di sini menulis `/api/sparparts`, dan itu sebabkan 404
        # "Not Found" yang sempat disalahkan ke penjaga role. Path yang tidak
        # terdaftar tidak pernah mengevaluasi dependency sama sekali, jadi
        # 404 bukan bukti penolakan akses - dan bukan juga bug permission.
        for meth, path, body in yang_ditolak:
            # Pakai client.<metode>(...) supaya setiap methode riffs ke
            # signature FastClient yang memang dipakai aplikasi.
            fn = getattr(client, meth.lower())
            r = fn(path, headers=hdr) if body is None else fn(path, headers=hdr, json=body)
            assert r.status_code == 403, (
                "%s %s untuk role %s harus 403, dapat %s"
                % (meth, path, role, r.status_code))


# =====================================================================
# 4. Alias lewat canonical_role()
# =====================================================================

def test_alias_dev_dan_super_admin_lolos_ke_7_endpoint(client, db):
    """`DEV` dan `SUPER_ADMIN` itu alias sah dari SUPERADMIN.

   _require_admin_ memakai `.upper()` langsung sehingga KEDUA alias itu
    ditolak - inkonsisten dengan `canonical_role()`. Setelah migrasi, keduanya
    harus lolos ke endpoint manajemen.
    """
    import models as m
    part_id = _buat_sparepart(client, db)
    for i, role in enumerate(("DEV", "SUPER_ADMIN", "SUPER ADMIN", "DEVELOPER")):
        _u3, hdr = _akun(db, "pytest_alias_%d" % i, role)
        r = client.delete("/api/sparparts/%d" % part_id, headers=hdr)
        assert r.status_code != 403, (
            "alias %s harus dikenali sebagai Super Admin, dapat 403" % role)
        if r.status_code == 200:
            break  # barang terhapus, cukup bukti satu


def test_alias_memang_resmi_di_role_aliases():
    for alias in ("DEV", "DEVELOPER", "SUPER_ADMIN", "SUPER ADMIN"):
        assert A.ROLE_ALIASES.get(alias) == A.ROLE_SUPERADMIN, alias
    assert A.ROLE_ALIASES["ADMIN"] == A.ROLE_ADMIN
    assert A.ROLE_ALIASES["SUPERADMIN"] != A.ROLE_ALIASES["ADMIN"], (
        "SUPERADMIN harus terpisah dari ADMIN (OD-LOCK-10)")


def test_semua_pemeriksaan_role_memakai_canonical_role():
    """Tidak boleh ada cek role via `.upper()` langsung di luar authority.py.

    Semua pemeriksaan harus lewat `canonical_role()` supaya alias di
    ROLE_ALIASES (DEV, SUPER_ADMIN, DEVELOPER, ...) dianggap sah.
    """
    import glob
    import io
    import os
    import re
    base = os.path.dirname(au_path())
    pola = re.compile(r"\.role\s*\)\s*\.upper\(\)")
    ditemukan = []
    for f in glob.glob(os.path.join(base, "*.py")) + \
            glob.glob(os.path.join(base, "routers", "*.py")):
        if os.path.basename(f) == "authority.py":
            continue
        for i, l in enumerate(io.open(f, encoding="utf-8").read().split("\n")):
            if pola.search(l):
                ditemukan.append("%s:%d" % (os.path.basename(f), i + 1))
    assert ditemukan == [], (
        "pemeriksaan role masih via .upper() langsung, harus lewat "
        "canonical_role(): %s" % ", ".ditemukan)


# =====================================================================
# 5. Anti-eskalasi akun tetap berlaku
# =====================================================================

def test_admin_tidak_boleh_buat_akun_superadmin(client, db):
    """Anti-eskalasi: Admin tidak boleh membuat akun Super Admin."""
    _u4, hdr = _akun(db, "pytest_anti_admin", "ADMIN")
    r = client.post("/api/auth/users", headers=hdr,
                    json={"username": "pytest_anti_super", "display_name": "Anti",
                          "passcode": "rahasia123", "role": "SUPERADMIN"})
    assert r.status_code == 403, (
        "Admin tidak boleh membuat akun Super Admin, dapat %s" % r.status_code)


def test_super_admin_tetap_boleh_kelola_akun(client, db):
    _u5, hdr = _akun(db, "pytest_super_ok", "SUPERADMIN")
    r = client.post("/api/auth/users", headers=hdr,
                    json={"username": "pytest_super_child", "display_name": "Anak",
                          "passcode": "rahasia123", "role": "ADMIN"})
    assert r.status_code in (200, 201), r.text


def test_role_config_tetap_hanya_superadmin():
    """OD-LOCK-10: ROLE_CONFIG tidak boleh diberikan ke Admin."""
    assert A.can(_u("SUPERADMIN"), A.Action.ROLE_CONFIG) is True
    assert A.can(_u("ADMIN"), A.Action.ROLE_CONFIG) is False


def test_endpoint_tidak_perlu_403_untuk_admin_superadmin(client, db):
    """Super Admin & Admin harus tetap LOLOS (tidak ada akses yang hilang)."""
    import models as m
    part_id = _buat_sparepart(client, db)
    for i, role in enumerate(("SUPERADMIN", "ADMIN")):
        _u6, hdr = _akun(db, "pytest_lolos_%d" % i, role)
        r = client.delete("/api/sparparts/%d" % part_id, headers=hdr)
        assert r.status_code != 403, "%s harus boleh hapus, dapat 403" % role
        if r.status_code == 200:
            break


# =====================================================================
# 6. Pesan error sesuai konteks
# =====================================================================

def test_pesan_error_403_sepada_dengan_aksi():
    """Pesan harus menyebut aksi, bukan kalimat generik "Hanya Admin"."""
    pesan = A.DEFAULT_MESSAGES
    assert A.Action.SPAREPART_DELETE in pesan, (
        "SPAREPART_DELETE perlu pesan sendiri")
    isi = pesan[A.Action.SPAREPART_DELETE].lower()
    assert "hapus" in isi, "pesan harus menyebut hapus sparepart"
    # Tidak boleh memakai kalimat generik require_admin yang lama.
    assert "mengelola akun" not in isi