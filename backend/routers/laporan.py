# -*- coding: utf-8 -*-
"""Laporan baca + ekspor untuk role monitoring (OD-LOCK-10).

Owner:
  - PENGELOLA (Pemilik): dashboard & laporan keuangan detail, laporan
    operasional & kinerja teknisi, riwayat Tutup Kas, Kas Aset, Hutang Beban,
    bagi hasil 30%. Boleh memfilter dan mengunduh laporan.
  - INVESTOR: omzet, laba, tren, laporan periode, DASAR PERHITUNGAN hak bagi
    hasil 30% beserta riwayat pembayarannya, RINGKASAN Kas Aset dan Hutang
    Beban. Boleh memfilter dan mengunduh. TIDAK mendapat data pribadi
    pelanggan atau informasi teknis sensitif.

Prinsip yang dijaga:
  - Otorisasi di BACKEND. `require_authority` dipakai di setiap endpoint; tidak
    ada andalan pada menyembunyikan tombol.
  - Pembatasan DATA sama dengan tampilan laporan: Investor tidak pernah
    menerima daftar pelanggan, nomor telepon, atau nomor unit.
  - Tidak ada endpoint yang menulis apa pun di modul ini.
  - Ekspor memakai content-disposition attachment, bukan JSON, supaya tidak
    bisa dipakai sebagai API data yang lebih luas.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

import cash as cash_mod
import distribution as distribution_mod
import expense_debt as debt_mod
import finance as fin
from authority import Action, require_any_authority, require_authority
from dependencies import get_db_session
from models import User
from routers.dashboard import batas_periode, get_active_period

router = APIRouter(prefix="/api/laporan", tags=["laporan"])


def _bulat(n):
    from money import quantize, to_decimal

    return quantize(to_decimal(n))


def _rupiah(n) -> str:
    """Format angka tanpa desimal, untuk ditampilkan ke user."""
    n = _bulat(n)
    return "Rp" + format(n, ",.0f")


# ─────────────────────────── Ringkasan investasi ───────────────────────────
@router.get("/investasi")
def ringkasan_investasi(
        db: Session = Depends(get_db_session),
        user: User = Depends(require_authority(Action.REPORT_INVESTOR))):
    """Ringkasan Kas Aset + Hutang Beban + dasar bagi hasil Investor.

    Hanya angka. Tanpa data pelanggan, tanpa daftar transaksi, tanpa nomor
    telepon, tanpa nomor unit.
    """
    period = get_active_period(db)
    start, end = batas_periode(period)
    core = fin.compute_finance_core(db, start, end, freeze=False)

    laba_bersih = _bulat(core["laba_bersih"])
    alokasi = distribution_mod.hitung(laba_bersih) if laba_bersih > 0 else None

    return {
        "periode": str(period.start_at),
        "untuk": "INVESTOR",
        "omzet": _bulat(core["omset"]),
        "laba_kotor": _bulat(core["laba_kotor"]),
        "total_beban": _bulat(core["total_beban"]),
        "laba_bersih": laba_bersih,
        "kas_aset": {
            "saldo": _bulat(cash_mod.saldo_kas_aset(db)),
            "cara_baca": "Saldo Kas Aset Besar / Pengelola. Ringkasan saja.",
        },
        "hutang_beban": {
            "saldo": _bulat(debt_mod.saldo_hutang(db)),
            "cara_baca": "Sisa kewajiban beban yang belum ditutup. "
                         "Ditutup manual oleh user (OD-LOCK-06).",
        },
        "hak_bagi_hasil": {
            "rate": "30%",
            "dasar_perhitungan": laba_bersih,
            "hak_periodo_ini": alokasi["investor"] if alokasi else _bulat(0),
            "cara_baca": "30% dari Laba Bersih. Muncul kalau Laba Bersih > 0.",
        },
        "catatan": "Ringkasan. Tidak termasuk data pelanggan atau detail "
                   "transaksi.",
    }


# ─────────────────────────── Laporan Redirecting ───────────────────────────
@router.get("/bisnis")
def laporan_bisnis(
        db: Session = Depends(get_db_session),
        user: User = Depends(require_authority(Action.REPORT_FULL))):
    """Laporan bisnis lengkap untuk PENGELOLA (Pemilik).

    Menghormati OD-LOCK-07: angka khusus periode yang diminta, tidak boleh
    menjatuhkan periode berjalan ke data periode lain dan sebaliknya.
    """
    period = get_active_period(db)
    start, end = batas_periode(period)
    core = fin.compute_finance_core(db, start, end, freeze=False)

    alokasi = (distribution_mod.hitung(_bulat(core["laba_bersih"]))
               if _bulat(core["laba_bersih"]) > 0 else None)

    return {
        "periode": str(period.start_at),
        "untuk": "PENGELOLA",
        "omzet": _bulat(core["omset"]),
        "modal": {
            "part": _bulat(core["modal_part"]),
            "jasa": _bulat(core["modal_jasa"]),
            "lain": _bulat(core["modal_lainnya"]),
            "total": _bulat(core["total_modal"]),
        },
        "laba_kotor": _bulat(core["laba_kotor"]),
        "total_beban": _bulat(core["total_beban"]),
        "laba_bersih": _bulat(core["laba_bersih"]),
        "kas_aset": _bulat(cash_mod.saldo_kas_aset(db)),
        "hutang_beban": _bulat(debt_mod.saldo_hutang(db)),
        "bagi_hasil": alokasi,
        "bagi_hasil_rate": {"karyawan": "10%", "pengelola": "30%",
                            "investor": "30%", "kas_aset": "30%"},
        "catatan": "Laporan periode kas berjalan (OD-LOCK-07).",
    }


# ─────────────────────────── Ekspor ───────────────────────────
#: Kolom tiap jenis laporan. Ditetapkan di server; klien tidak boleh
#: meminta kolom sembarang lewat parameter.
KOLOM = {
    "laba-bersih": (
        ["Omzet", "Modal Part", "Modal Jasa", "Modal Lain", "Total Modal",
         "Laba Kotor", "Total Beban", "Laba Bersih"], "REPORT_FULL"),
    "bagi-hasil": (
        ["Penerima", "Porsi", "Nilai"], "REPORT_FULL"),
    "bagian-investor": (
        ["Dasar Perhitungan (Laba Bersih)", "Porsi", "Hak Investor"], "REPORT_INVESTOR"),
}


def _csv(judul, header, baris) -> str:
    out = [judul, ",".join(header)]
    for b in baris:
        out.append(",".join(str(x) for x in b))
    return "\n".join(out) + "\n"


@router.get("/export")
def export_laporan(
        jenis: str = Query(..., description="laba-bersih | bagi-hasil | "
                                           "bagian-investor"),
        db: Session = Depends(get_db_session),
        user: User = Depends(require_any_authority(Action.REPORT_FULL,
                                             Action.REPORT_INVESTOR))):
    """Unduh laporan sebagai CSV.

    Otorisasinya dicek DUA kali: sekali lewat equire_authority di
    endpoint, sekali lagi per jenis di bawah. Jadi role yang punya
    REPORT_INVESTOR tidak otomatis boleh memakai endpoint ini kalau
    dipanggil tanpa REPORT_FULL, dan sebaliknya dikunci di tabel `KOLOM`.
    """
    import authority as auth_mod

    jenis = (jenis or "").strip().lower()
    if jenis not in KOLOM:
        raise HTTPException(
            status_code=400,
            detail="Jenis laporan tidak dikenal. Pilihan: %s"
                   % ", ".join(sorted(KOLOM)))
    header, butuh = KOLOM[jenis]
    if not auth_mod.can(user, getattr(auth_mod.Action, butuh)):
        raise HTTPException(
            status_code=403,
            detail="Jenis laporan '%s' di luar kewenangan role Anda." % jenis)

    period = get_active_period(db)
    start, end = batas_periode(period)
    core = fin.compute_finance_core(db, start, end, freeze=False)
    laba_bersih = _bulat(core["laba_bersih"])
    alokasi = (distribution_mod.hitung(laba_bersih)
               if laba_bersih > 0 else None)

    if jenis == "laba-bersih":
        baris = [[_rupiah(core["omset"]), _rupiah(core["modal_part"]),
                  _rupiah(core["modal_jasa"]), _rupiah(core["modal_lainnya"]),
                  _rupiah(core["total_modal"]), _rupiah(core["laba_kotor"]),
                  _rupiah(core["total_beban"]), _rupiah(laba_bersih)]]
        isi = _csv("Laporan Laba - Periode %s" % period.start_at, header, baris)
        nama = "laba-bersih.csv"
    elif jenis == "bagi-hasil":
        baris = []
        if alokasi:
            for nama_orang, porsi in (("Karyawan", "10%"),
                                      ("Pengelola", "30%"),
                                      ("Investor", "30%"),
                                      ("Hak Kas Aset", "30%")):
                kunci = {"Karyawan": "karyawan", "Pengelola": "pengelola",
                         "Investor": "investor", "Hak Kas Aset": "kas_aset"}[nama_orang]
                baris.append([nama_orang, porsi, _rupiah(alokasi[kunci])])
        isi = _csv("Pembagian Hasil - Periode %s" % period.start_at, header, baris)
        nama = "bagi-hasil.csv"
    else:  # bagian-investor
        hak = alokasi["investor"] if alokasi else _bulat(0)
        baris = [[_rupiah(laba_bersih), "30%", _rupiah(hak)]]
        isi = _csv("Hak Bagi Hasil Investor - Periode %s" % period.start_at,
                   header, baris)
        nama = "bagian-investor.csv"

    return Response(
        content=isi,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="%s"' % nama},
    )
