"""P2-13 — endpoint log notifikasi (read-only).

Tidak ada endpoint "kirim manual": notifikasi adalah efek samping dari aksi
bisnis (terima unit, unit selesai, tutup/buka kas) agar anti-duplikat & audit
satu sumber. Kirim manual = aturan baru yang belum diputuskan Owner.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from models import User

import notifications as notif_mod
from dependencies import get_db_session
from routers.auth import get_authenticated_user

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("")
def list_notifications(event: str = Query(""), limit: int = 100,
                       db: Session = Depends(get_db_session),
                       user: User = Depends(get_authenticated_user)):
    """Log notifikasi (read-only)."""
    return {"items": notif_mod.daftar(db, (event or "").strip().upper() or None, limit),
            "n_diantrekan": notif_mod.hitung_diantrekan(db, (event or "").strip().upper() or None),
            "provider_aktif": notif_mod.provider_aktif(),
            "catatan": "Pengiriman eksternal hanya bila NOTIF_PROVIDER_ENABLED=1."}


@router.get("/events")
def list_events(db: Session = Depends(get_db_session),
                user: User = Depends(get_authenticated_user)):
    """Daftar event notifikasi + jendela anti-duplikat (read-only)."""
    return {"events": list(notif_mod.EVENTS),
            "jendela_menit": notif_mod.JENDELA_MENIT,
            "provider_aktif": notif_mod.provider_aktif()}
