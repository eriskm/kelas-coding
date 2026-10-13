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
    ("tanpa_modal", "BOOLEAN NOT NULL DEFAULT 0"),
)


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
            conn.execute(text('ALTER TABLE "service_orders" ADD COLUMN "%s" %s'
                              % (name, sql_type)))
            report["changed"].append("service_orders.%s %s" % (name, sql_type))
    return report