"""P2-11 — endpoint Hutang Beban (SSOT-8 / Q8 / Q18).

Authority (Q13: PENGELOLA read-oriented):
- baca (GET)  : semua akun terautentikasi, termasuk PENGELOLA (monitoring);
- tulis       : `Action.EXPENSE_DEBT_WRITE` = Admin saja (PENGELOLA 403).
"""
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

import expense_debt as debt_mod
import idempotency as idem
from authority import Action, require_authority
from dependencies import get_db_session
from models import KasPeriod, User
from routers.auth import get_authenticated_user

router = APIRouter(prefix="/api/beban-hutang", tags=["beban-hutang"])


def _dengan_idem(db, scope: str, key: str, payload, aksi):
    """Jalankan aksi endpoint dengan proteksi Idempotency-Key (P2-14)."""
    if not key:
        return aksi()
    try:
        run = idem.jalankan(db, scope, key, payload, aksi)
    except idem.IdempotencyConflict as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc))
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise
    return run.get("result")


def _target_period(db: Session, kas_period_id=None):
    from routers.dashboard import get_active_period
    if kas_period_id is not None:
        row = db.query(KasPeriod).filter(KasPeriod.id == kas_period_id).first()
        if row is None:
            raise HTTPException(status_code=404, detail="Periode kas tidak ditemukan")
        return row
    return get_active_period(db)


@router.post("/proses")
def proses_defisit(kas_period_id: int = Query(None),
                   db: Session = Depends(get_db_session),
                   user: User = Depends(require_authority(Action.EXPENSE_DEBT_WRITE)),
                   idempotency_key: str = Header(None, alias=idem.HEADER)):
    """Proses defisit Beban: Kas Aset menutup dulu, sisanya Hutang (idempotent)."""
    return _dengan_idem(db, "beban_hutang.proses", idempotency_key,
                        {"kas_period_id": kas_period_id},
                        lambda: _proses_defisit_impl(kas_period_id, db, user))


def _proses_defisit_impl(kas_period_id, db, user):
    period = _target_period(db, kas_period_id)
    oleh = user.display_name or user.username
    try:
        res = debt_mod.proses_defisit(db, period.start_at, period.end_at,
                                      kas_period_id=period.id, oleh=oleh)
        db.commit()
    except debt_mod.DebtError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise
    row = res["periode_row"]
    return {"created": res["created"], "periode": row.periode,
            "beban": row.beban, "laba_kotor": row.laba_kotor, "defisit": row.defisit,
            "cover_kas_aset": row.cover_kas_aset, "hutang_baru": row.hutang_baru,
            "hutang_awal": row.hutang_awal, "hutang_akhir": row.hutang_akhir,
            "saldo_hutang": debt_mod.saldo_hutang(db),
            "sumber_dana": "KAS_ASET"}


@router.post("/lunas")
def lunas(nominal: float = Query(None, description="default = seluruh sisa hutang"),
          periode: str = Query(None),
          db: Session = Depends(get_db_session),
          user: User = Depends(require_authority(Action.EXPENSE_DEBT_WRITE)),
          idempotency_key: str = Header(None, alias=idem.HEADER)):
    """Pelunasan Hutang Beban dari Kas Aset (+ pre-check). P2-14: idempotency."""
    return _dengan_idem(db, "beban_hutang.lunas", idempotency_key,
                        {"nominal": nominal, "periode": periode},
                        lambda: _lunas_impl(nominal, periode, db, user))


def _lunas_impl(nominal, periode, db, user):
    oleh = user.display_name or user.username
    try:
        res = debt_mod.lunas_hutang(db, nominal, periode, oleh)
        db.commit()
    except debt_mod.DebtError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise
    entry = res["entry"]
    mut = res.get("kas_aset_mutation")
    # v4 #8: pelunasan TIDAK otomatis mengurangi Saldo Aset (pengeluaran aktual
    # dicatat manual Admin). Bila tetap ada mutasi (mode lama), pakai saldo
    # sesudah mutasi; tanpa mutasi -> saldo Aset berjalan saat ini.
    return {"tipe": entry.tipe, "nominal": entry.nominal,
            "saldo_hutang": res["saldo_hutang"],
            "saldo_kas_aset": (mut["saldo_setelah"] if mut
                               else res["saldo_kas_aset_setelah"]),
            "kas_entry_id": entry.kas_entry_id, "sumber_dana": "KAS_ASET",
            "efek_saldo": ("otomatis" if mut else "manual oleh Admin (v4 #8)"),
            "catatan": ("Pelunasan hanya menutup hutang; pengeluaran aktual dari "
                        "Saldo Aset dicatat manual Admin (POST /api/kas/aset/keluar).")}


@router.get("")
def status_hutang(db: Session = Depends(get_db_session),
                  user: User = Depends(get_authenticated_user)):
    """Status Hutang Beban + ledger (read-only; termasuk untuk PENGELOLA)."""
    return debt_mod.ringkasan(db)


@router.get("/precheck")
def precheck(db: Session = Depends(get_db_session),
             user: User = Depends(get_authenticated_user)):
    return debt_mod.precheck_hutang(db)


@router.get("/defisit/{kas_period_id}")
def defisit_periode(kas_period_id: int, db: Session = Depends(get_db_session),
                    user: User = Depends(get_authenticated_user)):
    """Simulasi defisit satu periode (read-only, tidak menulis apa pun)."""
    period = _target_period(db, kas_period_id)
    return debt_mod.hitung_defisit(db, period.start_at, period.end_at)
