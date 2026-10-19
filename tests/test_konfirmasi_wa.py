# -*- coding: utf-8 -*-
"""Konfirmasi WhatsApp saat transisi status Servis.

Alur yang dijaga test ini:

    DONE  ->_unit sudah SELESAI dikerjakan_ (reparasi rampung)
    CASH  -> _pengantar melengkapi Nota Garansi_ (bukan "unit selesai")

Dua pesan ini sengaja terpisah karena kejadiannya berbeda:

  - `statusflow.py`: "DONE": ["CASH"]. DONE = pekerjaan selesai,
    CASH = transaksi terealisasi (unit diambil + dibayar).
  - Garansi baru berlaku setelah transaksi CASH, jadi pengantar
    kelengkapan nota garansi memang belong ke CASH, bukan DONE.

Bug yang pernah ada: popup konfirmasi HANYA dipicu saat CASH
(`if (_usSt === 'CASH' && !_wasDone)`) walau komentar di kode sama-
sama menyebut DONE. DONE tidak pernah memberi konfirmasi.
"""
import io
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "frontend", "script.js")
INDEX = os.path.join(ROOT, "frontend", "index.html")


def _src(p):
    return io.open(p, encoding="utf-8").read()


def _fungsi(src, nama):
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
    return src[mulai:mulai + 4000]


# ─────────────────────────────────────────────────────────────────
# 1. Dua pesan terpisah
# ─────────────────────────────────────────────────────────────────

def test_ada_pesan_done_dan_pesan_cash_terpisah():
    """DONE dan CASH tidak boleh pakai pesan yang sama."""
    s = _src(SCRIPT)
    assert re.search(r"^function doneWaMessage\s*\(", s, re.M), \
        "fungsi doneWaMessage tidak ada"
    assert re.search(r"^function cashWaMessage\s*\(", s, re.M), \
        "fungsi cashWaMessage tidak ada - pesan CASH harus terpisah dari DONE"


def test_pesan_done_tentang_pekerjaan_selesai():
    """Pesan DONE = kabar repair selesai, bukan pengantar garansi."""
    bad = _fungsi(_src(SCRIPT), "doneWaMessage")
    assert bad, "doneWaMessage tidak ditemukan"
    assert "SELESAI" in bad or "selesai" in bad, \
        "pesan DONE harus menyatakan pekerjaan selesai"
    assert "Garansi" not in bad and "garansi" not in bad, \
        "pesan DONE tidak boleh bicara garansi - itu urusan CASH"
    # darf "silakan ambil" hanya sah kalau unit benar-benar siap diambil;
    # "siap diambil" sah di DONE karena pekerjaannya selesai,
    # tapi pesan tidak boleh menjanjikan pembayaran sudah lunas.
    assert "lunas" not in bad.lower() or "belum" in bad.lower(), \
        "pesan DONE tidak boleh menyatakan unit sudah lunas"


def test_pesan_cash_tentang_nota_garansi():
    """Pesan CASH = pengantar melengkapi Nota Garansi."""
    bad = _fungsi(_src(SCRIPT), "cashWaMessage")
    assert bad, "cashWaMessage tidak ditemukan"
    assert "aransi" in bad, \
        "pesan CASH harus menyebut garansi - itu tujuan pengantar ini"
    assert "Unit Selesai" not in bad and "sudah SELESAI" not in bad, \
        "pesan CASH tidak boleh memakai kalimat 'unit selesai' - itu punya DONE"


# ─────────────────────────────────────────────────────────────────
# 2. Pemicu transisi
# ─────────────────────────────────────────────────────────────────

def test_done_memicu_popup_konfirmasi():
    """DONE harus memicu popup - ini bug utama yang diperbaiki.

    Sengaja cek pemanggilan popup-nya, bukan sekadar `_usSt === 'DONE'`:
    di initUpdateServis sudah ada cabang lain yang mengecek DONE
    (validasi kolom wajib), jadi hanya cocok ke situmeaningless test.
    """
    bad = _fungsi(_src(SCRIPT), "initUpdateServis")
    assert bad, "initUpdateServis tidak ditemukan"
    assert re.search(r"doneWaShow\s*\(", bad), \
        "tidak ada pemanggilan doneWaShow di initUpdateServis"
    # pemanggilan popup DONE harus berada di dalam cabang DONE
    assert re.search(r"(?:_baruKe|_usSt\s*===?)\s*\(?\s*'DONE'[^)]*\)?\s*\)\s*\{\s*"
                     r"(?://[^\n]*\n\s*)*doneWaShow", bad), \
        "doneWaShow tidak dipanggil dari cabang status DONE"


def test_cash_memicu_pesan_garansi():
    """CASH memicu pengantar nota garansi, bukan konfirmasi unit selesai."""
    bad = _fungsi(_src(SCRIPT), "initUpdateServis")
    assert re.search(r"_usSt\s*===?\s*'CASH'", bad), \
        "tidak ada pemicu saat status jadi CASH"
    # di cabang CASH harus pesan garansi yang dipanggil
    cabang = bad[bad.find("_usSt === 'CASH'"):] if "_usSt === 'CASH'" in bad else bad
    assert "cashWaShow" in cabang or "cashWaMessage" in cabang, \
        "cabang CASH harus memakai pesan garansi (cashWa*), bukan doneWa*"


def test_hanya_satu_pemicu_per_transisi():
    """Popup tidak boleh muncul dua kali untuk transisi yang sama."""
    bad = _fungsi(_src(SCRIPT), "initUpdateServis")
    n_done = len(re.findall(r"_usSt\s*===?\s*'DONE'", bad))
    n_cash = len(re.findall(r"_usSt\s*===?\s*'CASH'", bad))
    assert n_done <= 2, "pemicu DONE terduplikasi (%d kali)" % n_done
    assert n_cash <= 2, "pemicu CASH terduplikasi (%d kali)" % n_cash


def test_setiap_pemicu_pakai_pengaman_transisi():
    """`_wasX` mencegah popup berulang saat status tidak berubah."""
    bad = _fungsi(_src(SCRIPT), "initUpdateServis")
    assert bad.count("_usStatusInit") >= 3, \
        "_usStatusInit harus dipakai untuk dendam transisi di kedua percabangan"


# ─────────────────────────────────────────────────────────────────
# 3. Anti dobel dengan Nota Garansi
# ─────────────────────────────────────────────────────────────────

def test_pesan_cash_tidak_menggantikan_nota_garansi():
    """Pesan CASH hanya pengantar; nota garansi tetap fitur terpisah.

    Kalau CASH ikut membuka popup nota garansi, customer menerima dua
    pesan garansi dalam sekali transisi.
    """
    bad = _fungsi(_src(SCRIPT), "initUpdateServis")
    cabang = bad[bad.find("_usSt === 'CASH'"):] if "_usSt === 'CASH'" in bad else bad
    assert "renderWarrantyNota" not in cabang and "openWarranty" not in cabang, \
        "cabang CASH tidak boleh ikut memicu popup nota garansi - hanya pengantar teks"


def test_popup_memakai_judul_yang_sesuai():
    """Judul popup berubah mengikuti jenis pesan."""
    h = _src(INDEX)
    assert 'id="doneWaTitle"' in h, "judul popup harus bisa diganti per jenis pesan"
    assert 'id="doneWaSub"' in h, "subjudul popup harus bisa diganti per jenis pesan"