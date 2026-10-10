"""P2-06 — Migrasi layer Kas (SSOT-7: Laci != Kas Aset).

NON-DESTRUKTIF: hanya menambah kolom yang belum ada pada `kas_entries`.
Baris lama otomatis berarti layer `LACI` (Kas Perputaran) — sama dengan
perilaku Buku Kas B sebelum P2-06. IDEMPOTEN: aman dipanggil berulang.
"""
from __future__ import annotations

from sqlalchemy import inspect, text

MONEY = "NUMERIC(18,2)"

COLUMNS = (
    ("layer", "VARCHAR(20)", "LACI"),
    ("saldo_setelah", MONEY, None),
    # P2-15 / Cash Model v4
    ("sumber", "VARCHAR(30)", "MANUAL"),
    ("oleh", "VARCHAR(120)", None),
    ("ref_type", "VARCHAR(30)", None),
    ("ref_id", "INTEGER", None),
)


def _cols(engine, table="kas_entries"):
    insp = inspect(engine)
    if table not in insp.get_table_names():
        return None
    return {c["name"] for c in insp.get_columns(table)}


def _pg_type(engine):
    try:
        rows = engine.connect().execute(text("SELECT version()")).first()
        return "postgres" in str(rows[0]).lower()
    except Exception:  # noqa: BLE001
        return False


def migrate_cash_layers(engine) -> dict:
    """Pisahkan layer kas_entries menjadi LACI / KAS_ASET. Aman dipanggil berulang."""
    report = {"changed": [], "skipped": []}
    existing = _cols(engine)
    if existing is None:
        report["skipped"].append("kas_entries: tabel tidak ada")
        return report

    with engine.begin() as conn:
        for name, sql_type, default in COLUMNS:
            if name in existing:
                report["skipped"].append("kas_entries.%s: sudah ada" % name)
                continue
            ddl = 'ALTER TABLE "kas_entries" ADD COLUMN "%s" %s' % (name, sql_type)
            if default is not None and _pg_type(engine):
                ddl += " DEFAULT '%s' NOT NULL" % default
            conn.execute(text(ddl))
            report["changed"].append("kas_entries.%s %s" % (name, sql_type))

        # Backfill Safety-net: baris lama (NULL/'') = Laci, sesuai semantik lama.
        conn.execute(text(
            "UPDATE \"kas_entries\" SET \"layer\" = 'LACI' "
            "WHERE \"layer\" IS NULL OR TRIM(\"layer\") = ''"))

    # Index untuk query saldo per layer (abaikan bila sudah ada / non-sqlite).
    try:
        with engine.begin() as conn:
            conn.execute(text('CREATE INDEX IF NOT EXISTS "ix_kas_entries_layer" '
                              'ON "kas_entries" ("layer")'))
        report["changed"].append("index ix_kas_entries_layer")
    except Exception as exc:  # noqa: BLE001
        report["skipped"].append("index layer dilewati: %s" % exc)

    return report