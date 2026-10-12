# -*- coding: utf-8 -*-
"""P2-08 — Orkestrasi Tutup Kas (OD-013, SSOT-1/6/7, Q7, Q14).

Tanggung jawab modul ini (TANPA redesign Buku Kas):
- (a) periode tetap 16:00 → 16:00;
- (b) Laba Bersih authoritative dari financial core (P2-05);
- (c) distribusi formed saat Tutup Kas (P2-07), idempotent per periode;
- (d) eksekusi cash-out 70% dari Laci sebagai SATU entri kas (bukan dobel);
- (e) Laci disetel ke uang fisik bila Admin Declare hitungan fisik
    (penyesuaian lewat entri 'Saldo Awal' yang sudah ada di Buku Kas B);
- (f) Kas Aset TIDAK pernah di-reset (SSOT-7);
- (g) satu transaksi: TIDAK ada commit di dalam modul; pemanggil (router) yang
    commit/rollback → kegagalan di tengah tidak meninggalkan data setengah jadi.

Yang SENGAJA tidak ada di sini: Hutang Beban carry-forward (P2-11), arsip/hard
delete (Q14 — periode closed tetap tersimpan & dibaca lewat filter presentasi).
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

import cash
import distribution as distribution_mod
import notifications as notif_mod
import journal
from money import ZERO, quantize, to_decimal
from routers.dashboard import batas_periode

KATEGORI_CASH_OUT = "Distribusi Laba"
MARKER_CASH_OUT = "Cash-out distribusi 70%%"

EVENT_CASH_OUT = "DISTRIBUSI_CASH_OUT"


def next_period_bounds(now: datetime, period_hour: int = 16) -> tuple:
    """Periode berikutnya: mulai `now`, berakhir 16:00 berikutnya (Q7/SSOT-1)."""
    end = now.replace(hour=period_hour, minute=0, second=0, microsecond=0)
    if end <= now:
        end += timedelta(days=1)
    return now, end


def _entry_id(entry):
    """Ambil `id` dari hasil mutasi yang bisa berupa dict atau objek ORM.

    P2-15 B-1: `catat_cash_out()` mengembalikan dict saat mutasi baru dibuat,
    tetapi mengembalikan baris `KasEntry` saat cash-out sudah pernah dieksekusi
    (jalur idempoten). Memanggil `.get()` pada objek ORM memicu AttributeError.
    """
    if entry is None:
        return None
    if isinstance(entry, dict):
        return entry.get("id")
    return getattr(entry, "id", None)


def catat_cash_out(db: Session, dist_row, oleh: str = None):
    """Eksekusi 70% cash-out sebagai pengurang SALDO LACI (v4 #4). Idempotent.

    Mengembalikan {'created', 'nominal', 'entry'} agar bentuknya stabil.
    """
    if dist_row is None:
        return {"created": False, "nominal": ZERO, "entry": None}
    if dist_row.cash_out_entry_id:
        from models import KasEntry
        row = db.query(KasEntry).filter(KasEntry.id == dist_row.cash_out_entry_id).first()
        return {"created": False, "entry": row,
                "nominal": to_decimal(getattr(row, "nominal", 0))}

    nominal = quantize(to_decimal(dist_row.cash_out))
    if nominal <= ZERO:
        return {"created": False, "nominal": ZERO, "entry": None}

    entry = cash.catat_cash_out(
        db, nominal, "%s periode %s" % (MARKER_CASH_OUT, dist_row.periode),
        ref_type="distribusi", ref_id=dist_row.id, actor=oleh)
    dist_row.cash_out_entry_id = entry["id"]
    journal.record(
        db, journal.DOMAIN_FINANCE, EVENT_CASH_OUT,
        entity_type="kas_entry", entity_id=entry["id"], amount=entry["nominal"],
        actor=oleh, ref_type="distribusi", ref_code=str(dist_row.id),
        details={"porsi": "70%", "periode": dist_row.periode,
                 "sumber": entry["sumber"], "layer": entry["layer"]})
    db.flush()
    return {"created": True, "nominal": entry["nominal"], "entry": entry}


def rekonsiliasi_periode(db: Session, dist_row, cash_counted, oleh: str = None):
    """Rekonsiliasi Laci vs hitungan fisik (v4 #7).

    `cash_counted` TIDAK menyuntik opening. Selisih dicatat sebagai **penyesuaian
    Laci eksplisit** + journal.
    """
    return cash.rekonsiliasi_laci(
        db, cash_counted, actor=oleh,
        ref_type="periode", ref_id=(dist_row.periode if dist_row is not None else None))


def tutup_periode(db: Session, period, counted=None, oleh: str = None,
                  compute_finance=None, period_hour: int = 16):
    """Tutup satu periode kas. TANPA commit — pemanggil yang melakukan transaksi.

    Urutan (semua dalam satu transaksi):
      1. Laba Bersih authoritative (financial core P2-05).
      2. Distribusi TIDAK lagi dibentuk di sini — sudah terjadi otomatis saat
         CTO tercapai (`distribution.pastikan_otomatis`). Kalau ternyata belum
         terbentuk (mis. order masih di bawah CTO), baris lama dikembalikan apa
         adanya karena `terapkan` bersifat idempoten.
      3. Set Laci = uang fisik bila ada Declare (idempotent per periode).
      4. Snapshot periode (TIDAK menghapus apa pun — Q14).
      5. Tutup periode & buka periode baru 16:00 → 16:00.
    """
    from models import KasPeriod

    if (period.status or "").strip().upper() == "CLOSED":
        raise PeriodAlreadyClosed(period)

    fin = compute_finance(db, *batas_periode(period))
    periode_key = period.start_at.date().isoformat()

# Distribusi TIDAK lagi dibentuk di sini. Ia terjadi OTOMATIS saat CTO tercapai,
    # dipanggil dari setiap event CASH / jurnal kas (`distribution.pastikan_otomatis`),
    # jadi di saat Tutup Kas cukup membaca apa yang sudah terbentuk.
    #
    # Memanggil `pastikan_otomatis` di sini sebelumnya berarti Tutup Kas bisa
    # menggerakkan uang (cash-out + pindah ke Aset) TEPAT pada saat penutupan,
    # SETELAH `counted` dicatat -- sehingga Selisih yang dilaporkan menjadi
    # palsu karena Laci ikut berkurang. Karena itu yang dipanggil hanya
    # pembacaan data, bukan gerbang pembentukan.
    dist_row = distribution_mod.sudah_ada(db, periode_key, kas_period_id=period.id)
    dist = {
        "created": False,
        "dibentuk": False,
        "distribution": dist_row,
        "alokasi": (distribution_mod.alokasi_dari(dist_row) if dist_row is not None
                    else distribution_mod.hitung(fin.get("laba_bersih", 0))),
        "trigger": "CTO tercapai",
        "alasan": (None if dist_row is not None
                   else "Belum ada distribusi di periode ini"),
        "periode": (dist_row.periode if dist_row is not None else periode_key),
    }

    laci_adjust = rekonsiliasi_periode(db, dist_row, counted, oleh=oleh)

    # P2-15 B-2: "Selisih Laci" memakai basis LEDGER (uang fisik vs Saldo Laci),
    # sama persis dengan selisih yang benar-benar dicatat sebagai penyesuaian.
    # Sebelumnya memakai `fin["saldo"]` (akrual Buku Kas) sehingga angkanya
    # berbeda jauh dan menyesatkan di snapshot/UI.
    selisih = (laci_adjust.get("selisih") if counted is not None else None)

    snapshot = {
        "period": {"id": period.id, "start_at": period.start_at.isoformat(),
                   "end_at": period.end_at.isoformat()},
        "finance": fin,
        "cash_counted": counted,
        "selisih": (None if selisih is None else str(selisih)),
        "selisih_basis": "LEDGER LACI (counted vs Saldo Laci)",
        "distribusi": {
            "terbentuk": bool(dist.get("created")),
            "sudah_ada": not bool(dist.get("created")),
            "periode": dist.get("periode") or periode_key,
            "periode_key": (dist_row.periode if dist_row is not None else periode_key),
            # Distribusi kini terbentuk OTOMATIS saat CTO tercapai, bukan di sini.
            "trigger": dist.get("trigger") or "CTO tercapai",
            "rasio": ["10%", "30%", "30%", "30%"],
            "alokasi": {k: str(v) for k, v in (dist.get("alokasi") or {}).items()},
            "alasan_tidak_terbentuk": dist.get("alasan"),
        },
        # Jejak eksekusi uang (audit, tanpa hard delete).
        "distribusi_uang": {
            "cash_out": str(dist.get("cash_out") or 0),
            "hak_kas_aset": str((dist.get("alokasi") or {}).get("kas_aset", 0)),
            "kas_aset_setelah": str(cash.saldo_kas_aset(db)),
        },
        "rekonsiliasi": {"selisih": (None if laci_adjust.get("selisih") is None
                                    else str(laci_adjust["selisih"])),
                         "penyesuaian": bool(laci_adjust.get("penyesuaian")),
                         "entry_id": ((laci_adjust.get("penyesuaian") or {}).get("id")),
                         "catatan": "cash_counted = hasil hitung fisik; tidak menyuntik opening."},
        "saldo": {
            # v4: Saldo Laci (Kas Aset Kecil), Saldo Aset (Kas Aset Besar), Master Kas.
            "kas_perputaran_laci_awal": str(cash.opening_layer(db, cash.LAYER_LACI)),
            "kas_perputaran_laci": str(cash.saldo_laci(db)),
            "kas_aset": str(cash.saldo_kas_aset(db)),
            "master_kas": str(cash.master_kas(db)),
        },
    }

    now = datetime.now()
    period.status = "CLOSED"
    period.closed_at = now
    period.closed_by = oleh
    # Periode berjalan sampai DITUTUP: end_at diisi waktu penutupan yang
    # sebenarnya, bukan nilai placeholder 16:00 yang bisa sudah basi kalau
    # periode telat ditutup.
    period.end_at = now
    import json

    from money import json_default
    period.snapshot = json.dumps(snapshot, default=json_default)

    new_start, new_end = next_period_bounds(now, period_hour)
    new_period = KasPeriod(start_at=new_start, end_at=new_end, status="OPEN")
    db.add(new_period)
    db.flush()
    db.refresh(new_period)

    # P2-13: laporan tutup kas & buka kas (dalam transaksi yang sama; anti-duplikat).
    _dist_total = ZERO
    try:
        _dist_total = to_decimal((snapshot.get("distribusi") or {}).get("alokasi", {}).get("total", 0))
    except Exception:  # noqa: BLE001
        _dist_total = ZERO
    # Kunci WAJIB "omset" (bukan "omzet"): `notifications.format_pesan` membacanya
    # dengan nama itu. Dulu ditulis "omzet" sehingga Omzet di laporan Tutup Kas
    # selalu keluar Rp 0 padahal snapshot-nya benar.
    notif_mod.kirim(db, notif_mod.EVENT_LAPORAN_TUTUP_KAS, ref_type="periode",
                    ref_code=periode_key,
                    data={"periode": periode_key, "omset": fin.get("omset"),
                          "total_beban": fin.get("total_beban"),
                          "laba_bersih": fin.get("laba_bersih"),
                          "distribusi": _dist_total,
                          "kas_aset": snapshot["saldo"]["kas_aset"]},
                    actor=oleh)
    notif_mod.kirim(db, notif_mod.EVENT_LAPORAN_BUKA_KAS, ref_type="periode",
                    ref_code=new_period.start_at.date().isoformat(),
                    data={"periode": new_period.start_at.date().isoformat(),
                          "distribusi": _dist_total,
                          "kas_aset": snapshot["saldo"]["kas_aset"],
                          "laci": snapshot["saldo"]["kas_perputaran_laci_awal"]},
                    actor=oleh)

    return {"ok": True, "closed_period_id": period.id, "snapshot": snapshot,
            "distribusi": snapshot["distribusi"],
            "distribusi_uang": snapshot["distribusi_uang"],
            "rekonsiliasi": snapshot["rekonsiliasi"],
            "saldo": snapshot["saldo"],
            "new_period": {"id": new_period.id,
                           "start_at": new_period.start_at.isoformat(),
                           "end_at": new_period.end_at.isoformat()}}


class PeriodAlreadyClosed(Exception):
    """Periode sudah ditutup — eksekusi kedua harus ditolak (VR-017)."""

    def __init__(self, period):
        self.period_id = getattr(period, "id", None)
        self.closed_at = getattr(period, "closed_at", None)
        super().__init__("Periode #%s sudah ditutup" % self.period_id)