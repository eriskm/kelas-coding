"""BOSS SF - Service System : FastAPI Application Entry.

Layer:
   App        -> main.py  (menggabungkan seluruh router + static)
   Router     -> routers/
   Schema     -> schemas.py
   Dependency -> dependencies.py
"""
import os

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse

from database import Base, engine
from routers import dashboard, orders, customers, auth
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
    title="BOSS SF - Service System API",
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
    """Buat tabel + seed dummy jika database masih kosong."""
    Base.metadata.create_all(bind=engine)
    from seed import seed as run_seed
    run_seed()


# ---------- Mount routers ----------
app.include_router(auth.router)
app.include_router(dashboard.router, dependencies=[Depends(get_authenticated_user)])
app.include_router(orders.router, dependencies=[Depends(get_authenticated_user)])
app.include_router(customers.router, dependencies=[Depends(get_authenticated_user)])


# ---------- Mount frontend (static) ----------
@app.get("/")
def root():
    return {
        "app": "BOSS SF - Service System",
        "docs": "/docs",
        "frontend": "/static/index.html",
    }


if os.path.isdir(FRONTEND_DIR):
    app.mount("/static", NoCacheStaticFiles(directory=FRONTEND_DIR), name="static")
