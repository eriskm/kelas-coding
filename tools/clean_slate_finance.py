# -*- coding: utf-8 -*-
"""tools/clean_slate_finance.py — Clean slate data keuangan sebelum deploy produksi.

Sesuai instruksi Owner:
- Beban hutang menjadi NOL (sisa hutang beban direset)
- Kas Aset tersedia jadi NOL (belum ada setoran riil pemilik)
- Kas Aset / Master Kas HANYA berisi DP saja (Rp 850.000 riil dari 5 unit aktif bengkel)
- Arsip Tutup Kas semua dihapus juga (periode kas test ditutup dihapus, snapshot dibersihkan)
- Sisakan hanya DP karena ini REAL

Data operasional toko (466 pelanggan riil, 92 sparepart, 39 servis aktif, 182 garansi)
TETAP AMAN dan terlindungi penuh.
"""
import os
import sys
import sqlite3
import shutil
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(PROJECT_ROOT, "servisku.db")
BACKUP_PATH = os.path.join(PROJECT_ROOT, "servisku.db.backup_before_finance_clean_slate")

# 5 payment DP riil dari antrean bengkel aktif
REAL_DP_PAYMENT_IDS = (26, 27, 28, 29, 30)


def run_clean_slate():
    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(f"Database tidak ditemukan: {DB_PATH}")

    # 1. Pastikan backup sebelum eksekusi
    if not os.path.exists(BACKUP_PATH):
        print(f"[BACKUP] Membuat backup keamanan ke: {BACKUP_PATH}")
        shutil.copyfile(DB_PATH, BACKUP_PATH)
    else:
        print(f"[BACKUP] Backup keamanan sudah ada: {BACKUP_PATH}")

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    try:
        cur.execute("BEGIN TRANSACTION")

        # -------------------------------------------------------------
        # 1. BEBAN & HUTANG BEBAN -> NOL
        # -------------------------------------------------------------
        cur.execute("SELECT COUNT(*), COALESCE(SUM(nominal), 0) FROM expense_debt_entries")
        debt_count, debt_total = cur.fetchone()
        cur.execute("DELETE FROM expense_debt_entries")
        cur.execute("DELETE FROM expense_debt_periods")
        cur.execute("DELETE FROM expense_periods")
        cur.execute("DELETE FROM expenses")
        print(f"[1/5] Hutang Beban & Expenses dibersihkan: {debt_count} baris hutang (Rp {debt_total:,}) dihapus. Sisa Hutang Beban = Rp 0")

        # -------------------------------------------------------------
        # 2. DISTRIBUSI & KAS ASET -> NOL
        # -------------------------------------------------------------
        cur.execute("SELECT COUNT(*) FROM distributions")
        dist_count = cur.fetchone()[0]
        cur.execute("DELETE FROM distributions")
        print(f"[2/5] Distribusi testing dibersihkan: {dist_count} baris dihapus. Kas Aset = Rp 0")

        # -------------------------------------------------------------
        # 3. KAS LEDGER (kas_entries) -> HANYA 5 DP RIIL
        # -------------------------------------------------------------
        cur.execute("""
            SELECT COUNT(*) FROM kas_entries
            WHERE NOT (ref_type = 'payment' AND ref_id IN (?, ?, ?, ?, ?))
        """, REAL_DP_PAYMENT_IDS)
        deleted_entries_count = cur.fetchone()[0]

        cur.execute("""
            DELETE FROM kas_entries
            WHERE NOT (ref_type = 'payment' AND ref_id IN (?, ?, ?, ?, ?))
        """, REAL_DP_PAYMENT_IDS)

        # Urutkan dan hitung ulang running balance (saldo_setelah) secara berurutan
        cur.execute("""
            SELECT id, nominal FROM kas_entries
            ORDER BY id ASC
        """)
        dp_entries = cur.fetchall()

        running_balance = 0
        for entry_id, nom in dp_entries:
            running_balance += int(nom)
            cur.execute("""
                UPDATE kas_entries
                SET layer = 'LACI', saldo_setelah = ?
                WHERE id = ?
            """, (running_balance, entry_id))

        print(f"[3/5] Buku Kas dibersihkan: {deleted_entries_count} entri dummy dihapus.")
        print(f"      Tersisa {len(dp_entries)} entri DP riil di Laci dengan total saldo: Rp {running_balance:,}")

        # -------------------------------------------------------------
        # 4. ARSIP TUTUP KAS -> DIHAPUS (sisakan archive historis tanpa snapshot + 1 periode OPEN)
        # -------------------------------------------------------------
        cur.execute("SELECT COUNT(*) FROM kas_periods WHERE id BETWEEN 6 AND 15")
        deleted_periods = cur.fetchone()[0]
        cur.execute("DELETE FROM kas_periods WHERE id BETWEEN 6 AND 15")

        # Update periode 1 (arsip garansi historis) agar menaungi semua transaksi masa lalu s.d. sebelum buka toko
        cur.execute("""
            UPDATE kas_periods
            SET start_at = '2026-05-01 00:00:00.000000',
                end_at = '2026-10-30 08:00:00.000000',
                status = 'CLOSED',
                snapshot = NULL,
                closed_by = 'Sistem (Migrasi)',
                closed_at = '2026-10-30 08:00:00.000000'
            WHERE id = 1
        """)

        # Pastikan ada 1 periode OPEN hari ini (dimulai jam 08:00)
        cur.execute("SELECT id FROM kas_periods WHERE status = 'OPEN' ORDER BY id DESC LIMIT 1")
        open_row = cur.fetchone()
        if open_row:
            cur.execute("""
                UPDATE kas_periods
                SET start_at = '2026-10-30 08:00:00.000000',
                    end_at = '2026-10-30 16:00:00.000000',
                    snapshot = NULL,
                    closed_by = NULL,
                    closed_at = NULL
                WHERE id = ?
            """, (open_row[0],))
            open_pid = open_row[0]
        else:
            cur.execute("""
                INSERT INTO kas_periods (start_at, end_at, status, created_at)
                VALUES ('2026-10-30 08:00:00.000000', '2026-10-30 16:00:00.000000', 'OPEN', datetime('now'))
            """)
            open_pid = cur.lastrowid

        # Hapus notifikasi laporan tutup kas & buka kas periode testing
        cur.execute("DELETE FROM notifications WHERE event IN ('LAPORAN_TUTUP_KAS', 'LAPORAN_BUKA_KAS')")
        print(f"[4/5] Arsip Tutup Kas testing dibersihkan: {deleted_periods} periode closed dihapus.")
        print(f"      Periode aktif saat ini: KasPeriod #{open_pid} [OPEN]")

        # -------------------------------------------------------------
        # 5. CATAT JURNAL AUDIT APPEND-ONLY
        # -------------------------------------------------------------
        import json
        audit_details = json.dumps({
            "action": "CLEAN_SLATE_FINANCE",
            "reason": "Software toko pindah kesini; reset beban hutang, kas aset nol, arsip tutup kas dihapus, sisakan 5 DP riil",
            "dp_retained": running_balance,
            "kas_aset": 0,
            "sisa_hutang_beban": 0,
            "active_period_id": open_pid
        })
        cur.execute("""
            INSERT INTO journal_entries (domain, event, entity_type, entity_id, ref_type, ref_code, actor, source, details, ts)
            VALUES ('FINANCE', 'FINANCE_CLEAN_SLATE', 'kas_period', ?, 'kas_period', ?, 'Owner', 'SYSTEM', ?, datetime('now'))
        """, (open_pid, str(open_pid), audit_details))
        print("[5/5] Audit trail dicatat ke journal_entries (domain=FINANCE, event=FINANCE_CLEAN_SLATE)")

        con.commit()
        print("\n=== CLEAN SLATE KEUANGAN BERHASIL DILAKSANAKAN ===")

    except Exception as e:
        con.rollback()
        print(f"\n[ERROR] Transaksi digagalkan (rollback): {e}")
        raise
    finally:
        con.close()


if __name__ == "__main__":
    run_clean_slate()
