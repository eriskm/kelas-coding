"""P2-02 — Migrasi presisi uang (Owner Rule Q10).

Karakteristik:
- NON-DESTRUKTIF: tidak menghapus baris, tidak mengubah kolom lain.
- IDEMPOTEN: SQLite membulatkan nilai menjadi skala 2 desimal (menjalankan
  berulang aman); PostgreSQL hanya mengubah tipe bila belum NUMERIC(18,2).
- HISTORIS DIPERTAHANKAN: nilai dibulatkan, bukan diganti/dibuang.
- DITJALANKAN pada start-up aplikasi seperti migrasi schema B yang sudah ada.
"""
from __future__ import annotations

from sqlalchemy import inspect, text

MONEY_COLUMNS = {
    "service_orders": ["estimate", "payment", "final_price", "part_cost",
                       "modal_jasa", "modal_lainnya", "laba_bersih"],
    "payments": ["amount"],
    "expenses": ["nilai"],
    "warranty_claims": ["customer_cost", "internal_cost"],
    "spareparts": ["harga_beli", "harga_jual"],
    "kas_entries": ["nominal"],
}

PG_TARGET = "NUMERIC(18,2)"


def _existing(engine, table):
    insp = inspect(engine)
    if table not in insp.get_table_names():
        return {}
    return {c["name"]: c for c in insp.get_columns(table)}


def _sqlite_round(conn, table, column) -> int:
    """SQLite bertipe dinamis: bulatkan nilai (profil NUMERIC dijaga SQLAlchemy)."""
    res = conn.execute(text(
        'UPDATE "%s" SET "%s" = ROUND("%s", 2) WHERE "%s" IS NOT NULL' % (
            table, column, column, column)))
    return int(res.rowcount or 0)


def _postgres_convert(conn, table, column, current_type: str) -> str:
    target = PG_TARGET
    if current_type and target in str(current_type).upper():
        return "sudah numeric"
    conn.execute(text(
        'ALTER TABLE "%s" ALTER COLUMN "%s" TYPE %s '
        'USING ROUND("%s"::numeric, 2)' % (table, column, target, column)))
    return "diubah ke %s" % target


def migrate_money_precision(engine) -> dict:
    """Jalankan migrasi presisi uang. Aman dipanggil berulang."""
    dialect = engine.dialect.name
    report = {"dialect": dialect, "changed": [], "skipped": [], "rounded_rows": 0}
    with engine.begin() as conn:
        for table, columns in MONEY_COLUMNS.items():
            existing = _existing(engine, table)
            if not existing:
                report["skipped"].append("%s: tabel tidak ada" % table)
                continue
            for column in columns:
                if column not in existing:
                    report["skipped"].append("%s.%s: kolom tidak ada" % (table, column))
                    continue
                if dialect == "postgresql":
                    res = _postgres_convert(conn, table, column,
                                            str(existing[column].get("type")))
                    report["changed"].append("%s.%s -> %s" % (table, column, res))
                elif dialect == "sqlite":
                    n = _sqlite_round(conn, table, column)
                    report["rounded_rows"] += n
                    report["changed"].append(
                        "%s.%s -> skala 2 desimal (%d baris dirapikan)" % (table, column, n))
                else:
                    report["skipped"].append("%s.%s: dialect tidak didukung" % (table, column))
    return report