# -*- coding: utf-8 -*-
"""Regresi: Simpan Gambar pada Nota Garansi / Klaim.

Bug yang diperbaiki: klik "Simpan Gambar ke Device" pada Nota Garansi
muncul "Belum ada data nota".

Dua sebabnya:

  1. `notaSaveDigitalImage()` membaca `notaData()` yang mengembalikan
     `_lastNota` - data nota PENERIMAAN. Waktu Nota Garansi dibuka dari
     unit yang sudah ada (Update Data Servis), `_lastNota` masih null,
     padahal `_lastWarranty` terisi.
  2. Selector sheet selalu `.nps-sheet`. Tiap jenis nota punya elemen
     sendiri:
         SERVICE  -> .nps-sheet
         CLAIM    -> .ndr-sheet
         WARRANTY -> .ng-sheet
     Selector salah membuat html2canvas dilewati, lalu jatuh ke
     `notaSaveDigitalImageManual()` yang menggambar ulang dengan kanvas
     - hasilnya bukan tampilan nota yang asli.
"""
import io
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "frontend", "script.js")


def _src():
    return io.open(SCRIPT, encoding="utf-8").read()


def _js_fungsi(src, nama):
    m = re.search(r"^(?:async\s+)?function %s\s*\(" % re.escape(nama), src, re.M)
    if not m:
        return ""
    mulai = src.index("{", m.end())
    tingkat = 0
    for i in range(mulai, len(src)):
        if src[i] == "{":
            tingkat += 1
        elif src[i] == "}":
            tingkat -= 1
            if tingkat == 0:
                return src[mulai:i + 1]
    return src[mulai:mulai + 6000]


# ─────────────────────────────────────────────────────────────────
# 1. Sumber data harus ikut mode
# ─────────────────────────────────────────────────────────────────

def test_ada_pemilih_data_per_mode():
    """Harus ada helper yang membaca _lastWarranty / _lastClaim."""
    s = _src()
    assert re.search(r"^function notaModeData\s*\(", s, re.M), \
        "notaModeData tidak ada - simpan gambar akan salah baca data"


def test_helper_data_memakai_ketiga_mode():
    bad = _js_fungsi(_src(), "notaModeData")
    assert bad, "notaModeData tidak terbaca"
    assert "_lastWarranty" in bad, "harus membaca _lastWarranty (Nota Garansi)"
    assert "_lastClaim" in bad, "harus membaca _lastClaim (Nota Klaim)"
    assert "notaData()" in bad, "harus tetap fallback ke notaData() untuk SERVICE"


def test_simpan_gambar_memakai_pemilih_per_mode():
    bad = _js_fungsi(_src(), "notaSaveDigitalImage")
    assert bad, "notaSaveDigitalImage tidak terbaca"
    assert "notaModeData()" in bad, \
        "notaSaveDigitalImage harus pakai notaModeData(), bukan notaData() langsung"
    assert "querySelector('.nps-sheet')" not in bad, \
        "selector sheet harus lewat helper per-mode"


# ─────────────────────────────────────────────────────────────────
# 2. Selector sheet per mode
# ─────────────────────────────────────────────────────────────────

def test_ada_pemilih_sheet_per_mode():
    s = _src()
    assert re.search(r"^function notaModeSheet\s*\(", s, re.M), \
        "notaModeSheet tidak ada"


def test_selector_sheet_mencakup_tiga_jenis_nota():
    """Tiap mode harus punya selector sendiri sesuai elemen yang di-render."""
    bad = _js_fungsi(_src(), "notaModeSheet")
    assert bad, "notaModeSheet tidak terbaca"
    assert "'WARRANTY'" in bad and "ng-sheet" in bad, \
        "mode WARRANTY harus memilih .ng-sheet"
    assert "'CLAIM'" in bad and "ndr-sheet" in bad, \
        "mode CLAIM harus memilih .ndr-sheet"
    assert "nps-sheet" in bad, \
        "mode SERVICE harus tetap memilih .nps-sheet"


def test_selector_sheet_cocok_dengan_yang_dirender():
    """Selector harus cocok dengan kelas yang benar-benar dipakai render."""
    s = _src()
    for sel in ("nps-sheet", "ng-sheet"):
        assert 'class="%s"' % sel in s, \
            "tidak ada elemen yang memakai class %s" % sel
    bad = _js_fungsi(s, "notaModeSheet")
    assert "getElementById('notaDigital')" in bad, \
        "harus mencari di dalam #notaDigital"


# ─────────────────────────────────────────────────────────────────
# 3. Fungsi lain sudah aman (regresi)
# ─────────────────────────────────────────────────────────────────

def test_fungsi_lain_tetap_aman():
    """notaSaveImage / notaPrint / notaDigitalShareWA sudah handle mode.

    Kalau salah satu kembali ke notaData() langsung, bug yang sama akan
    muncul di fungsi tersebut.
    """
    s = _src()
    for fn in ("notaSaveImage", "notaPrint", "notaDigitalShareWA"):
        bad = _js_fungsi(s, fn)
        assert bad, "%s tidak terbaca" % fn
        assert "_notaMode" in bad or "notaModeData()" in bad, \
            "%s harus membaca mode aktif" % fn