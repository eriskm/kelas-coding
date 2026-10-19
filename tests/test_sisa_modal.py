# -*- coding: utf-8 -*-
"""Kolom "Sisa Modal" di halaman Transaksi.

Definisi (keputusan Owner):

    SISA = Harga Final - Modal Part - Modal Jasa - Modal Lain-lain

Ditampilkan HANYA kalau dua syarat ini terpenuhi:

    1. status sudah CASH  (pekerjaan selesai DAN transaksi realisasi)
    2. Modal sudah diisi  (minimal satu komponen > 0, ATAU Owner menandai
                          "Tanpa Modal" secara eksplisit)

Kalau salah satu syarat tidak terpenuhi, kolom menampilkan "-", bukan
angka 0. Unit yang belum boleh dihitung tidak boleh terlihat sama
dengan unit yang benar-benar zeroes.

Kenapa bukan pakai `sisa` yang sudah ada di schema?
    `ServiceOrderList.sisa` sudah dipakai untuk SISA TAGIHAN (belum
    dibayar). Dua arti berbeda, jadi angka baru diberi nama `sisa_modal`
    supaya tidak tertukar di halaman yang sama.

Yang TIDAK boleh terjadi di sini:
- menghitung Laba Bersih per unit (Beban itu per periode kas, bukan
  per transaksi - jadi tidak bisa dialokasikan ke satu baris)
- memakai `statusflow.order_profit` apa adanya, karena gate-nya cuma
  CASH tanpa syarat modal terisi. Unit CASH yang modalnya belum diisi
  akan terlihat " untung penuh", persis jebakan yang
  `finance.settled_orders` sudah documenting.
"""
import io
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FINANCE = os.path.join(ROOT, "backend", "finance.py")
SCHEMAS = os.path.join(ROOT, "backend", "schemas.py")
ORDERS = os.path.join(ROOT, "backend", "routers", "orders.py")
SCRIPT = os.path.join(ROOT, "frontend", "script.js")
INDEX = os.path.join(ROOT, "frontend", "index.html")


def _src(p):
    return io.open(p, encoding="utf-8").read()


def _py_fungsi(src, nama):
    """Ambil body fungsi Python: dari 'def nama(' sampai baris indent 0 berikutnya."""
    m = re.search(r"^def %s\s*\(" % re.escape(nama), src, re.M)
    if not m:
        return ""
    mulai = src.index("\n", m.end())
    akhir = len(src)
    for line in src[m.end():].split("\n")[1:]:
        if line and not line[0].isspace():
            break
        akhir += len(line) + 1
    return src[m.start():akhir]


def _js_fungsi(src, nama):
    """Ambil body fungsi JS: dari 'function nama(' sampai '}' tingkat fungsi."""
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
# 1. SSOT: fungsi di finance.py
# ─────────────────────────────────────────────────────────────────

def test_ada_fungsi_order_sisa_di_finance():
    """Perhitungan harus di finance.py - itu sumber kebenaran Modal/Laba."""
    s = _src(FINANCE)
    assert re.search(r"^def order_sisa\s*\(", s, re.M), \
        "fungsi order_sisa tidak ada di backend/finance.py"


def test_order_sisa_menggunakan_gerbang_resmi():
    """Harus pakai boleh_masuk_omzet, bukan cek modal sendiri."""
    s = _src(FINANCE)
    bad = _py_fungsi(s, "order_sisa")
    assert bad, "body order_sisa tidak terbaca"
    assert "boleh_masuk_omzet" in bad, \
        "order_sisa harus memakai boleh_masuk_omzet() - jangan duplikasi gerbang modal"
    assert "kewajiban" in bad, \
        "order_sisa harus memakai kewajiban() - sumber omzet yang sama dengan SSOT"


def test_order_sisa_mengurangi_tiga_komponen_modal():
    """Part + Jasa + Lain = 3 komponen terpisah, wajib semua dikurangi."""
    bad = _py_fungsi(_src(FINANCE), "order_sisa")
    for f in ("part_cost", "modal_jasa", "modal_lainnya"):
        assert f in bad, "modal %s tidak dikurangi di order_sisa" % f


def test_order_sisa_mengembalikan_none_saat_belum_boleh():
    """Belum boleh dihitung harus None, bukan 0."""
    bad = _py_fungsi(_src(FINANCE), "order_sisa")
    assert "return None" in bad, \
        "order_sisa harus mengembalikan None kalau belum boleh dihitung"


# ─────────────────────────────────────────────────────────────────
# 2. Nama field tidak boleh bentrok dengan `sisa` tagihan
# ─────────────────────────────────────────────────────────────────

def test_nama_field_baru_terpisah_dari_sisa_tagihan():
    """`sisa` = sisa tagihan. Field baru wajib bernama lain."""
    s = _src(SCHEMAS)
    assert "sisa_modal" in s, "field sisa_modal belum ada di ServiceOrderList"
    m = re.search(r"class ServiceOrderList\(BaseModel\):(.*?)\n\nclass ", s, re.S)
    assert m, "blok ServiceOrderList tidak terbaca"
    blok = m.group(1)
    assert re.search(r"^\s*sisa:\s*Optional\[MoneyOut\]", blok, re.M), \
        "sisa (sisa tagihan) harus tetap ada dan tidak boleh diubah artinya"
    assert re.search(r"^\s*sisa_modal:\s*Optional\[MoneyOut\]", blok, re.M), \
        "sisa_modal harus typed Optional[MoneyOut]"


def test_endpoint_mengisi_sisa_modal():
    """Router harus mengisi field baru dari fungsi SSOT."""
    s = _src(ORDERS)
    bad = _py_fungsi(s, "_to_list_schema")
    assert bad, "_to_list_schema tidak terbaca"
    assert "sisa_modal=" in bad, "_to_list_schema tidak mengisi sisa_modal"
    assert "order_sisa" in bad, \
        "_to_list_schema harus memanggil order_sisa(), bukan menghitung sendiri"


# ─────────────────────────────────────────────────────────────────
# 3. Tampilan
# ─────────────────────────────────────────────────────────────────

def test_tabel_transaksi_punya_kolom_sisa():
    h = _src(INDEX)
    assert "<th" in h
    assert re.search(r"<th[^>]*>\s*Sisa\s*</th>", h), \
        "header <th>Sisa</th> tidak ada di tabel Transaksi"
    # harus ada tepat satu kolom Sisa (nama "Sisa" juga dipakai di kolom lain)
    assert len(re.findall(r"<th[^>]*>\s*Sisa\s*</th>", h)) == 1, \
        "ada lebih dari satu kolom Sisa"


def test_kolom_sisa_di_kanan_estimasi():
    """Urutan kolom harus mengikuti tabel Owner."""
    h = _src(INDEX)
    posisi = {}
    for m in re.finditer(r"<th[^>]*>(.*?)</th>", h, re.S):
        label = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", m.group(1))).strip()
        posisi[label] = m.start()
    for perlu in ("Estimasi Biaya", "Sisa", "Aksi"):
        assert perlu in posisi, "kolom %r tidak ditemukan di header tabel" % perlu
    assert posisi["Estimasi Biaya"] < posisi["Sisa"] < posisi["Aksi"], \
        "urutan kolom salah: harus Estimasi Biaya -> Sisa -> Aksi"


def test_sel_baris_sisa_memakai_sisa_modal():
    """Sel harus baca sisa_modal, bukan sisa (sisa tagihan)."""
    bad = _js_fungsi(_src(SCRIPT), "txRowHtml")
    assert bad, "txRowHtml tidak terbaca"
    assert re.search(r"txSisaModal\s*\(", bad), \
        "txRowHtml harus memanggil txSisaModal()"
    # harus ada tepat satu td Sisa, terpisah dari Estimasi
    assert bad.count("tx-sisa") == 1, "harus tepat satu sel Sisa"


def test_fungsi_tampil_sisa_menampilkan_tanda_strip():
    """Belum boleh dihitung -> '-', bukan Rp 0."""
    bad = _js_fungsi(_src(SCRIPT), "txSisaModal")
    assert bad, "fungsi txSisaModal tidak ada di script.js"
    assert re.search(r"null|undefined", bad), \
        "txSisaModal harus mengecek nilai null (belum boleh dihitung)"
    assert re.search(r"['\"]-['\"]", bad), \
        "txSisaModal harus mengembalikan tanda '-' saat belum boleh dihitung"


def test_txbodymenghormati_urutan_kolom():
    """Jumlah <th> tabel Transaksi harus sama dengan jumlah <td> per baris.

    Cuma boleh menghitung header milik tabel transaksi itu sendiri - halaman
    ini punya beberapa tabel, jadi menghitung semua <th> akan salah.
    """
    h = _src(INDEX)
    tbody = h.find('<tbody id="txBody">')
    assert tbody > 0, "tbody #txBody tidak ditemukan"
    awal_tabel = h.rfind("<table", 0, tbody)
    assert awal_tabel > 0, "tag <table> pembungkus txBody tidak ditemukan"
    head = h[awal_tabel:tbody]
    th = len(re.findall(r"<th[\s>]", head))  # <th> atau <th class=...>, bukan <thead>
    assert th == 10, "tabel Transaksi harus punya 10 kolom (sekarang %d)" % th

# ─────────────────────────────────────────────────────────────────
# 4. Bukti: gerbang modal mencegah "untung penuh" semu
# ─────────────────────────────────────────────────────────────────

class _Order:
    """Order palsu - cukup untuk order_sisa(), tidak perlu database."""

    def __init__(self, status="CASH", final=0, part=0, jasa=0, lain=0, tanpa=False):
        self.status = status
        self.final_price = final
        self.estimate = final
        self.part_cost = part
        self.modal_jasa = jasa
        self.modal_lainnya = lain
        self.tanpa_modal = tanpa


def test_urutan_aritmetika_benar():
    """Harga Final - (Part + Jasa + Lain)."""
    import finance
    v = finance.order_sisa(_Order(final=450000, part=50000, jasa=200000, lain=0))
    assert v is not None
    assert int(v) == 200000, "450000 - 50000 - 200000 harusnya 200000, dapat %s" % v


def test_semua_tiga_komponen_dikurangi():
    import finance
    v = finance.order_sisa(_Order(final=1000000, part=300000, jasa=200000, lain=100000))
    assert int(v) == 400000, "1.000.000 - (300rb+200rb+100rb) harusnya 400rb, dapat %s" % v


def test_bukan_cash_mengembalikan_none():
    """DONE / DITERIMA / CASH saja yang boleh."""
    import finance
    for st in ("DONE", "REPAIR", "DITERIMA", "ANALISA", "KONFIRMASI"):
        assert finance.order_sisa(_Order(status=st, final=450000, jasa=200000)) is None, \
            "status %s seharusnya None (belum boleh dihitung)" % st


def test_cash_modal_kosong_mengembalikan_none():
    """Ini jebakan utamanya: tanpa gerbang modal, unit tanpa biaya akan
    terlihat untung penuh (mis. Rp 450.000) padahal belum boleh masuk hitungan."""
    import finance
    v = finance.order_sisa(_Order(status="CASH", final=450000, part=0, jasa=0, lain=0))
    assert v is None, "CASH tanpa modal harus None, bukan %s" % v


def test_tanpa_modal_yang_ditandai_owner_boleh():
    """Owner punya jalan keluar: centang 'Tanpa Modal'. Itu tetap boleh."""
    import finance
    v = finance.order_sisa(_Order(status="CASH", final=450000, tanpa=True))
    assert v is not None, "unit bertanda Tanpa Modal harus boleh dihitung"
    assert int(v) == 450000, "tanpa modal = final price utuh, dapat %s" % v


def test_final_null_fallback_ke_estimate():
    """final_price null -> memakai estimate (sumber kewajiban())."""
    import finance
    o = _Order(final=None, jasa=200000)
    o.estimate = 500000
    v = finance.order_sisa(o)
    assert v is not None and int(v) == 300000, \
        "final null harus fallback estimate, dapat %s" % v


def test_nilai_nol_adalah_nol_bukan_none():
    """Modal sama dengan final -> SISA 0 yang sah, bukan None.

    Ini yang membuat kolom bisa menampilkan 'Rp 0' untuk unit untung
    nol, dan '-' untuk unit yang belum boleh dihitung. Dua-duanya
    punya arti berbeda.
    """
    import finance
    v = finance.order_sisa(_Order(status="CASH", final=450000, jasa=450000))
    assert v is not None, "modal = final harus boleh dihitung"
    assert int(v) == 0, "harus tepat 0, dapat %s" % v
