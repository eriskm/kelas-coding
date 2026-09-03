"""BOSS SF - Service System : FastAPI Application Entry.

Layer:
   App        -> main.py  (menggabungkan seluruh router + static)
   Router     -> routers/
   Schema     -> schemas.py
   Dependency -> dependencies.py
"""
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from database import Base, engine
from routers import dashboard, orders, customers

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(os.path.dirname(BASE_DIR), "frontend")

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
app.include_router(dashboard.router)
app.include_router(orders.router)
app.include_router(customers.router)


# ---------- Mount frontend (static) ----------
@app.get("/")
def root():
    return {
        "app": "BOSS SF - Service System",
        "docs": "/docs",
        "frontend": "/static/index.html",
    }


if os.path.isdir(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
