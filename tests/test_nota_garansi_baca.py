# -*- coding: utf-8 -*-
"""Lantai keterbacaan Nota Garansi Digital (.ng-*).

Masalah yang diperbaiki: nota dikirim ke WhatsApp sebagai gambar dan
dibaca di layar HP. Font 10px / 12px / 12.5px di sheet 961px praktis
tidak terbaca -ália jadiabu-abu.

Aturan yang dikunci di sini:
  - Tidak ada teks .ng-* di bawah 13px, kecuali tagline dekoratif
    kecil di footer kanan (".ng-foot-r span").
  - Ukuran nominal sheet tetap 961px (mengikuti referensi visual).
  - Blok komponen memakai kelas .ng-*, bukan .ndr-* milik nota lain.
"""
import io
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSS = os.path.join(ROOT, "frontend", "style.css")

# Batas bawah ukuran font. 13px di sheet 961px masih terbaca di HP.
BATAS_PX = 13.0
# Pengecualian: tagline huruf besar kecil di footer kanan.
KECUALIAN = (".ng-foot-r span",)


def _css():
    return io.open(CSS, encoding="utf-8").read()


def _blok_ng(css):
    """Ambil hanya blok .ng-*, bukan .ndr-* / .nps-* milik nota lain."""
    awal = css.find(".ng-sheet {")
    if awal < 0:
        return ""
    akhir = css.find(".ndr-sheet", awal)
    if akhir < 0:
        return css[awal:]
    return css[awal:akhir]


def _aturan_font(css):
    """Kembalikan [(selector, font-size)] untuk blok .ng-*."""
    hasil = []
    for m in re.finditer(r"\.ng-[\w-]+[^{]*\{([^}]*)\}", css):
        sel = m.group(0).split("{")[0].strip()
        bad = m.group(1)
        f = re.search(r"font-size:\s*([\d.]+)px", bad)
        if f:
            hasil.append((sel, float(f.group(1))))
    return hasil


# ─────────────────────────────────────────────────────────────────
# 1. Lantai font
# ─────────────────────────────────────────────────────────────────

def test_blok_ng_terdeteksi():
    css = _css()
    assert css.find(".ng-sheet {") >= 0, "blok .ng-* tidak ditemukan di style.css"
    assert _blok_ng(css).strip(), "blok .ng-* kosong"


def test_tidak_ada_font_ng_dibawah_batas():
    """Tidak boleh ada aturan .ng-* dengan font < 13px (selain pengecualian)."""
    css = _blok_ng(_css())
    assert css, "blok .ng-* tidak ditemukan"
    melanggar = []
    for sel, px in _aturan_font(css):
        if px >= BATAS_PX:
            continue
        if any(sel.startswith(k) for k in KECUALIAN):
            continue
        melanggar.append("%s = %.1fpx" % (sel, px))
    assert not melanggar, "font terlalu kecil untuk dibaca di HP: %s" % ", ".join(melanggar)


def test_font_dasar_sheet_membaca():
    """Font dasar sheet harus mengikuti skala baca yang comfortable."""
    css = _css()
    m = re.search(r"\.ng-sheet\s*\{[^}]*font-size:\s*([\d.]+)px", css, re.S)
    assert m, "font-size dasar .ng-sheet tidak ditemukan"
    assert float(m.group(1)) >= 16, \
        "font dasar sheet %.1fpx masih kecil" % float(m.group(1))


# ─────────────────────────────────────────────────────────────────
# 2. Lebar sheet sesuai referensi
# ─────────────────────────────────────────────────────────────────

def test_lebar_sheet_mengikuti_referensi():
    """Referensi Nota-garansi.png = 961px. Jangan diubah diam-diam."""
    css = _css()
    m = re.search(r"\.ng-sheet\s*\{[^}]*width:\s*(\d+)px", css, re.S)
    assert m, "width .ng-sheet tidak ditemukan"
    assert int(m.group(1)) == 961, \
        "lebar sheet %spx, referensi 961px" % m.group(1)


# ─────────────────────────────────────────────────────────────────
# 3. Isi penting tidak boleh hilang
# ─────────────────────────────────────────────────────────────────

def test_selector_kolom_masih_dua_kolom():
    css = _css()
    m = re.search(r"\.ng-cols\s*\{[^}]*grid-template-columns:\s*([^;]+);", css, re.S)
    assert m, "grid .ng-cols tidak ditemukan"
    assert "340px" in m.group(1), "kolom kanan harus 340px"


def test_kolom_kanan_merentang_setinggi_kiri():
    """Kolom kiri jauh lebih panjang; kanan akan bolong tanpa ini."""
    css = _css()
    m = re.search(r"\.ng-cols\s*\{[^}]*align-items:\s*([^;]+);", css, re.S)
    assert m, "align-items .ng-cols tidak ditemukan"
    assert m.group(1).strip() == "stretch", \
        "align-items harus stretch supaya kolom kanan ikut tinggi"


def test_kartu_qr_meregang():
    css = _css()
    assert re.search(r"\.ng-side\s*>\s*\.ng-card:last-child\s*\{[^}]*flex:\s*1", css), \
        "kartu QR harus meregang (flex:1) supaya kolom kanan penuh"


# ─────────────────────────────────────────────────────────────────
# 4. Kelas nota lain tidak boleh tertimpa
# ─────────────────────────────────────────────────────────────────

def test_blok_ng_tidak_menimpa_ndr():
    """Blok .ng-* tidak boleh memakai selector .ndr-* atau .nps-*."""
    css = _blok_ng(_css())
    for salah in ("ndr-", "nps-"):
        assert salah not in css, \
            "selector %s bocor ke dalam blok .ng-*" % salah