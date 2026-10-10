"""Spareparts endpoints — stok toko, satu-satunya sumber halaman Sparepart."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from dependencies import get_db_session
from models import Sparepart, User
from authority import Action, require_authority
from routers.auth import require_admin
import schemas

router = APIRouter(prefix="/api/spareparts", tags=["spareparts"])

DEFAULT_PAGE = 1
DEFAULT_LIMIT = 50
MAX_LIMIT = 100


@router.get("", response_model=schemas.SparepartPage)
def list_spareparts(db: Session = Depends(get_db_session), page: int = DEFAULT_PAGE,
                    limit: int = DEFAULT_LIMIT, q: str = Query("")):
    page = max(DEFAULT_PAGE, page)
    limit = min(MAX_LIMIT, max(1, limit))
    qry = db.query(Sparepart)
    if q.strip():
        like = "%" + q.strip() + "%"
        qry = qry.filter(or_(Sparepart.jenis.ilike(like), Sparepart.merek.ilike(like),
                             Sparepart.device.ilike(like), Sparepart.kategori.ilike(like)))
    total = qry.count()
    rows = qry.order_by(Sparepart.id.desc()).offset((page - 1) * limit).limit(limit).all()
    return schemas.SparepartPage(total=total, page=page, limit=limit,
                                 total_pages=(total + limit - 1) // limit if total else 1,
                                 items=rows)


@router.post("", response_model=schemas.SparepartOut, status_code=201)
def create_sparepart(data: schemas.SparepartCreate, db: Session = Depends(get_db_session),
                   user: User = Depends(require_authority(Action.SPAREPART_WRITE))):
    if not (data.jenis or "").strip():
        raise HTTPException(status_code=400, detail="Jenis sparepart wajib diisi")
    qty = data.qty or 0
    if qty < 0:
        raise HTTPException(status_code=400, detail="Qty tidak boleh negatif")
    for f in ("harga_beli", "harga_jual"):
        if (getattr(data, f) or 0) < 0:
            raise HTTPException(status_code=400, detail="Harga tidak boleh negatif")
    row = Sparepart(kategori=(data.kategori or "").strip() or None,
                    merek=(data.merek or "").strip() or None,
                    jenis=data.jenis.strip(),
                    device=(data.device or "").strip() or None,
                    qty=qty, harga_beli=data.harga_beli or 0,
                    harga_jual=data.harga_jual or 0,
                    tanggal=data.tanggal or date.today())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.put("/{sparepart_id}", response_model=schemas.SparepartOut)
def update_sparepart(sparepart_id: int, data: schemas.SparepartUpdate,
                     db: Session = Depends(get_db_session),
                   user: User = Depends(require_authority(Action.SPAREPART_WRITE))):
    row = db.query(Sparepart).filter(Sparepart.id == sparepart_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Sparepart tidak ditemukan")
    payload = data.model_dump(exclude_unset=True)
    if "qty" in payload and (payload["qty"] or 0) < 0:
        raise HTTPException(status_code=400, detail="Qty tidak boleh negatif")
    if "jenis" in payload and not (payload["jenis"] or "").strip():
        raise HTTPException(status_code=400, detail="Jenis sparepart wajib diisi")
    for f in ("harga_beli", "harga_jual"):
        if f in payload and (payload[f] or 0) < 0:
            raise HTTPException(status_code=400, detail="Harga tidak boleh negatif")
    for key, val in payload.items():
        setattr(row, key, val)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/{sparepart_id}")
def delete_sparepart(sparepart_id: int, db: Session = Depends(get_db_session),
                     admin=Depends(require_admin)):
    """Hapus sparepart — khusus Admin."""
    row = db.query(Sparepart).filter(Sparepart.id == sparepart_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Sparepart tidak ditemukan")
    db.delete(row)
    db.commit()
    return {"ok": True}
