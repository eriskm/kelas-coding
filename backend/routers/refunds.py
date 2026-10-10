"""P2-10 — Refund endpoints (Q9: 3 jenis, otoritas & sumber dana berbeda).

Tiga endpoint TERPISAH supaya authority & sumber dana tidak bisa tertukar:

| Jenis           | Endpoint                       | Authority                     | Sumber dana |
|-----------------|--------------------------------|-------------------------------|-------------|
| Refund DP       | POST /api/refunds/dp           | `Action.REFUND_DP`            | LACI        |
| Refund Garansi  | POST /api/refunds/garansi      | `Action.REFUND_GARANSI`       | KAS_ASET    |
| Failed → Cancel | POST /api/refunds/failed-cancel| `Action.FAILED_CANCEL`         | LACI        |

Semua penulisan dalam SATU transaksi: `commit()` hanya setelah domain sukses,
`rollback()` pada setiap kegagalan → tidak ada efek setengah jadi (Q9 satu efek).
"""
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

import idempotency as idem
import refunds as refunds_mod
from authority import Action, require_authority
from dependencies import get_db_session
from models import Refund, User
from routers.auth import get_authenticated_user
import schemas

router = APIRouter(prefix="/api/refunds", tags=["refunds"])

DEFAULT_PAGE = 1
DEFAULT_LIMIT = 20
MAX_LIMIT = 100


def _err(exc):
    """Refund domain error -> HTTP."""
    if isinstance(exc, refunds_mod.RefundKurangKas):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


def _to_out(row: Refund) -> schemas.RefundOut:
    return schemas.RefundOut(
        id=row.id, refund_no=row.refund_no, jenis=row.jenis,
        service_order_id=row.service_order_id,
        warranty_claim_id=row.warranty_claim_id, nominal=row.nominal,
        sumber_dana=row.sumber_dana, alasan=row.alasan,
        kas_entry_id=row.kas_entry_id, oleh=row.oleh, created_at=row.created_at)


def _dengan_idem(db, scope: str, key: str, payload, aksi):
    """Jalankan aksi endpoint dengan proteksi Idempotency-Key (P2-14)."""
    actor = "-"
    if not key:
        return aksi()
    try:
        run = idem.jalankan(db, scope, key, payload, aksi, actor=actor)
    except idem.IdempotencyConflict as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc))
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise
    if run.get("replayed"):
        # Sudah pernah diproses: kembalikan response tersimpan (tanpa efek baru).
        return run.get("result")
    return run.get("result")


def _jalankan(fn, db, oleh):
    """Jalankan domain refund dalam satu transaksi."""
    try:
        row, mutasi = fn()
        db.commit()
    except (refunds_mod.RefundError, refunds_mod.RefundKurangKas) as exc:
        db.rollback()
        raise _err(exc)
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise
    db.refresh(row)
    out = _to_out(row)
    return {"refund": out,
            # v4 #8: refund garansi tidak mengubah saldo posisi secara otomatis.
            "saldo_setelah": ((mutasi or {}).get("saldo_setelah")
                              if mutasi else _saldo_layer(db, out.sumber_dana)),
            "efek_saldo": ("otomatis" if mutasi else "manual oleh Admin (v4 #8)"),
            "sumber_dana": out.sumber_dana, "kas_entry_id": out.kas_entry_id}


def _saldo_layer(db, layer):
    """Saldo posisi setelah refund (untuk response; non-otomatis = saldo tak berubah)."""
    try:
        return cash.saldo_layer(db, layer)
    except Exception:  # noqa: BLE001
        return None


@router.post("/dp")
def create_refund_dp(data: schemas.RefundDPIn, db: Session = Depends(get_db_session),
                     user: User = Depends(require_authority(Action.REFUND_DP)),
                     idempotency_key: str = Header(None, alias=idem.HEADER)):
    """Refund DP — Admin/Kasir, dana dari Kas Perputaran (Laci). P2-14: idempotency key."""
    return _dengan_idem(db, "refunds.dp", idempotency_key, data.model_dump(),
                        lambda: _refund_dp_impl(data, db, user))


def _refund_dp_impl(data, db, user):
    oleh = user.display_name or user.username
    return _jalankan(lambda: refunds_mod.refund_dp(
        db, data.service_order_id, data.nominal, data.alasan, oleh), db, oleh)


@router.post("/garansi")
def create_refund_garansi(data: schemas.RefundGaransiIn, db: Session = Depends(get_db_session),
                          user: User = Depends(require_authority(Action.REFUND_GARANSI)),
                          idempotency_key: str = Header(None, alias=idem.HEADER)):
    """Refund Klaim Garansi — Admin saja, dana dari Kas Aset (+ pre-check). P2-14: idempotency."""
    return _dengan_idem(db, "refunds.garansi", idempotency_key, data.model_dump(),
                        lambda: _refund_garansi_impl(data, db, user))


def _refund_garansi_impl(data, db, user):
    oleh = user.display_name or user.username
    return _jalankan(lambda: refunds_mod.refund_garansi(
        db, data.warranty_claim_id, data.nominal, data.alasan, oleh), db, oleh)


@router.post("/failed-cancel")
def create_refund_failed_cancel(data: schemas.RefundFailedCancelIn,
                                db: Session = Depends(get_db_session),
                                user: User = Depends(require_authority(Action.FAILED_CANCEL)),
                                idempotency_key: str = Header(None, alias=idem.HEADER)):
    """Failed → Cancel — Admin/Kasir, dana dari Laci. BUKAN refund garansi. P2-14: idempotency."""
    return _dengan_idem(db, "refunds.failed_cancel", idempotency_key, data.model_dump(),
                        lambda: _refund_failed_cancel_impl(data, db, user))


def _refund_failed_cancel_impl(data, db, user):
    oleh = user.display_name or user.username
    return _jalankan(lambda: refunds_mod.refund_failed_cancel(
        db, data.service_order_id, data.nominal, data.alasan, oleh), db, oleh)


@router.get("/precheck/dp/{service_order_id}")
def precheck_dp(service_order_id: int, db: Session = Depends(get_db_session),
                user: User = Depends(get_authenticated_user)):
    return refunds_mod.precheck_dp(db, service_order_id)


@router.get("/precheck/garansi/{warranty_claim_id}")
def precheck_garansi(warranty_claim_id: int,
                     nominal: float = Query(0, description="nominal kesepakatan (opsional)"),
                     db: Session = Depends(get_db_session),
                     user: User = Depends(get_authenticated_user)):
    return refunds_mod.precheck_garansi(db, warranty_claim_id, nominal or None)


@router.get("", response_model=schemas.RefundPage)
def list_refunds(db: Session = Depends(get_db_session),
                 page: int = DEFAULT_PAGE, limit: int = DEFAULT_LIMIT,
                 jenis: str = Query("", description="DP | GARANSI | FAILED_CANCEL"),
                 service_order_id: int = Query(None)):
    """Riwayat refund (read-only)."""
    page = max(DEFAULT_PAGE, page)
    limit = min(MAX_LIMIT, max(1, limit))
    q = db.query(Refund)
    if (jenis or "").strip():
        q = q.filter(Refund.jenis == jenis.strip().upper())
    if service_order_id is not None:
        q = q.filter(Refund.service_order_id == service_order_id)
    total = q.count()
    rows = (q.order_by(Refund.id.desc())
            .offset((page - 1) * limit).limit(limit).all())
    return schemas.RefundPage(total=total, page=page, limit=limit,
                              total_pages=(total + limit - 1) // limit if total else 1,
                              items=[_to_out(r) for r in rows])


@router.get("/{refund_id}", response_model=schemas.RefundOut)
def get_refund(refund_id: int, db: Session = Depends(get_db_session)):
    row = db.query(Refund).filter(Refund.id == refund_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Refund tidak ditemukan")
    return _to_out(row)
