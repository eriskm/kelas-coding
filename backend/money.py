"""Helper nilai uang (Owner Rule Q10: Numeric/Decimal, bukan Float).

Aturan main:
- Semua konversi masuk lewat `to_decimal()` (berbasis str, TIDAK lewat float).
- `quantize()` membulatkan ke 2 desimal (ROUND_HALF_UP) hanya bila diperlukan.
- `to_number()` adalah SATU-SATUNYA tempat Decimal -> float, dan hanya untuk
  boundary serialisasi API/JSON. Fungsi ini eksplisit (bukan diam-diam).
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

MONEY_PRECISION = 18
MONEY_SCALE = 2
CENTS = Decimal("0.01")
ZERO = Decimal("0")

# Nilai yang sering dipakai sebagai konstanta persentase.
PCT_10 = Decimal("0.10")
PCT_30 = Decimal("0.30")
HUNDRED = Decimal("100")


def to_decimal(value, default: Decimal = ZERO) -> Decimal:
    """Ubah apa pun menjadi Decimal tanpa melewati float."""
    if value is None:
        return default
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise TypeError("nilai boolean tidak valid sebagai nominal")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        # str(float) mewakili nilai yang ditulis pengguna; menghindari repr panjang float.
        return Decimal(str(value))
    try:
        text = str(value).strip()
    except Exception:  # noqa: BLE001
        return default
    if not text:
        return default
    normalized = text.replace(",", ".") if text.count(",") == 1 and "." not in text else text
    try:
        return Decimal(normalized)
    except (InvalidOperation, ValueError):
        return default


def quantize(value: Decimal) -> Decimal:
    """Bulatkan ke skala uang (2 desimal, ROUND_HALF_UP)."""
    return value.quantize(CENTS, rounding=ROUND_HALF_UP)


def money_sum(values, start: Decimal = ZERO) -> Decimal:
    total = start
    for value in values:
        total += to_decimal(value)
    return total


def to_number(value) -> float:
    """Boundary eksplisit Decimal -> JSON number (HANYA untuk serialisasi)."""
    if value is None:
        return None
    return float(to_decimal(value))


def json_default(value):
    """`default=` untuk json.dumps: Decimal -> number, bukan string."""
    if isinstance(value, Decimal):
        return float(value)
    raise TypeError("Tipe tidak serializable: %s" % type(value).__name__)


try:  # Pydantic v2: serialisasi Decimal ke JSON number secara EKSPLISIT.
    from typing import Annotated
    from pydantic import PlainSerializer

    MoneyOut = Annotated[
        Decimal, PlainSerializer(lambda v: to_number(v), return_type=float, when_used="json")]
except Exception:  # pragma: no cover - pydantic tidak tersedia
    MoneyOut = Decimal  # type: ignore


def decimal_type():
    """Return tipe kolom SQLAlchemy untuk nilai uang."""
    from sqlalchemy import Numeric
    return Numeric(MONEY_PRECISION, MONEY_SCALE)