# -*- coding: utf-8 -*-
"""P2-14 (ID-13) — fixture pytest untuk Project B.

WAJIB: seluruh test berjalan pada **salinan** `servisku.db` di folder temp;
DB produksi tidak pernah dibuka untuk tulis.

Setup dilakukan saat modul ini di-import (sebelum test module meng-import
backend), karena `backend/database.py` membaca `DATABASE_URL` saat import.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta

import pytest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(TESTS_DIR)
BACKEND_DIR = os.path.join(PROJECT_DIR, "backend")
PROD_DB = os.path.join(PROJECT_DIR, "servisku.db")

SANDBOX = tempfile.mkdtemp(prefix="p214_pytest_")
DB_COPY = os.path.join(SANDBOX, "servisku.db")
BACKEND_COPY = os.path.join(SANDBOX, "backend")
if os.path.isfile(PROD_DB):
    shutil.copy2(PROD_DB, DB_COPY)
else:  # DB belum ada (fresh install) -> SQLite akan dibuat oleh aplikasi
    open(DB_COPY, "a").close()
shutil.copytree(BACKEND_DIR, BACKEND_COPY)

os.environ["DATABASE_URL"] = "sqlite:///%s" % DB_COPY
os.environ["NOTIF_PROVIDER_ENABLED"] = ""  # provider notifikasi nonaktif saat test
if BACKEND_COPY not in sys.path:
    sys.path.insert(0, BACKEND_COPY)


@pytest.fixture(scope="session")
def app_env():
    """Informasi sandbox aktif (DB copy + backend copy)."""
    return {"dir": SANDBOX, "db": DB_COPY, "backend": BACKEND_COPY}


@pytest.fixture(scope="session")
def client(app_env):
    """TestClient FastAPI terhadap aplikasi pada sandbox DB."""
    from database import Base, engine
    Base.metadata.create_all(bind=engine)

    from migrations_cash_layers import migrate_cash_layers
    from migrations_expense_recurring import migrate_expense_recurring
    from migrations_money import migrate_money_precision
    from migrations_warranty_claims import migrate_warranty_claims
    migrate_money_precision(engine=engine)
    migrate_cash_layers(engine=engine)
    migrate_warranty_claims(engine=engine)
    # FIN-MIRROR: kolom `expenses.recurring` (beban permanen) ikut boot produksi.
    migrate_expense_recurring(engine=engine)

    from fastapi.testclient import TestClient
    import main
    with TestClient(main.app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture()
def db(app_env, client):
    """Session DB untuk seed & assert (rollback di akhir test).

    Memakai fixture client agar migrasi non-destruktif (create_all + money/layer/
    klaim) selalu dijalankan lebih dulu — sama seperti boot aplikasi produksi.
    """
    from database import SessionLocal
    import models
    s = SessionLocal()
    try:
        u = s.query(models.User).filter(models.User.username == "pytest_admin").first()
        if u is None:
            u = models.User(username="pytest_admin", display_name="Pytest Admin",
                            role="ADMIN", passcode_hash="x", passcode_salt="y", active=True)
            s.add(u)
            s.commit()
            s.refresh(u)
        tok = s.query(models.AuthToken).filter(
            models.AuthToken.token == "pytest-token-admin").first()
        if tok is None:
            s.add(models.AuthToken(token="pytest-token-admin", user_id=u.id,
                                   expires_at=datetime.now() + timedelta(days=2)))
            s.commit()
        if s.query(models.Customer).filter(
                models.Customer.name == "Pytest Customer").first() is None:
            s.add(models.Customer(name="Pytest Customer", phone="080000000001",
                                  created_at=datetime.now()))
            s.commit()
        yield s
    finally:
        try:
            s.rollback()
            # Buang identity map. Tanpa ini, object ORM dari test sebelumnya
            # masih "dipinjam" session: ketika SQLite memakai ULANG rowid
            # (mis. setelah `DELETE FROM distributions`), object BARU dengan id
            # yang sama diam-diam memakai instance lama — termasuk nilai kolom
            # lamanya (mis. `laci_adjust_entry_id` yang sudah terisi).
            s.expunge_all()
        finally:
            s.close()


@pytest.fixture()
def auth(db):
    """Header Authorization untuk akun admin."""
    return {"Authorization": "Bearer pytest-token-admin"}


@pytest.fixture(scope="session")
def _id_order_produksi(app_env):
    """ID order yang sudah ADA sebelum test berjalan (data produksi nyata).

    Dipakai fixture `_buang_order_test_bermodal_kosong` supaya cleanup
    tidak mungkin menyentuh unit asli.
    """
    from database import SessionLocal
    import models
    s = SessionLocal()
    try:
        return {row[0] for row in s.query(models.ServiceOrder.id).all()}
    finally:
        s.close()


@pytest.fixture(autouse=True)
def _buang_order_test_bermodal_kosong(app_env, _id_order_produksi):
    """Setelah tiap test: hapus order CASH bermodal kosong BUATAN TEST.

    Tutup Kas sejak 2026-10-19 DITOLAK selama ada unit CASH bermodal kosong
    tanpa centang "Tanpa Modal" (keputusan Owner; lihat `_tutup_periode_impl`
    di `routers/kas.py`). Test yang membuat order semacam itu tidak bisa lagi
    sekadar menyisakan peringatan - sekarang ia memblokir `test_periode_kas`
    yang memanggil `POST /api/kas/close`.

    Sandbox DB dipakai bersama seluruh file test dalam satu sesi, jadi satu
    order yang bocor saja sudah cukup menggagalkan test lain. Di produksi
    sendiri TIDAK ADA satu pun order CASH bermodal kosong (dicek 2026-10-19),
    jadi ini murni artefak test.

    Pengaman: hanya order yang id-nya TIDAK ada di data produksi awal yang
    dihapus. Unit asli tidak mungkin tersentuh.
    """
    yield
    from database import SessionLocal
    import models
    s = SessionLocal()
    try:
        bocor = []
        for row in s.query(
                models.ServiceOrder.id,
                models.ServiceOrder.part_cost,
                models.ServiceOrder.modal_jasa,
                models.ServiceOrder.modal_lainnya,
                models.ServiceOrder.tanpa_modal).filter(
                models.ServiceOrder.status == "CASH").all():
            oid, part, jasa, lain, tm = row
            if oid in _id_order_produksi:
                continue
            if (part or 0) + (jasa or 0) + (lain or 0) > 0:
                continue
            if tm:
                continue
            # Order yang punya Payment (DP/PELUNASAN) TIDAK disentuh: baris
            # itu jadi fixture bagi test lain (mis. Laporan Titipan DP yang
            # menghitung 'live' dari payment yang masih ditahan). Menghapus
            # payment di sini merusak test yang tidak ada hubungannya.
            if s.query(models.Payment).filter(
                    models.Payment.service_order_id == oid).count():
                continue
            bocor.append(oid)
        if bocor:
            s.query(models.KasEntry).filter(
                models.KasEntry.ref_id.in_(bocor),
                models.KasEntry.sumber == "MODAL").delete(
                synchronize_session=False)
            s.query(models.ServiceOrder).filter(
                models.ServiceOrder.id.in_(bocor)).delete(
                synchronize_session=False)
            s.commit()
    except Exception:  # noqa: BLE001
        try:
            s.rollback()
        except Exception:  # noqa: BLE001
            pass
    finally:
        s.close()