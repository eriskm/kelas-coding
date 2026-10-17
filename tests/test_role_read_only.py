# -*- coding: utf-8 -*-
"""Owner: "Role pengelola hanya bisa melihat keseluruhan program, tidak ada
wewenang untuk mengubah apapun."

Dua bagian:

1. PENGELOLA (dan alias PEMILIK) ditolak di SELURUH aksi tulis. Ini ditegakkan
   oleh aturan `can()` yang menolak role read-oriented sebelum membaca matriks,
   jadi isi matriks tidak bisa membuat dia lolos.

2. `routers/customers.py` sebelumnya TIDAK punya penjaga role sama sekali.
   Terbukti lewat HTTP: PENGELOLA, INVESTOR, KASIR, dan TEKNISI semuanya bisa
   POST/PUT/DELETE customer. Itu kebocoran yang nyata dan ditutup di sini.

Aturan lain yang harus tetap utuh: Admin/Kasir/Technisi tetap boleh kerjakan
unitnya masing-masing. Test ini tidak boleh membekukan aplikasi.
"""
from datetime import datetime, timedelta

import pytest


class _U:
    def __init__(self, role):
        self.role = role
        self.display_name = role
        self.username = role.lower()


def _u(role):
    return _U(role)


# ────────────── (1) PENGELOLA benar-benar read-only ──────────────
#: Aksi BACA laporan yang memang diberikan Owner ke role monitoring.
AKSI_BACA_LAPORAN = {"REPORT_FULL", "REPORT_INVESTOR"}


@pytest.mark.parametrize("role", ["PENGELOLA", "PEMILIK", "INVESTOR"])
def test_role_monitoring_hanya_boleh_aksi_baca(role):
    """Tidak ada satu pun aksi TULIS yang boleh -- hanya laporan.

    Spec Owner: "dilarang melakukan seluruh operasi tulis", tapi juga "boleh
    memfilter dan mengunduh laporan yang diizinkan".
    """
    from authority import AUTHORITY_MATRIX, can

    boleh = [a for a in AUTHORITY_MATRIX if can(_u(role), a)]
    di_luar = [a for a in boleh if str(a) not in AKSI_BACA_LAPORAN]
    assert di_luar == [], "%s boleh melakukan: %s" % (role, di_luar)
    assert boleh, "role monitoring harus tetap punya akses baca laporan"


def test_pengelola_tidak_boleh_suntik_kas_aset():
    from authority import Action, can

    assert can(_u("PENGELOLA"), Action.KAS_ASET_INJEKSI) is False


def test_pengelola_tidak_boleh_menutup_kas():
    from authority import Action, can

    assert can(_u("PENGELOLA"), Action.KAS_CLOSE) is False


def test_pengelola_tidak_boleh_kelola_akun():
    from authority import Action, can

    assert can(_u("PENGELOLA"), Action.USER_MANAGE) is False


def test_pengelola_tidak_boleh_ubah_customer():
    from authority import Action, can

    assert can(_u("PENGELOLA"), Action.CUSTOMER_WRITE) is False
    assert can(_u("PENGELOLA"), Action.CUSTOMER_DELETE) is False


def test_blanet_read_only_tidak_bisa_dibobol_lewat_matriks(monkeypatch):
    """Skenario berbahaya: PENGELOLA MASUK ke matriks suatu saat.

    Kalau aturan read-only di `can()` hilang, cukup satu baris matriks yang
    keliru sudah memberi PENGELOLA hak tulis untuk SELURUH program. Test ini
    mensimulasikan itu dan membuktikan blanket-nya benar-benar menahan.

    Catatan: dengan matriks sekarang PENGELOLA tidak terdaftar di aksi mana pun,
    Hanya fakta bahwa "tidak ada PENGELOLA di matriks" saja TIDAK cukup --
    kebetulan aman karena matriksnya, bukan karena penjaganya.
    """
    import authority

    aksi = authority.Action.ORDER_DELETE
    asli = authority.AUTHORITY_MATRIX[aksi]
    monkeypatch.setitem(authority.AUTHORITY_MATRIX, aksi, set(asli) | {"PENGELOLA"})

    assert authority.canonical_role(_u("PENGELOLA")) == "PENGELOLA"
    assert authority.can(_u("PENGELOLA"), aksi) is False, (
        "matriks sempat memuat PENGELOLA, tapi blanket read-only harus tetap "
        "menahannya")
    assert authority.can(_u("INVESTOR"), aksi) is False


def test_rule_read_only_benar_benar_ada_di_kode():
    """Blanket-nya harus benar-benar ada di `can()`, bukan_andal pada matriks."""
    import inspect

    import authority

    src = inspect.getsource(authority.can)
    assert "is_monitoring" in src, \
        "can() harus menolak role read-oriented sebelum membaca matriks"
    assert "MONITORING_ROLES" in inspect.getsource(authority.is_monitoring)


#: Aksi BACA. Spec Owner mengizinkan Pengelola dan Investor "memfilter dan
#: mengunduh laporan yang diizinkan" -- itu operasi baca, bukan tulis.
AKSI_BACA = frozenset({"REPORT_FULL", "REPORT_INVESTOR"})


def test_matriks_memang_tidak_memuat_pengelola_untuk_tulis():
    """PENGELOLA boleh punya aksi BACA saja, tidak boleh aksi tulis apa pun."""
    from authority import AUTHORITY_MATRIX

    salah = [a for a, roles in AUTHORITY_MATRIX.items()
             if ("PENGELOLA" in roles or "PEMILIK" in roles)
             and str(a) not in AKSI_BACA]
    assert salah == [], "PENGELOLA tidak boleh punya authority tulis: %s" % salah


def test_matriks_tidak_memuat_investor_untuk_tulis():
    from authority import AUTHORITY_MATRIX

    salah = [a for a, roles in AUTHORITY_MATRIX.items()
             if "INVESTOR" in roles and str(a) not in AKSI_BACA]
    assert salah == [], "INVESTOR tidak boleh punya authority tulis: %s" % salah


# ────────────── (2) Alur normal tidak boleh beku ──────────────
def test_admin_masih_boleh_semua():
    from authority import Action, can

    for aksi in (Action.CUSTOMER_WRITE, Action.CUSTOMER_DELETE,
                 Action.KAS_ASET_INJEKSI, Action.KAS_CLOSE, Action.USER_MANAGE):
        assert can(_u("ADMIN"), aksi) is True


def test_kasir_tetap_boleh_kerja_unit_dan_tambah_customer():
    from authority import Action, can

    assert can(_u("KASIR"), Action.ORDER_CREATE) is True
    assert can(_u("KASIR"), Action.ORDER_UPDATE) is True
    assert can(_u("KASIR"), Action.PAYMENT_CREATE) is True
    assert can(_u("KASIR"), Action.CUSTOMER_WRITE) is True


def test_kasir_tidak_boleh_hapus_customer():
    from authority import Action, can

    assert can(_u("KASIR"), Action.CUSTOMER_DELETE) is False


def test_teknisi_tetap_boleh_kerja_unit():
    """Alur servis Teknisi tidak boleh beku.

    Perubahan OD-LOCK-10: `ORDER_CREATE` (penerimaan unit) dicabut dari
    Teknisi karena itu tugas Kasir/CS. Yang WAJIB tetap ada adalah
    `ORDER_UPDATE` dan `ORDER_HANDOVER` -- itulah cara Teknisi memperbarui
    progres dan menyerahkan unit.
    """
    from authority import Action, can

    assert can(_u("TEKNISI"), Action.ORDER_UPDATE) is True, \
        "Teknisi harus bisa memperbarui progres unit"
    assert can(_u("TEKNISI"), Action.ORDER_HANDOVER) is True, \
        "Teknisi harus bisa serah-terima unit"
    assert can(_u("TEKNISI"), Action.CUSTOMER_WRITE) is False
    assert can(_u("TEKNISI"), Action.ORDER_CREATE) is False, \
        "penerimaan unit adalah tugas Kasir/CS (OD-LOCK-10)"


# ────────────── (3) Bukti lewat HTTP ──────────────
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
    tok = "pytest-token-ro-" + username
    if db.query(models.AuthToken).filter(models.AuthToken.token == tok).first() is None:
        db.add(models.AuthToken(token=tok, user_id=u.id,
                                expires_at=datetime.now() + timedelta(days=2)))
        db.commit()
    return {"Authorization": "Bearer " + tok}


def _buat(client, hdr, telepon="0800000"):
    r = client.post("/api/customers", headers=hdr,
                    json={"name": "Pelanggan Uji", "phone": telepon})
    return (r.json().get("id") if r.status_code in (200, 201) else None), r.status_code


@pytest.mark.parametrize("role", ["PENGELOLA", "INVESTOR", "TEKNISI"])
def test_role_read_only_tidak_bisa_tambah_customer(client, db, role):
    hdr = _tok(db, "ro_tambah_" + role.lower(), role)
    cid, kode = _buat(client, hdr)
    assert kode == 403, "%s harus 403, dapat %s" % (role, kode)
    assert cid is None


def test_kasir_bisa_tambah_customer(client, db):
    hdr = _tok(db, "ro_kasir", "KASIR")
    cid, kode = _buat(client, hdr, "0800001")
    assert kode in (200, 201), kode
    assert cid is not None


@pytest.mark.parametrize("role", ["PENGELOLA", "INVESTOR", "TEKNISI"])
def test_role_read_only_tidak_bisa_ubah_customer(client, db, role):
    import models

    admin = _tok(db, "ro_admin_buat", "ADMIN")
    cid, kode = _buat(client, admin, "0800002")
    assert kode in (200, 201), kode

    hdr = _tok(db, "ro_ubah_" + role.lower(), role)
    r = client.put("/api/customers/%d" % cid, headers=hdr, json={"name": "Diubah"})
    assert r.status_code == 403, "%s harus 403, dapat %s" % (role, r.status_code)


def test_kasir_tetap_bisa_ubah_customer(client, db):
    """KASIR boleh ubah customer -- itu tetap bagian pekerjaan kasir."""
    admin = _tok(db, "ro_admin_ubah", "ADMIN")
    cid, kode = _buat(client, admin, "0800006")
    assert kode in (200, 201), kode
    hdr = _tok(db, "ro_kasir_ubah", "KASIR")
    r = client.put("/api/customers/%d" % cid, headers=hdr, json={"name": "Diubah Kasir"})
    assert r.status_code == 200, r.text


@pytest.mark.parametrize("role", ["PENGELOLA", "INVESTOR", "KASIR", "TEKNISI"])
def test_role_tidak_bisa_hapus_customer(client, db, role):
    admin = _tok(db, "ro_admin_hapus", "ADMIN")
    cid, kode = _buat(client, admin, "0800003")
    assert kode in (200, 201), kode

    hdr = _tok(db, "ro_hapus_" + role.lower(), role)
    r = client.delete("/api/customers/%d" % cid, headers=hdr)
    assert r.status_code == 403, "%s harus 403, dapat %s" % (role, r.status_code)


def test_admin_tetap_bisa_hapus_customer(client, db):
    admin = _tok(db, "ro_admin_bisa", "ADMIN")
    cid, kode = _buat(client, admin, "0800004")
    assert kode in (200, 201), kode
    r = client.delete("/api/customers/%d" % cid, headers=admin)
    assert r.status_code == 200, r.text


def test_membaca_customer_tetap_boleh_untuk_semua(client, db):
    """Read-only harus benar-benar read-only: melihat tetap boleh."""
    _tok(db, "ro_admin_lihat", "ADMIN")
    _buat(client, _tok(db, "ro_admin_lihat", "ADMIN"), "0800005")
    for role in ("PENGELOLA", "INVESTOR", "KASIR", "TEKNISI"):
        hdr = _tok(db, "ro_lihat_" + role.lower(), role)
        r = client.get("/api/customers", headers=hdr)
        assert r.status_code == 200, "%s harus bisa melihat daftar customer" % role


def test_router_customer_punya_penjaga_role():
    """Penjaga harus ada di kode, bukan cuma andalkan test."""
    import inspect

    from routers import customers

    src = inspect.getsource(customers)
    assert "CUSTOMER_WRITE" in src, "create/update customer tanpa penjaga"
    assert "CUSTOMER_DELETE" in src, "delete customer tanpa penjaga"
    for nama in ("create_customer", "update_customer", "delete_customer"):
        assert "require_authority" in inspect.getsource(
            getattr(customers, nama)), "%s tanpa require_authority" % nama


def test_tidak_ada_endpoint_tulis_tanpa_penjaga_role():
    """Audit ulang: setiap endpoint TULIS yang terdaftar di router harus punya penjaga.

    Dulu ada 13 endpoint tulis tanpa `require_authority` di signature-nya.
    Sebagian dijaga di dalam bodies, tapi `customers.py` bocor total. Test ini
    hanya menghitung fungsi yang benar-benar didaftarkan lewat dekorator
    `@router.<method>` supaya helper internal tidak ikut terhitung.
    """
    import inspect

    import routers.auth as a
    import routers.claims as cl
    import routers.customers as cu
    import routers.expenses as ex
    import routers.kas as k
    import routers.orders as o
    import routers.spareparts as sp

    eksepsi = {"login", "logout", "change_passcode"}
    bocor = []
    for mod in (a, cl, cu, ex, k, o, sp):
        for nama, fn in vars(mod).items():
            if not inspect.isfunction(fn) or nama in eksepsi:
                continue
            if fn.__module__ != mod.__name__:
                continue
            router = getattr(mod, "router", None)
            if router is None:
                continue
            terdaftar = any(getattr(r, "endpoint", None) is fn
                            for r in router.routes)
            if not terdaftar:
                continue
            metode = [getattr(r, "methods", set()) for r in router.routes
                      if getattr(r, "endpoint", None) is fn]
            metode = set().union(*metode) if metode else set()
            if not (metode & {"POST", "PUT", "PATCH", "DELETE"}):
                continue
            kode = inspect.getsource(fn)
            if not re_search_guard(kode):
                bocor.append("%s.%s" % (mod.__name__, nama))
    assert bocor == [], "endpoint tulis tanpa penjaga role: %s" % bocor


def re_search_guard(kode: str) -> bool:
    import re
    # `_matrix_user` adalah penjaga role milik routers/auth.py. Ia dipakai di
    # situ karena modul auth tidak boleh meng-import `authority` di level modul
    # (circular import: authority meng-import routers.auth). Penegakannya
    # tetap membaca AUTHORITY_MATRIX lewat `auth_mod.can(...)` - satu sumber
    # kebenaran, sama seperti `require_authority`.
    return bool(re.search(r"require_admin|require_authority|require_finance"
                          r"|_matrix_user|_boleh_|is_monitoring|canonical_role",
                          kode))
