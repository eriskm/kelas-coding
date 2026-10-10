"""Aturan status BOSS SF (FINAL DECISION LOCK) — satu sumber kebenaran.

Owner Cash Model (P2-15): terminology & alur mengikuti Project A.

Tiga dimensi terpisah:
- Status Servis  : DITERIMA ANALISA KONFIRMASI WAIT PART REPAIR DONE CASH
                   CANCEL FAILED
                   (label UI mengikuti Project A; CASH = event realisasi
                   transaksi + serah-terima unit)
- Status Bayar   : BELUM LUNAS / LUNAS (DERIVE dari payments, tidak disimpan)
- Status Unit    : DI TOKO / DIAMBIL (+ taken_at)
"""
from money import ZERO, to_decimal
from datetime import datetime, date

#: Status servis kanonis. `CASH` = event realisasi (transaction realization),
#: bukan bypass LUNAS: LUNAS tetap diturunkan dari Payment Ledger.
SERVICE_STATUSES = [
    "DITERIMA",
    "ANALISA",
    "KONFIRMASI",
    "WAIT PART",
    "REPAIR",
    "DONE",
    "CASH",
    "CANCEL",
    "FAILED",
]

#: Status yang menutup unit. DONE = pekerjaan selesai; CASH = transaksi terealisasi.
TERMINAL_STATUSES = ["CASH", "FAILED", "CANCEL"]

#: Status yang menutup pekerjaan tapi BELUM merealisasikan transaksi (bukan Cash).
WORK_DONE_STATUSES = ["DONE"]

SERVICE_TRANSITIONS = {
    "DITERIMA": ["ANALISA"],
    "ANALISA": ["KONFIRMASI"],
    "KONFIRMASI": ["WAIT PART", "REPAIR", "CANCEL"],
    "WAIT PART": ["REPAIR", "FAILED"],
    "REPAIR": ["DONE", "FAILED"],
    "DONE": ["CASH"],
    "CASH": [],
    "FAILED": [],
    "CANCEL": [],
}

#: Label status untuk UI (mengikuti Project A).
STATUS_LABELS = {
    "DITERIMA": "Diterima",
    "ANALISA": "Analisa",
    "KONFIRMASI": "Konfirmasi",
    "WAIT PART": "Wait Part",
    "REPAIR": "Repair",
    "DONE": "Done",
    "CASH": "Cash",
    "CANCEL": "Cancel",
    "FAILED": "Failed",
}

#: Opsi closing yang hanya boleh diubah oleh role ber-authority closing
#: (Admin/Kasir). Cash punya aturan tambahan: hanya dari DONE.
CLOSING_ONLY_STATUSES = ["CASH", "CANCEL"]

UNIT_STATUSES = ["DI TOKO", "DIAMBIL"]

PAYMENT_KINDS = ["DP", "PELUNASAN"]

# Initial path Servis Baru (kondisi operasional, bukan status bebas).
# target = initial status; chain = histori yang benar-benar terjadi.
# P2-15: target/chain adalah status PEKERJAAN -> selesai di DONE (bukan Cash).
INITIAL_PATHS = {
    "TITIP": {
        "target": "DITERIMA",
        "label": "titip unit",
        "chain": ["DITERIMA"],
    },
    "PERBAIKAN": {
        "target": "REPAIR",
        "label": "masuk perbaikan",
        "chain": ["DITERIMA", "ANALISA", "KONFIRMASI", "REPAIR"],
    },
    "SPAREPART": {
        "target": "WAIT PART",
        "label": "menunggu sparepart",
        "chain": ["DITERIMA", "ANALISA", "KONFIRMASI", "WAIT PART"],
    },
    "TUNGGU": {
        "target": "DONE",
        "label": "servis tunggu",
        "chain": ["DITERIMA", "ANALISA", "KONFIRMASI", "REPAIR", "DONE"],
    },
}


def check_initial_path(path, fields: dict):
    """Validasi guard per initial path. Return (target, chain, error).

    fields: repair_plan, estimate, technician, final_price (None = tak terdefinisi).
    Koreksi APPROVAL: TUNGGU menolak final NULL, mengizinkan 0.
    """
    spec = INITIAL_PATHS.get((path or "").strip().upper())
    if spec is None:
        return None, None, ("Initial path tidak valid. Pilihan: "
                            + ", ".join(INITIAL_PATHS.keys()))
    plan = (fields.get("repair_plan") or "").strip()
    est = fields.get("estimate") or 0
    tech = (fields.get("technician") or "").strip()
    final = fields.get("final_price")
    key = (path or "").strip().upper()
    if key in ("PERBAIKAN", "SPAREPART"):
        missing = []
        if not plan:
            missing.append("Rencana Perbaikan")
        if not (est or 0) > 0:
            missing.append("Estimasi Biaya")
        if not tech:
            missing.append("Teknisi Penanggung Jawab")
        if missing:
            return None, None, ("Path %s wajib melengkapi: %s" % (key, ", ".join(missing)))
    elif key == "TUNGGU":
        missing = []
        if not plan:
            missing.append("Rencana/Tindakan Perbaikan")
        if not tech:
            missing.append("Teknisi Penanggung Jawab")
        if final is None:
            missing.append("Harga Final (wajib terdefinisi, boleh 0)")
        if missing:
            return None, None, ("Path TUNGGU wajib melengkapi: %s" % ", ".join(missing))
    return spec["target"], spec["chain"], ""

# Status legacy → final (FINAL LOCK §12). P2-15: DIAGNOSA dianggap kondisi
# yang sama dengan ANALISA (Owner: "Analisa dan Diagnosa adalah status yang
# dianggap kondisi yg sama"); data legacy tidak dihapus, hanya dipetakan.
LEGACY_STATUS_MAP = {
    "RECEIVED": "DITERIMA",
    "ANALISA": "ANALISA",
    "DIAGNOSIS": "ANALISA",
    "DIAGNOSA": "ANALISA",
    "KONFIRMASI": "KONFIRMASI",
    "WAIT PART": "WAIT PART",
    "WAITING_PART": "WAIT PART",
    "MENUNGGU SPAREPART": "WAIT PART",
    "REPAIR": "REPAIR",
    "PERBAIKAN": "REPAIR",
    "QC": "REPAIR",
    "WAITING_APPROVAL": "KONFIRMASI",
    "DONE": "DONE",
    "COMPLETED": "DONE",
    "READY": "DONE",
    "SELESAI": "DONE",
    "CASH": "CASH",
    "FAILED": "FAILED",
    "GAGAL": "FAILED",
    "FILED": "FAILED",
    "CANCEL": "CANCEL",
    "CANCELLED": "CANCEL",
    "BATAL": "CANCEL",
}


def _num(v):
    """P2-02 / Q10: nilai uang selalu Decimal."""
    return to_decimal(v)


def check_transition(dari, ke, catatan=""):
    """Validasi perpindahan status. Return (ok, pesan_error)."""
    dari = (dari or "").strip()
    ke = (ke or "").strip()
    if ke not in SERVICE_STATUSES:
        return False, "Status tidak valid: %s. Pilihan: %s" % (ke, ", ".join(SERVICE_STATUSES))
    if not dari:
        if ke != "DITERIMA":
            return False, "Status awal harus DITERIMA"
        return True, ""
    if dari not in SERVICE_STATUSES:
        # Status legacy lolos migrasi — izinkan sekali menuju padanannya.
        _mapped = LEGACY_STATUS_MAP.get(dari)
        if _mapped is None or _mapped == dari:
            return False, "Status kini (%s) bukan status valid; koreksi manual diperlukan" % dari
        dari = _mapped
    if dari in TERMINAL_STATUSES:
        if not (catatan or "").strip():
            return False, "Status %s sudah terminal; perubahan wajib menyertakan catatan koreksi" % dari
        return True, ""
    allowed = SERVICE_TRANSITIONS.get(dari, [])
    if ke in allowed:
        return True, ""
    # Lompat mundur/di luar matriks: boleh bila ada catatan (tercatat di histori).
    if (catatan or "").strip():
        return True, ""
    return False, "Transisi %s → %s tidak diizinkan tanpa catatan" % (dari, ke)


def kewajiban(order):
    """Total kewajiban pelanggan: final_price ?? estimate."""
    fp = getattr(order, "final_price", None)
    if fp is not None:
        return _num(fp)
    return _num(getattr(order, "estimate", 0))


def payments_total(pay_rows):
    return sum(_num(getattr(p, "amount", 0)) for p in (pay_rows or []))


def _dp_total(pay_rows):
    """Total baris jurnal ber-kind DP (hold harmless terhadap kolom legacy)."""
    return sum(_num(getattr(p, "amount", 0)) for p in (pay_rows or [])
               if (getattr(p, "kind", "") or "").strip().upper() == "DP")


def payment_summary(order, pay_rows) -> dict:
    """Derive status pembayaran.

    Sumber: jurnal payments + kolom legacy `service_orders.payment` (arsip DP
    era sebelum jurnal). Agar DP yang tercatat di KEDUA tempat (kolom legacy
    + baris jurnal DP dari receive) tidak dihitung ganda, porsi legacy yang
    sudah tercermin di jurnal DP dikurangkan (tidak pernah negatif).
    Perilaku untuk data lama (tanpa baris DP) identik seperti sebelumnya.
    """
    must = kewajiban(order)
    legacy_dp = _num(getattr(order, "payment", 0))
    dp_journal = _dp_total(pay_rows)
    effective_legacy = max(ZERO, legacy_dp - dp_journal)
    paid = effective_legacy + payments_total(pay_rows)
    sisa = max(ZERO, must - paid)
    lunas = bool(must > 0 and paid >= must)
    return {
        "kewajiban": must,
        "total_bayar": paid,
        "sisa": sisa,
        "payment_status": "LUNAS" if lunas else "BELUM LUNAS",
    }


def lock_lunas_moment(order, when=None):
    """Kunci momen LUNAS sekali (pengganti lock cash_*). Return True bila baru dikunci."""
    when = when or datetime.now()
    changed = False
    if getattr(order, "lunas_date", None) is None:
        order.lunas_date = when.date() if isinstance(when, datetime) else when
        changed = True
    if getattr(order, "lunas_at", None) is None:
        order.lunas_at = when if isinstance(when, datetime) else datetime.now()
        changed = True
    return changed


def paid_moment(pay_row):
    """Momen kas sebuah baris pembayaran (untuk scope periode)."""
    ca = getattr(pay_row, "created_at", None)
    if ca is not None:
        return ca
    return None


def lunas_moment(order, pay_rows):
    """Momen order mencapai LUNAS: created_at pembayaran yang melewati ambang.
    Fallback: lunas_at / lunas_date@12:00 / created_at (legacy)."""
    must = kewajiban(order)
    if must > 0:
        rows = sorted([p for p in (pay_rows or []) if getattr(p, "created_at", None)],
                      key=lambda p: p.created_at)
        acc = max(ZERO, _num(getattr(order, "payment", 0)) - _dp_total(rows))
        for p in rows:
            acc += _num(p.amount)
            if acc >= must:
                return p.created_at
    if getattr(order, "lunas_at", None):
        return order.lunas_at
    ld = getattr(order, "lunas_date", None)
    if ld is not None:
        if isinstance(ld, datetime):
            return ld
        if isinstance(ld, date):
            return datetime(ld.year, ld.month, ld.day, 12, 0, 0)
    return getattr(order, "created_at", None)


def order_profit(order, pay_rows):
    """Laba transaksi per-order (Owner Cash Model P2-15).

    Rumus (FINAL LOCK): Omzet − Modal Part − Modal Jasa − Modal Lain-lain

    Sumber field:
      - Omzet           : `final_price` → fallback `estimate` (lewat `kewObligation`/payment_summary)
      - Modal Part      : `service_orders.part_cost`
      - Modal Jasa      : `service_orders.modal_jasa`
      - Modal Lain-lain : `service_orders.modal_lainnya`

    Gate: hanya bila order **CASH** (event realisasi transaksi) DAN LUNAS
    (diturunkan dari Payment Ledger). Selain itu 0 — termasuk unit yang sudah
    LUNAS tapi belum CASH (Owner: Omzet direalisasikan saat CASH).
    """
    try:
        s = payment_summary(order, pay_rows)
    except Exception:
        return ZERO
    if (getattr(order, "status", "") or "") != "CASH":
        return ZERO
    if s.get("payment_status") != "LUNAS":
        return ZERO
    return (to_decimal(s.get("kewajiban", 0))
            - to_decimal(getattr(order, "part_cost", 0))
            - to_decimal(getattr(order, "modal_jasa", 0))
            - to_decimal(getattr(order, "modal_lainnya", 0)))
