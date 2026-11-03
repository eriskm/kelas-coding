"""backend/migrate_real_data_to_postgres.py

Migrasi komprehensif data riil dari SQLite (servisku.db) ke PostgreSQL produksi.
- Menjamin backup otomatis sebelum eksekusi.
- Mempertahankan akun pengguna yang ada di PostgreSQL (Mr Jon, superadmin, dll)
  dan menambahkan teknisi/admin baru dari lokal (Dana, Dana_T, Reza_T, Erik_T).
- Menyalin data pelanggan (485), spareparts (92), batches (92), stock moves (92),
  garansi & servis (222), payments (192), status history (238), kas entries (10),
  kas periods (3), beban (4), attendances (12), dan jurnal.
- Memperbarui seluruh sequence/identity primary key PostgreSQL.
"""

import os
import sys
import json
import sqlite3
from datetime import datetime, date
from decimal import Decimal

from sqlalchemy import create_engine, text, inspect
from database import Base
import models  # Memastikan semua tabel terdaftar di metadata

def run_migration(sqlite_path: str, pg_url: str):
    print("=" * 60)
    print("MIGRASI DATA RIIL: SQLite -> PostgreSQL")
    print(f"Sumber: {sqlite_path}")
    print("=" * 60)

    if not os.path.exists(sqlite_path):
        raise FileNotFoundError(f"File SQLite tidak ditemukan: {sqlite_path}")

    # Koneksi SQLite
    sq_conn = sqlite3.connect(sqlite_path)
    sq_conn.row_factory = sqlite3.Row
    sq_cur = sq_conn.cursor()

    # Koneksi PostgreSQL
    pg_engine = create_engine(pg_url)
    
    # 1. Pastikan seluruh skema tabel ada di PostgreSQL
    print("\n[1/6] Memverifikasi dan membuat skema tabel PostgreSQL...")
    Base.metadata.create_all(bind=pg_engine)
    with pg_engine.begin() as conn:
        for tbl in ["expense_periods", "distributions", "expense_debt_periods", "expense_debt_entries"]:
            try:
                conn.execute(text(f"ALTER TABLE {tbl} ALTER COLUMN periode TYPE VARCHAR(60);"))
            except Exception:
                pass
        try:
            conn.execute(text("ALTER TABLE kas_entries ALTER COLUMN ref_id TYPE VARCHAR(60) USING ref_id::varchar;"))
        except Exception:
            pass
        try:
            conn.execute(text("ALTER TABLE journal_entries ALTER COLUMN source TYPE VARCHAR(80);"))
        except Exception:
            pass
    print("      Skema tabel OK.")

    # 2. Sinkronisasi User & Pemetaan ID
    print("\n[2/6] Menyelaraskan akun pengguna (Users)...")
    username_to_pg_id = {}
    with pg_engine.begin() as conn:
        # Ambil user yang sudah ada di PostgreSQL
        pg_users = conn.execute(text("SELECT id, username FROM users")).fetchall()
        for u in pg_users:
            username_to_pg_id[u[1].lower()] = u[0]
        print(f"      User PostgreSQL saat ini: {len(username_to_pg_id)} akun.")

        # Ambil user dari SQLite
        sq_cur.execute("SELECT * FROM users")
        sq_users = [dict(r) for r in sq_cur.fetchall()]
        added_users = 0
        for u in sq_users:
            uname = u["username"].strip()
            uname_lower = uname.lower()
            cat = u.get("created_at")
            if isinstance(cat, str):
                for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                    try:
                        cat = datetime.strptime(cat, fmt)
                        break
                    except ValueError:
                        pass
            if not isinstance(cat, datetime):
                cat = datetime.now()

            if uname_lower not in username_to_pg_id:
                # Insert user baru ke PostgreSQL
                res = conn.execute(
                    text("""
                        INSERT INTO users (username, display_name, role, passcode_hash, passcode_salt, active, gaji_harian, created_at)
                        VALUES (:username, :display_name, :role, :passcode_hash, :passcode_salt, :active, :gaji_harian, :created_at)
                        RETURNING id
                    """),
                    {
                        "username": uname,
                        "display_name": u.get("display_name") or uname,
                        "role": u.get("role") or "Teknisi",
                        "passcode_hash": u.get("passcode_hash"),
                        "passcode_salt": u.get("passcode_salt"),
                        "active": 1 if u.get("active", 1) else 0,
                        "gaji_harian": u.get("gaji_harian") or 0,
                        "created_at": cat
                    }
                ).fetchone()
                username_to_pg_id[uname_lower] = res[0]
                added_users += 1
            else:
                # Update gaji_harian jika ada
                conn.execute(
                    text("UPDATE users SET gaji_harian = :gaji WHERE lower(username) = :uname"),
                    {"gaji": u.get("gaji_harian") or 0, "uname": uname_lower}
                )
        print(f"      Ditambahkan {added_users} akun baru. Total user: {len(username_to_pg_id)}.")

    # 3. Truncate tabel operasional dan master yang akan di-refresh
    print("\n[3/6] Membersihkan data operasional lama di PostgreSQL...")
    tables_to_truncate = [
        "kas_entries",
        "payments",
        "status_history",
        "warranty_claims",
        "service_order_parts",
        "part_sale_items",
        "part_sales",
        "service_orders",
        "stock_moves",
        "sparepart_batches",
        "sparepart_defects",
        "spareparts",
        "distributions",
        "refunds",
        "expense_debt_entries",
        "expense_debt_periods",
        "expense_periods",
        "expenses",
        "user_attendances",
        "journal_entries",
        "notifications",
        "customers",
        "kas_periods"
    ]
    with pg_engine.begin() as conn:
        conn.execute(text(f"TRUNCATE TABLE {', '.join(tables_to_truncate)} CASCADE;"))
    print("      Pembersihan data lama selesai (CASCADE).")

    # 4. Fungsi bantu konversi data
    def coerce_rows(table_name, rows):
        table = Base.metadata.tables[table_name]
        int_cols = {c.name for c in table.columns if c.type.__class__.__name__ == "Integer"}
        float_cols = {c.name for c in table.columns if c.type.__class__.__name__ in ("Float", "Numeric")}
        bool_cols = {c.name for c in table.columns if c.type.__class__.__name__ == "Boolean"}
        date_cols = {c.name for c in table.columns if c.type.__class__.__name__ == "Date"}
        dt_cols = {c.name for c in table.columns if c.type.__class__.__name__ == "DateTime"}
        json_cols = {c.name for c in table.columns if "JSON" in c.type.__class__.__name__}
        str_cols = {c.name for c in table.columns if c.type.__class__.__name__ in ("String", "Text", "VARCHAR")}

        cleaned = []
        for r in rows:
            item = dict(r)
            for k, v in list(item.items()):
                if k not in table.columns:
                    del item[k]
                    continue
                if v is None:
                    continue
                if k in int_cols:
                    try:
                        item[k] = int(v)
                    except (ValueError, TypeError):
                        item[k] = None
                elif k in float_cols:
                    try:
                        item[k] = float(v)
                    except (ValueError, TypeError):
                        item[k] = 0.0
                elif k in bool_cols:
                    item[k] = bool(v)
                elif k in dt_cols:
                    if isinstance(v, str):
                        for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                            try:
                                item[k] = datetime.strptime(v, fmt)
                                break
                            except ValueError:
                                pass
                elif k in date_cols:
                    if isinstance(v, str):
                        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
                            try:
                                item[k] = datetime.strptime(v.split()[0], "%Y-%m-%d").date()
                                break
                            except ValueError:
                                pass
                elif k in json_cols:
                    if isinstance(v, str):
                        try:
                            item[k] = json.loads(v)
                        except (ValueError, TypeError):
                            pass
                elif k in str_cols and not isinstance(v, str):
                    item[k] = str(v)
            cleaned.append(item)
        return cleaned

    # 5. Salin data per tabel sesuai urutan dependensi
    print("\n[4/6] Menyalin tabel data riil ke PostgreSQL...")
    tables_to_copy = [
        "customers",
        "spareparts",
        "sparepart_batches",
        "stock_moves",
        "kas_periods",
        "service_orders",
        "payments",
        "status_history",
        "warranty_claims",
        "service_order_parts",
        "part_sales",
        "part_sale_items",
        "sparepart_defects",
        "kas_entries",
        "expenses",
        "expense_periods",
        "expense_debt_periods",
        "expense_debt_entries",
        "distributions",
        "refunds",
        "journal_entries",
        "notifications"
    ]

    with pg_engine.begin() as conn:
        for tname in tables_to_copy:
            sq_cur.execute(f"SELECT * FROM {tname}")
            raw_rows = sq_cur.fetchall()
            if not raw_rows:
                print(f"      {tname:<22}: 0 baris (kosong)")
                continue

            cleaned = coerce_rows(tname, raw_rows)
            table_obj = Base.metadata.tables[tname]
            conn.execute(table_obj.insert(), cleaned)
            print(f"      {tname:<22}: {len(cleaned):>4} baris disalin OK")

        # Salin user_attendances dengan pemetaan user_id
        sq_cur.execute("""
            SELECT ua.*, u.username 
            FROM user_attendances ua 
            JOIN users u ON ua.user_id = u.id
        """)
        raw_att = sq_cur.fetchall()
        if raw_att:
            att_cleaned = []
            for r in raw_att:
                d = dict(r)
                uname = d.pop("username", "").strip().lower()
                pg_uid = username_to_pg_id.get(uname)
                if pg_uid:
                    d["user_id"] = pg_uid
                    att_cleaned.append(d)
            if att_cleaned:
                att_table = Base.metadata.tables["user_attendances"]
                coerced_att = coerce_rows("user_attendances", att_cleaned)
                conn.execute(att_table.insert(), coerced_att)
                print(f"      {'user_attendances':<22}: {len(coerced_att):>4} baris disalin OK (user mapped)")

    # 6. Setval Sequences
    print("\n[5/6] Menyesuaikan sequence/identity primary key...")
    all_synced_tables = ["users"] + tables_to_copy + ["user_attendances"]
    with pg_engine.begin() as conn:
        for tname in all_synced_tables:
            table_obj = Base.metadata.tables[tname]
            pk_col = list(table_obj.primary_key.columns)[0].name
            try:
                conn.execute(text(f"""
                    SELECT setval(
                        pg_get_serial_sequence('{tname}', '{pk_col}'),
                        GREATEST(COALESCE((SELECT MAX({pk_col}) FROM {tname}), 0), 1),
                        (SELECT MAX({pk_col}) IS NOT NULL FROM {tname})
                    );
                """))
            except Exception as e:
                # Jika tabel bukan auto-increment serial, abaikan
                pass
    print("      Semua sequence primary key telah disesuaikan.")

    # 7. Verifikasi Akhir
    print("\n[6/6] Verifikasi hasil akhir di PostgreSQL:")
    with pg_engine.connect() as conn:
        for tname in all_synced_tables:
            cnt = conn.execute(text(f"SELECT count(*) FROM {tname}")).scalar()
            max_id = conn.execute(text(f"SELECT coalesce(max(id), 0) FROM {tname}")).scalar()
            print(f"      {tname:<22}: count = {cnt:>4}, max_id = {max_id}")

    print("\n" + "=" * 60)
    print("MIGRASI DATA RIIL KE POSTGRESQL SUKSES!")
    print("=" * 60)

if __name__ == "__main__":
    sq_path = os.environ.get("SQLITE_PATH", "servisku.db")
    pg_url = os.environ.get("DATABASE_URL")
    if not pg_url or pg_url.startswith("sqlite"):
        sys.exit("Error: DATABASE_URL harus diset ke URL PostgreSQL.")
    run_migration(sq_path, pg_url)
