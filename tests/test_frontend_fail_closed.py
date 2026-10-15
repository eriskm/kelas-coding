# -*- coding: utf-8 -*-
"""Fail-CLOSED di frontend (lapis tampilan).

Owner: "Jangan menganggap penyembunyian tombol sebagai proteksi keamanan."
Artinya tampilan BUKAN batas keamanan -- tapi tetap tidak boleh MENYESATKAN.
Kalau `bssfCaps()` jatuh ke daftar admin saat sesi belum siap, seluruh UI
sempat menampilkan hak Admin penuh. Itu berbahaya karena user bisa akan
melakukan aksi yang jelas ditolak backend.

Jadi diuji:
  - tidak ada fallback ke admin di capability/fail-guard;
  - peta peran frontend memuat 7 role dan tidak mencurigakan role asing jadi admin;
  - halaman punya penjaga, karena `navigateTo` bisa dipanggil dari hash URL.
"""
import re

JS = r"D:\PRAKTEK MJPRO\frontend\script.js"


def _src():
    return open(JS, encoding="utf-8").read()


def _fungsi(nama):
    src = _src()
    m = re.search(r"function %s\([^)]*\)\s*\{(.*?)\n\}" % re.escape(nama), src, re.S)
    assert m, "fungsi %s tidak ada" % nama
    return m.group(1)


def test_bssf_caps_tidak_fallback_ke_admin():
    body = _fungsi("bssfCaps")
    # Strip komentar dulu: penjelasan kenapa dulu begitu boleh tetap ada.
    kode = "\n".join(b for b in body.splitlines()
                     if not b.strip().startswith("//"))
    assert "BSSF_CAPS.admin" not in kode, \
        "bssfCaps() tidak boleh fallback ke admin (fail-OPEN)"
    assert "BSSF_CAPS.custom" in kode, "fallback harus custom (fail-closed)"


def test_set_role_capabilities_tidak_fallback_ke_admin():
    body = _fungsi("setRoleCapabilities")
    kode = "\n".join(b for b in body.splitlines()
                     if not b.strip().startswith("//"))
    assert "|| 'admin'" not in kode, \
        "role tak dikenal tidak boleh jadi admin (fail-OPEN)"
    assert "'custom'" in kode
    assert "map[key] || 'custom'" in kode


def test_can_view_aset_tidak_fallback_ke_admin():
    body = _fungsi("canViewAset")
    assert "return 'admin'" not in body, \
        "canViewAset() tidak boleh fallback ke admin"
    assert "return 'custom'" in body
    assert "superadmin" in body, "Super Admin harus boleh melihat Kas Aset"


def test_show_akun_memakai_fail_closed():
    body = _fungsi("showAkun")
    assert "_isAdmin !== true" in body, (
        "showAkun() harus menolak apa pun yang bukan true (termasuk undefined)")
    assert "_isAdmin === false" not in body


def test_peta_peran_frontend_memuat_tujuh_role():
    body = _fungsi("setRoleCapabilities")
    for role in ("superadmin", "admin", "kasir", "teknisi", "adminSparepart",
                 "pengelola", "investor"):
        assert "'%s'" % role in body, "peta peran frontend kurang: %s" % role


def test_alias_superadmin_terpisah_di_frontend():
    """Super Admin bukan Admin; kalau sama, akun developer tampil Manager Toko."""
    body = _fungsi("setRoleCapabilities")
    assert re.search(r"SUPERADMIN:\s*'superadmin'", body), \
        "SUPERADMIN harus dipetakan ke 'superadmin'"
    assert not re.search(r"SUPERADMIN:\s*'admin'", body), \
        "SUPERADMIN tidak boleh dipetakan ke 'admin'"
    assert re.search(r"ADMIN:\s*'admin'", body)


def test_konstanta_caps_memuat_superadmin_dan_sparepart():
    src = _src()
    m = re.search(r"const BSSF_CAPS = \{(.*?)\n\};", src, re.S)
    assert m, "BSSF_CAPS tidak ada"
    blok = m.group(1)
    assert re.search(r"\n\s*superadmin:\s*\[", blok), "tidak ada blok superadmin"
    assert re.search(r"\n\s*adminSparepart:\s*\[", blok), \
        "tidak ada blok adminSparepart"
    # Role Super Admin harus punya ROLE_CONFIG, Admin harus TIDAK.
    super_blok = re.search(r"\n\s*superadmin:\s*\[(.*?)\],", blok, re.S).group(1)
    admin_blok = re.search(r"\n\s*admin:\s*\[(.*?)\],", blok, re.S).group(1)
    assert "ROLE_CONFIG" in super_blok, "Super Admin wajib punya ROLE_CONFIG"
    assert "ROLE_CONFIG" not in admin_blok, \
        "Admin toko tidak boleh punya ROLE_CONFIG"
    # Admin Sparepart tidak boleh punya yang keuangan.
    sp_blok = re.search(r"\n\s*adminSparepart:\s*\[(.*?)\],", blok, re.S).group(1)
    forbidden = ("ORDER_CREATE", "PAYMENT_CREATE", "EXPENSE_WRITE", "KAS_CLOSE",
                 "CUSTOMER_WRITE", "USER_MANAGE")
    for aksi in forbidden:
        assert aksi not in sp_blok, \
            "Admin Sparepart tidak boleh punya %s" % aksi


def test_halaman_punya_penjaga():
    """`navigateTo` bisa dipanggil dari hash URL, jadi menu saja tak cukup."""
    src = _src()
    assert "const PAGE_CAP = {" in src, "PAGE_CAP tidak ada"
    m = re.search(r"const PAGE_CAP = \{(.*?)\n\};", src, re.S)
    blok = m.group(1)
    for halaman in ("akun", "keuangan", "sparepart", "garansi", "transaksi"):
        assert "'%s'" % halaman in blok, "halaman tanpa penjaga: %s" % halaman
    assert "'akun': ['USER_MANAGE']" in src, \
        "halaman akun harus dijaga USER_MANAGE"

    nav = _fungsi("navigateTo")
    assert "bolehBukaHalaman" in nav, \
        "navigateTo harus memanggil penjaga halaman"


def test_halaman_keuangan_bisa_dibuka_pengelola_dan_investor():
    """Laporan adalah tujuan mereka; penjaga tidak boleh menutupnya."""
    src = _src()
    m = re.search(r"'keuangan': \[(.*?)\]", src, re.S)
    assert m, "entri keuangan tidak ada"
    isi = m.group(1)
    assert "REPORT_FULL" in isi and "REPORT_INVESTOR" in isi, \
        "Pengelola dan Investor harus tetap bisa membuka halaman keuangan"


def test_admin_sparepart_bisa_buka_halaman_sparepart():
    src = _src()
    assert "'sparepart': ['SPAREPART_WRITE']" in src