# -*- coding: utf-8 -*-
"""Regression: DDL kolom BOOLEAN harus valid di SQLite DAN PostgreSQL.

Bug yang dikunci di sini (terbukti 2026-10-18):
`migrations_tanpa_modal` dan `migrations_expense_recurring` menulis DDL mentah
    ALTER TABLE ... ADD COLUMN "x" BOOLEAN NOT NULL DEFAULT 0
SQLite menerima literal `0`, PostgreSQL menolaknya dengan
`DatatypeMismatch: column "x" is of type boolean but default expression is of
type integer`. Efeknya dua lapis:

1. Kolom tidak pernah terbentuk di PostgreSQL, padahal models.py +
   `SELECT service_orders.tanpa_modal` sudah memakainya -> `GET /api/overview`
   balas 500 dan modul keuangan/modal mati total.
2.app.log hanya menulis "migrasi ... dilewati" dan startup tetap hijau, jadi
   kegagalan tidak pernah terlihat tanpa membaca log.

Karena test suite berjalan di SQLite (lihat conftest.py), saya tidak bisa
meniru error PostgreSQL lewat DB. Yang dikunci di sini adalah KEBERLAKUAN
literalnya per-dialek, karena itu titik yang salah.
"""
from types import SimpleNamespace

import pytest


class _FakeEngine:
    """Cukup untuk _bool_literal(): hanya butuh .dialect.name."""

    def __init__(self, name):
        self.dialect = SimpleNamespace(name=name)


@pytest.mark.parametrize("mod_name,fungsi,default", [
    ("migrations_tanpa_modal", "_bool_literal", False),
    ("migrations_expense_recurring", "_bool_literal", True),
])
def test_literal_boolean_per_dialek(mod_name, fungsi, default):
    mod = __import__(mod_name)
    helper = getattr(mod, fungsi)

    assert helper(_FakeEngine("sqlite"), default) == ("1" if default else "0"), \
        "SQLite menerima 0/1"
    assert helper(_FakeEngine("postgresql"), default) == ("true" if default else "false"), \
        "PostgreSQL menuntut true/false, bukan integer"


@pytest.mark.parametrize("mod_name,tabel,kolom,default_pg", [
    ("migrations_tanpa_modal", "service_orders", "tanpa_modal", "false"),
    ("migrations_expense_recurring", "expenses", "recurring", "true"),
])
def test_ddl_tidak_pernah_memakai_integer_default(mod_name, tabel, kolom, default_pg):
    """Template DDL harus berupa placeholder, bukan integer hard-coded."""
    mod = __import__(mod_name)
    kolom_ddl = dict((n, t) for n, t in mod.COLUMNS)
    assert kolom in kolom_ddl, "kolom %s hilang dari COLUMNS" % kolom

    template = kolom_ddl[kolom]
    assert "%s" in template, \
        "COLUMNS harus pakai placeholder %%s, bukan literal — supaya bisa " \
        "diisi _bool_literal() sesuai dialek"
    assert "DEFAULT 0" not in template and "DEFAULT 1" not in template, \
        "literal integer di template = bug DatatypeMismatch di PostgreSQL"

    ddl = template % ("true" if default_pg == "true" else "false")
    assert ddl.endswith("DEFAULT %s" % default_pg)
    assert "BOOLEAN NOT NULL DEFAULT" in ddl


def test_migrasi_lolos_di_sqlite_sandbox(client, db):
    """Jalankan kedua migrasi pada SQLite asli -> kolom terbentuk, idempoten."""
    from sqlalchemy import inspect

    import models
    import migrations_expense_recurring as mer
    import migrations_tanpa_modal as mtm
    from database import engine

    mtm.migrate_service_orders_tanpa_modal(engine)
    mer.migrate_expense_recurring(engine)

    insp = inspect(engine)
    assert "tanpa_modal" in {c["name"] for c in insp.get_columns("service_orders")}
    assert "recurring" in {c["name"] for c in insp.get_columns("expenses")}

    # idempoten: panggilan kedua harus melewati, tidak menambah kolom
    lagi = mtm.migrate_service_orders_tanpa_modal(engine)
    assert again_ok(lagi), "panggilan kedua harus idempoten"


def again_ok(report):
    assert report["changed"] == [], report
    assert any("sudah ada" in s for s in report["skipped"])
    return True