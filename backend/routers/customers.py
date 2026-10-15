"""Customers endpoints."""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from authority import Action, require_authority
from dependencies import get_db_session
from models import Customer, ServiceOrder, User, WarrantyClaim
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
    q: Optional[str] = Query(default=None, description="Cari nama / No. WA"),
    date: Optional[str] = Query(default=None, description="Filter tanggal terakhir servis (YYYY-MM-DD)"),
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
    base = db.query(Customer, agg.c.cnt, agg.c.last_at).outerjoin(
        agg, agg.c.cid == Customer.id
    )
    if q and q.strip():
        like = "%" + q.strip() + "%"
        base = base.filter(
            or_(Customer.name.ilike(like), Customer.phone.ilike(like))
        )
        total = base.order_by().with_entities(func.count(Customer.id)).scalar() or 0
    if date and date.strip():
        try:
            day = datetime.strptime(date.strip(), "%Y-%m-%d").date()
            base = base.filter(func.date(agg.c.last_at) == day.isoformat())
            total = base.order_by().with_entities(func.count(Customer.id)).scalar() or 0
        except ValueError:
            pass
    rows = (
        base.order_by(agg.c.last_at.desc().nullslast(), Customer.created_at.desc())
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
    for c, cnt, last_at in rows:
        o = latest.get(c.id)
        o_date = None
        if o is not None:
            o_date = o.service_date.isoformat() if o.service_date else None
            if not o_date and last_at is not None:
                o_date = last_at.date().isoformat() if hasattr(last_at, "date") else None
        o_price = None
        if o is not None:
            o_price = o.final_price if o.final_price is not None else o.estimate
        items.append(
            schemas.CustomerSummary(
                id=c.id,
                name=c.name,
                phone=c.phone,
                last_device=o.device if o else None,
                last_action=o.repair_plan if o else None,
                last_price=o_price,
                total_servis=cnt or 0,
                last_at=o_date,
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


@router.get("/{customer_id}/detail")
def customer_detail(customer_id: int, db: Session = Depends(get_db_session)):
    """Detail pelanggan by ID: agregat + seluruh riwayat servis (data real)."""
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer tidak ditemukan")
    orders = (
        db.query(ServiceOrder)
        .filter(ServiceOrder.customer_id == customer_id)
        .order_by(ServiceOrder.created_at.desc(), ServiceOrder.id.desc())
        .all()
    )
    devices = {o.device for o in orders if o.device}
    total_nilai = sum(
        (o.final_price if o.final_price is not None else (o.estimate or 0))
        for o in orders
    )
    first = orders[0] if orders else None
    last_at = None
    if first is not None:
        if first.service_date:
            last_at = first.service_date.isoformat()
        elif first.created_at:
            last_at = first.created_at.isoformat()
    return {
        "customer": {
            "id": customer.id,
            "name": customer.name,
            "phone": customer.phone,
        },
        "total_servis": len(orders),
        "device_count": len(devices),
        "total_nilai": total_nilai,
        "last_at": last_at,
        "orders": [
            {
                "id": o.id,
                "no_servis": o.no_servis,
                "device": o.device,
                "damagetype": o.damagetype,
                "repair_plan": o.repair_plan,
                "technician": o.technician,
                "status": o.status,
                "estimate": o.estimate,
                "final_price": o.final_price,
                "service_date": o.service_date.isoformat() if o.service_date else None,
                "created_at": o.created_at.isoformat() if o.created_at else None,
            }
            for o in orders
        ],
    }


@router.get("/{customer_id}", response_model=schemas.CustomerOut)
def get_customer(customer_id: int, db: Session = Depends(get_db_session)):
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer tidak ditemukan")
    return customer


@router.post("", response_model=schemas.CustomerOut, status_code=201)
def create_customer(data: schemas.CustomerCreate,
                   db: Session = Depends(get_db_session),
                   user: User = Depends(require_authority(Action.CUSTOMER_WRITE))):
    customer = Customer(**data.model_dump())
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer


@router.put("/{customer_id}", response_model=schemas.CustomerOut)
def update_customer(customer_id: int, data: schemas.CustomerUpdate,
                   db: Session = Depends(get_db_session),
                   user: User = Depends(require_authority(Action.CUSTOMER_WRITE))):
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer tidak ditemukan")
    for key, val in data.model_dump(exclude_unset=True).items():
        setattr(customer, key, val)
    db.commit()
    db.refresh(customer)
    return customer


@router.delete("/{customer_id}")
def delete_customer(customer_id: int, db: Session = Depends(get_db_session),
                   user: User = Depends(require_authority(Action.CUSTOMER_DELETE))):
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer tidak ditemukan")
    n_order = (
        db.query(ServiceOrder).filter(ServiceOrder.customer_id == customer_id).count()
    )
    n_claim = (
        db.query(WarrantyClaim).filter(WarrantyClaim.customer_id == customer_id).count()
    )
    if n_order or n_claim:
        raise HTTPException(
            status_code=409,
            detail=(
                "Pelanggan memiliki relasi aktif ("
                + str(n_order) + " servis, " + str(n_claim) + " klaim)"
                + " — tidak dapat dihapus."
            ),
        )
    db.delete(customer)
    db.commit()
    return {"ok": True}
