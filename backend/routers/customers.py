"""Customers endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from dependencies import get_db_session
from models import Customer, ServiceOrder
import schemas

router = APIRouter(prefix="/api/customers", tags=["customers"])

DEFAULT_PAGE = 1
DEFAULT_LIMIT = 10
MAX_LIMIT = 10


@router.get("", response_model=list[schemas.CustomerOut])
def list_customers(db: Session = Depends(get_db_session)):
    return db.query(Customer).order_by(Customer.created_at.desc()).all()


@router.get("/summary", response_model=schemas.CustomerSummaryPage)
def customer_summary(
    db: Session = Depends(get_db_session),
    page: int = DEFAULT_PAGE,
    limit: int = DEFAULT_LIMIT,
):
    """Master pelanggan + ringkasan servis terakhir (paginated, backend-side).

    Satu record per identitas pelanggan (Customer). Transaksi tetap menjadi history.
    """
    page = max(DEFAULT_PAGE, page)
    limit = min(MAX_LIMIT, max(1, limit))

    # Agregat per pelanggan: jumlah servis + waktu servis terakhir
    agg = (
        db.query(
            ServiceOrder.customer_id.label("cid"),
            func.count(ServiceOrder.id).label("cnt"),
            func.max(ServiceOrder.created_at).label("last_at"),
        )
        .group_by(ServiceOrder.customer_id)
        .subquery()
    )

    total = db.query(Customer).count()
    rows = (
        db.query(Customer, agg.c.cnt, agg.c.last_at)
        .outerjoin(agg, agg.c.cid == Customer.id)
        .order_by(agg.c.last_at.desc().nullslast(), Customer.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )

    # Detail servis terakhir untuk pelanggan di halaman ini saja
    cids = [c.id for c, _, _ in rows]
    latest = {}
    if cids:
        for o in (
            db.query(ServiceOrder)
            .filter(ServiceOrder.customer_id.in_(cids))
            .order_by(ServiceOrder.created_at.desc(), ServiceOrder.id.desc())
            .all()
        ):
            latest.setdefault(o.customer_id, o)

    items = []
    for c, cnt, _ in rows:
        o = latest.get(c.id)
        items.append(
            schemas.CustomerSummary(
                id=c.id,
                name=c.name,
                phone=c.phone,
                last_device=o.device if o else None,
                last_action=o.repair_plan if o else None,
                last_price=o.estimate if o else None,
                total_servis=cnt or 0,
            )
        )

    total_pages = (total + limit - 1) // limit if total else 1
    return schemas.CustomerSummaryPage(
        total=total,
        page=page,
        limit=limit,
        total_pages=total_pages,
        items=items,
    )


@router.get("/{customer_id}", response_model=schemas.CustomerOut)
def get_customer(customer_id: int, db: Session = Depends(get_db_session)):
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer tidak ditemukan")
    return customer


@router.post("", response_model=schemas.CustomerOut, status_code=201)
def create_customer(data: schemas.CustomerCreate, db: Session = Depends(get_db_session)):
    customer = Customer(**data.model_dump())
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer


@router.put("/{customer_id}", response_model=schemas.CustomerOut)
def update_customer(customer_id: int, data: schemas.CustomerUpdate, db: Session = Depends(get_db_session)):
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer tidak ditemukan")
    for key, val in data.model_dump(exclude_unset=True).items():
        setattr(customer, key, val)
    db.commit()
    db.refresh(customer)
    return customer


@router.delete("/{customer_id}")
def delete_customer(customer_id: int, db: Session = Depends(get_db_session)):
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer tidak ditemukan")
    db.delete(customer)
    db.commit()
    return {"ok": True}
