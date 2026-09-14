"""Service orders endpoints (FINAL LOCK: 3 dimensi terpisah)."""
import random
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from dependencies import get_db_session
from models import Payment, ServiceOrder, Customer, StatusHistory, User
from routers.auth import get_authenticated_user
from statusflow import (
    SERVICE_STATUSES,
    TERMINAL_STATUSES,
    check_transition,
    lock_lunas_moment,
    payment_summary,
)
import schemas

router = APIRouter(prefix="/api/orders", tags=["orders"])

TECHNICIANS = ["Budi", "Andi", "Rizky", "Dedi", "Fajar"]


def _generate_no_servis() -> str:
    return "SV-" + datetime.now().strftime("%Y%m%d") + "-" + str(random.randint(1000, 9999))


def _actor(user) -> str:
    try:
        return (getattr(user, "display_name", None) or getattr(user, "username", None) or "sistem")
    except Exception:
        return "sistem"


def _log_transition(db: Session, order_id: int, dari, ke, oleh, catatan=""):
    db.add(StatusHistory(service_order_id=order_id, dari_status=dari,
                         ke_status=ke, oleh=oleh, waktu=datetime.now(),
                         catatan=(catatan or "") or None))


def _attach_summary(db: Session, order):
    """Tempel ringkasan pembayaran (derive) ke objek response."""
    pays = db.query(Payment).filter(Payment.service_order_id == order.id).all()
    s = payment_summary(order, pays)
    order.payment_status = s["payment_status"]
    order.total_bayar = s["total_bayar"]
    order.sisa = s["sisa"]
    return s


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
def receive_unit(data: schemas.ServiceReceiveIn, db: Session = Depends(get_db_session),
                 user: User = Depends(get_authenticated_user)):
    """Daftarkan unit servis baru (buat customer + service order sekaligus)."""
    st = (data.status or "DITERIMA").strip() or "DITERIMA"
    if st not in SERVICE_STATUSES:
        raise HTTPException(status_code=400,
                            detail="Status tidak valid: %s. Pilihan: %s" % (st, ", ".join(SERVICE_STATUSES)))
    ok, msg = check_transition("", st)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
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
        status=st,
        unit_status="DI TOKO",
        estimate=data.estimate or 0,
        payment=data.dp or 0,
        service_date=date.today(),
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    _log_transition(db, order.id, None, st, _actor(user), "pendaftaran unit")
    db.commit()
    db.refresh(order)
    _attach_summary(db, order)
    return order


DEFAULT_PAGE = 1
DEFAULT_LIMIT = 10
MAX_LIMIT = 10


def _summaries(db: Session, orders):
    """Ringkasan pembayaran per order (satu query payments untuk semua id)."""
    ids = [o.id for o in orders]
    pays = db.query(Payment).filter(Payment.service_order_id.in_(ids)).all() if ids else []
    by_order = {}
    for p in pays:
        by_order.setdefault(p.service_order_id, []).append(p)
    return {o.id: payment_summary(o, by_order.get(o.id, [])) for o in orders}


def _to_list_schema(o, summ=None):
    summ = summ or {"payment_status": None, "total_bayar": None, "sisa": None}
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
        unit_status=o.unit_status,
        taken_at=o.taken_at,
        estimate=o.estimate,
        payment=o.payment,
        service_date=o.service_date,
        final_price=o.final_price,
        part_cost=o.part_cost,
        modal_jasa=o.modal_jasa,
        modal_lainnya=o.modal_lainnya,
        lunas_date=o.lunas_date,
        lunas_at=o.lunas_at,
        warranty_months=o.warranty_months,
        payment_status=summ.get("payment_status"),
        total_bayar=summ.get("total_bayar"),
        sisa=summ.get("sisa"),
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
    riwayat: bool = False,
):
    """Daftar servis order dengan pagination (backend-side).

    Default (FINAL LOCK A): sembunyikan SELESAI + DIAMBIL (riwayat).
    riwayat=true → tampilkan kembali semuanya. Data tidak dihapus/diubah.
    """
    page, limit = _page_clamp(page, limit)
    qry = db.query(ServiceOrder)
    if not riwayat:
        # NULL unit_status (legacy) dianggap DI TOKO → tetap tampil.
        qry = qry.filter(~((ServiceOrder.status == "SELESAI")
                           & (ServiceOrder.unit_status == "DIAMBIL")))
    total = qry.count()
    rows = (
        qry.options(joinedload(ServiceOrder.customer))
        .order_by(ServiceOrder.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )
    total_pages = (total + limit - 1) // limit if total else 1
    sums = _summaries(db, rows)
    items = [_to_list_schema(o, sums.get(o.id)) for o in rows]
    return schemas.ServiceOrderPage(
        total=total,
        page=page,
        limit=limit,
        total_pages=total_pages,
        items=items,
    )


@router.get("/latest", response_model=list[schemas.ServiceOrderList])
def latest_orders(db: Session = Depends(get_db_session), limit: int = 10,
                  riwayat: bool = False):
    qry = db.query(ServiceOrder)
    if not riwayat:
        qry = qry.filter(~((ServiceOrder.status == "SELESAI")
                           & (ServiceOrder.unit_status == "DIAMBIL")))
    rows = (
        qry.options(joinedload(ServiceOrder.customer))
        .order_by(ServiceOrder.created_at.desc())
        .limit(limit)
        .all()
    )
    result = []
    sums = _summaries(db, rows)
    for o in rows:
        result.append(_to_list_schema(o, sums.get(o.id)))
    return result


@router.get("/{order_id}", response_model=schemas.ServiceOrderOut)
def get_order(order_id: int, db: Session = Depends(get_db_session)):
    order = db.query(ServiceOrder).filter(ServiceOrder.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Service order tidak ditemukan")
    _attach_summary(db, order)
    return order


@router.post("", response_model=schemas.ServiceOrderOut, status_code=201)
def create_order(data: schemas.ServiceOrderCreate, db: Session = Depends(get_db_session),
                 user: User = Depends(get_authenticated_user)):
    customer = db.query(Customer).filter(Customer.id == data.customer_id).first()
    if not customer:
        raise HTTPException(status_code=400, detail="Customer tidak ditemukan")
    dump = data.model_dump()
    st = (dump.get("status") or "DITERIMA").strip() or "DITERIMA"
    if st == "RECEIVED":
        st = "DITERIMA"
    if st not in SERVICE_STATUSES:
        raise HTTPException(status_code=400,
                            detail="Status tidak valid: %s. Pilihan: %s" % (st, ", ".join(SERVICE_STATUSES)))
    dump["status"] = st
    dump.setdefault("unit_status", "DI TOKO")
    # Ringkasan derive — bukan kolom DB, jangan teruskan ke ORM.
    dump.pop("payment_status", None)
    dump.pop("total_bayar", None)
    dump.pop("sisa", None)
    order = ServiceOrder(**dump)
    db.add(order)
    db.commit()
    db.refresh(order)
    _log_transition(db, order.id, None, st, _actor(user), "dibuat via API")
    db.commit()
    db.refresh(order)
    _attach_summary(db, order)
    return order


@router.put("/{order_id}", response_model=schemas.ServiceOrderOut)
def update_order(order_id: int, data: schemas.ServiceOrderUpdate,
                 db: Session = Depends(get_db_session),
                 user: User = Depends(get_authenticated_user)):
    order = db.query(ServiceOrder).filter(ServiceOrder.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Service order tidak ditemukan")
    old_status = order.status
    payload = data.model_dump(exclude_unset=True)
    note = (payload.pop("status_note", None) or "").strip()
    # Masa garansi toko hanya 0 (tidak garansi) / 1 / 3 / 6 bulan.
    if "warranty_months" in payload and payload["warranty_months"] not in (0, 1, 3, 6):
        raise HTTPException(status_code=400,
                            detail="Masa garansi tidak valid. Pilihan: 1, 3, 6 bulan atau 0 (tidak garansi)")
    new_status = payload.get("status")
    if new_status is not None:
        new_status = (new_status or "").strip()
        if not new_status:
            raise HTTPException(status_code=400, detail="Status tidak boleh kosong")
        ok, msg = check_transition(order.status, new_status, note)
        if not ok:
            raise HTTPException(status_code=400, detail=msg)
        # Guard per status (nama label Indonesia).
        if new_status == "KONFIRMASI":
            missing = []
            plan = payload.get("repair_plan", order.repair_plan)
            if not (plan or "").strip():
                missing.append("Rencana Perbaikan")
            est = payload.get("estimate", order.estimate)
            if not (est or 0) > 0:
                missing.append("Estimasi Biaya")
            if missing:
                raise HTTPException(status_code=400,
                                    detail="Status KONFIRMASI wajib melengkapi: " + ", ".join(missing))
        elif new_status == "PERBAIKAN":
            tech = payload.get("technician", order.technician)
            if not (tech or "").strip():
                raise HTTPException(status_code=400,
                                    detail="Status PERBAIKAN wajib melengkapi: Teknisi Penanggung Jawab")
        elif new_status == "SELESAI":
            missing = []
            plan = payload.get("repair_plan", order.repair_plan)
            if not (plan or "").strip():
                missing.append("Perbaikan / Tindakan Perbaikan")
            tech = payload.get("technician", order.technician)
            if not (tech or "").strip():
                missing.append("Teknisi Penanggung Jawab")
            if missing:
                raise HTTPException(status_code=400,
                                    detail="Status SELESAI wajib melengkapi: " + ", ".join(missing))
            if payload.get("part_cost") is None and order.part_cost is None:
                payload["part_cost"] = 0
        elif new_status in ("GAGAL", "BATAL"):
            if not note:
                label = ("Alasan kegagalan" if new_status == "GAGAL"
                         else "Alasan pembatalan")
                raise HTTPException(status_code=400,
                                    detail="Status %s wajib menyertakan %s (catatan)" % (new_status, label))
        payload["status"] = new_status
    for key, val in payload.items():
        setattr(order, key, val)
    # Garansi months default 1 bila SELESAI tanpa pilihan.
    if order.status == "SELESAI" and order.warranty_months is None:
        order.warranty_months = 1
    db.commit()
    if new_status is not None and new_status != old_status:
        _log_transition(db, order.id, old_status, new_status, _actor(user), note)
        db.commit()
    db.refresh(order)
    _attach_summary(db, order)
    return order


@router.delete("/{order_id}")
def delete_order(order_id: int, db: Session = Depends(get_db_session)):
    order = db.query(ServiceOrder).filter(ServiceOrder.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Service order tidak ditemukan")
    db.delete(order)
    db.commit()
    return {"ok": True}


@router.post("/{order_id}/handover", response_model=schemas.ServiceOrderOut)
def handover_unit(order_id: int, db: Session = Depends(get_db_session),
                  user: User = Depends(get_authenticated_user)):
    """Serahkan unit ke konsumen: DI TOKO → DIAMBIL (+ taken_at). Idempoten."""
    order = db.query(ServiceOrder).filter(ServiceOrder.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Service order tidak ditemukan")
    if (order.unit_status or "DI TOKO") == "DIAMBIL":
        _attach_summary(db, order)
        return order
    order.unit_status = "DIAMBIL"
    order.taken_at = datetime.now()
    db.commit()
    db.refresh(order)
    _attach_summary(db, order)
    return order


@router.get("/{order_id}/history", response_model=list[schemas.StatusHistoryOut])
def order_history_timeline(order_id: int, db: Session = Depends(get_db_session)):
    order = db.query(ServiceOrder).filter(ServiceOrder.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Service order tidak ditemukan")
    return (
        db.query(StatusHistory)
        .filter(StatusHistory.service_order_id == order_id)
        .order_by(StatusHistory.waktu.asc(), StatusHistory.id.asc())
        .all()
    )
