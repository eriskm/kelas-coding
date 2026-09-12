"""SUKABUMI FLASHER - Business Operating System : FastAPI Application Entry.

Layer:
   App        -> main.py  (menggabungkan seluruh router + static)
   Router     -> routers/
   Schema     -> schemas.py
   Dependency -> dependencies.py
"""
import os

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse

from database import Base, engine
from routers import dashboard, orders, customers, auth, claims, expenses
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
    Base.metadata.create_all(bind=engine)
    _migrate_schema()
    from seed import ensure_admin
    ensure_admin()


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
    ]
    with engine.begin() as conn:
        for table, column, dtype in migrations:
            cols = [r[1] for r in conn.execute(text(f"PRAGMA table_info({table})")).fetchall()]
            if column not in cols:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {dtype}"))
        # Backfill aman untuk data lama: checklist default, IMEI dibiarkan NULL.
        conn.execute(text("UPDATE service_orders SET check_fisik = '[]' WHERE check_fisik IS NULL"))
        conn.execute(text("UPDATE service_orders SET check_len = '[\"unit_saja\"]' WHERE check_len IS NULL"))
        conn.execute(text("UPDATE service_orders SET part_cost = 0 WHERE part_cost IS NULL"))
        conn.execute(text("UPDATE service_orders SET modal_jasa = 0 WHERE modal_jasa IS NULL"))
        conn.execute(text("UPDATE service_orders SET modal_lainnya = 0 WHERE modal_lainnya IS NULL"))


# ---------- Mount routers ----------
app.include_router(auth.router)
app.include_router(dashboard.router, dependencies=[Depends(get_authenticated_user)])
app.include_router(orders.router, dependencies=[Depends(get_authenticated_user)])
app.include_router(customers.router, dependencies=[Depends(get_authenticated_user)])
app.include_router(claims.router, dependencies=[Depends(get_authenticated_user)])
app.include_router(expenses.router, dependencies=[Depends(get_authenticated_user)])


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
