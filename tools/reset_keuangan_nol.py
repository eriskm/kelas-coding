"""Reset data transaksi + kas ke NOL, pertahankan akun pengguna.

Skrip ini menghapus SELURUH data operasional sehingga uji ulang fungsi
Keuangan bisa dijalankan dari kondisi benar-benar kosong:

  - service order (Servis Baru / Update Data Servis), pembayaran, refund,
    klaim garansi, riwayat status, pemakaian & mutasi stok sparepart
  - seluruh jurnal kas layer LACI dan KAS_ASET
  - beban (expenses), periode beban, hutang beban, distribusi laba
  - pelanggan, sparepart, notifikasi, idempotency key, sesi login
  - periode kas tertutup (arsip) -> dibuat ulang satu periode OPEN

Yang TIDAK dihapus: tabel `users` (akun Admin/Kasir/CS).

Karena `auth_tokens` ikut dibersihkan, semua pengguna wajib login ulang
setelah reset.

Pemakaian:
    python tools/reset_keuangan_nol.py                  # backup + reset
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

#: Tabel yang wajib dikosongkan. `users` sengaja tidak ada di sini.
TABLES = (
    # anak-anak service order dulu ( biar FK aman walau FK enforcement mati)
    "service_order_parts",
    "stock_moves",
    "payments",
    "refunds",
    "warranty_claims",
    "status_history",
    "expense_periods",
    # jurnal kas & turunannya
    "expense_debt_entries",
    "expense_debt_periods",
    "distributions",
    "kas_entries",
    "kas_periods",
    # jurnal kas, beban, dan jurnal audit
    "expenses",
    "journal_entries",
    # induk operasional
    "service_orders",
    "customers",
    "spareparts",
    # cache, notifikasi, dan sesi login
    "notifications",
    "idempotency_keys",
    "auth_tokens",
)

#: Dipakai untuk laporan-ringkasan, bukan untuk konsistensi data.
KEEP = ("users",)


def backup(db_path: str) -> str:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    dst = os.path.join(os.path.dirname(db_path),
                       "backup-preRESET-%s.db" % ts)
    # sqlite3 backup API: aman walau DB sedang dipakai proses lain.
    src = sqlite3.connect(db_path)
    out = sqlite3.connect(dst)
    with out:
        src.backup(out)
    out.close()
    src.close()
    return dst


def counts(conn) -> dict:
    cur = {}
    for t in TABLES + KEEP:
        cur[t] = conn.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0]
    return cur


PERIOD_HOUR = 16


def new_open_period(conn, now: datetime):
    """Bikin satu periode kas OPEN memakai aturan yang sama dengan backend.

    Mengikuti `routers.dashboard._period_bounds`: periode berjalan dari
    pukul 16:00 hari sebelumnya sampai pukul 16:00 hari ini. Kalau reset
    dilakukan sebelum jam 16:00, periodenya dimulai kemarin 16:00.
    """
    start = now.replace(hour=PERIOD_HOUR, minute=0, second=0, microsecond=0)
    if now < start:
        start -= timedelta(days=1)
    end = start + timedelta(days=1)
    cur = conn.execute(
        "INSERT INTO kas_periods (start_at, end_at, status, snapshot,"
        " closed_by, closed_at, created_at) VALUES (?,?,?,?,?,?,?)",
        (start, end, "OPEN", None, None, None, now),
    )
    return cur.lastrowid, start, end


def main() -> int:
    ap = argparse.ArgumentParser(description="Reset transaksi + kas ke NOL.")
    ap.add_argument("--db", default=DEFAULT_DB, help="path ke servisku.db")
    ap.add_argument("--no-backup", action="store_true", help="lewati backup")
    ap.add_argument("--dry-run", action="store_true", help="hanya tampilkan rencana")
    args = ap.parse_args()

    db_path = os.path.abspath(args.db)
    if not os.path.exists(db_path):
        print("DB tidak ditemukan: %s" % db_path)
        return 2

    conn = sqlite3.connect(db_path, timeout=30)
    conn.execute("PRAGMA foreign_keys=OFF")
    before = counts(conn)

    print("DB  : %s" % db_path)
    print("Isi :")
    for t in TABLES + KEEP:
        flag = "  (dijaga)" if t in KEEP else ""
        print("   %-26s %6d%s" % (t, before[t], flag))

    if args.dry_run:
        print("\n--dry-run: tidak ada perubahan.")
        conn.close()
        return 0

    if not args.no_backup:
        print("\nBackup -> %s" % backup(db_path))

    with conn:
        for t in TABLES:
            conn.execute("DELETE FROM %s" % t)
        pid, start, end = new_open_period(conn, datetime.now())

    conn.execute("VACUUM")
    conn.commit()

    after = counts(conn)
    print("\nSelesai. Periode kas OPEN baru #%d (%s s/d %s)."
          % (pid, start, end))
    sisa = {t: after[t] for t in TABLES if after[t]}
    print("Sisa data operasional: %s" % (sisa or "NOL (bersih)"))
    print("Akun pengguna tersisa : %d" % after["users"])
    print("Sesi login dihapus    : semua pengguna wajib login ulang.")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())