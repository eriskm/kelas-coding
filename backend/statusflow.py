"""Aturan status BOSS SF (FINAL DECISION LOCK) — satu sumber kebenaran.

Tiga dimensi terpisah:
- Status Servis  : DITERIMA ANALISA DIAGNOSA KONFIRMASI MENUNGGU SPAREPART
                   PERBAIKAN SELESAI GAGAL BATAL (Bahasa Indonesia)
- Status Bayar   : BELUM LUNAS / LUNAS (DERIVE dari payments, tidak disimpan)
- Status Unit    : DI TOKO / DIAMBIL (+ taken_at)
"""
from datetime import datetime, date

SERVICE_STATUSES = [
    "DITERIMA",
    "ANALISA",
    "DIAGNOSA",
    "KONFIRMASI",
    "MENUNGGU SPAREPART",
    "PERBAIKAN",
    "SELESAI",
    "GAGAL",
    "BATAL",
]

TERMINAL_STATUSES = ["SELESAI", "GAGAL", "BATAL"]

SERVICE_TRANSITIONS = {
    "DITERIMA": ["ANALISA"],
    "ANALISA": ["DIAGNOSA"],
    "DIAGNOSA": ["KONFIRMASI"],
    "KONFIRMASI": ["MENUNGGU SPAREPART", "PERBAIKAN", "BATAL"],
    "MENUNGGU SPAREPART": ["PERBAIKAN", "GAGAL"],
    "PERBAIKAN": ["SELESAI", "GAGAL"],
    "SELESAI": [],
    "GAGAL": [],
    "BATAL": [],
}

UNIT_STATUSES = ["DI TOKO", "DIAMBIL"]

PAYMENT_KINDS = ["DP", "PELUNASAN"]

# Initial path Servis Baru (kondisi operasional, bukan status bebas).
# target = initial status; chain = histori yang benar-benar terjadi.
INITIAL_PATHS = {
    "TITIP": {
        "target": "DITERIMA",
        "label": "titip unit",
        "chain": ["DITERIMA"],
    },
    "PERBAIKAN": {
        "target": "PERBAIKAN",
        "label": "masuk perbaikan",
        "chain": ["DITERIMA", "ANALISA", "DIAGNOSA", "KONFIRMASI", "PERBAIKAN"],
    },
    "SPAREPART": {
        "target": "MENUNGGU SPAREPART",
        "label": "menunggu sparepart",
        "chain": ["DITERIMA", "ANALISA", "DIAGNOSA", "KONFIRMASI", "MENUNGGU SPAREPART"],
    },
    "TUNGGU": {
        "target": "SELESAI",
        "label": "servis tunggu",
        "chain": ["DITERIMA", "ANALISA", "DIAGNOSA", "KONFIRMASI", "PERBAIKAN", "SELESAI"],
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

# Status legacy → final (FINAL LOCK §12). CASH ditangani khusus (§3.1).
LEGACY_STATUS_MAP = {
    "RECEIVED": "DITERIMA",
    "ANALISA": "ANALISA",
    "DIAGNOSIS": "DIAGNOSA",
    "KONFIRMASI": "KONFIRMASI",
    "WAIT PART": "MENUNGGU SPAREPART",
    "WAITING_PART": "MENUNGGU SPAREPART",
    "REPAIR": "PERBAIKAN",
    "DONE": "SELESAI",
    "COMPLETED": "SELESAI",
    "READY": "SELESAI",
    "QC": "PERBAIKAN",
    "WAITING_APPROVAL": "KONFIRMASI",
    "FAILED": "GAGAL",
    "FILED": "GAGAL",
    "CANCEL": "BATAL",
    "CANCELLED": "BATAL",
}


def _num(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


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


def kewajiban(order) -> float:
    """Total kewajiban pelanggan: final_price ?? estimate."""
    fp = getattr(order, "final_price", None)
    if fp is not None:
        return _num(fp)
    return _num(getattr(order, "estimate", 0))


def payments_total(pay_rows) -> float:
    return sum(_num(getattr(p, "amount", 0)) for p in (pay_rows or []))


def payment_summary(order, pay_rows) -> dict:
    """Derive status pembayaran (single source: jurnal payments + DP legacy)."""
    must = kewajiban(order)
    legacy_dp = _num(getattr(order, "payment", 0))
    paid = legacy_dp + payments_total(pay_rows)
    sisa = max(0.0, must - paid)
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
        acc = _num(getattr(order, "payment", 0))
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
