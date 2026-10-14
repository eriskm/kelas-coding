# -*- coding: utf-8 -*-
"""Pengaman: uang DP tidak boleh muncul di Kondisi Kas Operasional.

Owner (tegas): "uang DP tidak masuk ke Kondisi Kas Operasional. DP hanya masuk
Laporan Titipan DP."

Repo ini tidak punya infrastruktur test JavaScript, jadi aturan ini dikunci
secara statis terhadap sumber `renderKondisiKas()`: fungsi itu tidak boleh
memuat baris `row(...)` yang menyebut DP/titipan, dan tidak boleh menarik
angka `titipan_dp` dari backend. `renderKuTitipan()` adalah satu-satunya
tempat yang boleh menampilkannya.
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "frontend", "script.js")


def _baca():
    with open(SCRIPT, encoding="utf-8") as f:
        return f.read()


def _fungsi(nama):
    """Isi satu fungsi JS, dari `function nama(` sampai baris penutupnya."""
    baris = _baca().splitlines()
    awal = next(i for i, b in enumerate(baris)
                if b.startswith("function %s(" % nama))
    for i in range(awal + 1, len(baris)):
        if baris[i].startswith("}"):
            return "\n".join(baris[awal:i + 1])
    raise AssertionError("fungsi %s tidak ketemu penutupnya" % nama)


def _kode(isi):
    """Buang komentar supaya assertion tidak salah karena penjelasan di kode."""
    isi = re.sub(r"/\*.*?\*/", "", isi, flags=re.S)
    return re.sub(r"//[^\n]*", "", isi)


def test_tidak_ada_baris_dp_di_kondisi_kas_operasional():
    isi = _fungsi("renderKondisiKas")
    terlarang = [n for n in re.findall(r"row\(\s*'([^']*)'", isi)
                 if re.search(r"dp|titipan", n, re.I)]
    assert not terlarang, (
        "baris DP/titipan masih ada di Kondisi Kas Operasional: %s" % terlarang)


def test_kondisi_kas_tidak_membaca_angka_titipan():
    kode = _kode(_fungsi("renderKondisiKas"))
    assert "titipan_dp" not in kode, (
        "Kondisi Kas Operasional tidak boleh memakai angka titipan_dp")


def test_laporan_titipan_dp_masih_hidup():
    """Yang dilarang adalah DP masuk Kondisi Kas, bukan dihapus dari laporan."""
    isi = _kode(_fungsi("renderKuTitipan"))
    assert "titipan_dp" in isi, "panel Laporan Titipan DP harus tetap ada"
    assert "live" in isi, "panel harus memakai data DP yang masih ditahan"


def _argumen_baris(kode, label):
    """Argumen pemanggilan row() untuk label tertentu, digabung jadi satu baris."""
    m = re.search(r"row\(\s*'%s[^']*'(.*?)\)" % re.escape(label.split(" (")[0]),
                  kode, flags=re.S)
    return re.sub(r"\s+", " ", m.group(1)) if m else None


def test_baris_kas_kecil_memakai_angka_bebas_dp():
    kode = _kode(_fungsi("renderKondisiKas"))
    assert "kas_aset_awal_operasional" in kode, (
        "baris Laci harus memakai saldo operasional yang bebas DP")

    args = _argumen_baris(kode, "Kas Aset Kecil / Laci")
    assert args, "baris 'Kas Aset Kecil / Laci' harus ada di tabel"
    assert "kas_aset_awal_operasional" in args, (
        "baris Laci harus memakai kas_aset_awal_operasional")
    assert "saldo_laci" not in args, (
        "baris Laci tidak boleh memakai saldo_laci fisik yang memuat DP")

    assert _argumen_baris(kode, "Kas Kecil / Laci") is None, (
        "label lama 'Kas Kecil / Laci' harus diganti -- itu yang membuat angka "
        "awal periode tertukar dengan posisi kas sekarang")


def test_baris_laci_jelas_saldo_awal_bukan_posisi_sekarang():
    """Angka 'Laci' di tabel harus menyebut bahwa itu saldo AWAL periode.

    Alasannya: kartu ringkasan menampilkan posisi uang SEKARANG, sedangkan baris
    tabel adalah jangkar pembuka akumulasi laba. Dua angka berbeda dengan label
    yang sama membuat layar ambigu (ditemukan Owner).
    """
    kode = _kode(_fungsi("renderKondisiKas"))
    assert "saldo awal periode" in kode, (
        "baris posisi kas di tabel harus ditandai 'saldo awal periode'")


def test_tabel_akruas_memakai_nama_akumulasi_laba():
    """Kepala kolom harus 'Akumulasi Laba', bukan 'Saldo' yang menyesatkan."""
    with open(SCRIPT, encoding="utf-8") as f:
        html = f.read()
    assert "Akumulasi Laba" in html, "kolom terakhir tabel harus bernama Akumulasi Laba"
    assert ">Saldo</th>" not in html, (
        "nama kolom 'Saldo' membuat kolom akrual terbaca seperti saldo uang")


def test_kartu_kas_memakai_angka_milik_toko():
    """Kartu Kas Aset Kecil dan Master Kas juga harus bebas DP.

    Angka fisik boleh kept sebagai fallback supaya respons lama tidak bikin
    kartu kosong, tapi versi milik-toko harus jadi cabang yang DIPILIH lebih dulu.
    """
    src = _baca()
    i = src.index("Kas Aset Kecil (Laci)")
    potongan = src[i:i + 600]
    assert "laci_milik_toko" in potongan, (
        "kartu Kas Aset Kecil harus memakai laci_milik_toko")
    assert "master_kas_milik_toko" in potongan, (
        "kartu Master Kas harus memakai master_kas_milik_toko")
    for versi, label in (("laci_milik_toko", "Laci"),
                         ("master_kas_milik_toko", "Master Kas")):
        pola = r"laci\.%s\s*!=\s*null\s*\?\s*laci\.%s" % (versi, versi)
        assert re.search(pola, potongan), (
            "kartu %s harus memakai %s sebagai nilai utama" % (label, versi))