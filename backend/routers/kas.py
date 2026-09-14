"""Kas endpoints — jurnal manual, riwayat gabungan, tutup kas.

Prinsip single source of truth (FINAL LOCK):
- Pemasukan servis = jurnal payments (DP/PELUNASAN) dalam periode.
- Beban = expenses (popup Beban Harian).
- kas_entries HANYA untuk arus kas di luar keduanya (pemasukan non-servis,
  saldo awal, penyesuaian). Bukan duplikat order/expense.
- Tutup Kas TIDAK mengubah status apa pun (hanya tutup periode + snapshot).
"""
import json
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from dependencies import get_db_session
from models import Expense, KasEntry, KasPeriod, Payment, ServiceOrder, User
from routers.auth import get_authenticated_user
from routers.dashboard import _period_bounds, compute_finance, get_active_period
import schemas

router = APIRouter(prefix="/api/kas", tags=["kas"])

SALDO_AWAL_KATEGORI = "Saldo Awal"

DEFAULT_PAGE = 1
DEFAULT_LIMIT = 50
MAX_LIMIT = 100


def _num(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _moment(dt_val, d_val) -> Optional[datetime]:
    if dt_val is not None:
        return dt_val
    if d_val is not None:
        return datetime(d_val.year, d_val.month, d_val.day, 12, 0, 0)
    return None


def opening_balance(db: Session) -> float:
    """Saldo awal = neto seluruh entri 'Saldo Awal' lintas periode (sekali definisi)."""
    rows = db.query(KasEntry).filter(KasEntry.kategori == SALDO_AWAL_KATEGORI).all()
    return sum(_num(r.nominal) if (r.jenis or "").strip().lower() == "masuk" else -_num(r.nominal) for r in rows)


def period_rows(db: Session, start: datetime, end: datetime):
    """Seluruh baris kas dalam [start, end) terurut menaik + saldo berjalan.
    Entri 'Saldo Awal' dikecualikan dari baris (sudah tercakup di opening)."""
    rows = []

    for p in db.query(Payment).options(joinedload(Payment.service_order)).all():
        m = _moment(getattr(p, "created_at", None), None)
        if m is None or not (start <= m < end):
            continue
        o = p.service_order
        kind = (p.kind or "PELUNASAN").strip().upper()
        rows.append({
            "moment": m,
            "tgl": m.date().isoformat() if hasattr(m, "date") else None,
            "jenis": "Masuk",
            "kategori": "DP" if kind == "DP" else "Pelunasan",
            "ket": "%s • %s" % ((o.device if o else None) or "-",
                                (o.no_servis if o else None) or "-"),
            "nominal": _num(p.amount),
            "source": "order",
            "ref_id": p.id,
        })

    for e in db.query(Expense).all():
        m = _moment(getattr(e, "created_at", None), getattr(e, "tanggal", None))
        if m is None or not (start <= m < end):
            continue
        rows.append({
            "moment": m,
            "tgl": (e.tanggal.isoformat() if e.tanggal
                    else (m.date().isoformat() if hasattr(m, "date") else None)),
            "jenis": "Keluar",
            "kategori": e.kategori,
            "ket": e.uraian,
            "nominal": _num(e.nilai),
            "source": "expense",
            "ref_id": e.id,
        })

    for k in db.query(KasEntry).filter(KasEntry.kategori != SALDO_AWAL_KATEGORI).all():
        m = _moment(getattr(k, "created_at", None), getattr(k, "tanggal", None))
        if m is None or not (start <= m < end):
            continue
        j = (k.jenis or "").strip().capitalize()
        if j not in ("Masuk", "Keluar"):
            continue
        rows.append({
            "moment": m,
            "tgl": (k.tanggal.isoformat() if k.tanggal
                    else (m.date().isoformat() if hasattr(m, "date") else None)),
            "jenis": j,
            "kategori": k.kategori,
            "ket": k.keterangan,
            "nominal": _num(k.nominal),
            "source": "manual",
            "ref_id": k.id,
        })

    rows.sort(key=lambda r: (r["moment"], r["source"], r["ref_id"] or 0))
    saldo = opening_balance(db)
    for r in rows:
        saldo += r["nominal"] if r["jenis"] == "Masuk" else -r["nominal"]
        r["saldo"] = saldo
        del r["moment"]
    return rows


def _clamp(page: int, limit: int):
    return max(DEFAULT_PAGE, page), min(MAX_LIMIT, max(1, limit))


# ---------- Jurnal manual ----------
@router.get("/entries", response_model=schemas.KasEntryPage)
def list_entries(db: Session = Depends(get_db_session), page: int = DEFAULT_PAGE,
                 limit: int = DEFAULT_LIMIT, q: str = Query("")):
    page, limit = _clamp(page, limit)
    qry = db.query(KasEntry)
    if q.strip():
        like = "%" + q.strip() + "%"
        qry = qry.filter(or_(KasEntry.keterangan.ilike(like), KasEntry.kategori.ilike(like)))
    total = qry.count()
    rows = qry.order_by(KasEntry.id.desc()).offset((page - 1) * limit).limit(limit).all()
    return schemas.KasEntryPage(total=total, page=page, limit=limit,
                                total_pages=(total + limit - 1) // limit if total else 1, items=rows)


@router.post("/entries", response_model=schemas.KasEntryOut, status_code=201)
def create_entry(data: schemas.KasEntryCreate, db: Session = Depends(get_db_session)):
    jenis = (data.jenis or "").strip().capitalize()
    if jenis not in ("Masuk", "Keluar"):
        raise HTTPException(status_code=400, detail="Jenis wajib Masuk atau Keluar")
    if not (data.kategori or "").strip():
        raise HTTPException(status_code=400, detail="Kategori wajib diisi")
    if not (data.keterangan or "").strip():
        raise HTTPException(status_code=400, detail="Keterangan wajib diisi")
    nominal = _num(data.nominal)
    if nominal < 0:
        raise HTTPException(status_code=400, detail="Nominal tidak boleh negatif")
    row = KasEntry(jenis=jenis, kategori=data.kategori.strip(),
                   keterangan=data.keterangan.strip(), nominal=nominal,
                   tanggal=data.tanggal)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.put("/entries/{entry_id}", response_model=schemas.KasEntryOut)
def update_entry(entry_id: int, data: schemas.KasEntryUpdate, db: Session = Depends(get_db_session)):
    row = db.query(KasEntry).filter(KasEntry.id == entry_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Entri kas tidak ditemukan")
    payload = data.model_dump(exclude_unset=True)
    if "jenis" in payload:
        j = (payload["jenis"] or "").strip().capitalize()
        if j not in ("Masuk", "Keluar"):
            raise HTTPException(status_code=400, detail="Jenis wajib Masuk atau Keluar")
        payload["jenis"] = j
    if "nominal" in payload and _num(payload["nominal"]) < 0:
        raise HTTPException(status_code=400, detail="Nominal tidak boleh negatif")
    for key, val in payload.items():
        setattr(row, key, val)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/entries/{entry_id}")
def delete_entry(entry_id: int, db: Session = Depends(get_db_session)):
    row = db.query(KasEntry).filter(KasEntry.id == entry_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Entri kas tidak ditemukan")
    db.delete(row)
    db.commit()
    return {"ok": True}


# ---------- Riwayat gabungan ----------
@router.get("/riwayat", response_model=schemas.KasRiwayatPage)
def kas_riwayat(db: Session = Depends(get_db_session), page: int = DEFAULT_PAGE,
                limit: int = DEFAULT_LIMIT, q: str = Query(""),
                jenis: str = Query(""), date: str = Query(""),
                period: str = Query("all", description="all | current")):
    """Riwayat kas gabungan (jurnal payments + expenses + jurnal manual) + saldo berjalan.
    Read-only turunan — tanpa tabel baru, tanpa persistence."""
    page, limit = _clamp(page, limit)
    period = (period or "all").strip().lower()
    if period == "current":
        p = get_active_period(db)
        rows = period_rows(db, p.start_at, p.end_at)
    else:
        rows = period_rows(db, datetime.min, datetime.max)

    if jenis.strip():
        j = jenis.strip().capitalize()
        rows = [r for r in rows if r["jenis"] == j]
    if date.strip():
        rows = [r for r in rows if (r["tgl"] or "") == date.strip()]
    if q.strip():
        ql = q.strip().lower()
        rows = [r for r in rows if ql in str(r.get("ket") or "").lower()
                or ql in str(r.get("kategori") or "").lower()]

    total = len(rows)
    total_pages = (total + limit - 1) // limit if total else 1
    page = min(max(DEFAULT_PAGE, page), total_pages)
    shown = rows[::-1]
    items = shown[(page - 1) * limit:page * limit]
    return schemas.KasRiwayatPage(total=total, page=page, limit=limit,
                                  total_pages=total_pages,
                                  opening=opening_balance(db), items=items)


# ---------- Tutup kas ----------
@router.post("/close")
def close_period(data: schemas.KasCloseIn, db: Session = Depends(get_db_session),
                 user: User = Depends(get_authenticated_user)):
    """Tutup periode aktif: kunci snapshot keuangan, arsipkan, buka periode baru."""
    period = get_active_period(db)
    fin = compute_finance(db, period.start_at, period.end_at)
    counted = data.cash_counted
    selisih = (float(counted) - float(fin.get("saldo", 0))) if counted is not None else None
    snapshot = {
        "period": {"id": period.id, "start_at": period.start_at.isoformat(),
                   "end_at": period.end_at.isoformat()},
        "finance": fin,
        "cash_counted": counted,
        "selisih": selisih,
    }
    now = datetime.now()
    period.status = "CLOSED"
    period.closed_at = now
    period.closed_by = user.display_name or user.username
    period.snapshot = json.dumps(snapshot)
    new_period = KasPeriod(start_at=now, end_at=now + timedelta(days=1),
                           status="OPEN")
    db.add(new_period)
    db.commit()
    db.refresh(new_period)
    return {"ok": True, "closed_period_id": period.id, "snapshot": snapshot,
            "new_period": {"id": new_period.id, "start_at": new_period.start_at.isoformat(),
                           "end_at": new_period.end_at.isoformat()}}


@router.get("/periods", response_model=list[schemas.KasPeriodDetailOut])
def list_periods(db: Session = Depends(get_db_session)):
    return db.query(KasPeriod).order_by(KasPeriod.id.desc()).limit(50).all()
