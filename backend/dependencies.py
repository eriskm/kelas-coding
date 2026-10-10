"""Shared FastAPI dependencies."""
from fastapi import Depends
from sqlalchemy.orm import Session

from database import get_db


def get_db_session(db: Session = Depends(get_db)) -> Session:
    """Provide a DB session to route handlers.

    P2-14 (b) — safety net atomik: bila request berakhir dengan exception, sesi
    di-rollback eksplisit sehingga tidak ada state setengah jadi yang tertinggal
    (sesi yang di-close tanpa commit juga melakukan rollback, tapi eksplisit
    membuat jejaknya jelas dan konsisten untuk semua endpoint).
    """
    try:
        yield db
    except Exception:
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
        raise
    finally:
        db.close()
