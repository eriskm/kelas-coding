"""Service orders endpoints."""
import random
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from dependencies import get_db_session
from models import ServiceOrder, Customer
import schemas

router = APIRouter(prefix="/api/orders", tags=["orders"])

TECHNICIANS = ["Budi", "Andi", "Rizky", "Dedi", "Fajar"]


def _generate_no_servis() -> str:
    return "SV-" + datetime.now().strftime("%Y%m%d") + "-" + str(random.randint(1000, 9999))


@router.get("/technicians")
def list_technicians():
    return TECHNICIANS


@router.get("/history/{phone}")
def order_history(phone: str, db: Session = Depends(get_db_session)):
    customers = db.query(Customer).filter(Customer.phone == phone).all()
    if not customers:
        return []
    cids = [c.id for c in customers]
    return (
        db.query(ServiceOrder)
        .filter(ServiceOrder.customer_id.in_(cids))
        .order_by(ServiceOrder.created_at.desc())
        .limit(20)
        .all()
    )


@router.post("/receive", response_model=schemas.ServiceOrderOut, status_code=201)
def receive_unit(data: schemas.ServiceReceiveIn, db: Session = Depends(get_db_session)):
    """Daftarkan unit servis baru (buat customer + service order sekaligus)."""
    customer = None
    if data.customer_phone:
        customer = (
            db.query(Customer)
            .filter(Customer.phone == data.customer_phone)
            .order_by(Customer.id.desc())
            .first()
        )
    if not customer:
        customer = Customer(name=data.customer_name, phone=data.customer_phone)
        db.add(customer)
        db.commit()
        db.refresh(customer)
    elif data.customer_name and data.customer_name.strip() and customer.name != data.customer_name.strip():
        # Opsi (a): nomor WA sama = identitas sama → koreksi nama terbaru.
        # Tidak membuat customer baru; No. Servis dan histori order lain tidak berubah.
        customer.name = data.customer_name.strip()
        db.commit()
        db.refresh(customer)

    order = ServiceOrder(
        no_servis=_generate_no_servis(),
        customer_id=customer.id,
        device=data.device,
        damagetype=data.damagetype,
        device_password=data.device_password,
        imei=(data.imei or "").strip() or None,
        check_fisik=list(data.check_fisik or []),
        check_len=list(data.check_len) if data.check_len is not None else ["unit_saja"],
        repair_plan=data.repair_plan,
        technician=data.technician,
        status=data.status,
        estimate=data.estimate or 0,
        payment=data.dp or 0,
        service_date=date.today(),
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


DEFAULT_PAGE = 1
DEFAULT_LIMIT = 10
MAX_LIMIT = 10


def _to_list_schema(o):
    return schemas.ServiceOrderList(
        id=o.id,
        no_servis=o.no_servis,
        customer_id=o.customer_id,
        device=o.device,
        brand=o.brand,
        model=o.model,
        damagetype=o.damagetype,
        imei=o.imei,
        check_fisik=list(o.check_fisik or []),
        check_len=list(o.check_len) if o.check_len is not None else ["unit_saja"],
        technician=o.technician,
        status=o.status,
        estimate=o.estimate,
        payment=o.payment,
        service_date=o.service_date,
        final_price=o.final_price,
        part_cost=o.part_cost,
        modal_jasa=o.modal_jasa,
        modal_lainnya=o.modal_lainnya,
        cash_date=o.cash_date,
        cash_at=o.cash_at,
        warranty_months=o.warranty_months,
        created_at=o.created_at,
        customer_name=o.customer.name if o.customer else None,
        customer_phone=o.customer.phone if o.customer else None,
    )


def _page_clamp(page: int, limit: int):
    page = max(DEFAULT_PAGE, page)
    limit = min(MAX_LIMIT, max(1, limit))
    return page, limit


@router.get("", response_model=schemas.ServiceOrderPage)
def list_orders(
    db: Session = Depends(get_db_session),
    page: int = DEFAULT_PAGE,
    limit: int = DEFAULT_LIMIT,
):
    """Daftar servis order dengan pagination (backend-side)."""
    page, limit = _page_clamp(page, limit)
    total = db.query(ServiceOrder).count()
    rows = (
        db.query(ServiceOrder)
        .options(joinedload(ServiceOrder.customer))
        .order_by(ServiceOrder.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )
    items = [_to_list_schema(o) for o in rows]
    total_pages = (total + limit - 1) // limit if total else 1
    return schemas.ServiceOrderPage(
        total=total,
        page=page,
        limit=limit,
        total_pages=total_pages,
        items=items,
    )


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
                imei=o.imei,
                check_fisik=list(o.check_fisik or []),
                check_len=list(o.check_len) if o.check_len is not None else ["unit_saja"],
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
    payload = data.model_dump(exclude_unset=True)
    # Masa garansi toko hanya 0 (tidak garansi) / 1 / 3 / 6 bulan.
    if "warranty_months" in payload and payload["warranty_months"] not in (0, 1, 3, 6):
        raise HTTPException(status_code=400,
                            detail="Masa garansi tidak valid. Pilihan: 1, 3, 6 bulan atau 0 (tidak garansi)")
    # Syarat CASH: Tindakan Perbaikan + Harga Final + Teknisi wajib isi.
    # Modal Part kosong dianggap Rp0 (bukan error).
    # Syarat DONE (lebih ringan): Tindakan Perbaikan + Teknisi wajib isi.
    if payload.get("status") == "CASH":
        missing = []
        plan = payload.get("repair_plan", order.repair_plan)
        if not (plan or "").strip():
            missing.append("Tindakan Perbaikan")
        final = payload.get("final_price", order.final_price)
        if not (final or 0) > 0:
            missing.append("Harga Final")
        tech = payload.get("technician", order.technician)
        if not (tech or "").strip():
            missing.append("Teknisi Penanggung Jawab")
        if missing:
            raise HTTPException(status_code=400,
                                detail="Status CASH wajib melengkapi: " + ", ".join(missing))
        if payload.get("part_cost") is None and order.part_cost is None:
            payload["part_cost"] = 0
    elif payload.get("status") == "DONE":
        missing = []
        plan = payload.get("repair_plan", order.repair_plan)
        if not (plan or "").strip():
            missing.append("Tindakan Perbaikan")
        tech = payload.get("technician", order.technician)
        if not (tech or "").strip():
            missing.append("Teknisi Penanggung Jawab")
        if missing:
            raise HTTPException(status_code=400,
                                detail="Status DONE wajib melengkapi: " + ", ".join(missing))
    for key, val in payload.items():
        setattr(order, key, val)
    # Awal masa garansi: dikunci saat pertama kali CASH, tidak berubah setelahnya.
    # Default 1 bulan bila CASH tanpa pilihan masa garansi.
    # cash_at = jam penetapan CASH (scope periode kas 16:00).
    if order.status == "CASH" and order.cash_date is None:
        order.cash_date = date.today()
    if order.status == "CASH" and order.cash_at is None:
        order.cash_at = datetime.now()
    if order.status == "CASH" and order.warranty_months is None:
        order.warranty_months = 1
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
