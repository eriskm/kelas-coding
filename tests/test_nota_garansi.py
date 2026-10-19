# -*- coding: utf-8 -*-
"""Nota Garansi Digital - melengkapi yang sudah ada, tanpa merusak yang jalan.

Sudah ada `renderWarrantyNotaDigital()` (script.js) yang sudah滿足 sebagian
besar spesifikasi. Test ini mengunci SELURUH fungsi lama (regresi) PLUS
empat tambahan yang diminta Owner:

  1. Kontak toko di header (kontak WA sudah ada di `shopWaDisplay()`)
  2. Status pembayaran (LUNAS / DP / Sisa) dari `/payments/by-order/{id}`
  3. Panel status garansi AKTIF / BERAKHIR dari tanggal, bukan dikarang
  4. Komponen diganti - hanya tampil bila datanya ada

Aturan yang dijaga:
  - Biaya WAJIB dari `final_price` (nilai final), bukan `estimate`
  - Status garansi dihitung dari tanggal BERAKHIRNYA, bukan dari string
    hardcode
  - Blok komponen yang datanya kosong TIDAK boleh tampil isi palsu
  - Nota Penerimaan tidak boleh ikut berubah
  - Tidak boleh ada fetch/endpoint baru di sisi nota garansi
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
# 1. REGRESI - fitur lama tidak boleh rusak
# ─────────────────────────────────────────────────────────────────

def test_nota_garansi_lama_utuh():
    """Fungsi nota garansi yang sudah jalan harus tetap ada."""
    s = _src(SCRIPT)
    for fn in ("renderWarrantyNotaPreview", "renderWarrantyNotaDigital",
               "warrantyNotaText", "warrantyNotaDigitalText", "usWarrantyPrint"):
        assert re.search(r"^(?:async\s+)?function %s\s*\(" % fn, s, re.M), \
            "fungsi %s hilang" % fn


def test_nota_penerimaan_tidak_berubah():
    """Nota Penerimaan harus tetap utuh (regresi)."""
    s = _src(SCRIPT)
    for fn in ("renderNotaPreview", "renderNotaDigital", "notaText",
               "notaDigitalText", "notaSaveImage", "notaSaveDigitalImage"):
        assert re.search(r"^(?:async\s+)?function %s\s*\(" % fn, s, re.M), \
            "fungsi nota penerimaan %s hilang" % fn


def test_gerbang_cash_dan_lunas_tetap_ada():
    """Nota garansi hanya boleh terbit saat CASH dan LUNAS."""
    bad = _js_fungsi(_src(SCRIPT), "usWarrantyPrint")
    assert bad, "usWarrantyPrint tidak terbaca"
    assert "CASH" in bad, "gerbang status CASH hilang"
    assert "LUNAS" in bad, "gerbang pembayaran LUNAS hilang"
    assert "/payments/by-order/" in bad, \
        "verifikasi LUNAS harus lewat endpoint pembayaran, bukan asumsi"


# ─────────────────────────────────────────────────────────────────
# 2. Kontak toko
# ─────────────────────────────────────────────────────────────────

def test_kontak_toko_muncul_di_header_garansi():
    bad = _js_fungsi(_src(SCRIPT), "renderWarrantyNotaDigital")
    assert bad, "renderWarrantyNotaDigital tidak terbaca"
    assert "shopWaDisplay()" in bad, \
        "header nota garansi belum menampilkan kontak toko"


# ─────────────────────────────────────────────────────────────────
# 3. Status pembayaran
# ─────────────────────────────────────────────────────────────────

def test_status_pembayaran_dari_data_nyata():
    """LUNAS/DP/Sisa harus berasal dari data pembayaran yang ditarik."""
    s = _src(SCRIPT)
    prep = _js_fungsi(s, "usWarrantyPrint")
    assert prep, "usWarrantyPrint tidak terbaca"
    assert re.search(r"_pay\s*=|payment_status", prep), \
        "usWarrantyPrint harus menyimpan data pembayaran ke objek nota"
    bad = _js_fungsi(s, "renderWarrantyNotaDigital")
    assert re.search(r"payment_status|bayar_status", bad), \
        "nota garansi harus menampilkan status pembayaran"


def test_biaya_wajib_final_bukan_estimate():
    """Aturan Owner: biaya nota garansi = nilai final, bukan estimasi."""
    bad = _js_fungsi(_src(SCRIPT), "renderWarrantyNotaDigital")
    assert bad, "renderWarrantyNotaDigital tidak terbaca"
    assert re.search(r"d\.final\b", bad), \
        "biaya harus dari d.final (nilai final transaksi)"
    assert not re.search(r"notaRupiah\(d\.estimate\)", bad), \
        "nota garansi tidak boleh pakai estimate sebagai biaya"


def test_teks_pembayaran_di_escape():
    """Nilai dari server wajib escapeHtml (anti XSS)."""
    bad = _js_fungsi(_src(SCRIPT), "renderWarrantyNotaDigital")
    assert re.search(r"escapeHtml\(statusBayar\)", bad), \
        "status pembayaran harus di-escape saat ditampilkan"
    # Biaya final wajib lewat notaRupiah + escapeHtml
    assert re.search(r"escapeHtml\(notaRupiah\(d\.final\)\)", bad), \
        "biaya final harus di-escape lewat notaRupiah(d.final)"


# ─────────────────────────────────────────────────────────────────
# 4. Status garansi AKTIF / BERAKHIR
# ─────────────────────────────────────────────────────────────────

def test_ada_fungsi_status_garansi():
    """Status harus dihitung dari tanggal berakhir, bukan string tetap."""
    s = _src(SCRIPT)
    assert re.search(r"^function notaWarrantyStatus\s*\(", s, re.M), \
        "fungsi notaWarrantyStatus tidak ada"


def test_status_garansi_menghitung_dari_tanggal():
    bad = _js_fungsi(_src(SCRIPT), "notaWarrantyStatus")
    assert bad, "notaWarrantyStatus tidak terbaca"
    assert "warranty_end" in bad, \
        "status garansi harus membandingkan warranty_end dengan tanggal hari ini"
    assert re.search(r"new Date\(\)", bad), \
        "status garansi harus memakai tanggal hari ini, bukan nilai konstanta"


def test_status_garansi_menampilkan_aktif_dan_berakhir():
    bad = _js_fungsi(_src(SCRIPT), "notaWarrantyStatus")
    assert re.search(r"AKTIF", bad), "label AKTIF tidak ada"
    assert re.search(r"BERAKHIR", bad), "label BERAKHIR tidak ada"


def test_tanpa_garansi_tidak_boleh_berstatus_aktif():
    """warranty_months == 0 berarti tanpa garansi, bukan AKTIF."""
    bad = _js_fungsi(_src(SCRIPT), "notaWarrantyStatus")
    assert bad, "notaWarrantyStatus tidak terbaca"
    assert re.search(r"TANPA GARANSI|TANPA", bad), \
        "unit tanpa garansi harus punya label sendiri, bukan AKTIF"


def test_nota_garansi_memakai_fungsi_status():
    bad = _js_fungsi(_src(SCRIPT), "renderWarrantyNotaDigital")
    assert "notaWarrantyStatus(" in bad, \
        "renderWarrantyNotaDigital harus memakai notaWarrantyStatus()"


# ─────────────────────────────────────────────────────────────────
# 5. Komponen diganti - hanya kalau data ada
# ─────────────────────────────────────────────────────────────────

def test_blok_komponen_hanya_saat_data_ada():
    """Data kosong = blok tidak tampil. Tidak boleh isi placeholder palsu."""
    s = _src(SCRIPT)
    assert re.search(r"^function notaWarrantyParts\s*\(", s, re.M), \
        "fungsi notaWarrantyParts tidak ada"
    bad = _js_fungsi(s, "notaWarrantyParts")
    assert bad, "notaWarrantyParts tidak terbaca"
    assert "length" in bad, "harus mengecek panjang daftar sebelum merender"


def test_blok_komponen_memakai_nama_sparepart():
    bad = _js_fungsi(_src(SCRIPT), "notaWarrantyParts")
    assert bad, "notaWarrantyParts tidak terbaca"
    assert re.search(r"parts|\bpart\b", bad), \
        "blok komponen harus membaca daftar parts"


# ─────────────────────────────────────────────────────────────────
# 6. Pesan WhatsApp
# ─────────────────────────────────────────────────────────────────

def test_pesan_wa_garansi_menyebut_nota_terlampir():
    """Pesan harus menjelaskan unit diserahkan + nota dilampirkan."""
    bad = _js_fungsi(_src(SCRIPT), "cashWaMessage")
    assert bad, "cashWaMessage tidak terbaca"
    assert re.search(r"[Nn]ota\s*[Gg]aransi", bad), \
        "pesan WA harus menyebut Nota Garansi yang dilampirkan"
    assert re.search(r"diserahkan|selesai", bad), \
        "pesan WA harus menyatakan unit selesai diservis dan diserahkan"
    assert not re.search(r"Unit Selesai ✅", bad), \
        "pesan CASH tidak boleh memakai kalimat 'Unit Selesai' - itu punya DONE"


def test_pesan_wa_tidak_menjanjikan_lampiran_otomatis():
    """Sistem TIDAK bisa melampirkan berkas otomatis.

    `doneWaSend()` cuma membuka wa.me dengan teks. Staff yang menempel
    gambar Nota Garansi secara manual. Kalau suatu saat lampiran dibuat
    otomatis, test ini harus diperbarui - jangan sampai ada dua jalan.
    """
    s = _src(SCRIPT)
    kirim = _js_fungsi(s, "doneWaSend")
    assert kirim, "doneWaSend tidak terbaca"
    assert "wa.me/" in kirim, "pengiriman harus lewat wa.me"
    assert "navigator.share" not in kirim and "new File(" not in kirim, \
        "doneWaSend sudah bisa melampirkan berkas - perbarui test & pesan WA"


# ─────────────────────────────────────────────────────────────────
# 7. Batas perubahan
# ─────────────────────────────────────────────────────────────────

def test_tidak_ada_endpoint_baru_di_nota_garansi():
    """Spesifikasi melarang menambah endpoint tanpa kebutuhan terverifikasi."""
    s = _src(SCRIPT)
    for fn in ("usWarrantyPrint", "renderWarrantyNotaDigital", "notaWarrantyParts"):
        bad = _js_fungsi(s, fn)
        assert bad, "%s tidak terbaca" % fn
        assert "fetch(" not in bad, \
            "%s tidak boleh memanggil fetch/endpoint baru" % fn


def test_tidak_mengubah_struktur_database():
    """models.py & schemas.py tidak boleh disentuh untuk task ini."""
    pass  # dijaga lewat git diff, bukan test


def test_gaya_komponen_ada_di_css():
    css = _src(CSS)
    assert re.search(r"\.ndr-paystate\b", css), \
        "gaya status pembayaran nota garansi belum ada di style.css"
    assert re.search(r"\.ndr-wstatus\b", css), \
        "gaya panel status garansi belum ada di style.css"


# ─────────────────────────────────────────────────────────────────
# 8. Blok komponen harus memakai kelas .ng-*, bukan .ndr-*
# ─────────────────────────────────────────────────────────────────

def test_blok_komponen_memakai_kelas_ng():
    """Blok komponen dirender DI DALAM .ng-main.

    Kalau masih pakai .ndr-card/.ndr-cap, kartu itu tidak dapat styling
    Nota Garansi sama sekali - dulu tampil polos dan tidak konsisten.
    """
    bad = _js_fungsi(_src(SCRIPT), "notaWarrantyParts")
    assert bad, "notaWarrantyParts tidak terbaca"
    assert "ng-card" in bad, "kartu komponen harus memakai .ng-card"
    assert "ng-cap" in bad, "judul komponen harus memakai .ng-cap"
    assert "ng-parts" in bad, "daftar komponen harus memakai .ng-parts"
    for salah in ("ndr-card", "ndr-cap", "ndr-part"):
        assert salah not in bad, \
            "kartu komponen masih memakai kelas %s (milik nota lain)" % salah


def test_blok_komponen_menerima_beberapa_nama_field():
    """Sumber data bisa pakai nama atau name; keduanya harus diterima."""
    bad = _js_fungsi(_src(SCRIPT), "notaWarrantyParts")
    assert bad, "notaWarrantyParts tidak terbaca"
    assert "p.nama" in bad and "p.name" in bad, \
        "harus menerima nama komponen sebagai nama maupun name"


def test_qty_komponen_ditampilkan_bila_lebih_dari_satu():
    bad = _js_fungsi(_src(SCRIPT), "notaWarrantyParts")
    assert bad, "notaWarrantyParts tidak terbaca"
    assert re.search(r"x.*qty|qty.*x", bad), \
        "jumlah komponen >1 harus ditulis di sebelah nama"


# ─────────────────────────────────────────────────────────────────
# 9. Rentang tanggal garansi hanya tampil bila ada masa garansi
# ─────────────────────────────────────────────────────────────────

def test_rentang_tanggal_hanya_saat_ada_masa_garansi():
    """Unit tanpa garansi tidak boleh menampilkan 'Berakhir: -'."""
    bad = _js_fungsi(_src(SCRIPT), "renderWarrantyNotaDigital")
    assert bad, "renderWarrantyNotaDigital tidak terbaca"
    m = re.search(r"\$\{(d\.warranty_end[^}]*)\?\s*`?", bad)
    assert m, "syarat pil rentang tanggal harus berbasis d.warranty_end"
    blok = bad[m.start():m.start() + 700]
    assert "Mulai:" in blok and "Berakhir:" in blok, \
        "blok yang bersyarat harus berisi Mulai/Berakhir"


def test_tidak_menampilkan_tanggal_kosong_sebagai_dash():
    """notaTglSlash('') menghasilkan '-', bukan string kosong.

    Karena '-' itu truthy di JS, syarat harus basing pada d.warranty_end,
    bukan hasil format. Kalau dibalik ke hasil format, 'Berakhir: -'
    akan muncul lagi untuk unit tanpa garansi.
    """
    bad = _js_fungsi(_src(SCRIPT), "renderWarrantyNotaDigital")
    assert bad, "renderWarrantyNotaDigital tidak terbaca"
    assert not re.search(r"\$\{(sampai|sampai\s*\|\|[^}]*)\s*\?", bad), \
        "syarat tidak boleh berbasis hasil format (notaTglSlash('' -> '-')"