"""Attendance router — presensi harian karyawan per periode kas toko.

Terintegrasi langsung dengan:
1. Akun Pengguna (`users.gaji_harian`)
2. Beban Gaji toko (`expense_periods`, `backend/finance.py`)

Karyawan yang Hadir: gaji harian diakui penuh sebagai Beban Gaji toko.
Karyawan yang Tidak Masuk (Libur/Izin/Alpha): gaji hari itu di-disable (Rp 0),
sehingga kas laci tidak keluar dan beban toko di hari itu otomatis berkurang.
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from authority import Action, require_authority
from dependencies import get_db_session
from finance import sync_open_period_salary_expense
from models import KasPeriod, User, UserAttendance
from money import ZERO, to_decimal
from routers.auth import get_authenticated_user
from routers.dashboard import get_active_period

router = APIRouter(prefix="/api/attendance", tags=["attendance"])


class AttendanceItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    user_id: int
    username: str
    display_name: str
    role: str
    gaji_harian: Decimal
    hadir: bool
    gaji_nominal: Decimal
    keterangan: str
    updated_by: Optional[str] = None
    updated_at: Optional[datetime] = None


class AttendanceTodayOut(BaseModel):
    kas_period_id: int
    periode_status: str
    items: list[AttendanceItemOut]
    total_karyawan: int
    total_hadir: int
    total_absen: int
    total_beban_gaji: Decimal


class AttendanceToggleIn(BaseModel):
    user_id: int
    hadir: bool
    keterangan: Optional[str] = None


def init_period_attendance(db: Session, kas_period_id: int) -> int:
    """Inisialisasi absensi default 'Hadir' untuk seluruh karyawan aktif pada kas_period_id dan sinkronkan ke Beban Gaji."""
    period = db.query(KasPeriod).filter(KasPeriod.id == kas_period_id).first()
    if not period or (period.status or "").upper() != "OPEN":
        return 0

    active_users = (
        db.query(User)
        .filter(User.active == 1)
        .order_by(User.role.asc(), User.display_name.asc())
        .all()
    )

    existing_atts = {
        att.user_id: att
        for att in db.query(UserAttendance)
        .filter(UserAttendance.kas_period_id == period.id)
        .all()
    }

    new_created = False
    for u in active_users:
        if u.id not in existing_atts:
            gaji = to_decimal(getattr(u, "gaji_harian", 0) or 0)
            att = UserAttendance(
                kas_period_id=period.id,
                user_id=u.id,
                hadir=True,
                gaji_nominal=gaji,
                keterangan="Hadir",
                updated_by="Sistem",
                updated_at=datetime.now(),
            )
            db.add(att)
            existing_atts[u.id] = att
            new_created = True

    if new_created:
        db.flush()
        sync_open_period_salary_expense(db, period.id)
    return len(existing_atts)


@router.get("/today", response_model=AttendanceTodayOut)
def get_today_attendance(
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_authenticated_user),
):
    """Ambil daftar kehadiran seluruh karyawan aktif untuk periode kas yang berjalan."""
    period = get_active_period(db)
    if not period:
        raise HTTPException(status_code=400, detail="Tidak ada periode kas aktif")

    init_period_attendance(db, period.id)

    active_users = (
        db.query(User)
        .filter(User.active == 1)
        .order_by(User.role.asc(), User.display_name.asc())
        .all()
    )

    existing_atts = {
        att.user_id: att
        for att in db.query(UserAttendance)
        .filter(UserAttendance.kas_period_id == period.id)
        .all()
    }

    items = []
    tot_hadir = 0
    tot_absen = 0
    tot_gaji = ZERO

    for u in active_users:
        att = existing_atts.get(u.id)
        hadir = bool(att.hadir) if att else True
        gaji_nom = to_decimal(att.gaji_nominal) if (att and hadir) else ZERO
        ket = (att.keterangan if att else "Hadir") or ("Hadir" if hadir else "Tidak Masuk / Libur")

        if hadir:
            tot_hadir += 1
            tot_gaji += gaji_nom
        else:
            tot_absen += 1

        items.append(
            AttendanceItemOut(
                user_id=u.id,
                username=u.username,
                display_name=u.display_name,
                role=u.role or "Teknisi",
                gaji_harian=to_decimal(getattr(u, "gaji_harian", 0) or 0),
                hadir=hadir,
                gaji_nominal=gaji_nom,
                keterangan=ket,
                updated_by=att.updated_by if att else None,
                updated_at=att.updated_at if att else None,
            )
        )

    return AttendanceTodayOut(
        kas_period_id=period.id,
        periode_status=period.status or "OPEN",
        items=items,
        total_karyawan=len(items),
        total_hadir=tot_hadir,
        total_absen=tot_absen,
        total_beban_gaji=tot_gaji,
    )


@router.post("/toggle", response_model=AttendanceTodayOut)
def toggle_attendance(
    payload: AttendanceToggleIn,
    db: Session = Depends(get_db_session),
    admin: User = Depends(require_authority(Action.EXPENSE_WRITE)),
):
    """Ubah status kehadiran karyawan pada periode kas berjalan (Hadir <-> Libur).

    Hanya diperbolehkan pada periode yang masih OPEN.
    Mengubah nominal gaji hari itu menjadi Rp 0 jika Tidak Hadir, dan
    mensinkronkan ExpensePeriod secara real-time.
    """
    period = get_active_period(db)
    if not period or (period.status or "").upper() != "OPEN":
        raise HTTPException(
            status_code=400,
            detail="Tidak dapat mengubah absensi pada periode kas yang sudah ditutup",
        )

    user = db.query(User).filter(User.id == payload.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Karyawan tidak ditemukan")

    att = (
        db.query(UserAttendance)
        .filter(
            UserAttendance.kas_period_id == period.id,
            UserAttendance.user_id == user.id,
        )
        .first()
    )

    gaji_harian = to_decimal(getattr(user, "gaji_harian", 0) or 0)
    nominal = gaji_harian if payload.hadir else ZERO
    default_ket = "Hadir" if payload.hadir else "Tidak Masuk / Libur"
    ket = payload.keterangan.strip() if (payload.keterangan or "").strip() else default_ket

    if not att:
        att = UserAttendance(
            kas_period_id=period.id,
            user_id=user.id,
            hadir=payload.hadir,
            gaji_nominal=nominal,
            keterangan=ket,
            updated_by=admin.display_name or admin.username,
            updated_at=datetime.now(),
        )
        db.add(att)
    else:
        att.hadir = payload.hadir
        att.gaji_nominal = nominal
        att.keterangan = ket
        att.updated_by = admin.display_name or admin.username
        att.updated_at = datetime.now()

    db.flush()
    db.commit()

    # Sinkronkan baris Beban Gaji di ExpensePeriod
    sync_open_period_salary_expense(db, period.id)

    # Return status terbaru
    return get_today_attendance(db=db, current_user=admin)
