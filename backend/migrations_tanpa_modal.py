"""Migrasi flag `tanpa_modal` pada tabel `service_orders`.

Owner menetapkan aturan: unit CASH yang Modalnya belum diisi BELUM masuk
Omzet/Transaksi. Implementasi pertama menyaring SEMUA unit modal-0 dari kohort
Omzet -- benar untuk kasus "lupa mengisi modal", tapi juga menjerat unit yang
memang SENGAJA tanpa modal (mis. servis hanya software, tanpa ganti part).
Unit seperti itu tidak akan pernah masuk Omzet.

Flag ini memisahkan keduanya:
    tanpa_modal = 0  -> modal kosong dianggap belum lengkap (peringatan keras)
    tanpa_modal = 1  -> Owner menyatakan unit ini memang tanpa modal

Kolom ini hanya pengakuan, bukan angka: tetap TIDAK menambah Omzet maupun Modal.
Bedanya cuma pengakuan administratif: unit yang ditandai tetap dihitung
sebagai transaksi, sedangkan yang tidak ditandai tidak.

NON-DESTRUKTIF:
- hanya menambah kolom yang belum ada;
- TIDAK mengubah/menghapus baris `service_orders` yang sudah ada;
- default 0, jadi seluruh data lama dianggap "belum diisi modal" -- AMAN,
  karena itu status yang lebih konservatif (tidak ikut dihitung) dan cocok dengan
  perlakuan sebelum flag ini ada.

IDEMPOTEN: aman dipanggil berulang (dijalankan saat startup backend).
"""
from __future__ import annotations

from sqlalchemy import inspect, text

COLUMNS = (
    ("tanpa_modal", "BOOLEAN NOT NULL DEFAULT %s"),  # literal diisi per-dialek
)


def _bool_literal(engine, value: bool) -> str:
    """SQLite menerima 0/1, PostgreSQL menuntut true/false.

    Tanpa ini `ADD COLUMN ... BOOLEAN DEFAULT 0` gagal di PostgreSQL dengan
    DatatypeMismatch, kolom tidak pernah terbentuk, dan seluruh query yang
    memakainya jadi 500.
    """
    if engine.dialect.name == "postgresql":
        return "true" if value else "false"
    return "1" if value else "0"


def _cols(engine, table="service_orders"):
    insp = inspect(engine)
    if table not in insp.get_table_names():
        return None
    return {c["name"] for c in insp.get_columns(table)}


def migrate_service_orders_tanpa_modal(engine) -> dict:
    """Tambah `service_orders.tanpa_modal` bila belum ada."""
    report = {"changed": [], "skipped": []}
    existing = _cols(engine)
    if existing is None:
        report["skipped"].append("service_orders: tabel tidak ada")
        return report
    with engine.begin() as conn:
        for name, sql_type in COLUMNS:
            if name in existing:
                report["skipped"].append("service_orders.%s: sudah ada" % name)
                continue
            ddl = sql_type % _bool_literal(engine, False)
            conn.execute(text('ALTER TABLE "service_orders" ADD COLUMN "%s" %s'
                              % (name, ddl)))
            report["changed"].append("service_orders.%s %s" % (name, ddl))
    return report