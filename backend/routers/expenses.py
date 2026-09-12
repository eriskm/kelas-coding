"""Expenses endpoints — beban toko (Gaji/Operasional/...) per periode kas.

Beban dicatat di sini (mis. dari popup Beban Harian), BUKAN modal transaksi.
Modal Part/Jasa/Lainnya tetap atribut ServiceOrder (Update Data Servis).
"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from dependencies import get_db_session
from models import Expense
import schemas

router = APIRouter(prefix="/api/expenses", tags=["expenses"])

DEFAULT_PAGE = 1
DEFAULT_LIMIT = 50
MAX_LIMIT = 100


@router.get("", response_model=schemas.ExpensePage)
def list_expenses(
    db: Session = Depends(get_db_session),
    page: int = DEFAULT_PAGE,
    limit: int = DEFAULT_LIMIT,
    kategori: str = Query("", description="Filter kategori: Gaji | Operasional | ..."),
):
    page = max(DEFAULT_PAGE, page)
    limit = min(MAX_LIMIT, max(1, limit))
    q = db.query(Expense)
    if kategori.strip():
        q = q.filter(Expense.kategori == kategori.strip())
    total = q.count()
    rows = q.order_by(Expense.created_at.desc()).offset((page - 1) * limit).limit(limit).all()
    total_pages = (total + limit - 1) // limit if total else 1
    return schemas.ExpensePage(total=total, page=page, limit=limit, total_pages=total_pages, items=rows)


@router.post("", response_model=schemas.ExpenseOut, status_code=201)
def create_expense(data: schemas.ExpenseCreate, db: Session = Depends(get_db_session)):
    kat = (data.kategori or "").strip()
    uraian = (data.uraian or "").strip()
    if not kat:
        raise HTTPException(status_code=400, detail="Kategori beban wajib diisi")
    if not uraian:
        raise HTTPException(status_code=400, detail="Uraian beban wajib diisi")
    nilai = data.nilai or 0
    if nilai < 0:
        raise HTTPException(status_code=400, detail="Nilai beban tidak boleh negatif")
    row = Expense(kategori=kat, uraian=uraian, nilai=nilai, tanggal=data.tanggal or date.today())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.put("/{expense_id}", response_model=schemas.ExpenseOut)
def update_expense(expense_id: int, data: schemas.ExpenseUpdate, db: Session = Depends(get_db_session)):
    row = db.query(Expense).filter(Expense.id == expense_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Beban tidak ditemukan")
    payload = data.model_dump(exclude_unset=True)
    if "nilai" in payload and (payload["nilai"] or 0) < 0:
        raise HTTPException(status_code=400, detail="Nilai beban tidak boleh negatif")
    for key, val in payload.items():
        setattr(row, key, val)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/{expense_id}")
def delete_expense(expense_id: int, db: Session = Depends(get_db_session)):
    row = db.query(Expense).filter(Expense.id == expense_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Beban tidak ditemukan")
    db.delete(row)
    db.commit()
    return {"ok": True}
