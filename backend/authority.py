"""Authority matrix — Owner Decision Q12 & Q13.

ADAPT dari authority Project A ke architecture Project B (dependency-based).
BUKAN permission string seperti Project A (Q12: "jangan copy permission string").

Sumber aturan:
- OD-014 / FIX-33: akun TEKNISI tidak boleh mengubah status closing.
- Project A `app.py:2079-2084`: role tanpa authority finance mempertahankan nilai
  angka lama (tidak ditolak, tidak ditimpa).
- Project A `app.py:2786`: pembayaran boleh admin / kasir (permission 'servis').
- Project A `app.py:2051-2551`: master sparepart boleh admin; hapus admin.
- Q13: PENGELOLA = pemilik/pengelola usaha, beneficiary 30% bagi hasil.
  Peran ini read-oriented (monitoring), aksesnya kurang lebih seperti Investor.

Detail granularitas role/dependency adalah implementation detail (ID-11):
role di Project B berupa free-text, sehingga role yang tidak dikenal bersifat
fail-closed untuk semua aksi tulis.
"""
from __future__ import annotations

from fastapi import Depends, HTTPException
from routers.auth import get_authenticated_user

ROLE_ADMIN = "ADMIN"
ROLE_KASIR = "KASIR"
ROLE_TEKNISI = "TEKNISI"
ROLE_PENGELOLA = "PENGELOLA"
ROLE_CUSTOM = "CUSTOM"

# Alias: Project B menyimpan role free-text, jadi dinormalisasi di satu tempat.
ROLE_ALIASES = {
    "SUPERADMIN": ROLE_ADMIN,
    "ADMIN": ROLE_ADMIN,
    "KASIR": ROLE_KASIR,
    "TEKNISI": ROLE_TEKNISI,
    "TEKNIKER": ROLE_TEKNISI,
    "PENGELOLA": ROLE_PENGELOLA,
    "PEMILIK": ROLE_PENGELOLA,
    "INVESTOR": ROLE_PENGELOLA,
    "CUSTOM": ROLE_CUSTOM,
}

# Role yang hanya boleh melihat/monitoring (Q13).
MONITORING_ROLES = frozenset({ROLE_PENGELOLA})

# Status "closing" di Project B. Warranty/claim/refund berada di domain terpisah (P2-09/P2-10).
# P2-15 / Owner Cash Model: CASH ikut menjadi status closing (event realisasi transaksi
# + serah-terima unit), sehingga hanya Admin/Kasir yang boleh mengubah status ke CASH.
CLOSING_STATUSES = frozenset({"CANCEL", "CASH"})

# Kolom angka keuangan pada service order (ADAPT dari app.py:2079-2084).
FINANCE_FIELDS = (
    "final_price",
    "part_cost",
    "modal_jasa",
    "modal_lainnya",
    "estimate",
    "payment",
)


class Action:
    ORDER_CREATE = "ORDER_CREATE"
    ORDER_UPDATE = "ORDER_UPDATE"
    ORDER_UPDATE_FINANCE = "ORDER_UPDATE_FINANCE"
    ORDER_STATUS_CLOSING = "ORDER_STATUS_CLOSING"
    ORDER_HANDOVER = "ORDER_HANDOVER"
    ORDER_DELETE = "ORDER_DELETE"
    PAYMENT_CREATE = "PAYMENT_CREATE"
    PAYMENT_CANCEL = "PAYMENT_CANCEL"
    EXPENSE_WRITE = "EXPENSE_WRITE"
    EXPENSE_DEBT_WRITE = "EXPENSE_DEBT_WRITE"
    KAS_ENTRY_WRITE = "KAS_ENTRY_WRITE"
    KAS_CLOSE = "KAS_CLOSE"
    KAS_ASET_INJEKSI = "KAS_ASET_INJEKSI"
    REFUND_DP = "REFUND_DP"
    REFUND_GARANSI = "REFUND_GARANSI"
    FAILED_CANCEL = "FAILED_CANCEL"
    SPAREPART_WRITE = "SPAREPART_WRITE"
    CLAIM_WRITE = "CLAIM_WRITE"
    USER_MANAGE = "USER_MANAGE"


AUTHORITY_MATRIX = {
    #-unit servis
    Action.ORDER_CREATE: {ROLE_ADMIN, ROLE_KASIR, ROLE_TEKNISI},
    Action.ORDER_UPDATE: {ROLE_ADMIN, ROLE_KASIR, ROLE_TEKNISI},
    # angka keuangan: TEKNISI tidak boleh (ADAPT app.py:2079-2084)
    Action.ORDER_UPDATE_FINANCE: {ROLE_ADMIN, ROLE_KASIR},
    # status closing: TEKNISI tidak boleh (OD-014 / FIX-33)
    Action.ORDER_STATUS_CLOSING: {ROLE_ADMIN, ROLE_KASIR},
    Action.ORDER_HANDOVER: {ROLE_ADMIN, ROLE_KASIR, ROLE_TEKNISI},
    Action.ORDER_DELETE: {ROLE_ADMIN},
    # uang
    Action.PAYMENT_CREATE: {ROLE_ADMIN, ROLE_KASIR},
    Action.PAYMENT_CANCEL: {ROLE_ADMIN},
    Action.EXPENSE_WRITE: {ROLE_ADMIN},
    # P2-11: Hutang Beban (Q8/Q18) — Admin; PENGELOLA read-oriented (Q13).
    Action.EXPENSE_DEBT_WRITE: {ROLE_ADMIN},
    Action.KAS_ENTRY_WRITE: {ROLE_ADMIN},
    Action.KAS_CLOSE: {ROLE_ADMIN},
    Action.KAS_ASET_INJEKSI: {ROLE_ADMIN},
    Action.REFUND_DP: {ROLE_ADMIN, ROLE_KASIR},
    Action.REFUND_GARANSI: {ROLE_ADMIN},
    Action.FAILED_CANCEL: {ROLE_ADMIN, ROLE_KASIR},
    # inventaris & klaim
    Action.SPAREPART_WRITE: {ROLE_ADMIN, ROLE_KASIR, ROLE_TEKNISI},
    Action.CLAIM_WRITE: {ROLE_ADMIN, ROLE_KASIR},
    # akun
    Action.USER_MANAGE: {ROLE_ADMIN},
}

DEFAULT_MESSAGES = {
    Action.ORDER_CREATE: "Hanya Admin/Kasir/Teknisi yang boleh menerima unit.",
    Action.ORDER_UPDATE: "Hanya Admin/Kasir/Teknisi yang boleh mengubah unit.",
    Action.ORDER_UPDATE_FINANCE: "Hanya Admin/Kasir yang boleh mengubah angka keuangan unit.",
    Action.ORDER_STATUS_CLOSING: "Akun ini tidak diizinkan mengubah status closing.",
    Action.ORDER_HANDOVER: "Hanya Admin/Kasir/Teknisi yang boleh mencatat pengambilan unit.",
    Action.ORDER_DELETE: "Hanya Admin yang boleh menghapus unit.",
    Action.PAYMENT_CREATE: "Hanya Admin/Kasir yang boleh mencatat pembayaran.",
    Action.PAYMENT_CANCEL: "Hanya Admin yang boleh membatalkan pembayaran.",
    Action.EXPENSE_WRITE: "Hanya Admin yang boleh mengelola beban.",
    Action.EXPENSE_DEBT_WRITE: "Hanya Admin yang boleh memproses atau melunasi Hutang Beban.",
    Action.KAS_ENTRY_WRITE: "Hanya Admin yang boleh menulis jurnal kas.",
    Action.KAS_CLOSE: "Hanya Admin yang boleh menutup periode kas.",
    Action.KAS_ASET_INJEKSI: "Hanya Admin yang boleh menambah dana Kas Aset.",
    Action.REFUND_DP: "Hanya Admin/Kasir yang boleh memproses refund DP.",
    Action.REFUND_GARANSI: "Refund klaim garansi adalah keputusan Admin.",
    Action.FAILED_CANCEL: "Hanya Admin/Kasir yang boleh membatalkan unit.",
    Action.SPAREPART_WRITE: "Hanya Admin/Kasir/Teknisi yang boleh mengelola sparepart.",
    Action.CLAIM_WRITE: "Hanya Admin/Kasir yang boleh mengelola klaim garansi.",
    Action.USER_MANAGE: "Hanya Admin yang boleh mengelola akun.",
}


def canonical_role(user) -> str:
    raw = (getattr(user, "role", "") or "").strip().upper()
    return ROLE_ALIASES.get(raw, ROLE_CUSTOM)


def is_monitoring(user) -> bool:
    """Role read-oriented (Q13): hanya melihat dan monitoring."""
    return canonical_role(user) in MONITORING_ROLES


def can(user, action: str) -> bool:
    allowed = AUTHORITY_MATRIX.get(action)
    if allowed is None:
        return False
    if is_monitoring(user):
        return False
    return canonical_role(user) in allowed


def allowed_roles(action: str) -> set:
    return set(AUTHORITY_MATRIX.get(action, set()))


def is_closing_status(status: str) -> bool:
    return (status or "").strip().upper() in CLOSING_STATUSES


def check(user, action: str, message: str = None) -> None:
    """Angkat 403 bila role tidak berwenang."""
    if not can(user, action):
        raise HTTPException(status_code=403, detail=message or DEFAULT_MESSAGES.get(
            action, "Aksi ini tidak diizinkan untuk akun Anda."))


def require_authority(action: str, message: str = None):
    """Dependency factory: `user = Depends(require_authority(Action.X))`."""

    def _dep(user=Depends(get_authenticated_user)):
        check(user, action, message)
        return user

    _dep.__name__ = "require_%s" % action.lower()
    return _dep


def sanitize_finance_payload(user, payload: dict, current) -> tuple:
    """Role tanpa authority finance: pertahankan nilai lama (app.py:2079-2084).

    Mengembalikan (payload, daftar field yang diabaikan).
    """
    if can(user, Action.ORDER_UPDATE_FINANCE):
        return payload, []
    ignored = [f for f in FINANCE_FIELDS if f in payload]
    for field in ignored:
        payload[field] = getattr(current, field, None)
    return payload, ignored
