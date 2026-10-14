"""Expenses endpoints — beban toko (Gaji/Operasional/...) per periode kas.

Beban dicatat di sini (mis. dari popup Beban Harian), BUKAN modal transaksi.
Modal Part/Jasa/Lainnya tetap atribut ServiceOrder (Update Data Servis).
"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from dependencies import get_db_session
import cash
from models import Expense, User
from authority import Action, require_authority
from routers.auth import require_admin
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
def create_expense(data: schemas.ExpenseCreate, db: Session = Depends(get_db_session),
                   user: User = Depends(require_authority(Action.EXPENSE_WRITE))):
    kat = (data.kategori or "").strip()
    uraian = (data.uraian or "").strip()
    if not kat:
        raise HTTPException(status_code=400, detail="Kategori beban wajib diisi")
    if not uraian:
        raise HTTPException(status_code=400, detail="Uraian beban wajib diisi")
    nilai = data.nilai or 0
    if nilai < 0:
        raise HTTPException(status_code=400, detail="Nilai beban tidak boleh negatif")
    # FIN-MIRROR: default True = beban permanen, sama dengan Proyek A `beban`
    # (dipotong dari setiap siklus). Admin bisa opting out per baris.
    row = Expense(kategori=kat, uraian=uraian, nilai=nilai,
                  tanggal=data.tanggal or date.today(),
                  recurring=True if data.recurring is None else bool(data.recurring))
    db.add(row)
    db.flush()
    # OD-LOCK-06 (Owner, LOCKED): pembayaran Beban TIDAK dicatat per-baris di
    # sini.
    #
    # Sebelumnya baris ini memanggil `cash.catat_beban(db, row)` yang langsung
    # mengurangi Saldo Laci. Itu menyebabkan Beban dibayar DUA KALI, karena
    # `closing.selesaikan_periode` juga membayar seluruh Total Beban periode
    # dengan penanda idempotensi yang BERBEDA (`ref_type` 'expense' vs
    # 'beban_periode'). Terbukti: Beban 300.000 mengurangi Laci 600.000.
    #
    # Sekarang satu-satunya pencatatatan pembayaran Beban adalah
    # `beban_bayar.bayar_beban_periode` (Laci -> Kas Aset -> Hutang Beban),
    # yang dipanggil saat periode dibekukan dan dipanggil ulang oleh Tutup Kas
    # untuk membayar sisa saja. Satu jalur, satu penanda, tidak ada dobel.
    db.commit()
    db.refresh(row)
    return row


@router.put("/{expense_id}", response_model=schemas.ExpenseOut)
def update_expense(expense_id: int, data: schemas.ExpenseUpdate, db: Session = Depends(get_db_session),
                   user: User = Depends(require_authority(Action.EXPENSE_WRITE))):
    row = db.query(Expense).filter(Expense.id == expense_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Beban tidak ditemukan")
    payload = data.model_dump(exclude_unset=True)
    if "nilai" in payload and (payload["nilai"] or 0) < 0:
        raise HTTPException(status_code=400, detail="Nilai beban tidak boleh negatif")
    if "kategori" in payload and not (payload["kategori"] or "").strip():
        raise HTTPException(status_code=400, detail="Kategori beban wajib diisi")
    if "uraian" in payload and not (payload["uraian"] or "").strip():
        raise HTTPException(status_code=400, detail="Uraian beban wajib diisi")
    # FIN-MIRROR: `recurring` tidak boleh di-set NULL (kolom NOT NULL).
    if payload.get("recurring") is None:
        payload.pop("recurring", None)
    for key, val in payload.items():
        setattr(row, key, val)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/{expense_id}")
def delete_expense(expense_id: int, db: Session = Depends(get_db_session),
                   admin=Depends(require_admin)):
    """Hapus beban — khusus Admin (beban masuk hitungan periode berjalan)."""
    row = db.query(Expense).filter(Expense.id == expense_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Beban tidak ditemukan")
    db.delete(row)
    db.commit()
    return {"ok": True}
