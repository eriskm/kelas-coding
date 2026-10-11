"""Payments endpoints — jurnal pembayaran per service order (FINAL LOCK §7).

Aturan: DP + PELUNASAN saja (tanpa cicilan kompleks). Append-only:
tanpa PUT/DELETE baris. payment_status = derive (BELUM LUNAS/LUNAS).
"""
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session
from typing import Optional

import cash
import journal
from money import CENTS, ZERO, quantize, to_decimal
import idempotency as idem
from authority import Action, require_authority
from dependencies import get_db_session
from models import Payment, ServiceOrder, User
from statusflow import PAYMENT_KINDS, kewajiban, lock_lunas_moment, payment_summary
import schemas

router = APIRouter(prefix="/api/payments", tags=["payments"])


def _summary(db: Session, order) -> dict:
    pays = db.query(Payment).filter(Payment.service_order_id == order.id).all()
    return payment_summary(order, pays)


def catat_payment(db: Session, order, kind: str, amount, method: str = "CASH",
                  note: str = None, actor: str = None, when=None,
                  allow_settled: bool = False):
    """TULIS SATU BARIS PAYMENT LEDGER — SATU-SATUNYA jalur (P2-15 / FIX-27).

    Fungsi ini dipakai oleh `POST /api/payments` **dan** oleh event `CASH`
    (Owner Cash Model), sehingga tidak ada jalur tulis payment kedua dan
    mutasi Saldo Laci (`cash.catat_penerimaan`) selalu tepat satu kali per
    baris payment.

    - `when` : momen yang dikunci sebagai `lunas_at` bila menjadi LUNAS
               (pada CASH = waktu event CASH).
    - `allow_settled` : izinkan saat unit sudah LUNAS (dipakai CASH agar replay
               tidak 400, tanpa membuat entry ganda karena `sisa` = 0).
    Saat baris ini membuat unit LUNAS, DP yang tertahan dilepas ke Kas Laci
    (`cash.catat_pelepasan_dp`) sehingga kas mencerminkan kewajiban penuh.
    Tidak commit — pemanggil yang mengatur transaksi.
    """
    kind = (kind or "PELUNASAN").strip().upper()
    if kind not in PAYMENT_KINDS:
        raise HTTPException(status_code=400,
                            detail="Jenis pembayaran tidak valid. Pilihan: " + ", ".join(PAYMENT_KINDS))
    amount = quantize(to_decimal(amount))
    if not amount > ZERO:
        raise HTTPException(status_code=400, detail="Nominal pembayaran harus lebih dari 0")
    must = kewajiban(order)
    if not must > ZERO:
        raise HTTPException(status_code=400,
                            detail="Kewajiban belum ditentukan (isi Harga Final/Estimasi dulu)")
    pays = db.query(Payment).filter(Payment.service_order_id == order.id).all()
    before = payment_summary(order, pays)
    if before["payment_status"] == "LUNAS" and not allow_settled:
        raise HTTPException(
            status_code=400,
            detail="Transaksi sudah LUNAS; pembayaran tambahan tidak diterima. "
                   "Gunakan alur pengembalian dana bila perlu.")
    # Penjaga replay: kalau kewajiban sudah tertutup seluruhnya, `allow_settled`
    # (dipakai event CASH) tidak boleh menambah baris baru. Tanpa ini, mengulang
    # event CASH akan menulis PELUNASAN 0/berulang — dan setiap baris_payment
    # dijumlahkan penuh oleh payment_summary serta Buku Kas.
    if allow_settled and before["sisa"] <= ZERO:
        return None
    if before["total_bayar"] + amount > must + CENTS:
        raise HTTPException(
            status_code=400,
            detail="Melebihi kewajiban (Rp %s). Sisa: Rp %s"
                   % (int(must), int(before["sisa"])))
    row = Payment(service_order_id=order.id, kind=kind, amount=amount,
                  method=method, note=note)
    db.add(row)
    db.flush()
    journal.record(
        db, journal.DOMAIN_PAYMENT, journal.PAYMENT_CREATED,
        entity_type="PAYMENT", entity_id=row.id, amount=amount,
        actor=actor, source=journal.SOURCE_API,
        ref_type="NO_SERVIS", ref_code=(order.no_servis or None),
        details={"kind": kind, "method": method,
                 "kewajiban": str(must), "sisa_sebelum": str(before["sisa"])})
    pays_after = db.query(Payment).filter(Payment.service_order_id == order.id).all()
    after = payment_summary(order, pays_after)
    if after["payment_status"] == "LUNAS":
        journal.record(
            db, journal.DOMAIN_PAYMENT, journal.PAYMENT_SETTLED,
            entity_type="SERVICE_ORDER", entity_id=order.id,
            amount=after["total_bayar"], actor=actor,
            source=journal.SOURCE_API,
            ref_type="NO_SERVIS", ref_code=(order.no_servis or None),
            details={"kewajiban": str(after["kewajiban"]), "sisa": str(after["sisa"])})
        lock_lunas_moment(order, when=when)
        # Owner Cash Model — DP adalah TITIPAN: tidak pernah masuk ledger kas
        # sejak awal; nominalnya baru dilepas ke Laci SEKALI di sini, saat unit
        # sudah LUNAS. Setelah ini total masuk kas untuk unit =
        # sisa pelunasan + DP = kewajiban penuh.
        cash.catat_pelepasan_dp(db, order, actor=actor)
    # Owner Cash Model v4 #1: payment non-DP diterima di toko -> SALDO LACI bertambah.
    # (`catat_penerimaan` otomatis melewati DP.)
    cash.catat_penerimaan(db, row, actor=actor)
    return row


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
def create_payment(data: schemas.PaymentCreate, db: Session = Depends(get_db_session),
                   user: User = Depends(require_authority(Action.PAYMENT_CREATE)),
                   idempotency_key: Optional[str] = Header(None, alias=idem.HEADER)):
    """Catat pembayaran. P2-14: `Idempotency-Key` mencegah retry menggandakan efek."""
    if idempotency_key:
        try:
            _run = idem.jalankan(
                db, "payments.create", idempotency_key,
                data.model_dump(), lambda: _create_payment_impl(data, db, user),
                actor=(user.display_name or user.username))
        except idem.IdempotencyConflict as exc:
            db.rollback()
            raise HTTPException(status_code=409, detail=str(exc))
        except HTTPException:
            db.rollback()
            raise
        except Exception:
            db.rollback()
            raise
        db.commit()
        return _run["result"]
    return _create_payment_impl(data, db, user)


def _create_payment_impl(data, db: Session, user):
    order = db.query(ServiceOrder).filter(ServiceOrder.id == data.service_order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Service order tidak ditemukan")
    try:
        amount = to_decimal(data.amount)
    except (TypeError, ValueError):
        amount = ZERO
    method = (data.method or "CASH").strip() or "CASH"
    note = (data.note or "").strip() or None
    actor = getattr(user, "display_name", None) or getattr(user, "username", None)
    # P2-04: payment + journal + kunci momen LUNAS + mutasi Laci dalam SATU
    # transaksi. Kegagalan di salah satu langkah membatalkan semuanya.
    try:
        catat_payment(db, order, data.kind, amount, method=method, note=note, actor=actor)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        raise HTTPException(status_code=500,
                            detail="Gagal menyimpan pembayaran: %s" % exc)
    db.refresh(order)
    return payments_by_order(order.id, db)



