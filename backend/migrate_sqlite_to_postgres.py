"""Salin data servisku.db (SQLite) ke PostgreSQL (DATABASE_URL).

Pakai:
    set DATABASE_URL=postgresql+psycopg://<user>:<pass>@<host>:5432/<db>
    python migrate_sqlite_to_postgres.py                 # mode fill (default)
    python migrate_sqlite_to_postgres.py --mode upsert   # mode upsert

SQLITE_PATH=... untuk menunjuk file SQLite lain (default: DB_PATH).

Dua mode:
- fill   (default, paling aman): hanya menyalin ke tabel yang masih KOSONG di
         PostgreSQL. Tabel yang sudah berisi baris dilewati. Dipakai untuk
         mengisi server yang data Slate-nya hilang, tidak pernah menimpa.
- upsert: menyalin baris per primary key, `ON CONFLICT DO UPDATE`. Dipakai
         supaya server bisa menyusul perubahan lokal. TETAP tidak menghapus
         baris yang hanya ada di PostgreSQL (tidak ada sync two-way).

Skema dibuat dulu via Base.metadata.create_all, lalu sequence disesuaikan.

Toleran terhadap skewema SQLite<->PostgreSQL:
- tabel yang belum ada di SQLite dilewati (schema PostgreSQL boleh lebih baru);
- kolom yang belum ada di SQLite diisi DEFAULT, bukan digagalkan;
- nilai non-numerik di kolom INTEGER (SQLite bertipe dinamis, mis.
  `ref_id = "kas_period:3"`) menjadi NULL supaya PostgreSQL tidak menolak;
  referensinya tetap terbaca di kolom keterangan.
"""
import argparse
import json
import os
import sqlite3
import sys
from datetime import date, datetime

from sqlalchemy import insert, inspect, text
from sqlalchemy import JSON as SAJSON
from sqlalchemy.dialects.postgresql import insert as pg_insert

from database import Base, DB_PATH, SQLALCHEMY_DATABASE_URL, engine as pg_engine
import models  # noqa: F401  (registrasi seluruh tabel ke Base.metadata)

# Urutan = urutan dependensi FK (induk sebelum anak).
TABLE_ORDER = [
    "users",
    "customers",
    "service_orders",
    "payments",
    "warranty_claims",
    "status_history",
    "auth_tokens",
    "expenses",
    "kas_periods",
    "spareparts",
    "kas_entries",
]

# auth_tokens = sesi login, tidak pernah disalin dari mesin 개발.
SKIP_TABLES = {"auth_tokens"}


def _row_to_dict(row, json_cols):
    d = {k: row[k] for k in row.keys()}
    for col in json_cols:
        v = d.get(col)
        if isinstance(v, str):
            try:
                d[col] = json.loads(v)
            except ValueError:
                d[col] = None
    return d


def _coerce(data, table, report):
    """Samakan tipe SQLite (dinamis) dengan kolom PostgreSQL (statis)."""
    int_cols = {c.name for c in table.columns
                if c.type.__class__.__name__ == "Integer"}
    date_cols = {c.name for c in table.columns
                 if c.type.__class__.__name__ in ("Date", "DateTime")}
    for item in data:
        for k, v in list(item.items()):
            if k in int_cols and v is not None and not isinstance(v, int):
                try:
                    item[k] = int(str(v))
                except ValueError:
                    report.append((table.name, k, str(v)))
                    item[k] = None
            elif k in date_cols and isinstance(v, str) and v.strip():
                for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S",
                            "%Y-%m-%d"):
                    try:
                        item[k] = datetime.strptime(v, fmt)
                        break
                    except ValueError:
                        continue
            if isinstance(v, (date, datetime)):
                item[k] = v
    return data


def _pk_of(table):
    return list(table.primary_key.columns)[0].name


def sync(mode="fill", sqlite_path=None, tables=None):
    if SQLALCHEMY_DATABASE_URL.startswith("sqlite"):
        sys.exit("DATABASE_URL belum diset ke PostgreSQL - batal "
                 "(app tetap SQLite).")

    sqlite_path = sqlite_path or os.environ.get("SQLITE_PATH") or DB_PATH
    if not os.path.isfile(sqlite_path):
        sys.exit("SQLite tidak ditemukan: %s" % sqlite_path)

    print("[1] Memastikan skema PostgreSQL (create_all)...")
    Base.metadata.create_all(bind=pg_engine)

    src = sqlite3.connect("file:%s?mode=ro" % sqlite_path, uri=True)
    src.row_factory = sqlite3.Row
    sqlite_tabs = {r[0] for r in src.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    pg_tabs = set(inspect(pg_engine).get_table_names())
    print("    SQLite %d tabel, PostgreSQL %d tabel" % (len(sqlite_tabs), len(pg_tabs)))

    targets = [t for t in (tables or TABLE_ORDER) if t not in SKIP_TABLES]
    copied = updated = 0
    coerced_report = []

    with pg_engine.begin() as conn:
        for table_name in targets:
            if table_name not in pg_tabs:
                print("   %-18s dilewati: tidak ada di PostgreSQL" % table_name)
                continue
            if table_name not in sqlite_tabs:
                print("   %-18s dilewati: tidak ada di SQLite" % table_name)
                continue

            table = Base.metadata.tables[table_name]
            json_cols = [c.name for c in table.columns if isinstance(c.type, SAJSON)]
            sq_cols = {r[1] for r in src.execute('PRAGMA table_info("%s")' % table_name)}
            use_cols = [c.name for c in table.columns if c.name in sq_cols]
            missing = [c.name for c in table.columns if c.name not in sq_cols]
            if missing:
                print("   %-18s kolom tak ada di SQLite -> DEFAULT: %s"
                      % (table_name, missing))

            rows = src.execute("SELECT %s FROM %s"
                               % (", ".join(use_cols), table_name)).fetchall()
            if not rows:
                print("   %-18s sumber kosong" % table_name)
                continue
            data = _coerce([_row_to_dict(r, json_cols) for r in rows], table,
                           coerced_report)
            n_target = conn.execute(
                text("SELECT count(*) FROM %s" % table_name)).scalar() or 0

            if mode == "fill":
                if n_target:
                    print("   %-18s DILEWATI (target sudah %d baris)"
                          % (table_name, n_target))
                    continue
                conn.execute(insert(table), data)
                copied += len(data)
                print("   %-18s %d baris OK" % (table_name, len(data)))
                continue

            # mode upsert
            pk = _pk_of(table)
            upd_cols = [c.name for c in table.columns if c.name != pk]
            stmt = pg_insert(table)
            stmt = stmt.on_conflict_do_update(
                index_elements=[pk],
                set_={c: stmt.excluded[c] for c in upd_cols})
            conn.execute(stmt, data)
            updated += len(data)
            print("   %-18s %d baris upsert (target %d baris)"
                  % (table_name, len(data), n_target))
    src.close()

    if coerced_report:
        print("\n[!] nilai non-numerik di kolom INTEGER -> NULL:")
        for t, k, v in coerced_report[:20]:
            print("    %s.%s = %s" % (t, k, v))
        if len(coerced_report) > 20:
            print("    ... %d nilai lain" % (len(coerced_report) - 20))
        print("    (referensinya tetap ada di kolom keterangan)")

    print("\n[2] Menyesuaikan sequence/identity primary key...")
    with pg_engine.begin() as conn:
        for table_name in targets:
            if table_name not in pg_tabs:
                continue
            table = Base.metadata.tables[table_name]
            pk = _pk_of(table)
            info = conn.execute(text(
                "SELECT is_identity, column_default FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = :t AND column_name = :c"
            ), {"t": table_name, "c": pk}).first()
            has_seq = bool(info and (info[0] == "YES" or (info[1] and "nextval" in info[1])))
            if not has_seq:
                conn.execute(text(
                    "ALTER TABLE %s ALTER COLUMN %s ADD GENERATED BY DEFAULT AS IDENTITY"
                    % (table_name, pk)))
                print("   %-18s + identity" % table_name)
            conn.execute(text(
                "SELECT setval(pg_get_serial_sequence('%(t)s', '%(c)s'), "
                "GREATEST(COALESCE((SELECT MAX(%(c)s) FROM %(t)s), 0), 1), "
                "(SELECT MAX(%(c)s) IS NOT NULL FROM %(t)s))" % {"t": table_name, "c": pk}))

    print("\n[3] Verifikasi hasil...")
    with pg_engine.connect() as conn:
        for table_name in targets:
            if table_name not in pg_tabs:
                continue
            n = conn.execute(text("SELECT count(*) FROM %s" % table_name)).scalar()
            print("   %-18s %d baris" % (table_name, n))

    print("\nSelesai mode=%s: %d baris disalin, %d baris di-upsert (SQLite: %s)"
          % (mode, copied, updated, sqlite_path))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mode", choices=("fill", "upsert"), default="fill",
                    help="fill = hanya tabel kosong (aman); "
                         "upsert = insert/update per primary key")
    ap.add_argument("--sqlite", default=None, help="path file SQLite")
    ap.add_argument("--tables", default=None,
                    help="batasi tabel, dipisah koma (default: TABLE_ORDER)")
    args = ap.parse_args()
    tables = [t.strip() for t in (args.tables or "").split(",") if t.strip()] or None
    sync(mode=args.mode, sqlite_path=args.sqlite, tables=tables)


if __name__ == "__main__":
    main()