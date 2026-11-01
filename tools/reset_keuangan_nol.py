"""Reset data transaksi + kas ke NOL, pertahankan akun pengguna dan master data.

Skrip ini menghapus data operasional sehingga operasional toko fisik resmi
dijalankan dari kondisi benar-benar bersih pada Periode #1:

  - service order (Servis Baru / Update Data Servis), pembayaran, refund,
    klaim garansi, riwayat status, pemakaian & penjualan sparepart
  - seluruh jurnal kas layer LACI dan KAS_ASET
  - periode kas tertutup (arsip) -> dibuat ulang SATU periode OPEN (ID: 1)
  - periode beban, hutang beban, distribusi laba, notifikasi, idempotency key, sesi login
  - secara default (--keep-master), data MASTER (Akun Pengguna, Pelanggan,
    Katalog Sparepart + Batches, dan Beban Berulang Toko) DIPERTAHANKAN.

Karena `auth_tokens` ikut dibersihkan, semua pengguna wajib login ulang
setelah reset.

Pemakaian:
    python tools/reset_keuangan_nol.py                  # backup + reset (pertahankan master)
    python tools/reset_keuangan_nol.py --clean-all      # reset total termasuk master
    python tools/reset_keuangan_nol.py --db <path>      # DB lain
    python tools/reset_keuangan_nol.py --no-backup      # tanpa backup
    python tools/reset_keuangan_nol.py --dry-run        # hanya rencana
"""

import argparse
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timedelta

DEFAULT_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "servisku.db")

#: Tabel operasional yang wajib dikosongkan saat reset transaksi
OPERATIONAL_TABLES = (
    "service_order_parts",
    "payments",
    "refunds",
    "warranty_claims",
    "status_history",
    "part_sales",
    "part_sale_items",
    "sparepart_defects",
    "expense_periods",
    "expense_debt_entries",
    "expense_debt_periods",
    "distributions",
    "kas_entries",
    "kas_periods",
    "service_orders",
    "journal_entries",
    "notifications",
    "idempotency_keys",
    "auth_tokens",
)

#: Tabel master yang bisa dipertahankan (--keep-master)
MASTER_TABLES = (
    "customers",
    "spareparts",
    "sparepart_batches",
    "expenses",
)

#: Selalu dijaga
ALWAYS_KEEP = ("users",)


def backup(db_path: str) -> str:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    dst = os.path.join(os.path.dirname(db_path),
                       "backup-preRESET-%s.db" % ts)
    src = sqlite3.connect(db_path)
    out = sqlite3.connect(dst)
    with out:
        src.backup(out)
    out.close()
    src.close()
    return dst


def get_existing_tables(conn) -> set:
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    return {r[0] for r in cur.fetchall()}


def counts(conn, all_tables) -> dict:
    existing = get_existing_tables(conn)
    cur = {}
    for t in all_tables:
        if t in existing:
            cur[t] = conn.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0]
        else:
            cur[t] = 0
    return cur


PERIOD_HOUR = 16


def new_open_period(conn, now: datetime):
    """Bikin satu periode kas OPEN dengan ID=1 memakai aturan batas 16:00."""
    start = now.replace(hour=PERIOD_HOUR, minute=0, second=0, microsecond=0)
    if now < start:
        start -= timedelta(days=1)
    end = start + timedelta(days=1)
    cur = conn.execute(
        "INSERT INTO kas_periods (id, start_at, end_at, status, snapshot,"
        " closed_by, closed_at, created_at) VALUES (?,?,?,?,?,?,?,?)",
        (1, start, end, "OPEN", None, None, None, now),
    )
    return cur.lastrowid, start, end


def record_clean_slate_audit(conn, now: datetime, keep_master: bool):
    existing = get_existing_tables(conn)
    if "journal_entries" in existing:
        ket = ("Reset operasional ke Periode #1. Master data Pelanggan, "
               "Sparepart, Beban, dan Akun dipertahankan." if keep_master
               else "Reset total sistem ke kondisi kosong Periode #1.")
        conn.execute(
            "INSERT INTO journal_entries (ts, domain, event, entity_type, "
            "entity_id, actor, source, details) VALUES (?,?,?,?,?,?,?,?)",
            (now, "FINANCE", "FINANCE_CLEAN_SLATE", "SYSTEM", 1,
             "Developer", "tools/reset_keuangan_nol.py", ket),
        )


def main() -> int:
    ap = argparse.ArgumentParser(description="Reset transaksi + kas ke NOL (Periode #1).")
    ap.add_argument("--db", default=DEFAULT_DB, help="path ke servisku.db")
    ap.add_argument("--clean-all", action="store_true",
                    help="hapus seluruh master (pelanggan, sparepart, beban); default mempertahankan master")
    ap.add_argument("--no-backup", action="store_true", help="lewati backup")
    ap.add_argument("--dry-run", action="store_true", help="hanya tampilkan rencana")
    args = ap.parse_args()

    keep_master = not args.clean_all
    db_path = os.path.abspath(args.db)
    if not os.path.exists(db_path):
        print("DB tidak ditemukan: %s" % db_path)
        return 2

    conn = sqlite3.connect(db_path, timeout=30)
    conn.execute("PRAGMA foreign_keys=OFF")
    existing = get_existing_tables(conn)

    tables_to_delete = list(OPERATIONAL_TABLES)
    if not keep_master:
        tables_to_delete.extend(MASTER_TABLES)
        tables_to_delete.append("stock_moves")
        keep_tables = list(ALWAYS_KEEP)
    else:
        keep_tables = list(ALWAYS_KEEP) + list(MASTER_TABLES)

    all_tracked = list(tables_to_delete) + keep_tables
    if keep_master and "stock_moves" not in all_tracked:
        all_tracked.append("stock_moves")

    before = counts(conn, all_tracked)

    print("DB          : %s" % db_path)
    print("Mode Master : %s" % ("DIPERTAHANKAN (Pelanggan, Sparepart, Beban, Akun)" if keep_master else "HAPUS TOTAL"))
    print("Isi Saat Ini:")
    for t in all_tracked:
        if t in existing:
            flag = "  (dijaga)" if t in keep_tables else ""
            if keep_master and t == "stock_moves":
                flag = "  (dijaga move MASUK, hapus PAKAI/transaksi)"
            print("   %-26s %6d%s" % (t, before[t], flag))

    if args.dry_run:
        print("\n--dry-run: tidak ada perubahan.")
        conn.close()
        return 0

    if not args.no_backup:
        print("\nBackup -> %s" % backup(db_path))

    now = datetime.now()
    with conn:
        for t in tables_to_delete:
            if t in existing:
                conn.execute("DELETE FROM %s" % t)

        if keep_master:
            if "stock_moves" in existing:
                conn.execute("DELETE FROM stock_moves WHERE aksi != 'MASUK'")
        else:
            if "stock_moves" in existing:
                conn.execute("DELETE FROM stock_moves")

        # Reset SQLite autoincrement sequence
        if "sqlite_sequence" in existing:
            seq_targets = [t for t in tables_to_delete if t in existing]
            if not keep_master and "stock_moves" in existing:
                seq_targets.append("stock_moves")
            placeholders = ",".join("?" for _ in seq_targets)
            conn.execute("DELETE FROM sqlite_sequence WHERE name IN (%s)" % placeholders, seq_targets)

        # Buat Periode Kas #1
        pid, start, end = new_open_period(conn, now)

        # Catat audit trail
        record_clean_slate_audit(conn, now, keep_master)

    conn.execute("VACUUM")
    conn.commit()

    after = counts(conn, all_tracked)
    print("\nSelesai. Periode kas OPEN baru #%d (%s s/d %s)."
          % (pid, start, end))
    sisa = {t: after[t] for t in tables_to_delete if after.get(t, 0) > 0}
    print("Sisa data transaksi operasional: %s" % (sisa or "NOL (bersih)"))
    print("Akun pengguna tersisa          : %d" % after.get("users", 0))
    if keep_master:
        print("Pelanggan tersisa              : %d" % after.get("customers", 0))
        print("Katalog sparepart tersisa      : %d" % after.get("spareparts", 0))
        print("Beban berulang tersisa         : %d" % after.get("expenses", 0))
        print("Stok move MASUK tersisa        : %d" % after.get("stock_moves", 0))
    print("Sesi login dihapus             : semua pengguna wajib login ulang.")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())