# -*- coding: utf-8 -*-
"""Role Investor sebagai role BERPISAH (bukan alias dari Pengelola).

Owner meminta ada role Investor, Pengelola, dan Kasir. Kasir dan Pengelola sudah
ada di `authority.py`; yang bermasalah adalah `INVESTOR` hanya alias yang
dipetakan ke PENGELOLA -- artinya akun "Investor" otomatis mendapat hak yang
sama dengan pengelola toko, termasuk melihat Kas Aset + Master Kas.

Yang dikunci test:
- INVESTOR adalah role sendiri, bukan PENGELOLA;
- read-only: tidak punya authority tulis sama sekali;
- tetap monitoring (boleh melihat laporan), tapi TIDAK masuk role yang boleh
  melihat Kas Aset/Master Kas (SSOT-7 / v4 #11 masih Admin & Pengelola);
- role yang tidak dikenal tetap CUSTOM, tidak jatuh ke admin.
"""
import authority as auth_mod


#: Aksi yang sifatnya BACA. Role monitoring boleh punya ini tanpa melanggar aturan
#: "tidak boleh mengubah apapun" -- yang dilarang adalah operasi tulis.
_AKSI_BACA = frozenset({
    "REPORT_INVESTOR",
    "REPORT_FULL",
})


def _u(role):
    class _U:
        pass
    return _U()


def test_investor_adalah_role_sendiri():
    assert auth_mod.ROLE_INVESTOR == "INVESTOR"
    assert auth_mod.ROLE_ALIASES["INVESTOR"] == auth_mod.ROLE_INVESTOR
    assert auth_mod.ROLE_ALIASES["INVESTOR"] != auth_mod.ROLE_PENGELOLA


def test_investor_tidak_punya_authority_tulis():
    """Investor boleh AKSES BACA laporan, tapi nol authority tulis.

    Spec Owner: Investor "hanya untuk monitoring", boleh "memfilter dan
    mengunduh laporan yang diizinkan", tapi "dilarang melakukan seluruh
    operasi tulis".
    """
    punya_tulis = [str(a) for a, roles in auth_mod.AUTHORITY_MATRIX.items()
                   if auth_mod.ROLE_INVESTOR in roles
                   and str(a) not in _AKSI_BACA]
    assert punya_tulis == [], \
        "Investor tidak boleh punya authority tulis, tapi punya: %s" % punya_tulis


def test_investor_monitoring_tetapi_bukan_pengelola():
    assert auth_mod.canonical_role(_u_with("INVESTOR")) == auth_mod.ROLE_INVESTOR
    assert auth_mod.is_monitoring(_u_with("INVESTOR")) is True
    # Beda dari Pengelola hanya di hak EKONOMI, bukan di status monitoring.
    assert auth_mod.is_monitoring(_u_with("PENGELOLA")) is True


def test_superadmin_terpisah_dari_admin():
    """Owner: Super Admin (Developer) bukan Manager Toko.

    Sebelumnya `SUPERADMIN` cuma alias `ADMIN`, jadi keduanya tidak beda sama
    sekali dan "jangan berikan role ini otomatis kepada Admin toko" mustahil
    ditegakkan.
    """
    assert auth_mod.ROLE_SUPERADMIN != auth_mod.ROLE_ADMIN
    assert auth_mod.ROLE_ALIASES["SUPERADMIN"] == auth_mod.ROLE_SUPERADMIN
    assert auth_mod.canonical_role(_u_with("SUPERADMIN")) == auth_mod.ROLE_SUPERADMIN
    assert auth_mod.canonical_role(_u_with("ADMIN")) == auth_mod.ROLE_ADMIN


def test_alias_lama_tetap_berfungsi():
    assert auth_mod.canonical_role(_u_with("TEKNIKER")) == auth_mod.ROLE_TEKNISI
    assert auth_mod.canonical_role(_u_with("PEMILIK")) == auth_mod.ROLE_PENGELOLA
    assert auth_mod.canonical_role(_u_with("Teknisi")) == auth_mod.ROLE_TEKNISI


def test_admin_sparepart_adalah_role_sendiri():
    assert auth_mod.ROLE_ADMIN_SPAREPART == "ADMIN_SPAREPART"
    assert auth_mod.ROLE_ALIASES["ADMIN SPAREPART"] == auth_mod.ROLE_ADMIN_SPAREPART
    assert auth_mod.canonical_role(_u_with("ADMIN SPAREPART")) == auth_mod.ROLE_ADMIN_SPAREPART


def test_role_tidak_dikenal_jadi_custom_bukan_admin():
    """Typo di kolom Role tidak boleh memberi hak admin."""
    for salah in ("", "   ", "Invesotr", "adminn", "apakah", None):
        assert auth_mod.canonical_role(_u_with(salah)) == auth_mod.ROLE_CUSTOM


def test_endpoint_roles_mencerminkan_matrix():
    from routers.auth import list_roles
    out = list_roles(user=_u_with("ADMIN"))
    assert set(out["roles"]) == {"Super Admin", "Admin", "Kasir", "Teknisi",
                                 "Pengelola", "Investor", "Admin Sparepart"}
    inv = out["ringkasan"]["Investor"]
    assert inv["canonical"] == auth_mod.ROLE_INVESTOR
    assert inv["monitoring"] is True
    assert set(inv["otoritas"]) & _AKSI_BACA == set(inv["otoritas"]), (
        "Investor hanya boleh punya aksi baca, tapi punya: %s" % inv["otoritas"])
    peng = out["ringkasan"]["Pengelola"]
    assert peng["monitoring"] is True
    kas = out["ringkasan"]["Kasir"]
    assert kas["otoritas"], "Kasir harus punya authority"
    adm = out["ringkasan"]["Admin"]
    assert "KAS_CLOSE" in adm["otoritas"]


def _u_with(role):
    class _U:
        pass
    u = _U()
    u.role = role
    return u
