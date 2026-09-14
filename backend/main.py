"""SUKABUMI FLASHER - Business Operating System : FastAPI Application Entry.

Layer:
   App        -> main.py  (menggabungkan seluruh router + static)
   Router     -> routers/
   Schema     -> schemas.py
   Dependency -> dependencies.py
"""
import os
import shutil
from datetime import date, datetime

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse

from database import Base, engine
from routers import dashboard, orders, customers, auth, claims, expenses, kas, spareparts, payments
from routers.auth import get_authenticated_user

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(os.path.dirname(BASE_DIR), "frontend")


class NoCacheStaticFiles(StaticFiles):
    """StaticFiles yang selalu memaksa browser mengambil versi terbaru (no-cache)."""

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        if isinstance(response, FileResponse):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

app = FastAPI(
    title="SUKABUMI FLASHER - Business Operating System API",
    description="POS & Service Management untuk toko servis smartphone",
    version="1.0.0",
)

# CORS - izinkan semua origin (untuk development)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    """Buat tabel + pastikan superadmin ada. Data dummy TIDAK di-seed
    otomatis (jalankan `python seed.py` manual bila butuh data contoh)."""
    _backup_ok = _backup_database()
    Base.metadata.create_all(bind=engine)
    _migrate_schema()
    if _backup_ok:
        _migrate_status_data()
    else:
        print("[migrasi] dilewati karena backup gagal (data tidak disentuh)")
    from seed import ensure_admin
    ensure_admin()


def _backup_database():
    """Salin servisku.db sebelum migrasi apa pun (non-destruktif).
    Return True bila aman melanjutkan migrasi data."""
    try:
        from database import DB_PATH
        if not os.path.isfile(DB_PATH):
            return True  # DB baru: create_all yang bekerja, tak ada data lama
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        dst = os.path.join(os.path.dirname(DB_PATH), "backup-servisku-%s.db" % ts)
        if not os.path.isfile(dst):
            shutil.copy2(DB_PATH, dst)
            print("[backup] database disalin ke %s" % os.path.basename(dst))
        return True
    except Exception as exc:
        print("[backup] GAGAL: %s (migrasi data dilewati, aplikasi tetap jalan)" % exc)
        return False


def _migrate_schema():
    """Tambah kolom baru pada tabel yang sudah ada (migrasi ringan)."""
    from sqlalchemy import text

    migrations = [
        ("service_orders", "device_password", "VARCHAR(120)"),
        ("service_orders", "repair_plan", "TEXT"),
        ("service_orders", "imei", "VARCHAR(80)"),
        ("service_orders", "check_fisik", "TEXT"),
        ("service_orders", "check_len", "TEXT"),
        ("service_orders", "final_price", "FLOAT"),
        ("service_orders", "part_cost", "FLOAT"),
        ("service_orders", "modal_jasa", "FLOAT"),
        ("service_orders", "modal_lainnya", "FLOAT"),
        ("service_orders", "cash_date", "DATE"),
        ("service_orders", "cash_at", "DATETIME"),
        ("service_orders", "warranty_months", "INTEGER"),
        ("service_orders", "unit_status", "VARCHAR(10)"),
        ("service_orders", "taken_at", "DATETIME"),
        ("payments", "kind", "VARCHAR(10)"),
    ]
    with engine.begin() as conn:
        for table, column, dtype in migrations:
            cols = [r[1] for r in conn.execute(text(f"PRAGMA table_info({table})")).fetchall()]
            if column not in cols:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {dtype}"))
        # Rename cash_* → lunas_* (FINAL LOCK E): momen pelunasan, bukan status.
        so_cols = [r[1] for r in conn.execute(text("PRAGMA table_info(service_orders)")).fetchall()]
        if "cash_date" in so_cols and "lunas_date" not in so_cols:
            conn.execute(text("ALTER TABLE service_orders RENAME COLUMN cash_date TO lunas_date"))
            so_cols = [r[1] for r in conn.execute(text("PRAGMA table_info(service_orders)")).fetchall()]
        if "cash_at" in so_cols and "lunas_at" not in so_cols:
            conn.execute(text("ALTER TABLE service_orders RENAME COLUMN cash_at TO lunas_at"))
        # Backfill aman untuk data lama: checklist default, IMEI dibiarkan NULL.
        conn.execute(text("UPDATE service_orders SET check_fisik = '[]' WHERE check_fisik IS NULL"))
        conn.execute(text("UPDATE service_orders SET check_len = '[\"unit_saja\"]' WHERE check_len IS NULL"))
        conn.execute(text("UPDATE service_orders SET part_cost = 0 WHERE part_cost IS NULL"))
        conn.execute(text("UPDATE service_orders SET modal_jasa = 0 WHERE modal_jasa IS NULL"))
        conn.execute(text("UPDATE service_orders SET modal_lainnya = 0 WHERE modal_lainnya IS NULL"))
        conn.execute(text("UPDATE service_orders SET unit_status = 'DI TOKO' WHERE unit_status IS NULL"))
        conn.execute(text("UPDATE payments SET kind = 'PELUNASAN' WHERE kind IS NULL"))


def _migrate_status_data():
    """Migrasi data legacy → FINAL LOCK (§3 blueprint). Idempoten:
    hanya menyentuh baris berstatus legacy; nol baris = nol aksi."""
    from database import SessionLocal
    from models import Payment, ServiceOrder, StatusHistory
    from statusflow import LEGACY_STATUS_MAP

    db = SessionLocal()
    try:
        total_before = db.query(ServiceOrder).count()
        mapped = {}
        for old, new in LEGACY_STATUS_MAP.items():
            if old == new or old == "CASH":
                continue
            n = (
                db.query(ServiceOrder)
                .filter(ServiceOrder.status == old)
                .update({ServiceOrder.status: new}, synchronize_session=False)
            )
            if n:
                mapped["%s→%s" % (old, new)] = n
        # CASH → SELESAI + backfill payments (tanpa mengarang).
        cash_orders = db.query(ServiceOrder).filter(ServiceOrder.status == "CASH").all()
        overpay, unpaid = [], []
        for o in cash_orders:
            dp = 0.0
            try:
                dp = float(o.payment or 0)
            except (TypeError, ValueError):
                dp = 0.0
            fp = getattr(o, "final_price", None)
            must = float(fp) if fp is not None else float(o.estimate or 0)
            if dp > 0:
                db.add(Payment(service_order_id=o.id, kind="DP", amount=dp,
                               method="CASH", note="DP awal (migrasi non-destruktif)",
                               created_at=o.created_at))
            rest = max(0.0, must - dp)
            moment = (getattr(o, "lunas_at", None)
                      or getattr(o, "lunas_date", None)
                      or getattr(o, "created_at", None))
            if isinstance(moment, date) and not isinstance(moment, datetime):
                moment = datetime(moment.year, moment.month, moment.day, 12, 0, 0)
            if rest > 0:
                db.add(Payment(service_order_id=o.id, kind="PELUNASAN", amount=rest,
                               method="CASH", note="Pelunasan (migrasi non-destruktif)",
                               created_at=moment))
            else:
                if dp > must:
                    overpay.append(o.no_servis)
            if not (must > 0 and (dp + rest) >= must):
                unpaid.append(o.no_servis)
            o.status = "SELESAI"
        # History awal untuk order tanpa jejak.
        with_hist = {r[0] for r in db.query(StatusHistory.service_order_id).distinct().all()}
        seeded = 0
        for o in db.query(ServiceOrder).all():
            if o.id in with_hist:
                continue
            db.add(StatusHistory(service_order_id=o.id, dari_status=None,
                                 ke_status=o.status, oleh="migrasi",
                                 waktu=o.created_at or datetime.now(),
                                 catatan="migrasi awal"))
            seeded += 1
        db.commit()
        total_after = db.query(ServiceOrder).count()
        print("[migrasi] orders %s→%s, mapping=%s, CASH→SELESAI=%d, history_seed=%d"
              % (total_before, total_after, mapped, len(cash_orders), seeded))
        if overpay:
            print("[migrasi] OVERPAY_REVIEW (DP>kewajiban): %s" % ", ".join(overpay))
        if unpaid:
            print("[migrasi] CASH_UNPAID_REVIEW (tetap BELUM LUNAS): %s" % ", ".join(unpaid))
    except Exception as exc:
        db.rollback()
        print("[migrasi] GAGAL, rollback: %s" % exc)
    finally:
        db.close()


# ---------- Mount routers ----------
app.include_router(auth.router)
app.include_router(dashboard.router, dependencies=[Depends(get_authenticated_user)])
app.include_router(orders.router, dependencies=[Depends(get_authenticated_user)])
app.include_router(customers.router, dependencies=[Depends(get_authenticated_user)])
app.include_router(claims.router, dependencies=[Depends(get_authenticated_user)])
app.include_router(expenses.router, dependencies=[Depends(get_authenticated_user)])
app.include_router(kas.router, dependencies=[Depends(get_authenticated_user)])
app.include_router(spareparts.router, dependencies=[Depends(get_authenticated_user)])
app.include_router(payments.router, dependencies=[Depends(get_authenticated_user)])


# ---------- Mount frontend (static) ----------
@app.get("/", include_in_schema=False)
def root():
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.isfile(index_path):
        return FileResponse(
            index_path,
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )
    return {"detail": "Frontend index.html tidak ditemukan"}


if os.path.isdir(FRONTEND_DIR):
    app.mount("/static", NoCacheStaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/favicon.ico")
def favicon():
    favicon_path = os.path.join(FRONTEND_DIR, "assets", "logo.png")
    if os.path.isfile(favicon_path):
        return FileResponse(favicon_path, media_type="image/png")
    raise HTTPException(status_code=404)
