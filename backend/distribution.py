# -*- coding: utf-8 -*-
"""P2-07 — Distribusi Laba Bersih 10% / 30% / 30% / 30% (Financial SSOT-6).

SSOT-6:
    10% Bonus Karyawan | 30% Pengelola | 30% Investor | 30% Hak Kas Aset
    70% = cash-out (permanen keluar dari Laci)
    30% = Hak Kas Aset (keluar dari Laci, MASUK ke Saldo Aset)
    TRIGGER = CTO tercapai (Laba Kotor >= Beban Gaji + Beban Operasional)

ATURAN BISNIS (keputusan Owner):
    Saat target operasional (CTO) tercapai, distribusi LANGSUNG terbentuk dan
    uangnya langsung bergerak — tidak menunggu Tutup Kas:

        Bonus Karyawan 10%  -> keluar dari Laci (permanen)
        Pengelola       30%  -> keluar dari Laci (permanen)
        Investor        30%  -> keluar dari Laci (permanen)
        Hak Kas Aset    30%  -> keluar dari Laci, masuk Saldo Aset

    Efeknya: Master Kas turun HANYA 70% (uang yang benar-benar dibagikan).
    Porsi Hak Kas Aset hanya pindah lokasi, jadi Master Kas tetap utuh.

Aturan implementasi (ID-01/ID-14, bukan business rule baru):
- Dasar pembagian = LABA BERSIH dari financial core P2-05.
- Pembagian hanya bila Laba Bersih > 0. Bila Laba Bersih <= 0 tidak ada
  distribusi (deficit Beban mengikuti SSOT-8: Kas Aset cover + Hutang Beban —
  mekanisme hutang adalah tahap P2-11, TIDAK dibuat di sini).
- Sisa pembulatan Placement di Hak Kas Aset supaya total selalu tepat 100%.
- Satu baris `Distribution` per periode kas (idempotent, replay-safe) — dipanggil
  ulang berkali-kali TIDAK akan menggerakkan uang dua kali.
- Tutup Kas TIDAK lagi membentuk distribusi; ia hanya melakukan rekonsiliasi +
  arsip + buka periode baru.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

import cash
import journal
from money import ZERO, quantize, to_decimal

RATE_KARYAWAN = Decimal("0.10")
RATE_PENGELOLA = Decimal("0.30")
RATE_INVESTOR = Decimal("0.30")
RATE_KAS_ASET = Decimal("0.30")
TOTAL_RATE = Decimal("1.00")
CASH_OUT_RATE = Decimal("0.70")

NAMA = ("Bonus Karyawan", "Pengelola", "Investor", "Hak Kas Aset")
KATEGORI = "Hak Kas Aset"

EVENT_DISTRIBUSI = "DISTRIBUSI_DIBENTUK"

#: Alasan distribusi tidak terbentuk — dikirim ke UI supaya user tahu kenapa.
ALASAN_BELUM_SIAP = "Laba Kotor belum menutup Total Beban (CTO)"
ALASAN_LABA_NOL = "Laba Bersih tidak positif"
ALASAN_KAS_KURANG = "Saldo Laci tidak cukup untuk seluruh porsi distribusi"


class DistributionError(ValueError):
    """Syarat distribusi tidak terpenuhi."""


def hitung(laba_bersih):
    """Hitung 4 porsi distribusi dari Laba Bersih (tanpa efek samping).

    Return dict lengkap; `eligible=False` bila Laba Bersih <= 0.
    """
    laba = quantize(to_decimal(laba_bersih))
    if laba <= ZERO:
        return {"eligible": False, "alasan": "Laba Bersih tidak positif",
                "laba_bersih": laba, "karyawan": ZERO, "pengelola": ZERO,
                "investor": ZERO, "kas_aset": ZERO, "cash_out": ZERO,
                "total": ZERO}
    karyawan = quantize(laba * RATE_KARYAWAN)
    pengelola = quantize(laba * RATE_PENGELOLA)
    investor = quantize(laba * RATE_INVESTOR)
    # Sisa pembuluan masuk Hak Kas Aset supaya total = 100% dari Laba Bersih.
    hak_kas_aset = quantize(laba - karyawan - pengelola - investor)
    cash_out = quantize(karyawan + pengelola + investor)
    return {"eligible": True, "alasan": None, "laba_bersih": laba,
            "karyawan": karyawan, "pengelola": pengelola, "investor": investor,
            "kas_aset": hak_kas_aset, "cash_out": cash_out,
            "total": quantize(karyawan + pengelola + investor + hak_kas_aset)}


def preview(laba_bersih) -> dict:
    """Hitungan distribusi tanpa persist (untuk pratinjau UI)."""
    return hitung(laba_bersih)


def label_periode(kunci: str) -> str:
    """Label periode yang enak dibaca manusia: `2026-10-06#4` -> `2026-10-06`."""
    return (kunci or "").split("#", 1)[0]


def sudah_ada(db: Session, periode: str, kas_period_id=None):
    """Cari Distribution untuk SATU Kas Period.

    P2-15 B-1: identitas yang benar adalah `kas_period_id`, BUKAN tanggal kalender.
    Admin boleh menutup Kas lebih dari sekali sehari, sehingga dua Kas Period
    dapat memiliki tanggal yang sama. Pencarian mendahulukan `kas_period_id`
    (kanonik), lalu jatuh ke kunci periode untuk kompatibilitas baris lama.
    """
    from models import Distribution
    if kas_period_id is not None:
        # Identitas kanonik: HANYA baris milik Kas Period ini. Tidak boleh jatuh
        # ke baris Kas Period lain hanya karena tanggalnya sama.
        return db.query(Distribution).filter(
            Distribution.kas_period_id == kas_period_id).first()
    row = db.query(Distribution).filter(Distribution.periode == periode).first()
    if row is not None:
        return row
    # Baris dengan kunci ber-suffix (`2026-10-06#4`) = Kas Period kedua pada
    # tanggal sama. Laporan per tanggal (dashboard) tetap harus melihatnya.
    return db.query(Distribution).filter(
        Distribution.periode.like("%s#%%" % periode)).order_by(
        Distribution.id.desc()).first()


def kunci_unik(db: Session, periode: str, kas_period_id) -> str:
    """Kunci penyimpanan yang unik per Kas Period, tetap enak dibaca.

    - Kas Period pertama pada suatu tanggal -> `YYYY-MM-DD` (tidak berubah,
      sehingga baris lama & tampilan UI tetap sama).
    - Kas Period berikutnya pada tanggal yang sama -> `YYYY-MM-DD#<id>`.
    """
    if kas_period_id is None:
        return periode
    from models import Distribution
    row = db.query(Distribution).filter(
        Distribution.kas_period_id == kas_period_id).first()
    if row is not None:
        return row.periode
    if sudah_ada(db, periode) is None:
        return periode
    return "%s#%s" % (periode, kas_period_id)


def terapkan(db: Session, periode: str, laba_bersih, kas_period_id=None,
             oleh: str = None, commit: bool = False):
    """Bentuk distribusi untuk satu KAS PERIOD (dipanggil otomatis saat CTO tercapai).

    IDEMPOTENT per Kas Period: bila Kas Period ini sudah punya Distribution,
    baris lama dikembalikan tanpa menulis ulang dan TANPA menggerakkan uang lagi.
    Kas Period lain pada tanggal yang sama tetap mendapat barisnya sendiri.
    Saat baris baru terbentuk, uangnya langsung bergerak: 70% keluar permanen dari
    Laci, 30% Hak Kas Aset dipindahkan Laci -> Saldo Aset.
    Tidak memaksa commit; pemanggil (router) yang memutuskan transaksi.
    """
    existing = sudah_ada(db, periode, kas_period_id)
    if existing is not None:
        return {"created": False, "distribution": existing,
                "alokasi": alokasi_dari(existing), "kas_aset_mutation": None,
                "kas_aset_entry": None, "cash_out": ZERO,
                "trigger": "CTO tercapai",
                "periode": label_periode(existing.periode),
                "periode_key": existing.periode}

    hit = hitung(laba_bersih)
    if not hit["eligible"]:
        if commit:
            db.commit()
        return {"created": False, "distribution": None, "alokasi": hit,
                "kas_aset_mutation": None, "kas_aset_entry": None,
                "cash_out": ZERO, "trigger": None,
                "alasan": hit.get("alasan"),
                "periode": periode, "periode_key": periode}

    from models import Distribution
    row = Distribution(
        periode=kunci_unik(db, periode, kas_period_id),
        kas_period_id=kas_period_id,
        laba_bersih=hit["laba_bersih"],
        karyawan_pct=RATE_KARYAWAN, pengelola_pct=RATE_PENGELOLA,
        investor_pct=RATE_INVESTOR, kas_aset_pct=RATE_KAS_ASET,
        bonus_karyawan=hit["karyawan"], pengelola=hit["pengelola"],
        investor=hit["investor"], hak_kas_aset=hit["kas_aset"],
        cash_out=hit["cash_out"], oleh=oleh,
    )
    db.add(row)
    db.flush()

    # ---------------------------------------------------------------------------
    # UANGNYA SEKARANG BERGERAK (keputusan Owner: distribusi saat CTO tercapai).
    #   70% (Karyawan + Pengelola + Investor) -> KELUAR permanen dari Laci.
    #   30% (Hak Kas Aset)                   -> KELUAR dari Laci, MASUK Saldo Aset.
    # Efek Master Kas: turun hanya sebesar 70%.
    # ---------------------------------------------------------------------------
    co_mut = catat_cash_out(db, row, oleh=oleh)
    aset_mut = catat_hak_kas_aset(db, row, oleh=oleh)
    row.cash_out_entry_id = co_mut.get("entry_id")
    # Disimpan sisi MASUK (sisi Aset) — itu yang jadi bukti uang benar-benar
    # berpindah posisi, dan dipakai closing untuk idempotensi.
    row.laci_adjust_entry_id = aset_mut.get("masuk_id")

    journal.record(
        db, journal.DOMAIN_FINANCE, EVENT_DISTRIBUSI,
        entity_type="distribution", entity_id=row.id,
        amount=hit["laba_bersih"], actor=oleh,
        ref_type="periode", ref_code=periode,
        details={"laba_bersih": str(hit["laba_bersih"]),
                 "karyawan": str(hit["karyawan"]), "pengelola": str(hit["pengelola"]),
                 "investor": str(hit["investor"]), "kas_aset": str(hit["kas_aset"]),
                 "cash_out": str(hit["cash_out"]),
                 "rasio": ["10%", "30%", "30%", "30%"],
                 "trigger": "CTO tercapai",
                 "hak_kas_aset": "dipindahkan Laci -> Saldo Aset",
                 "master_kas_setelah": str(cash.master_kas(db))})

    if commit:
        db.commit()
    else:
        db.flush()
    db.refresh(row)
    return {"created": True, "distribution": row, "alokasi": hit,
            "kas_aset_mutation": aset_mut, "kas_aset_entry": aset_mut["masuk_id"],
            "cash_out": hit["cash_out"], "trigger": "CTO tercapai",
            "alasan": None,
            "periode": label_periode(row.periode), "periode_key": row.periode}


def catat_cash_out(db: Session, row, oleh: str = None) -> dict:
    """70% distribusi KELUAR dari Saldo Laci (permanen). Idempoten per Distribution."""
    if row is None:
        return {"created": False, "nominal": ZERO, "entry_id": None}
    if row.cash_out_entry_id:
        from models import KasEntry
        e = db.query(KasEntry).filter(
            KasEntry.id == row.cash_out_entry_id).first()
        return {"created": False,
                "nominal": quantize(to_decimal(getattr(e, "nominal", 0))),
                "entry_id": row.cash_out_entry_id}
    nominal = quantize(to_decimal(row.cash_out))
    if nominal <= ZERO:
        return {"created": False, "nominal": ZERO, "entry_id": None}
    mut = cash.catat_cash_out(db, nominal, "Bagi hasil periode %s" % row.periode,
                              ref_type="distribusi", ref_id=row.id, actor=oleh,
                              check_saldo=False)
    row.cash_out_entry_id = mut["id"]
    db.flush()
    return {"created": True, "nominal": mut["nominal"], "entry_id": mut["id"]}


def catat_hak_kas_aset(db: Session, row, oleh: str = None) -> dict:
    """30% Hak Kas Aset: KELUAR dari Laci lalu MASUK ke Saldo Aset.

    Dipakai `cash.transfer` supaya dua sisinya dijamin berpasangan (Laci ∓,
    Aset ±) dan Master Kas tidak berubah — hanya lokasi uang yang pindah.
    """
    if row is None:
        return {"created": False, "nominal": ZERO, "masuk_id": None}
    if row.laci_adjust_entry_id:
        return {"created": False,
                "nominal": quantize(to_decimal(row.hak_kas_aset)),
                "masuk_id": row.laci_adjust_entry_id}
    nominal = quantize(to_decimal(row.hak_kas_aset))
    if nominal <= ZERO:
        return {"created": False, "nominal": ZERO, "masuk_id": None}
    res = cash.transfer(
        db, nominal, cash.LAYER_LACI, cash.LAYER_ASET,
        "Setoran Hak Kas Aset periode %s" % row.periode,
        actor=oleh, ref_type="distribusi", ref_id=row.id, check_saldo=False,
        sumber=cash.SUMBER_DISTRIBUSI_ASET)
    masuk_id = res.get("masuk_id") or res.get("entry_id")
    row.laci_adjust_entry_id = masuk_id
    db.flush()
    return {"created": bool(res.get("created", True)), "nominal": nominal,
            "masuk_id": masuk_id, "keluar_id": res.get("keluar_id")}


def pastikan_otomatis(db: Session, periode: str, laba_bersih, cto_tercapai,
                      kas_period_id=None, oleh: str = None):
    """Bentuk distribusi OTOMATIS begitu CTO tercapai. Aman dipanggil sesering mungkin.

    Syarat (semua harus lewat, kalau tidak TIDAK ada yang disentuh):
      1. CTO tercapai  : Laba Kotor >= Beban Gaji + Beban Operasional.
      2. Laba Bersih > 0
      3. Saldo Laci cukup untuk SELURUH porsi (cash-out + Hak Kas Aset), supaya
         tidak ada uang yang keluar sebagian lalu posisi terpisah.
      4. Periode ini belum punya Distribution.

    Idempoten lewat (4): dipanggil lagi pada periode yang sama tidak menggerakkan
    uang dua kali.
    """
    res = {"dibentuk": False, "alasan": None, "alokasi": hitung(laba_bersih),
           "distribution": None, "cash_out": ZERO, "hak_kas_aset": ZERO}
    # (1) Sudah pernah terbentuk? -> einde, tidak ada yang perlu dicek lagi.
    # Dicek PALING AWAL supaya alasannya akurat ("sudah terbentuk"), bukan
    # salah dilaporkan sebagai "kas kurang" padahal saldonya memang sudah habis
    # karena distribusi tadi.
    existing = sudah_ada(db, periode, kas_period_id)
    if existing is not None:
        res["alasan"] = "Sudah pernah terbentuk di periode ini"
        res["alokasi"] = alokasi_dari(existing)
        res["distribution"] = existing
        res["cash_out"] = to_decimal(existing.cash_out)
        res["hak_kas_aset"] = to_decimal(existing.hak_kas_aset)
        return res
    # (2) Syarat-syarat berurutan dari yang paling mendasar.
    if not cto_tercapai:
        res["alasan"] = ALASAN_BELUM_SIAP
        return res
    hit = hitung(laba_bersih)
    if not hit["eligible"]:
        res["alasan"] = hit.get("alasan") or ALASAN_LABA_NOL
        return res
    total = quantize(hit["cash_out"] + hit["kas_aset"])
    if cash.saldo_laci(db) < total:
        res["alasan"] = "%s (butuh %s, ada %s)" % (
            ALASAN_KAS_KURANG, total, cash.saldo_laci(db))
        res["alokasi"] = hit
        return res
    out = terapkan(db, periode, laba_bersih, kas_period_id=kas_period_id, oleh=oleh)
    res["dibentuk"] = bool(out.get("created"))
    res["alasan"] = None if out.get("created") else "Sudah pernah terbentuk"
    res["alokasi"] = out.get("alokasi") or hit
    res["distribution"] = out.get("distribution")
    res["cash_out"] = out.get("cash_out") or ZERO
    res["hak_kas_aset"] = (res["alokasi"] or {}).get("kas_aset", ZERO)
    return res


def alokasi_dari(row) -> dict:
    """Bentuk dict alokasi dari baris Distribution (untuk response API)."""
    if row is None:
        return hitung(ZERO)
    return {"eligible": True, "alasan": None,
            "laba_bersih": to_decimal(row.laba_bersih),
            "karyawan": to_decimal(row.bonus_karyawan),
            "pengelola": to_decimal(row.pengelola),
            "investor": to_decimal(row.investor),
            "kas_aset": to_decimal(row.hak_kas_aset),
            "cash_out": to_decimal(row.cash_out),
            "total": quantize(to_decimal(row.bonus_karyawan) + to_decimal(row.pengelola)
                              + to_decimal(row.investor) + to_decimal(row.hak_kas_aset))}


def ringkasan(db: Session, periode: str, kas_period_id=None) -> dict:
    """Status distribusi satu KAS PERIOD (read-only untuk response API).

    P2-15 B-1: `kas_period_id` diteruskan supaya Kas Period kedua pada tanggal
    yang sama membaca baris distributinya sendiri, bukan baris milik periode
    sebelumnya. Label yang ditampilkan tetap tanggal murni (`2026-10-06`).
    """
    row = sudah_ada(db, periode, kas_period_id)
    if row is None:
        return {"terbentuk": False, "periode": periode,
                "alokasi": hitung(ZERO), "trigger": "CTO tercapai",
                "rasio": ["10%", "30%", "30%", "30%"],
                "hak_kas_aset_posisi": "Sudah dipindahkan ke Saldo Aset",
                "master_kas_setelah": str(cash.master_kas(db))}
    al = alokasi_dari(row)
    return {"terbentuk": True, "periode": label_periode(row.periode),
            "periode_key": row.periode, "alokasi": al,
            "created_at": row.created_at, "oleh": row.oleh,
            "trigger": "CTO tercapai", "rasio": ["10%", "30%", "30%", "30%"],
            # Porsi Hak Kas Aset sudah berpindah Laci -> Saldo Aset.
            "hak_kas_aset": str(to_decimal(row.hak_kas_aset)),
            "hak_kas_aset_posisi": "Sudah dipindahkan ke Saldo Aset",
            "catatan": "30% Hak Kas Aset adalah alokasi; posisinya tetap di Laci sampai transfer fisik.",
            "master_kas_setelah": str(cash.master_kas(db))}