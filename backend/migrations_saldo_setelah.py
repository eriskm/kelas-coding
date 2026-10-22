"""Hitung ulang rantai `saldo_setelah` pada `kas_entries`.

Kenapa perlu migrasi:

`saldo_setelah` adalah saldo BERJALAN yang disimpan saat entri dibuat. Nilai
itu bisa basi kalau ada entri yang dihapus setelahnya, atau kalau entri dibuat
di tengah satu request sehingga urutannya tidak sama dengan urutan waktu.

Bukti di produksi (2026-10-19): 8 entri lama (id 3-10, periode 2026-10-15)
menyimpan angka 500.000 lebih rendah dari running sum sebenarnya. Entri #1
(DP 500.000) dibuat saat server sedang jalan dengan kode setengah jadi -
versi itu membuat entri DP tapi belum ikut menghitungnya dalam saldo.

Yang TIDAK rusak: saldo yang dipakai menghitung uang (`cash.saldo_layer`)
selalu dihitung ulang dari kolom `nominal`. Yang rusak cuma tampilan kolom
Saldo di Jurnal Kas.

NON-DESTRUKTIF: hanya mengisi kolom `saldo_setelah` yang sudah ada. Tidak
menambah/menghapus baris, tidak mengubah `nominal`, `jenis`, atau `tanggal`.
IDEMPOTEN: kalau semua nilai sudah cocok, tidak ada yang ditulis.
"""
from __future__ import annotations

from sqlalchemy import inspect


def _cols(engine, table="kas_entries"):
    insp = inspect(engine)
    if table not in insp.get_table_names():
        return None
    return {c["name"] for c in insp.get_columns(table)}


def migrate_saldo_setelah(engine) -> dict:
    """Samakan `saldo_setelah` dengan running sum sebenarnya."""
    report = {"changed": [], "skipped": []}
    existing = _cols(engine)
    if existing is None:
        report["skipped"].append("kas_entries: tabel tidak ada")
        return report
    if "saldo_setelah" not in existing:
        report["skipped"].append("kas_entries.saldo_setelah: kolom tidak ada")
        return report

    # Pakai helper cash.py supaya perhitungannya PUNYA SATU sumber -
    # tidak boleh ada versi kedua yang bisa berbeda.
    import cash
    from database import SessionLocal

    s = SessionLocal()
    try:
        diubah = cash.recompute_saldo_setelah(s)
        s.commit()
        if diubah:
            report["changed"].append("kas_entries.saldo_setelah: %d baris"
                                     " disesuaikan" % diubah)
        else:
            report["skipped"].append("kas_entries.saldo_setelah: sudah cocok")
    except Exception as exc:  # noqa: BLE001
        s.rollback()
        report["skipped"].append("kas_entries.saldo_setelah: %s" % exc)
    finally:
        s.close()
    return report
