"""Service orders endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from dependencies import get_db_session
from models import ServiceOrder, Customer
import schemas

router = APIRouter(prefix="/api/orders", tags=["orders"])


@router.get("", response_model=list[schemas.ServiceOrderList])
def list_orders(db: Session = Depends(get_db_session), limit: int = 100):
    rows = (
        db.query(ServiceOrder)
        .options(joinedload(ServiceOrder.customer))
        .order_by(ServiceOrder.created_at.desc())
        .limit(limit)
        .all()
    )
    result = []
    for o in rows:
        result.append(
            schemas.ServiceOrderList(
                id=o.id,
                no_servis=o.no_servis,
                customer_id=o.customer_id,
                device=o.device,
                brand=o.brand,
                model=o.model,
                damagetype=o.damagetype,
                technician=o.technician,
                status=o.status,
                estimate=o.estimate,
                payment=o.payment,
                service_date=o.service_date,
                created_at=o.created_at,
                customer_name=o.customer.name if o.customer else None,
                customer_phone=o.customer.phone if o.customer else None,
            )
        )
    return result


@router.get("/latest", response_model=list[schemas.ServiceOrderList])
def latest_orders(db: Session = Depends(get_db_session), limit: int = 10):
    rows = (
        db.query(ServiceOrder)
        .options(joinedload(ServiceOrder.customer))
        .order_by(ServiceOrder.created_at.desc())
        .limit(limit)
        .all()
    )
    result = []
    for o in rows:
        result.append(
            schemas.ServiceOrderList(
                id=o.id,
                no_servis=o.no_servis,
                customer_id=o.customer_id,
                device=o.device,
                brand=o.brand,
                model=o.model,
                damagetype=o.damagetype,
                technician=o.technician,
                status=o.status,
                estimate=o.estimate,
                payment=o.payment,
                service_date=o.service_date,
                created_at=o.created_at,
                customer_name=o.customer.name if o.customer else None,
                customer_phone=o.customer.phone if o.customer else None,
            )
        )
    return result


@router.get("/{order_id}", response_model=schemas.ServiceOrderOut)
def get_order(order_id: int, db: Session = Depends(get_db_session)):
    order = db.query(ServiceOrder).filter(ServiceOrder.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Service order tidak ditemukan")
    return order


@router.post("", response_model=schemas.ServiceOrderOut, status_code=201)
def create_order(data: schemas.ServiceOrderCreate, db: Session = Depends(get_db_session)):
    customer = db.query(Customer).filter(Customer.id == data.customer_id).first()
    if not customer:
        raise HTTPException(status_code=400, detail="Customer tidak ditemukan")
    order = ServiceOrder(**data.model_dump())
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


@router.put("/{order_id}", response_model=schemas.ServiceOrderOut)
def update_order(order_id: int, data: schemas.ServiceOrderUpdate, db: Session = Depends(get_db_session)):
    order = db.query(ServiceOrder).filter(ServiceOrder.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Service order tidak ditemukan")
    for key, val in data.model_dump(exclude_unset=True).items():
        setattr(order, key, val)
    db.commit()
    db.refresh(order)
    return order


@router.delete("/{order_id}")
def delete_order(order_id: int, db: Session = Depends(get_db_session)):
    order = db.query(ServiceOrder).filter(ServiceOrder.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Service order tidak ditemukan")
    db.delete(order)
    db.commit()
    return {"ok": True}
