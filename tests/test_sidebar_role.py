# -*- coding: utf-8 -*-
"""Sidebar harus menampilkan role AKTUAL, bukan tulisan hardcode.

Bug yang diperbaiki: baris di bawah nama akun di sidebar berisi
`Administrator` yang ditulis langsung di `index.html` dan tidak pernah diubah
oleh JavaScript. Akibatnya akun dengan role Kasir / Teknisi / Pengelola /
Investor tetap tampil dengan tulisan "Administrator".

Yang dijaga:
  - baris itu punya `id` dan diisi dari `user.role`;
  - alias dipetakan (PEMILIK = PENGELOLA, SUPERADMIN = ADMIN);
  - role tidak dikenal TIDAP dikasih label "Administrator" (fail-safe: lebih
    baik "Tanpa role" daripada menampilkan hak yang tidak dimiliki).
"""
import re

HTML = r"D:\PRAKTEK MJPRO\frontend\index.html"
JS = r"D:\PRAKTEK MJPRO\frontend\script.js"


def _html():
    return open(HTML, encoding="utf-8").read()


def _js():
    return open(JS, encoding="utf-8").read()


def test_baris_role_punya_id():
    """Tanpa id, tidak ada yang bisa mengisinya."""
    src = _html()
    assert 'id="adminName"' in src
    assert 'id="adminRole"' in src, "baris role di sidebar harus punya id"


def test_tulisan_administrator_tidak_lagi_hardcoded_tanpa_id():
    """Hardcoded tanpa id persis penyebab bug ini."""
    src = _html()
    buruk = re.findall(r'<div class="text-\[10\.5px\] text-gray-500">Administrator</div>', src)
    assert buruk == [], (
        "masih ada tulisan 'Administrator' tanpa id di sidebar: %d buah" % len(buruk))


def test_set_adminui_mengisi_role():
    src = _js()
    m = re.search(r"function setAdminUI\(user\)\s*\{(.*?)\n\}", src, re.S)
    assert m, "fungsi setAdminUI tidak ada"
    body = m.group(1)
    assert "adminRole" in body, "setAdminUI harus mengisi #adminRole"
    assert "labelRole(user.role)" in body, "isi harus dari user.role"


def test_label_role_memetakan_semua_alias():
    src = _js()
    assert "function labelRole(role)" in src
    for pasangan in ("ADMIN: 'Administrator'", "SUPERADMIN: 'Super Admin'",
                     "KASIR: 'Kasir'", "TEKNISI: 'Teknisi'",
                     "PENGELOLA: 'Pengelola'", "PEMILIK: 'Pengelola'",
                     "INVESTOR: 'Investor'", "ADMIN_SPAREPART: 'Admin Sparepart'"):
        assert pasangan in src, "peta role kurang: %s" % pasangan


def test_super_admin_label_berbeda_dari_admin():
    """Super Admin role terpisah, jadi labelnya tidak boleh sama dengan Admin."""
    import re as _re

    src = _js()
    peta = dict(_re.findall(r"(\w+):\s*'([^']*)'", src))
    assert peta["ADMIN"] == "Administrator"
    assert peta["SUPERADMIN"] == "Super Admin"
    assert peta["SUPERADMIN"] != peta["ADMIN"], (
        "kalau sama, akun developer akan tampil sebagai Manager Toko")


def test_label_role_aman_untuk_role_asing():
    """Role tak dikenal tidak boleh tampil jadi Administrator."""
    src = _js()
    assert "'Tanpa role'" in src, "role kosong harus tampil jujur, bukan Administrator"
    assert "ROLE_LABEL[key] || (role ? String(role) : 'Tanpa role')" in src, \
        "fallback labelRole harus jujur"


def test_label_role_berrynti():
    """Cek logika map-nya benar-benar jalan."""
    import sys
    import types

    src = _js()
    m = re.search(r"const ROLE_LABEL = \{(.*?)\n\};", src, re.S)
    assert m, "ROLE_LABEL tidak ada"
    peta = {}
    for k, v in re.findall(r"(\w+):\s*'([^']*)'", m.group(1)):
        peta[k] = v
    assert len(peta) >= 7, "peta role terparsing hanya %d: %s" % (len(peta), peta)
    assert peta["KASIR"] == "Kasir"
    assert peta["TEKNISI"] == "Teknisi"
    assert peta["PEMILIK"] == peta["PENGELOLA"] == "Pengelola"
    assert peta["INVESTOR"] == "Investor"

    def label(role):
        key = str(role or "").strip().upper()
        return peta.get(key) or (str(role) if role else "Tanpa role")

    assert label("ADMIN") == "Administrator"
    assert label("superadmin") == "Super Admin"
    assert label("Teknisi") == "Teknisi"
    assert label(" PEMILIK ") == "Pengelola"
    assert label("INVESTOR") == "Investor"
    assert label("") == "Tanpa role"
    assert label(None) == "Tanpa role"
    assert label("ROLE-Aneh") == "ROLE-Aneh"
    assert label("ROLE-Aneh") != "Administrator"


def test_set_role_capabilities_masih_dipakai():
    """Penetapan capability tidak boleh ikut hilang."""
    src = _js()
    assert "setRoleCapabilities(user.role)" in src