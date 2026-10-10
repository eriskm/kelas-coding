"""P2-03 — Journal Infrastructure Project B.

Fondasi pencatatan event/mutasi lintas domain. INI HANYA INFRASTRUKTUR:
- tidak memuat business rule apa pun (tidak ada hitungan omzet/laba/distribusi,
  tidak ada status Cash, tidak ada aturan refund/payment workflow);
- tidak menyediakan fungsi update/delete journal (append-only, Q14);
- amount monetary SELALU Decimal/Numeric (P2-02 / Q10);
- pencatatan ikut transaksi pemanggil (caller yang decide commit/rollback),
  sehingga konsisten secara atomic.

Penggunaan domain berikutnya (P2-04 dsb) memanggil `record()` di dalam session
yang sama dengan penulisan datanya.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from models import MONEY, JournalEntry
from money import to_decimal

# Nilai yang belum dikunci oleh Owner. Ini placeholder yang dapat dikembangkan,
# TIDAK daftar final domain.
DOMAIN_SERVICE = "SERVICE"
DOMAIN_PAYMENT = "PAYMENT"
DOMAIN_KAS = "KAS"
DOMAIN_FINANCE = "FINANCE"
DOMAIN_INVENTORY = "INVENTORY"
DOMAIN_WARRANTY = "WARRANTY"
DOMAIN_SYSTEM = "SYSTEM"

SOURCE_API = "API"
SOURCE_SYSTEM = "SYSTEM"
SOURCE_JOB = "JOB"
SOURCE_IMPORT = "IMPORT"

# Konstanta event payment (foundation untuk P2-04; belum dipakai di router).
PAYMENT_CREATED = "PAYMENT_CREATED"
PAYMENT_CANCELLED = "PAYMENT_CANCELLED"
PAYMENT_SETTLED = "PAYMENT_SETTLED"

REQUIRED = ("domain", "event")


class JournalError(ValueError):
    """Field wajib journal tidak terpenuhi."""


def _validate(domain: str, event: str) -> None:
    missing = [name for name, value in (("domain", domain), ("event", event))
               if not (value or "").strip()]
    if missing:
        raise JournalError("journal: field wajib kosong: %s" % ", ".join(missing))


def record(db: Session, domain: str, event: str, entity_type: str = None,
           entity_id: int = None, amount=None, actor: str = None,
           source: str = SOURCE_API, ref_code: str = None,
           details: dict = None, ref_type: str = None) -> JournalEntry:
    """Catat satu event journal (append-only, tanpa commit).

    `amount` boleh None (event non-monetary). Bila diberikan, nilainya
    dinormalisasi ke Decimal agar tidak pernah menjadi float.
    """
    _validate(domain, event)
    entry = JournalEntry(
        domain=(domain or "").strip().upper(),
        event=(event or "").strip().upper(),
        entity_type=(entity_type or None),
        entity_id=(int(entity_id) if entity_id is not None else None),
        ref_type=(ref_type or None),
        ref_code=(ref_code or None),
        amount=(to_decimal(amount) if amount is not None else None),
        actor=(actor or None),
        source=(source or SOURCE_SYSTEM),
        details=(details if isinstance(details, dict) else None),
        ts=datetime.now(),
    )
    db.add(entry)
    return entry


def record_many(db: Session, events) -> list:
    """Catat banyak event dalam satu flush (satu transaksi pemanggil)."""
    entries = []
    for kwargs in events:
        entries.append(record(db, **kwargs))
    if entries:
        db.flush()
    return entries


def by_reference(db: Session, entity_type: str = None, entity_id: int = None,
                 domain: str = None, limit: int = 50) -> list:
    """Baca journal berdasarkan referensi (tanpa mengubah apa pun)."""
    q = db.query(JournalEntry)
    if entity_type:
        q = q.filter(JournalEntry.entity_type == entity_type)
    if entity_id is not None:
        q = q.filter(JournalEntry.entity_id == int(entity_id))
    if domain:
        q = q.filter(JournalEntry.domain == domain.strip().upper())
    return q.order_by(JournalEntry.id.desc()).limit(limit).all()


def recent(db: Session, limit: int = 50, domain: str = None) -> list:
    return by_reference(db, domain=domain, limit=limit)


# Catatan arsitektur sengaja:
# - Tidak ada `update_journal()` / `delete_journal()` di modul ini (Q14:
#   historical record tidak boleh hard delete).
# - `JournalEntry` sengaja TIDAK memakai ForeignKey ke tabel domain: jurnal
#   harus tetap utuh walau record sumber berubah/diarsipkan, dan tidak ada
#   risiko cascade delete.
# - Dedupe/replay: jurnal membolehkan event identik berulang (append-only).
#   Kennethalan idempotensi adalah tanggung jawab domain, bukan infrastruktur.