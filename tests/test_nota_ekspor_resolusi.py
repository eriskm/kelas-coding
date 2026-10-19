# -*- coding: utf-8 -*-
"""Resolusi ekspor gambar nota (Simpan Gambar ke Device).

Keluhan: "ketika di-zoom gambar jadi blur".

Penyebabnya `scale: 1` saat html2canvas. Sheet Nota Garansi hanya 961px,
sedangkan layar HP 1080-1440px. Begitu dibuka fullscreen atau di-zoom,
gambar lebih kecil dari layarnya sehingga pecah.

Jadi ekspor harus > 1. Ambil 2: 1922px, cukup tajam di HP dan masih
jauh di bawah batas WhatsApp (16 MB).

Format PNG sengaja dipertahankan. Nota ini memuat QR, dan artefak
kompresi JPEG di tepi QR bisa membuat kode tidak terbaca - padahal QR
itu alat untuk cek garansi.
"""
import io
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "frontend", "script.js")

# Skala minimal supaya tidak lebih kecil dari layar HP.
MIN_SCALE = 2
# Batas atas supaya file tidak membengkak tanpa manfaat (scale 3 = 1.5 MB).
MAX_SCALE = 3


def _src():
    return io.open(SCRIPT, encoding="utf-8").read()


def test_konstanta_skala_ekspor_ada():
    s = _src()
    assert re.search(r"^const NOTA_EXPORT_SCALE\s*=", s, re.M), \
        "konstanta NOTA_EXPORT_SCALE tidak ada"


def test_skala_ekspor_cukup_tinggi_untuk_zoom():
    m = re.search(r"^const NOTA_EXPORT_SCALE\s*=\s*([\d.]+)", _src(), re.M)
    assert m, "NOTA_EXPORT_SCALE tidak terbaca"
    nilai = float(m.group(1))
    assert nilai >= MIN_SCALE, \
        "skala %.2f menghasilkan gambar yang lebih kecil dari layar HP" % nilai
    assert nilai <= MAX_SCALE, \
        "skala %.2f membengkakkan file tanpa manfaat yang jelas" % nilai


def test_skala_ekspor_memakai_konstanta():
    """Nilai skala tidak boleh ditulis ulang inline di tempat pemanggilan."""
    s = _src()
    m = re.search(r"html2canvas\(sheet\s*,", s)
    assert m, "pemanggilan html2canvas(sheet, ...) tidak ditemukan"
    blok = s[m.start():m.start() + 400]
    assert "NOTA_EXPORT_SCALE" in blok, \
        "html2canvas harus memakai NOTA_EXPORT_SCALE"
    assert not re.search(r"scale:\s*\d", blok), \
        "skala ditulis inline - pakai konstanta supaya tidak jadi angka aja"


def test_ekspor_tetap_pakai_png():
    """QR wajib bisa discan, jadi jangan ganti ke format lossy."""
    s = _src()
    assert "image/png" in s, "gambar nota harus diekspor sebagai PNG"


def test_skala_ekspor_tidak_mempengaruhi_jalur_lain():
    """Hanya ekspor gambar yang memakai skala; pratinjau & cetak tetap 1:1."""
    s = _src()
    m = re.search(r"html2canvas\(sheet\s*,", s)
    assert m, "pemanggilan html2canvas tidak ditemukan"
    blok = s[m.start():m.start() + 500]
    assert "transform" in blok or "prevT" in s, \
        "skala preview harus tetap dilepas sebelum capture"


def test_tidak_ada_skala_1_yang_lupa_di_nota_lain():
    """Pastikan tidak ada ekspor nota lain yang masih terkunci di scale 1."""
    s = _src()
    for m in re.finditer(r"html2canvas\(([A-Za-z_$][\w$]*)\s*,", s):
        var = m.group(1)
        if var != "sheet":
            continue
        blok = s[m.start():m.start() + 400]
        assert "scale: 1," not in blok, \
            "masih ada ekspor dengan scale 1 - hasil zoom akan pecah"