"""P2-09 — Migrasi kolom lifecycle klaim pada `warranty_claims`.

NON-DESTRUKTIF: hanya menambah kolom yang belum ada.
IDEMPOTEN: aman dipanggil berulang (dijalankan saat startup backend).
Kolom yang ditambahkan:
- `resolusi`                  : REPAIR | REPLACE | REFUND (P2-09 roadmap d)
- `origin_payment_status`     : snapshot settlement unit asal saat claim dibuat
- `origin_warranty_months`    : snapshot masa garansi unit asal saat claim dibuat
"""
from __future__ import annotations

from sqlalchemy import inspect, text

COLUMNS = (
    ("resolusi", "VARCHAR(20)"),
    ("origin_payment_status", "VARCHAR(20)"),
    ("origin_warranty_months", "INTEGER"),
)


def _cols(engine, table="warranty_claims"):
    insp = inspect(engine)
    if table not in insp.get_table_names():
        return None
    return {c["name"] for c in insp.get_columns(table)}


def migrate_warranty_claims(engine) -> dict:
    report = {"changed": [], "skipped": []}
    existing = _cols(engine)
    if existing is None:
        report["skipped"].append("warranty_claims: tabel tidak ada")
        return report
    with engine.begin() as conn:
        for name, sql_type in COLUMNS:
            if name in existing:
                report["skipped"].append("warranty_claims.%s: sudah ada" % name)
                continue
            conn.execute(text('ALTER TABLE "warranty_claims" ADD COLUMN "%s" %s'
                              % (name, sql_type)))
            report["changed"].append("warranty_claims.%s %s" % (name, sql_type))
    return report