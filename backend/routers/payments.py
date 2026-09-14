"""Payments endpoints — jurnal pembayaran per service order (FINAL LOCK §7).

Aturan: DP + PELUNASAN saja (tanpa cicilan kompleks). Append-only:
tanpa PUT/DELETE baris. payment_status = derive (BELUM LUNAS/LUNAS).
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from dependencies import get_db_session
from models import Payment, ServiceOrder
from statusflow import PAYMENT_KINDS, kewajiban, lock_lunas_moment, payment_summary
import schemas

router = APIRouter(prefix="/api/payments", tags=["payments"])


def _summary(db: Session, order) -> dict:
    pays = db.query(Payment).filter(Payment.service_order_id == order.id).all()
    return payment_summary(order, pays)


@router.get("/by-order/{order_id}", response_model=schemas.PaymentHistoryOut)
def payments_by_order(order_id: int, db: Session = Depends(get_db_session)):
    order = db.query(ServiceOrder).filter(ServiceOrder.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Service order tidak ditemukan")
    pays = (
        db.query(Payment)
        .filter(Payment.service_order_id == order_id)
        .order_by(Payment.created_at.asc(), Payment.id.asc())
        .all()
    )
    s = payment_summary(order, pays)
    return schemas.PaymentHistoryOut(
        kewajiban=s["kewajiban"], total_bayar=s["total_bayar"], sisa=s["sisa"],
        payment_status=s["payment_status"],
        items=[schemas.PaymentOut.model_validate(p) for p in pays],
    )


@router.post("", response_model=schemas.PaymentHistoryOut, status_code=201)
def create_payment(data: schemas.PaymentCreate, db: Session = Depends(get_db_session)):
    order = db.query(ServiceOrder).filter(ServiceOrder.id == data.service_order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Service order tidak ditemukan")
    kind = (data.kind or "PELUNASAN").strip().upper()
    if kind not in PAYMENT_KINDS:
        raise HTTPException(status_code=400,
                            detail="Jenis pembayaran tidak valid. Pilihan: " + ", ".join(PAYMENT_KINDS))
    try:
        amount = float(data.amount or 0)
    except (TypeError, ValueError):
        amount = 0.0
    if not amount > 0:
        raise HTTPException(status_code=400, detail="Nominal pembayaran harus lebih dari 0")
    must = kewajiban(order)
    if not must > 0:
        raise HTTPException(status_code=400,
                            detail="Kewajiban belum ditentukan (isi Harga Final/Estimasi dulu)")
    pays = db.query(Payment).filter(Payment.service_order_id == order.id).all()
    before = payment_summary(order, pays)
    if before["total_bayar"] + amount > must + 0.01:
        raise HTTPException(
            status_code=400,
            detail="Melebihi kewajiban (Rp %s). Sisa: Rp %s"
                   % (int(must), int(before["sisa"])))
    row = Payment(service_order_id=order.id, kind=kind, amount=amount,
                  method=(data.method or "CASH").strip() or "CASH",
                  note=(data.note or "").strip() or None)
    db.add(row)
    db.commit()
    pays = db.query(Payment).filter(Payment.service_order_id == order.id).all()
    after = payment_summary(order, pays)
    if after["payment_status"] == "LUNAS":
        if lock_lunas_moment(order):
            db.commit()
            db.refresh(order)
    return payments_by_order(order.id, db)
