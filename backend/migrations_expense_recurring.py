"""FIN-MIRROR — Migrasi flag `recurring` pada tabel `expenses`.

Mirror Proyek A (tabel `beban`): beban bersifat PERMANEN — tidak punya dimensi
tanggal, nilai yang sama dipotong dari setiap siklus. Proyek B sebelumnya
membekukan `expenses` hanya ke periode di mana `created_at`-nya jatuh, sehingga
periode tanpa expense menghasilkan `beban = 0` dan `laba_bersih = laba_kotor`
(lalu memicu distribusi 10/30/30/30 dari laba kotor).

NON-DESTRUKTIF:
- hanya menambah kolom yang belum ada;
- TIDAK mengubah/menghapus baris `expenses` yang sudah ada;
- TIDAK menyentuh `expense_periods` (snapshot periode closed tetap utuh).

IDEMPOTEN: aman dipanggil berulang (dijalankan saat startup backend).

DEFAULT BARU = 1 (recurring) supaya SELURUH beban yang sudah ada ikut memakai
semantik Proyek A mulai periode berikutnya. Periode yang SUDAH beku tidak
berubah karena `expense_periods` tetap menjadi SSOT untuk periode tersebut.
"""
from __future__ import annotations

from sqlalchemy import inspect, text

COLUMNS = (
    ("recurring", "BOOLEAN NOT NULL DEFAULT %s"),  # literal diisi per-dialek
)


def _bool_literal(engine, value: bool) -> str:
    """SQLite menerima 0/1, PostgreSQL menuntut true/false.

    Tanpa ini `ADD COLUMN ... BOOLEAN DEFAULT 1` gagal di PostgreSQL dengan
    DatatypeMismatch, kolom tidak pernah terbentuk, dan query mirror beban
    permanen jadi 500.
    """
    if engine.dialect.name == "postgresql":
        return "true" if value else "false"
    return "1" if value else "0"


def _cols(engine, table="expenses"):
    insp = inspect(engine)
    if table not in insp.get_table_names():
        return None
    return {c["name"] for c in insp.get_columns(table)}


def migrate_expense_recurring(engine) -> dict:
    report = {"changed": [], "skipped": []}
    existing = _cols(engine)
    if existing is None:
        report["skipped"].append("expenses: tabel tidak ada")
        return report
    with engine.begin() as conn:
        for name, sql_type in COLUMNS:
            if name in existing:
                report["skipped"].append("expenses.%s: sudah ada" % name)
                continue
            ddl = sql_type % _bool_literal(engine, True)
            conn.execute(text('ALTER TABLE "expenses" ADD COLUMN "%s" %s'
                              % (name, ddl)))
            report["changed"].append("expenses.%s %s" % (name, ddl))
    return report