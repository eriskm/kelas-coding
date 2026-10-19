# -*- coding: utf-8 -*-
"""Test untuk Nota Digital pada Nota Penerimaan Service.

Memastikan:
  1. Tab & container Nota Digital ada di index.html.
  2. Fungsi rendering dan pembantu Nota Digital ada di script.js.
  3. Pemetaan status & lifecycle progress tracker sinkron dan tidak out-of-bounds.
  4. Seluruh input user terlindungi escapeHtml (anti XSS).
"""
import io
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "frontend", "script.js")
INDEX = os.path.join(ROOT, "frontend", "index.html")
CSS = os.path.join(ROOT, "frontend", "style.css")


def _src(p):
    return io.open(p, encoding="utf-8").read()


def _fungsi(src, nama):
    m = re.search(r"^function %s\s*\(" % re.escape(nama), src, re.M)
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
    return src[mulai:mulai + 4000]


def test_komponen_html_nota_digital_ada():
    """Wadah, tab, dan tombol aksi Nota Digital wajib tersedia di index.html."""
    h = _src(INDEX)
    assert 'id="pageNota"' in h, "floating window #pageNota tidak ditemukan"
    assert 'id="notaTabDigital"' in h, "tombol tab #notaTabDigital tidak ditemukan"
    assert 'id="notaDigitalWrap"' in h, "kontainer wrap #notaDigitalWrap tidak ditemukan"
    assert 'id="notaDigital"' in h, "elemen #notaDigital tidak ditemukan"
    assert "notaDigitalShareWA()" in h, "tombol share WA nota digital tidak ditemukan"
    assert "notaSaveDigitalImage()" in h, "tombol simpan gambar nota digital tidak ditemukan"


def test_fungsi_nota_digital_di_script():
    """Fungsi utama Nota Digital wajib terdefinisi di script.js."""
    s = _src(SCRIPT)
    for fn in ("renderNotaDigital", "notaDigitalFit", "notaSnapshotStatus",
               "notaDigitalText", "notaDigitalShareWA", "notaSaveDigitalImage"):
        assert re.search(r"^function %s\s*\(" % fn, s, re.M) or \
               re.search(r"^async function %s\s*\(" % fn, s, re.M), \
            f"Fungsi {fn} tidak ditemukan di script.js"


def test_tahapan_lifecycle_nota_digital_valid():
    """Indeks stage pada notaSnapshotStatus harus sinkron dengan NPS_STAGES (0..6)."""
    s = _src(SCRIPT)
    fn_status = _fungsi(s, "notaSnapshotStatus")
    assert fn_status, "notaSnapshotStatus tidak ditemukan"

    m_stages = re.search(r"const NPS_STAGES\s*=\s*\[(.*?)\];", s)
    assert m_stages, "NPS_STAGES tidak ditemukan"
    raw_stages = [x.strip().strip("'\"") for x in m_stages.group(1).split(",")]
    assert len(raw_stages) == 7, f"NPS_STAGES harus memiliki 7 tahap, didapat {len(raw_stages)}"
    assert raw_stages == ['DITERIMA', 'ANALISA', 'KONFIRMASI', 'WAIT PART', 'REPAIR', 'DONE', 'CASH']

    # Cek bahwa tidak ada stage >= 7 di dalam map notaSnapshotStatus
    stages_in_map = re.findall(r"stage:\s*(-?\d+)", fn_status)
    assert stages_in_map, "tidak ada stage yang terdefinisi di notaSnapshotStatus"
    for stg in stages_in_map:
        val = int(stg)
        assert -1 <= val < len(raw_stages), \
            f"Stage {val} out of bounds! Harus dalam rentang -1 s.d. {len(raw_stages)-1}"

    # Cek pemetaan indeks stage
    assert re.search(r"KONFIRMASI:\s*\{[^}]*stage:\s*2", fn_status), "KONFIRMASI harus stage 2"
    assert re.search(r"REPAIR:\s*\{[^}]*stage:\s*4", fn_status), "REPAIR harus stage 4"
    assert re.search(r"DONE:\s*\{[^}]*stage:\s*5", fn_status), "DONE harus stage 5"
    assert re.search(r"CASH:\s*\{[^}]*stage:\s*6", fn_status), "CASH harus stage 6"


def test_anti_xss_render_nota_digital():
    """Semua field dinamis nota wajib di-escapeHtml."""
    s = _src(SCRIPT)
    fn = _fungsi(s, "renderNotaDigital")
    assert fn, "renderNotaDigital tidak ditemukan"
    for field in ("no", "nama", "phone", "device", "damage", "plan"):
        pola = rf"escapeHtml\([^)]*d\.{field}"
        assert re.search(pola, fn), f"d.{field} tidak di-escape dengan escapeHtml di renderNotaDigital"
