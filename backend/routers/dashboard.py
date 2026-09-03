"""Dashboard endpoints - data untuk star cards & charts."""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from dependencies import get_db_session
from models import ServiceOrder

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/overview")
def get_overview(db: Session = Depends(get_db_session)):
    """Data untuk star cards + insight hari ini (dummy finansial)."""
    orders = db.query(ServiceOrder).all()
    total = len(orders)
    done = sum(1 for o in orders if o.status == "COMPLETED")
    active = sum(1 for o in orders if o.status in ("REPAIR", "QC", "RECEIVED", "DIAGNOSIS"))
    pending = sum(1 for o in orders if o.status in ("WAITING_PART", "WAITING_APPROVAL"))
    ready = sum(1 for o in orders if o.status == "READY")

    omset = sum(o.payment for o in orders)
    piutang = sum(o.estimate - o.payment for o in orders if o.estimate > o.payment)

    # dummy finansial (karena belum ada tabel expenses)
    laba_kotor = 8750000
    total_beban = 3750000
    laba_bersih = laba_kotor - total_beban
    target_gaji = 15000000

    return {
        "star_cards": [
            {"label": "Omset Hari Ini", "value": omset, "change": "+12% dari kemarin", "up": True},
            {"label": "Laba Kotor", "value": laba_kotor, "change": None, "up": None},
            {"label": "Total Beban", "value": total_beban, "change": None, "up": None},
            {"label": "Laba Bersih", "value": laba_bersih, "change": "+8% dari bulan lalu", "up": True},
            {"label": "Target Gaji (CTS)", "value": target_gaji, "change": "Tercapai 83%", "up": True},
        ],
        "insight": [
            {"value": active, "label": "Dikerjakan", "color": "text-cyan-600"},
            {"value": 3, "label": "Terlambat", "color": "text-red-500"},
            {"value": pending, "label": "Menunggu Acc", "color": "text-amber-600"},
            {"value": round(piutang), "label": "Piutang", "color": "text-rose-600"},
        ],
        "stats": {"total": total, "done": done, "active": active, "pending": pending, "ready": ready},
    }


@router.get("/statistics/status")
def get_status_stats(db: Session = Depends(get_db_session)):
    """Data untuk smooth line chart - tren status transaksi minggu ini."""
    days = [d.strftime("%a") for d in (datetime.now() - timedelta(days=i) for i in range(6, -1, -1))]
    # dummy volume per hari
    masuk = [12, 10, 14, 13, 16, 15, 18]
    selesai = [8, 9, 11, 10, 12, 13, 12]
    pending = [4, 3, 5, 6, 5, 4, 7]
    return {
        "categories": days,
        "series": [
            {"name": "Masuk", "data": masuk},
            {"name": "Selesai", "data": selesai},
            {"name": "Pending", "data": pending},
        ],
    }


@router.get("/statistics/damage")
def get_damage_stats(db: Session = Depends(get_db_session)):
    """Data untuk horizontal bar chart - tren kerusakan minggu ini."""
    return {
        "categories": ["Layar Pecah", "Baterai", "Charging", "Speaker", "Kamera", "Water"],
        "data": [14, 9, 7, 5, 4, 3],
    }
