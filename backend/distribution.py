# -*- coding: utf-8 -*-
"""P2-07 — Distribusi Laba Bersih 10% / 30% / 30% / 30% (Financial SSOT-6).

SSOT-6:
    10% Bonus Karyawan | 30% Pengelola | 30% Investor | 30% Hak Kas Aset
    70% = cash-out        30% = Hak Kas Aset
    TRIGGER = Tutup Kas periode  (BUKAN CTO)

Aturan implementasi (ID-01/ID-14, bukan business rule baru):
- Dasar pembagian = LABA BERSIH dari financial core P2-05.
- Pembagian hanya bila Laba Bersih > 0. Bila Laba Bersih <= 0 tidak ada
  distribusi (deficit Beban siguen SSOT-8: Kas Aset cover + Hutang Beban —
  mekanisme hutang adalah tahap P2-11, TIDAK dibuat di sini).
- Sisa pembulatan Placement di Hak Kas Aset supaya total selalu tepat 100%.
- Satu baris `Distribution` per periode kas (idempotent, replay-safe).
- 30% Hak Kas Aset dicatat sebagai mutasi Kas Aset (layer KAS_ASET, P2-06).
- 70% cash-out dicatat sebagai jurnaldistribution; pengeluaran kas nyatanya
  dieksekusi pada tahap Tutup Kas (P2-08), bukan mengurangi saldo Laci di sini.
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
    """Bentuk distribusi untuk satu KAS PERIOD (dipanggil saat Tutup Kas).

    IDEMPOTENT per Kas Period: bila Kas Period ini sudah punya Distribution,
    baris lama dikembalikan tanpa menulis ulang (tidak ada dobel cash-out).
    Kas Period lain pada tanggal yang sama tetap mendapat barisnya sendiri.
    Tidak memaksa commit; pemanggil (router) yang memutuskan transaksi.
    """
    existing = sudah_ada(db, periode, kas_period_id)
    if existing is not None:
        return {"created": False, "distribution": existing,
                "alokasi": alokasi_dari(existing), "kas_aset_mutation": None,
                "periode": label_periode(existing.periode),
                "periode_key": existing.periode}

    hit = hitung(laba_bersih)
    if not hit["eligible"]:
        if commit:
            db.commit()
        return {"created": False, "distribution": None, "alokasi": hit,
                "kas_aset_mutation": None, "periode": periode,
                "periode_key": periode}

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

    # Owner Cash Model v4 #4: 30% Hak Kas Aset adalah ALOKASI, bukan uang baru.
    # Tidak ada mutasi posisi kas: posisinya tetap di SALDO LACI sampai terjadi
    # transfer fisik Laci -> Aset. Nilai alokasi tetap tersimpan di tabel
    # `distributions.hak_kas_aset` (designation) dan diekspos di ringkasan.
    mutasi = None

    journal.record(
        db, journal.DOMAIN_FINANCE, EVENT_DISTRIBUSI,
        entity_type="distribution", entity_id=row.id,
        amount=hit["laba_bersih"], actor=oleh,
        ref_type="periode", ref_code=periode,
        details={"laba_bersih": str(hit["laba_bersih"]),
                 "karyawan": str(hit["karyawan"]), "pengelola": str(hit["pengelola"]),
                 "investor": str(hit["investor"]), "kas_aset": str(hit["kas_aset"]),
                 "cash_out": str(hit["cash_out"]),
                 "rasio": ["10%", "30%", "30%", "30%"]})

    if commit:
        db.commit()
    else:
        db.flush()
    db.refresh(row)
    return {"created": True, "distribution": row, "alokasi": hit,
            "kas_aset_mutation": mutasi, "periode": label_periode(row.periode),
            "periode_key": row.periode}


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
                "alokasi": hitung(ZERO), "trigger": "Tutup Kas",
                "rasio": ["10%", "30%", "30%", "30%"],
                "hak_kas_aset_posisi": "LACI (alokasi; belum transfer)",
                "master_kas_setelah": str(cash.master_kas(db))}
    al = alokasi_dari(row)
    return {"terbentuk": True, "periode": label_periode(row.periode),
            "periode_key": row.periode, "alokasi": al,
            "created_at": row.created_at, "oleh": row.oleh,
            "trigger": "Tutup Kas", "rasio": ["10%", "30%", "30%", "30%"],
            # v4 #4: designation — belum menjadi uang di posisi Aset.
            "hak_kas_aset": str(to_decimal(row.hak_kas_aset)),
            "hak_kas_aset_posisi": "LACI (alokasi; belum transfer)",
            "catatan": "30% Hak Kas Aset adalah alokasi; posisinya tetap di Laci sampai transfer fisik.",
            "master_kas_setelah": str(cash.master_kas(db))}