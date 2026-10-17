# -*- coding: utf-8 -*-
"""P2-15 / Owner Cash Model v4 — Ledger posisi MASTER KAS.

    MASTER KAS = KAS ASET
    ├── SALDO LACI  -> "Kas Aset Kecil (Laci)"  : uang fisik di toko
    └── SALDO ASET  -> "Kas Aset Besar (Pengelola)" : uang dipegang Pengelola
    MASTER KAS = SALDO LACI + SALDO ASET

Aturan v4 yang ditegakkan modul ini:
1. Payment non-DP   -> Laci Masuk   (`catat_penerimaan`)
1b. **DP = TITIPAN.** DP masuk TIDAK membuat entri kas sama sekali; dicatat di
    `payments` + Laporan Titipan DP. Saat unitnya LUNAS, DP dilepas ke Laci
    tepat satu kali (`catat_pelepasan_dp`) supaya total kas unit = kewajiban
    penuh tanpa dobel hitung. Refund DP juga tidak menyentuh ledger kas.
2. Modal dibayar     -> Laci Keluar  (`catat_modal`)
3. Beban dibayar     -> Laci Keluar  (`catat_beban`)
4. Distribusi 70%    -> Laci Keluar  (`catat_cash_out`); 30% = ALOKASI, bukan uang
5. Transfer Laci<->Aset: Laci ∓, Aset ±, Master Kas tetap (`transfer`)
6. Injection memilih posisi Laci/Aset (`catat_injeksi`)
7. Rekonsiliasi: `cash_counted` hanya pembanding; selisih jadi PENYESUAIAN LACI
   eksplisit, TIDAK menyuntik opening (`rekonsiliasi_laci`)
8. Refund Garansi / Hutang Beban bersumber dari SALDO ASET; pengeluaran aktual
   dicatat MANUAL oleh Admin — proses tidak otomatis mengurangi saldo.

Anti double count dengan Buku Kas (v4 #9): mutasi turunan diberi `sumber` khusus
sehingga `dashboard.compute_finance` & `routers/kas.period_rows` hanya menghitung
`MANUAL` + arus operasional miliknya sendiri (`payments`, `expenses`).
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

import journal
from money import ZERO, quantize, to_decimal

LAYER_LACI = "LACI"
LAYER_ASET = "KAS_ASET"
LAYERS = (LAYER_LACI, LAYER_ASET)
#: Alias kompatibilitas (P2-06) — sedang dimigrasi ke LAYER_ASET.
LAYER_KAS_ASET = LAYER_ASET

#: Nama posisi sesuai terminology v4 (#12)
LABEL = {LAYER_LACI: "Kas Aset Kecil (Laci)", LAYER_ASET: "Kas Aset Besar (Pengelola)"}
KATEGORI_DEFAULT = {
    LAYER_LACI: "Kas Aset Kecil (Laci)",
    LAYER_ASET: "Kas Aset Besar (Pengelola)",
}

#: Kategori entri yang membentuk OPENING posisi (v4 #10: baris "KAS ASET AWAL" di
#: Buku Kas = opening Saldo Laci, bukan opening Master Kas).
SALDO_AWAL_KATEGORI = "Saldo Awal"

# --- sumber mutasi (v4 #9: pisahkan Buku Kas vs Master Kas) ---
SUMBER_MANUAL = "MANUAL"
SUMBER_PAYMENT = "PAYMENT"
SUMBER_MODAL = "MODAL"
SUMBER_BEBAN = "BEBAN"
SUMBER_CASH_OUT = "CASH_OUT"
SUMBER_REFUND_DP = "REFUND_DP"
SUMBER_REFUND_GARANSI = "REFUND_GARANSI"
SUMBER_FAILED_CANCEL = "FAILED_CANCEL"
SUMBER_TRANSFER = "TRANSFER"
SUMBER_INJEKSI = "INJEKSI"
SUMBER_REKONSILIASI = "REKONSILIASI"
SUMBER_PENYESUAIAN = "PENYESUAIAN"
SUMBER_HUTANG_BEBAN = "HUTANG_BEBAN"
#: Porsi "Hak Kas Aset" 30% dari Distribusi Laba. Uangnya BENAR-BENAR pindah dari
#: Laci ke Kas Aset (bukan sekadar penanda), jadi dicatat sebagai mutasi berpasangan
#: di dua layer. Berbeda dari `TRANSFER` biasa, ini bersumber dari laba periode.
SUMBER_DISTRIBUSI_ASET = "DISTRIBUSI_ASET"

#: Sumber yang boleh masuk ARUS KAS AKRUAL (`compute_finance` -> total_masuk /
#: total_keluar). Harus SEMPIT: apa pun yang sudah tercakup di `omset`,
#: `total_modal`, atau `total_beban` akan terhitung dua kali kalau ikut di sini.
#: `DISTRIBUSI_ASET` ikut dihitung (2026-10-17). Dua gerak Laci nyata yang
#: sebelumnya hilang dari Buku Kas accrual:
#:   - sisi Keluar Laci saat Hak Kas Aset dipindahkan ke Saldo Aset;
#:   - jurnal "Koreksi Bagi Hasil" saat topdown mengembalikan kelebihan cash-out.
#: Tanpa keduanya, `total_keluar` Arsip Tutup Kas lebih besar dari Laba Bersih
#: yang sebenarnya dan `saldo` berakhir negatif (-4.000 di UJI, padahal tabel
#: Kondisi Kas Operasional berakhir 0).
SUMBER_BUKU_KAS = frozenset({
    SUMBER_MANUAL, SUMBER_CASH_OUT, SUMBER_REFUND_DP, SUMBER_FAILED_CANCEL,
    SUMBER_DISTRIBUSI_ASET,
})

#: Sumber entri kas yang ditampilkan sebagai BARIS di Mutasi Kas
#: (`routers.kas.period_rows`). Sifatnya **FISIS**: Mutasi Kas memuat SETIAP
#: perpindahan uang di laci, supaya kolom Saldo Berjalan selalu sama dengan
#: `saldo_laci()` dan bisa dipakai merekonsiliasi uang fisik saat Tutup Kas.
#:
#: Prinsip penyusunannya: semua sumber yang bisa menulis ke layer LACI, KECUALI
#: `PAYMENT` — karena `PAYMENT` sudah diambil langsung dari tabel `payments`
#: oleh loop terpisah di `period_rows`, jadi ikutkan di sini akan menghitung dua
#: kali.
#:
#: Yang TIDAK ikut dan alasannya:
#:   - `PAYMENT`   : sudah di loop `payments` (cegah dobel).
#:   - lapisan `KAS_ASET`  : bukan uang di laci; `period_rows` sudah memfilter
#:                           `layer == LACI`, jadi pasangan transfer tidak pernah
#:                           terhitung dua kali dan Master Kas tetap utuh.
#:
#: `BEBAN` sekarang DIKUTIPKAN (sebelumnya tidak, 2026-10-17). Alasannya:
#: pembayarannya yang sungguhan dicatat sebagai SATU entri agregat
#: `sumber=BEBAN, ref_type='beban_periode'` -- bukan satu baris per katalog.
#: Kalau `BEBAN` dikecualikan, Mutasi Kas tidak pernah menampilkan pembayaran
#: Beban dan saldo berjalan-nya meleset sebesar nilai Beban (605.000 di UJI).
#: Yang tidak boleh masuk bukan `BEBAN`, melainkan KATALOG `expenses` dibaca
#: sebagai arus -- itu sudah dinonaktifkan di `period_rows`.
SUMBER_BARIS_KAS = frozenset({
    SUMBER_MANUAL, SUMBER_MODAL, SUMBER_CASH_OUT, SUMBER_REFUND_DP,
    SUMBER_REFUND_GARANSI, SUMBER_FAILED_CANCEL, SUMBER_TRANSFER,
    SUMBER_INJEKSI, SUMBER_REKONSILIASI, SUMBER_PENYESUAIAN,
    SUMBER_HUTANG_BEBAN, SUMBER_DISTRIBUSI_ASET, SUMBER_BEBAN,
})

KATEGORI = {
    SUMBER_PAYMENT: "Penerimaan Pembayaran",
    SUMBER_MODAL: "Pembelian Modal",
    SUMBER_BEBAN: "Pembayaran Beban",
    SUMBER_CASH_OUT: "Distribusi Laba (Cash-out 70%)",
    SUMBER_REFUND_DP: "Refund DP",
    SUMBER_REFUND_GARANSI: "Refund Garansi",
    SUMBER_FAILED_CANCEL: "Failed → Cancel",
    SUMBER_TRANSFER: "Transfer Kas Aset",
    SUMBER_INJEKSI: "Injection Kas Aset",
    SUMBER_REKONSILIASI: "Penyesuaian Rekonsiliasi",
    SUMBER_PENYESUAIAN: "Penyesuaian Laci",
    SUMBER_HUTANG_BEBAN: "Hutang Beban",
    SUMBER_DISTRIBUSI_ASET: "Setoran Hak Kas Aset (Distribusi)",
}

EVENT_TRANSFER = "KAS_ASET_DITRANSFER"
EVENT_INJEKSI = "KAS_ASET_DIINJEKSI"
EVENT_REKONSILIASI = "LACI_DIREKONSILIASI"
EVENT_OPERASIONAL = "POSISI_KAS_BERUBAH"

CARA_BACA = ("Master Kas = Saldo Laci (Kas Aset Kecil) + Saldo Aset (Kas Aset Besar). "
             "Transfer Laci ↔ Aset tidak mengubah Master Kas.")


class CashError(ValueError):
    """Aturan Master Kas dilanggar (mis. transfer melebihi saldo Laci)."""


def norm_layer(layer: Optional[str]) -> str:
    v = (layer or "").strip().upper().replace(" ", "_").replace("-", "_")
    if v in ("KAS_ASET", "KASASET", "ASET", "SALDO_ASET", "BESAR"):
        return LAYER_ASET
    if v in ("", "LACI", "KAS_ASET_KECIL", "KECIL", "SALDO_LACI", "PERPUTARAN"):
        return LAYER_LACI
    raise CashError("Posisi kas tidak dikenal: %r" % layer)


def _entry_model():
    from models import KasEntry
    return KasEntry


def _num(v) -> "object":
    return to_decimal(v)


def _moment(row) -> Optional[datetime]:
    dt_val = getattr(row, "created_at", None)
    if dt_val is not None:
        return dt_val
    d_val = getattr(row, "tanggal", None)
    if d_val is not None:
        return datetime(d_val.year, d_val.month, d_val.day, 12, 0, 0)
    return None


def rows_layer(db: Session, layer: str = LAYER_LACI):
    lay = norm_layer(layer)
    out = []
    for r in db.query(_entry_model()).all():
        row_layer = getattr(r, "layer", None) or LAYER_LACI
        try:
            row_layer = norm_layer(row_layer)
        except CashError:
            continue
        if row_layer != lay:
            continue
        out.append(r)
    return out


def opening_layer(db: Session, layer: str = LAYER_LACI):
    """Saldo awal posisi = kategori 'Saldo Awal' (warisan P2-06, tetap dipertahankan)."""
    total = ZERO
    for r in rows_layer(db, layer):
        if (r.kategori or "").strip() != SALDO_AWAL_KATEGORI:
            continue
        n = _num(r.nominal)
        total += n if (r.jenis or "").strip().lower() == "masuk" else -n
    return quantize(total)


def saldo_layer(db: Session, layer: str = LAYER_LACI) -> "object":
    """Saldo posisi sekarang (opening + seluruh mutasi layer)."""
    lay = norm_layer(layer)
    saldo = opening_layer(db, lay)
    for r in rows_layer(db, lay):
        if (r.kategori or "").strip() == SALDO_AWAL_KATEGORI:
            continue
        n = _num(r.nominal)
        saldo += n if (r.jenis or "").strip().lower() == "masuk" else -n
    return quantize(saldo)


def saldo_laci(db: Session):
    return saldo_layer(db, LAYER_LACI)


def saldo_kas_aset(db: Session):
    return saldo_layer(db, LAYER_ASET)


def master_kas(db: Session):
    """MASTER KAS = Saldo Laci + Saldo Aset (v4)."""
    return quantize(saldo_laci(db) + saldo_kas_aset(db))


def saldo_laci_sampai(db: Session, mulai: datetime):
    """Saldo Laci pada AWAL periode (< `mulai`) — untuk baris "KAS ASET AWAL" (v4 #10)."""
    saldo = opening_layer(db, LAYER_LACI)
    for r in rows_layer(db, LAYER_LACI):
        if (r.kategori or "").strip() == SALDO_AWAL_KATEGORI:
            continue
        m = _moment(r)
        if m is not None and m < mulai:
            n = _num(r.nominal)
            saldo += n if (r.jenis or "").strip().lower() == "masuk" else -n
    return quantize(saldo)


def mutasi_tersimpan(db: Session, layer: str, sumber: str, ref_type=None, ref_id=None):
    """Cek mutasi turunan yang sudah tercatat (idempotensi turunan)."""
    lay = norm_layer(layer)
    q = db.query(_entry_model()).filter(
        _entry_model().layer == lay,
        _entry_model().sumber == sumber,
    )
    if ref_type is not None:
        q = q.filter(_entry_model().ref_type == ref_type)
    if ref_id is not None:
        q = q.filter(_entry_model().ref_id == ref_id)
    return q.first()


def catat_mutasi(db: Session, layer: str, jenis: str, kategori: Optional[str],
                 keterangan: str, nominal, tanggal=None, sumber: str = SUMBER_MANUAL,
                 ref_type=None, ref_id=None, commit: bool = False, check_saldo: bool = True,
                 oleh: str = None):
    """Tulis SATU mutasi posisi Master Kas (+ journal). Tidak commit."""
    from models import KasEntry

    lay = norm_layer(layer)
    j = (jenis or "").strip().capitalize()
    if j not in ("Masuk", "Keluar"):
        raise CashError("Jenis wajib Masuk atau Keluar")
    kat = (kategori or "").strip() or KATEGORI_DEFAULT[lay]
    ket = (keterangan or "").strip()
    if not ket:
        raise CashError("Keterangan wajib diisi")
    n = quantize(_num(nominal))
    if n < 0:
        raise CashError("Nominal tidak boleh negatif")

    if check_saldo and j == "Keluar" and n > 0:
        saldo = saldo_layer(db, lay)
        if n > saldo:
            raise CashError("Saldo %s tidak cukup (saldo %s, diminta %s)"
                            % (LABEL[lay], saldo, n))

    saldo_baru = quantize(saldo_layer(db, lay) + (n if j == "Masuk" else -n))
    row = KasEntry(jenis=j, kategori=kat, keterangan=ket, nominal=n, tanggal=tanggal,
                   layer=lay, saldo_setelah=saldo_baru, sumber=sumber,
                   ref_type=ref_type, ref_id=ref_id, oleh=oleh)
    db.add(row)
    db.flush()
    db.refresh(row)
    return {"id": row.id, "layer": lay, "label": LABEL[lay], "jenis": j, "kategori": kat,
            "keterangan": ket, "nominal": n, "saldo_setelah": saldo_baru,
            "sumber": sumber, "ref_type": ref_type, "ref_id": ref_id}


def _journal(db: Session, event: str, mutasi: dict, actor=None, details=None, amount=None):
    journal.record(db, journal.DOMAIN_FINANCE, event,
                   entity_type="kas_entry", entity_id=mutasi["id"],
                   amount=amount if amount is not None else mutasi["nominal"],
                   actor=actor, ref_type=mutasi.get("ref_type"),
                   ref_code=str(mutasi.get("ref_id") or mutasi["id"]),
                   details=dict(details or {}, layer=mutasi["layer"], sumber=mutasi["sumber"]))


# ---------------------------------------------------------------- 1) PAYMENT (v4 #1)
def catat_penerimaan(db: Session, payment, actor: str = None):
    """Payment diterima di toko -> SALDO LACI bertambah (v4 #1). Idempotent per payment.

    Berlaku juga untuk **DP**. DP belum tentu Omzet — Omzet baru naik saat unit
    LUNAS, lewat `statusflow.kewajiban` — TAPI uang DP benar-benar diterima
    kasir dan wajib bisa direkonsiliasi saat Tutup Kas. Karena itu DP tetap
    menjadi mutasi Saldo Laci.

    Pemisahan "bukan Omzet" dibuat di LAPORAN, bukan dengan menghilangkan uangnya
    dari ledger kas:
      - `compute_finance` menghitung DP hanya lewat Omzet (`SUMBER_BUKU_KAS`
        tidak memuat `PAYMENT`), jadi kartu Total Masuk tidak dobel;
      - baris Conditions Kas "Kas Kecil/Laci" memakai `kas_aset_awal_operasional`
        yang dikurangi saldo titipan (`routers/dashboard.py`);
      - Mutasi Kas menampilkannya dengan label "DP / Uang Titipan (bukan Omzet)".
    """
    if mutasi_tersimpan(db, LAYER_LACI, SUMBER_PAYMENT, "payment", payment.id):
        return None
    mut = catat_mutasi(db, LAYER_LACI, "Masuk", KATEGORI[SUMBER_PAYMENT],
                       "Penerimaan pembayaran %s unit #%s (%s)" % (
                           payment.kind or "PELUNASAN", payment.service_order_id,
                           payment.method or "-"),
                       payment.amount, sumber=SUMBER_PAYMENT,
                       ref_type="payment", ref_id=payment.id, oleh=actor)
    _journal(db, EVENT_OPERASIONAL, mut, actor=actor,
             details={"event": "PAYMENT", "service_order_id": payment.service_order_id,
                      "kind": payment.kind})
    return mut


def is_dp(payment) -> bool:
    """Payment ini DP (titipan), bukan pelunasan."""
    return (getattr(payment, "kind", "") or "").strip().upper() == "DP"


def dp_diterima(db: Session, order_id: int):
    """Total DP yang benar-benar diterima untuk satu unit."""
    from models import Payment
    total = ZERO
    for p in (db.query(Payment)
              .filter(Payment.service_order_id == order_id).all()):
        if is_dp(p):
            total += _num(p.amount)
    return quantize(total)


def dp_terpakai(db: Session, order, rows=None) -> Decimal:
    """DP yang benar-benar berubah jadi pembayaran transaksi untuk satu unit.

    HANYA sebesar kewajiban unit. Kalau DP-nya lebih besar dari kewajiban --
    unit dibayar DP tapi RP-nya nanti dikurangi -- sisanya BUKAN terpakai:
    itu uang customer yang masih WAJIB dikembalikan, jadi tetap dihitung
    sebagai titipan (Owner). Tanpa aturan ini, DP Rp1.000.000 pada unit
    kewajiban Rp200.000 akan dianggap habis seluruhnya dan Rp800.000-nya
    hilang dari Laporan Titipan DP padahal uangnya masih di laci.
    """
    from statusflow import kewajiban, payment_summary
    if rows is None:
        from models import Payment
        rows = (db.query(Payment)
                .filter(Payment.service_order_id == order.id).all())
    dp_order = ZERO
    for p in rows:
        if is_dp(p):
            dp_order += _num(p.amount)
    if dp_order <= ZERO:
        return ZERO
    if payment_summary(order, rows)["payment_status"] != "LUNAS":
        return ZERO
    return quantize(min(dp_order, to_decimal(kewajiban(order))))


def saldo_titipan_dp(db: Session) -> Decimal:
    """Total DP yang masih DITAHAN customer di laci (bukan milik toko).

    Turunan dari `payments` + `refunds`, sama seperti Laporan Titipan DP:
      ditahan per unit = DP - DP terpakai (max sebesar kewajiban) - DP dikembalikan
    Tidak bisa negatif per unit; dijepit di 0.

    Dipakai untuk MEMISAHKAN uang milik toko dari uang titipan saat menampilkan
    posisi kas. Ledger sendiri TIDAK berubah -- uang DP tetap satu kesatuan
    fisik di dalam laci, dan angka mentahnya tetap dipakai untuk rekonsiliasi
    serta Declare saat Tutup Kas.
    """
    from models import Payment, Refund, ServiceOrder

    pays_by_order = {}
    for p in db.query(Payment).all():
        pays_by_order.setdefault(p.service_order_id, []).append(p)

    refund_by_order = {}
    for r in db.query(Refund).all():
        if (getattr(r, "jenis", "") or "").strip().upper() == "DP":
            refund_by_order[r.service_order_id] = (
                refund_by_order.get(r.service_order_id, ZERO) + _num(r.nominal))

    total = ZERO
    for o in db.query(ServiceOrder).all():
        rows = pays_by_order.get(o.id) or []
        dp_order = ZERO
        for p in rows:
            if is_dp(p):
                dp_order += _num(p.amount)
        if dp_order <= ZERO:
            continue
        ditahan = (dp_order - dp_terpakai(db, o, rows)
                   - refund_by_order.get(o.id, ZERO))
        if ditahan > ZERO:
            total += ditahan
    return quantize(total)


# ---------------------------------------------------------------- 2) MODAL (v4 #2)
def catat_modal(db: Session, order, actor: str = None):
    """Modal Part/Jasa/Lain yang dibayar dari kas toko -> SALDO LACI berkurang (v4 #2).

    Dicatat satu kali per unit (idempotent lewat ref order + sumber per komponen).
    Tanpa pre-check saldo, sama seperti `catat_beban`: modal yang sudah dibayar
    tetap harus tercatat; defisit ditutup lewat jalur Hutang Beban / Saldo Aset.
    """
    out = []
    for attr, kode in (("part_cost", "MODAL_PART"), ("modal_jasa", "MODAL_JASA"),
                       ("modal_lainnya", "MODAL_LAIN")):
        nilai = quantize(_num(getattr(order, attr, 0)))
        if nilai <= ZERO:
            continue
        if mutasi_tersimpan(db, LAYER_LACI, SUMBER_MODAL, kode, order.id):
            continue
        mut = catat_mutasi(db, LAYER_LACI, "Keluar", KATEGORI[SUMBER_MODAL],
                           "%s unit %s" % (kode.replace("_", " ").title(),
                                            order.no_servis or order.id),
                           nilai, sumber=SUMBER_MODAL, ref_type=kode, ref_id=order.id,
                           oleh=actor, check_saldo=False)
        _journal(db, EVENT_OPERASIONAL, mut, actor=actor,
                 details={"event": "MODAL", "komponen": kode,
                          "service_order_id": order.id})
        out.append(mut)
    return out


# ---------------------------------------------------------------- 3) BEBAN (v4 #3)
def catat_modal_selisih(db: Session, order, actor: str = None) -> list:
    """Catat SELISIH modal yang baru diisi SETELAH order sudah CASH.

    `catat_modal` itu idempoten berdasarkan KEHADIRAN entri per komponen. Itu
    benar untuk event CASH (replay tidak boleh menggandakan), tapi menyisakan
    lubang: kalau Modal Part/Jasa diisi atau dikoreksi setelah unit di-CASH,
    `catat_modal` melihat "sudah pernah" lalu MELewatkannya -- modalnya tidak
    pernah masuk ledger dan Laci tidak pernah tergerus. Akibatnya beban tidak
    tercatat, laba terlihat lebih besar, dan saat Tutup Kas uang fisik laci
    justru lebih banyak dari sistem (terbaca sebagai selisih, bukan sebagai
    modal).

    Fungsi ini menutup lubang itu dengan membandingkan total modal SUDAH
    tercatat di ledger dengan total modal saat ini per komponen, lalu mencatat
    HANYA bedanya. Memanggilnya berulang aman: begitu selisih nol, tidak ada yang
    ditulis.
    """
    from models import KasEntry
    out = []
    for attr, kode in (("part_cost", "MODAL_PART"), ("modal_jasa", "MODAL_JASA"),
                       ("modal_lainnya", "MODAL_LAIN")):
        pristine = quantize(_num(getattr(order, attr, 0)))
        tercatat = ZERO
        for e in db.query(KasEntry).filter(
                KasEntry.layer == LAYER_LACI,
                KasEntry.sumber == SUMBER_MODAL,
                KasEntry.ref_type == kode,
                KasEntry.ref_id == order.id).all():
            n = _num(e.nominal)
            # Modal yang SUDAH terbayar adalah entri "Keluar" -- jadi menambah
            # modal yang tercatat. Entri "Masuk" adalah koreksi yang mengembalikan
            # modal, jadi mengurangi. Kalau arahnya dibalik, `tercatat` jadi
            # negatif dan koreksi justru menggandakan modal dua kali.
            tercatat += n if (e.jenis or "").strip().lower() == "keluar" else -n
        tercatat = quantize(_num(tercatat))
        selisih = quantize(pristine - tercatat)
        if selisih == ZERO:
            continue
        mut = catat_mutasi(db, LAYER_LACI, "Masuk" if selisih > ZERO else "Keluar",
                           KATEGORI[SUMBER_MODAL],
                           "%s unit %s (koreksi modal setelah CASH)"
                           % (kode.replace("_", " ").title(), order.no_servis or order.id),
                           abs(selisih), sumber=SUMBER_MODAL, ref_type=kode,
                           ref_id=order.id, oleh=actor, check_saldo=False)
        _journal(db, EVENT_OPERASIONAL, mut, actor=actor,
                 details={"event": "MODAL_KOREKSI", "komponen": kode,
                          "service_order_id": order.id,
                          "modal_tercatat_sebelumnya": str(tercatat),
                          "modal_sekarang": str(pristine),
                          "selisih": str(selisih)})
        out.append(mut)
    return out


def catat_beban(db: Session, expense, actor: str = None):
    """Beban (Gaji/Operasional) dibayar dari kas toko -> SALDO LACI berkurang (v4 #3).

    TIDAK memakai pre-check saldo: beban adalah FAKTA transaksi, bukan mutasi dana
    yang bebas dipilih. Kalau kas toko tidak cukup, kekurangan itu ditutup Hutang
    Beban (P2-11 / SSOT-8) saat Tutup Kas. Menolak pencatatan beban akan membuat
    jalur Hutang Beban tidak pernah bisa terjadi.
    """
    if mutasi_tersimpan(db, LAYER_LACI, SUMBER_BEBAN, "expense", expense.id):
        return None
    mut = catat_mutasi(db, LAYER_LACI, "Keluar", KATEGORI[SUMBER_BEBAN],
                       "Beban %s: %s" % ((expense.kategori or "-").title(),
                                         (expense.uraian or expense.kategori or "-")),
                       expense.nilai, sumber=SUMBER_BEBAN,
                       ref_type="expense", ref_id=expense.id, oleh=actor,
                       check_saldo=False)
    _journal(db, EVENT_OPERASIONAL, mut, actor=actor,
             details={"event": "BEBAN", "kategori": expense.kategori})
    return mut


# ---------------------------------------------------------------- 4) CASH-OUT 70% (v4 #4)
def catat_cash_out(db: Session, nominal, keterangan: str, ref_type=None, ref_id=None,
                   actor: str = None, check_saldo: bool = True):
    """70% distribusi = cash-out dari LACI (v4 #4).

    `check_saldo=False` dipakai `distribution.catat_cash_out` karena pemanggilnya
    (`pastikan_otomatis`) sudah memastikan Saldo Laci cukup untuk SELURUH porsi
    sebelum satu baris pun ditulis — jadi penolakan saat pencatatan tidak akan
    pernah terjadi dan tidak ada Heidi yang tertulis separuh jalan.
    """
    mut = catat_mutasi(db, LAYER_LACI, "Keluar", KATEGORI[SUMBER_CASH_OUT],
                       keterangan, nominal, sumber=SUMBER_CASH_OUT,
                       ref_type=ref_type, ref_id=ref_id, check_saldo=check_saldo)
    _journal(db, EVENT_OPERASIONAL, mut, actor=actor,
             details={"event": "DISTRIBUSI_CASH_OUT", "porsi": "70%"})
    return mut


# ---------------------------------------------------------------- 5) TRANSFER (v4 #5)
def transfer(db: Session, nominal, dari: str, ke: str, keterangan: str,
             actor: str = None, ref_type=None, ref_id=None, check_saldo: bool = True,
             sumber: str = None, idempoten: bool = True):
    """Transfer fisik Laci <-> Aset: Laci ∓, Aset ±, MASTER KAS TETAP (v4 #5).

    Bukan omzet/beban/laba/distribusi baru — karena itu `sumber` kedua baris
   adalah `TRANSFER` (TIDAK masuk Buku Kas accrual).

    `sumber` bisa dioverride untuk transfer yang berasal dari kejadian lain,
    misalnya `DISTRIBUSI_ASET` (porsi Hak Kas Aset dari Distribusi Laba).
    Override ini tetap menghasilkan pasangan Laci/Aset yang sama dan Master Kas
    tetap utuh; hanya label sumbernya yang lebih spesifik untuk pelacakan.
    """
    a = norm_layer(dari)
    b = norm_layer(ke)
    if a == b:
        raise CashError("Transfer harus antara dua posisi yang berbeda")
    n = quantize(_num(nominal))
    if n <= ZERO:
        raise CashError("Nominal transfer harus lebih besar dari nol")

    src = sumber or SUMBER_TRANSFER
    kat = KATEGORI.get(src, KATEGORI[SUMBER_TRANSFER])
    ref = ref_id
    # Guard idempoten dicocokkan pada (layer, sumber, ref_type, ref_id). Itu benar
    # untuk satu transfer, tapimenOLAK top-up Distribusi: transfer Hak Kas Aset
    # kedua untuk Distribution yang sama punya ref_id yang sama persis, sehingga
    # porsinya tidak pernah berpindah ke Saldo Aset. `idempoten=False` dipakai
    # hanya untuk top-up, yang memang_transfer kedua yang disengaja.
    if (idempoten and ref_type and ref_id is not None
            and mutasi_tersimpan(db, a, src, ref_type, ref)):
        return {"created": False, "dari": a, "ke": b, "nominal": n,
                "master_sebelum": master_kas(db)}

    keluar = catat_mutasi(db, a, "Keluar", kat, keterangan, n,
                          sumber=src, ref_type=ref_type, ref_id=ref_id,
                          check_saldo=check_saldo)
    masuk = catat_mutasi(db, b, "Masuk", kat, keterangan, n,
                         sumber=src, ref_type=ref_type, ref_id=ref_id,
                         check_saldo=False, oleh=actor)
    journal.record(db, journal.DOMAIN_FINANCE, EVENT_TRANSFER,
                   entity_type="kas_entry", entity_id=keluar["id"], amount=n, actor=actor,
                   ref_type=ref_type, ref_code=str(ref_id or keluar["id"]),
                   details={"dari": a, "ke": b, "nominal": str(n),
                            "sumber": src,
                            "master_kas_setelah": str(master_kas(db)),
                            "keterangan": keterangan})
    db.flush()
    return {"created": True, "dari": a, "ke": b, "nominal": n,
            "masuk_id": masuk["id"], "keluar_id": keluar["id"],
            "saldo_dari_setelah": keluar["saldo_setelah"],
            "saldo_ke_setelah": masuk["saldo_setelah"],
            "master_kas_setelah": master_kas(db)}


# ---------------------------------------------------------------- 6) INJECTION (v4 #6)
def catat_injeksi(db: Session, layer: str, nominal, keterangan: str, actor: str = None):
    """Injection Kas Aset dengan POSISI yang dipilih (Laci atau Aset) — v4 #6."""
    lay = norm_layer(layer)
    mut = catat_mutasi(db, lay, "Masuk", KATEGORI[SUMBER_INJEKSI], keterangan, nominal,
                       sumber=SUMBER_INJEKSI, check_saldo=False, oleh=actor)
    _journal(db, EVENT_INJEKSI, mut, actor=actor,
             details={"event": "INJEKSI", "posisi": lay,
                      "master_kas_setelah": str(master_kas(db))})
    return mut


# ---------------------------------------------------------------- 7) REKONSILIASI (v4 #7)
def rekonsiliasi_laci(db: Session, cash_counted, actor: str = None, ref_type=None, ref_id=None):
    """Rekonsiliasi Saldo Laci dengan hitungan fisik (v4 #7).

    TIDAK menyuntik opening. Selisih dicatat sebagai **penyesuaian Laci eksplisit**
    (+journal). Mengembalikan dict {'selisih', 'penyesuaian', 'saldo_sezudah'}.

    IDEMPOTEN per `ref_type`/`ref_id` (= periode kas). Tanpa guard ini, menjalankan
    Tutup Kas ulang untuk periode yang sama akan mencatat selisih DUA KALI: yang
    pertama membuat saldo Laci bergerak mendekati fisik, sehingga selisih kedua
    jadi terukur ulang dari angka yang sudah disesuaikan — bukan selisih asli.
    """
    if cash_counted is None:
        return {"dilewati": True, "selisih": None, "penyesuaian": None,
                "saldo_sezudah": saldo_laci(db)}
    # Sudah pernah direkonsiliasi untuk periode ini -> jangan catat lagi.
    if ref_type and ref_id is not None and mutasi_tersimpan(
            db, LAYER_LACI, SUMBER_REKONSILIASI, ref_type, ref_id):
        from models import KasEntry
        row = (db.query(KasEntry)
               .filter(KasEntry.layer == LAYER_LACI,
                       KasEntry.sumber == SUMBER_REKONSILIASI,
                       KasEntry.ref_type == ref_type,
                       KasEntry.ref_id == ref_id).first())
        return {"dilewati": False, "sudah_ada": True,
                "selisih": quantize(_num(row.nominal)) if (row.jenis or "").strip().lower() == "masuk"
                else quantize(-_num(row.nominal)),
                "penyesuaian": None, "entry_id": getattr(row, "id", None),
                "sistem": saldo_laci(db), "fisik": quantize(_num(cash_counted)),
                "saldo_sezudah": saldo_laci(db)}
    sistem = saldo_laci(db)
    fisik = quantize(_num(cash_counted))
    selisih = quantize(fisik - sistem)
    if selisih == ZERO:
        return {"dilewati": False, "selisih": ZERO, "penyesuaian": None,
                "sistem": sistem, "fisik": fisik, "saldo_sezudah": sistem}
    mut = catat_mutasi(db, LAYER_LACI, "Masuk" if selisih > ZERO else "Keluar",
                       KATEGORI[SUMBER_REKONSILIASI],
                       "Penyesuaian rekonsiliasi Laci (sistem %s, fisik %s)" % (sistem, fisik),
                       abs(selisih), sumber=SUMBER_REKONSILIASI,
                       ref_type=ref_type, ref_id=ref_id, check_saldo=False, oleh=actor)
    _journal(db, EVENT_REKONSILIASI, mut, actor=actor,
             details={"event": "REKONSILIASI", "saldo_sistem": str(sistem),
                      "cash_counted": str(fisik), "selisih": str(selisih),
                      "master_kas_setelah": str(master_kas(db))})
    return {"dilewati": False, "selisih": selisih, "penyesuaian": mut,
            "sistem": sistem, "fisik": fisik, "saldo_sezudah": mut["saldo_setelah"]}


# ---------------------------------------------------------------- Ringkasan (read-only)
def cukup_kas_aset(db: Session, jumlah):
    """Pre-check SALDO ASET BESAR (sumber dana Refund Garansi & Hutang Beban — v4 #8)."""
    jumlah = quantize(_num(jumlah))
    saldo = saldo_kas_aset(db)
    kurang = ZERO if jumlah <= ZERO else quantize(jumlah - saldo)
    return (saldo >= jumlah, saldo, kurang)


def cukup_laci(db: Session, jumlah):
    jumlah = quantize(_num(jumlah))
    saldo = saldo_laci(db)
    kurang = ZERO if jumlah <= ZERO else quantize(jumlah - saldo)
    return (saldo >= jumlah, saldo, kurang)


def ringkasan(db: Session, *, termasuk_aset: bool = True, periode_mulai=None) -> dict:
    """Ringkasan posisi kas. `termasuk_aset=False` untuk role yang hanya boleh
    melihat Saldo Laci (v4 #11) - tidak ada key Aset/Master sama sekali.

    DUA versi posisi, karena uang DP secara fisik ADA di dalam laci tapi BUKAN
    milik toko (ia kewajiban customer):

      * `laci` / `aset` / `master_kas` -- FISIK, apa yang benar-benar terhitung
        saat dihitung tangan. INI yang dipakai untuk Declare saat Tutup Kas.
      * `laci_milik_toko` / `master_kas_milik_toko` -- setelah DP yang masih
        ditahan dikurangi. INI yang ditampilkan ke Owner sebagai posisi kas,
        supaya uang customer tidak dibaca sebagai uang usaha (Owner).

    Ledger tidak diubah oleh pemisahan ini; hanya pennyajiannya.
    """
    laci = saldo_laci(db)
    titipan = saldo_titipan_dp(db)
    out = {"laci": laci, "label_laci": LABEL[LAYER_LACI], "cara_baca": CARA_BACA,
           "kas_aset_awal": (saldo_laci_sampai(db, periode_mulai)
                             if periode_mulai is not None else laci),
           "titipan_dp": titipan,
           "laci_milik_toko": quantize(laci - titipan)}
    if termasuk_aset:
        aset = saldo_kas_aset(db)
        out.update({"aset": aset, "label_aset": LABEL[LAYER_ASET],
                    "master_kas": quantize(laci + aset),
                    "master_kas_milik_toko": quantize(laci - titipan + aset)})
    return out


def ringkasan_saldo(db: Session) -> dict:
    """Compat P2-06 (dipakai router lama): layer Laci & Aset terpisah, tanpa total."""
    r = ringkasan(db, termasuk_aset=True)
    return {"layer": {LAYER_LACI: {"label": LABEL[LAYER_LACI], "saldo": r["laci"]},
                      LAYER_ASET: {"label": LABEL[LAYER_ASET], "saldo": r["aset"]}},
            "master_kas": r["master_kas"], "cara_baca": CARA_BACA}


def riwayat_layer(db: Session, layer: str = LAYER_LACI, limit: int = 100):
    """Riwayat mutasi posisi (read-only)."""
    lay = norm_layer(layer)
    rows = rows_layer(db, lay)
    items = []
    for r in sorted(rows, key=lambda x: (getattr(x, "created_at", None) or datetime.min,
                                         x.id or 0)):
        if (r.kategori or "").strip() == SALDO_AWAL_KATEGORI:
            continue
        items.append({"id": r.id, "jenis": r.jenis, "kategori": r.kategori,
                      "ket": r.keterangan, "nominal": quantize(_num(r.nominal)),
                      "sumber": getattr(r, "sumber", SUMBER_MANUAL),
                      "ref_type": getattr(r, "ref_type", None),
                      "ref_id": getattr(r, "ref_id", None),
                      "saldo": getattr(r, "saldo_setelah", None),
                      "layer": lay, "oleh": r.oleh,
                      "tgl": (r.tanggal.isoformat() if getattr(r, "tanggal", None)
                              else (_moment(r).date().isoformat() if _moment(r) else None))})
    return items[-limit:] if limit else items