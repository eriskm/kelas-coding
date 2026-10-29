"""Spareparts endpoints — stok toko, satu-satunya sumber halaman Sparepart."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from dependencies import get_db_session
from datetime import datetime, date
from decimal import Decimal
from models import Sparepart, User, SparepartBatch, PartSale, PartSaleItem
from money import to_decimal
from authority import Action, require_authority
from routers.auth import get_authenticated_user
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



def _generate_sale_no(db: Session) -> str:
    prefix = "TRX-P-" + datetime.now().strftime("%y%m%d") + "-"
    count = db.query(PartSale).filter(PartSale.no_transaksi.startswith(prefix)).count()
    return f"{prefix}{count + 1:04d}"

# ---------- Direct Part Sales (Kasir POS) ----------
@router.post("/sales", response_model=schemas.PartSaleOut, status_code=201)
def create_part_sale(
    data: schemas.PartSaleCreate,
    db: Session = Depends(get_db_session),
    user: User = Depends(require_authority(Action.PART_SALE_CREATE)),
):
    """Transaksi Penjualan Sparepart / Aksesoris Langsung di Kasir (POS)."""
    if not data.items:
        raise HTTPException(status_code=400, detail="Keranjang belanja tidak boleh kosong")

    total_omzet = Decimal("0")
    total_modal = Decimal("0")
    sale_items_to_add = []

    for item_in in data.items:
        if item_in.qty <= 0:
            raise HTTPException(status_code=400, detail="Qty harus lebih besar dari 0")
        sp = db.query(Sparepart).filter(Sparepart.id == item_in.sparepart_id).first()
        if not sp:
            raise HTTPException(status_code=404, detail=f"Sparepart ID {item_in.sparepart_id} tidak ditemukan")
        if (sp.qty or 0) < item_in.qty:
            raise HTTPException(
                status_code=400,
                detail=f"Stok {sp.jenis} tidak mencukupi (sisa {sp.qty}, diminta {item_in.qty})"
            )

        rem_qty = item_in.qty
        active_batches = (
            db.query(SparepartBatch)
            .filter(SparepartBatch.sparepart_id == sp.id, SparepartBatch.qty_sisa > 0)
            .order_by(SparepartBatch.tanggal_masuk.asc(), SparepartBatch.id.asc())
            .all()
        )

        if active_batches:
            for b in active_batches:
                if rem_qty <= 0:
                    break
                take = min(rem_qty, b.qty_sisa)
                b.qty_sisa -= take
                if b.qty_sisa == 0:
                    b.status = "DEPLETED"
                rem_qty -= take
                sub = to_decimal(take) * to_decimal(b.harga_jual)
                mod = to_decimal(take) * to_decimal(b.harga_beli)
                total_omzet += sub
                total_modal += mod
                sale_items_to_add.append({
                    "sparepart_id": sp.id,
                    "sparepart_name": f"{sp.jenis} ({sp.merek or '-'})",
                    "batch_id": b.id,
                    "qty": take,
                    "harga_beli": b.harga_beli,
                    "harga_jual": b.harga_jual,
                    "subtotal": sub,
                })
            if rem_qty > 0:
                sub = to_decimal(rem_qty) * to_decimal(sp.harga_jual or Decimal("0"))
                mod = to_decimal(rem_qty) * to_decimal(sp.harga_beli or Decimal("0"))
                total_omzet += sub
                total_modal += mod
                sale_items_to_add.append({
                    "sparepart_id": sp.id,
                    "sparepart_name": f"{sp.jenis} ({sp.merek or '-'})",
                    "batch_id": None,
                    "qty": rem_qty,
                    "harga_beli": sp.harga_beli,
                    "harga_jual": sp.harga_jual,
                    "subtotal": sub,
                })
        else:
            sub = to_decimal(rem_qty) * to_decimal(sp.harga_jual or Decimal("0"))
            mod = to_decimal(rem_qty) * to_decimal(sp.harga_beli or Decimal("0"))
            total_omzet += sub
            total_modal += mod
            sale_items_to_add.append({
                "sparepart_id": sp.id,
                "sparepart_name": f"{sp.jenis} ({sp.merek or '-'})",
                "batch_id": None,
                "qty": rem_qty,
                "harga_beli": sp.harga_beli,
                "harga_jual": sp.harga_jual,
                "subtotal": sub,
            })

        sp.qty = max(0, (sp.qty or 0) - item_in.qty)

        next_b = (
            db.query(SparepartBatch)
            .filter(SparepartBatch.sparepart_id == sp.id, SparepartBatch.qty_sisa > 0)
            .order_by(SparepartBatch.tanggal_masuk.asc(), SparepartBatch.id.asc())
            .first()
        )
        if next_b:
            sp.harga_jual = next_b.harga_jual
            sp.harga_beli = next_b.harga_beli

        try:
            import inventory as inv_mod
            inv_mod.catat_pakai(db, sp.id, item_in.qty, None, None, "PENJUALAN LANGSUNG", user.display_name or user.username)
        except Exception:
            pass

    no_trx = _generate_sale_no(db)
    laba = total_omzet - total_modal

    sale = PartSale(
        no_transaksi=no_trx,
        customer_name=(data.customer_name or "").strip() or "Pelanggan Umum",
        customer_phone=(data.customer_phone or "").strip() or None,
        total_omzet=total_omzet,
        total_modal=total_modal,
        laba=laba,
        payment_method=(data.payment_method or "CASH").strip().upper(),
        kasir_id=user.id,
        oleh=user.display_name or user.username,
        created_at=datetime.now(),
    )
    db.add(sale)
    db.flush()

    out_items = []
    for it in sale_items_to_add:
        psi = PartSaleItem(
            part_sale_id=sale.id,
            sparepart_id=it["sparepart_id"],
            batch_id=it["batch_id"],
            qty=it["qty"],
            harga_beli=it["harga_beli"],
            harga_jual=it["harga_jual"],
            subtotal=it["subtotal"],
        )
        db.add(psi)
        db.flush()
        out_items.append(
            schemas.PartSaleItemOut(
                id=psi.id,
                sparepart_id=psi.sparepart_id,
                sparepart_name=it["sparepart_name"],
                batch_id=psi.batch_id,
                qty=psi.qty,
                harga_beli=psi.harga_beli,
                harga_jual=psi.harga_jual,
                subtotal=psi.subtotal,
            )
        )

    db.flush()
    try:
        from cash import catat_part_sale
        catat_part_sale(db, sale, actor=user.display_name or user.username)
    except Exception:
        pass

    db.commit()
    db.refresh(sale)

    return schemas.PartSaleOut(
        id=sale.id,
        no_transaksi=sale.no_transaksi,
        customer_name=sale.customer_name,
        customer_phone=sale.customer_phone,
        total_omzet=sale.total_omzet,
        total_modal=sale.total_modal,
        laba=sale.laba,
        payment_method=sale.payment_method,
        oleh=sale.oleh,
        created_at=sale.created_at,
        items=out_items,
    )


@router.get("/sales", response_model=schemas.PartSalePage)
def list_part_sales(
    db: Session = Depends(get_db_session),
    page: int = 1,
    limit: int = 20,
    q: str = Query(""),
):
    page = max(1, page)
    limit = min(100, max(1, limit))
    qry = db.query(PartSale)
    if q.strip():
        like = "%" + q.strip() + "%"
        qry = qry.filter(or_(PartSale.no_transaksi.ilike(like), PartSale.customer_name.ilike(like)))
    total = qry.count()
    rows = qry.order_by(PartSale.id.desc()).offset((page - 1) * limit).limit(limit).all()

    out_rows = []
    for r in rows:
        items_out = []
        for it in r.items:
            sp_name = f"{it.sparepart.jenis} ({it.sparepart.merek or '-'})" if it.sparepart else "-"
            items_out.append(
                schemas.PartSaleItemOut(
                    id=it.id,
                    sparepart_id=it.sparepart_id,
                    sparepart_name=sp_name,
                    batch_id=it.batch_id,
                    qty=it.qty,
                    harga_beli=it.harga_beli,
                    harga_jual=it.harga_jual,
                    subtotal=it.subtotal,
                )
            )
        out_rows.append(
            schemas.PartSaleOut(
                id=r.id,
                no_transaksi=r.no_transaksi,
                customer_name=r.customer_name,
                customer_phone=r.customer_phone,
                total_omzet=r.total_omzet,
                total_modal=r.total_modal,
                laba=r.laba,
                payment_method=r.payment_method,
                oleh=r.oleh,
                created_at=r.created_at,
                items=items_out,
            )
        )
    return schemas.PartSalePage(
        total=total,
        page=page,
        limit=limit,
        total_pages=(total + limit - 1) // limit if total else 1,
        items=out_rows,
    )


@router.get("/sales/{sale_id}", response_model=schemas.PartSaleOut)
def get_part_sale_detail(sale_id: int, db: Session = Depends(get_db_session)):
    sale = db.query(PartSale).filter(PartSale.id == sale_id).first()
    if not sale:
        raise HTTPException(status_code=404, detail="Transaksi penjualan part tidak ditemukan")
    items_out = []
    for it in sale.items:
        sp_name = f"{it.sparepart.jenis} ({it.sparepart.merek or '-'})" if it.sparepart else "-"
        items_out.append(
            schemas.PartSaleItemOut(
                id=it.id,
                sparepart_id=it.sparepart_id,
                sparepart_name=sp_name,
                batch_id=it.batch_id,
                qty=it.qty,
                harga_beli=it.harga_beli,
                harga_jual=it.harga_jual,
                subtotal=it.subtotal,
            )
        )
    return schemas.PartSaleOut(
        id=sale.id,
        no_transaksi=sale.no_transaksi,
        customer_name=sale.customer_name,
        customer_phone=sale.customer_phone,
        total_omzet=sale.total_omzet,
        total_modal=sale.total_modal,
        laba=sale.laba,
        payment_method=sale.payment_method,
        oleh=sale.oleh,
        created_at=sale.created_at,
        items=items_out,
    )


# ---------- Sparepart Batches (FIFO) ----------
@router.post("/{sparepart_id}/batches", response_model=schemas.SparepartBatchOut, status_code=201)
def create_sparepart_batch(
    sparepart_id: int,
    data: schemas.SparepartBatchCreate,
    db: Session = Depends(get_db_session),
    user: User = Depends(require_authority(Action.SPAREPART_WRITE)),
):
    """Pengadaan Stok Baru / Restock Batch Lot (FIFO)."""
    sp = db.query(Sparepart).filter(Sparepart.id == sparepart_id).first()
    if not sp:
        raise HTTPException(status_code=404, detail="Sparepart tidak ditemukan")
    qty = data.qty_masuk or 0
    if qty <= 0:
        raise HTTPException(status_code=400, detail="Qty masuk harus lebih besar dari 0")
    if (data.harga_beli or 0) < 0 or (data.harga_jual or 0) < 0:
        raise HTTPException(status_code=400, detail="Harga tidak boleh negatif")

    tgl = data.tanggal_masuk or date.today()
    batch = SparepartBatch(
        sparepart_id=sp.id,
        supplier=(data.supplier or "").strip() or None,
        harga_beli=data.harga_beli,
        harga_jual=data.harga_jual,
        qty_masuk=qty,
        qty_sisa=qty,
        tanggal_masuk=tgl,
        status="ACTIVE",
    )
    db.add(batch)

    prev_qty = sp.qty or 0
    sp.qty = prev_qty + qty
    sp.harga_beli = data.harga_beli
    if not sp.harga_jual or prev_qty <= 0:
        sp.harga_jual = data.harga_jual

    try:
        import inventory as inv_mod
        inv_mod.catat_masuk(db, sp.id, qty, f"Pengadaan Batch: {batch.supplier or '-'}", user.display_name or user.username)
    except Exception:
        pass

    db.commit()
    db.refresh(batch)
    return batch


@router.get("/{sparepart_id}/batches", response_model=list[schemas.SparepartBatchOut])
def list_sparepart_batches(
    sparepart_id: int,
    db: Session = Depends(get_db_session),
):
    sp = db.query(Sparepart).filter(Sparepart.id == sparepart_id).first()
    if not sp:
        raise HTTPException(status_code=404, detail="Sparepart tidak ditemukan")
    return (
        db.query(SparepartBatch)
        .filter(SparepartBatch.sparepart_id == sparepart_id)
        .order_by(SparepartBatch.tanggal_masuk.desc(), SparepartBatch.id.desc())
        .all()
    )


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
                     admin=Depends(require_authority(Action.SPAREPART_DELETE))):
    """Hapus sparepart — khusus Admin."""
    row = db.query(Sparepart).filter(Sparepart.id == sparepart_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Sparepart tidak ditemukan")
    db.delete(row)
    db.commit()
    return {"ok": True}


# ---------- Revolving Fund (Dana Perputaran Sparepart & Valuasi Stok) ----------
@router.get("/revolving-fund/summary")
def get_revolving_fund_summary(
    db: Session = Depends(get_db_session),
    user: User = Depends(require_authority(Action.REPORT_SPAREPART))
):
    """Ringkasan dana perputaran sparepart (Revolving Fund & Valuasi Stok Fisik):
    - Modal part yang sudah disetor kembali dari unit servis (CASH)
    - Modal part yang sudah disetor kembali dari penjualan langsung POS
    - Total belanja pengadaan batch stok baru
    - Estimasi nilai modal barang fisik yang aktif di rak (valuasi stok)
    - Sisa dana berputar di kas pengadaan sparepart
    """
    from models import ServiceOrder, PartSale, SparepartBatch, Sparepart, PartSaleItem, ServiceOrderPart
    from sqlalchemy import func
    from money import to_decimal, ZERO

    m_servis = (
        db.query(func.sum(ServiceOrder.part_cost))
        .filter(ServiceOrder.status == "CASH")
        .scalar()
    ) or Decimal("0")

    m_sales = (
        db.query(func.sum(PartSale.total_modal))
        .scalar()
    ) or Decimal("0")

    total_modal_disetor = to_decimal(m_servis) + to_decimal(m_sales)

    batches = db.query(SparepartBatch).all()
    total_belanja_batch = sum(
        (to_decimal(b.qty_masuk) * to_decimal(b.harga_beli) for b in batches),
        ZERO
    )

    valuasi_stok_aktif = sum(
        (to_decimal(b.qty_sisa) * to_decimal(b.harga_beli) for b in batches if (b.qty_sisa or 0) > 0),
        ZERO
    )

    batch_part_ids = {b.sparepart_id for b in batches}
    legacy_parts = db.query(Sparepart).filter(~Sparepart.id.in_(batch_part_ids)).all() if batch_part_ids else db.query(Sparepart).all()
    valuasi_legacy = sum(
        (to_decimal(sp.qty or 0) * to_decimal(sp.harga_beli or 0) for sp in legacy_parts if (sp.qty or 0) > 0),
        ZERO
    )
    total_valuasi_stok = valuasi_stok_aktif + valuasi_legacy

    sisa_dana_kas_part = total_modal_disetor - total_belanja_batch

    total_unit_terjual_pos = (db.query(func.sum(PartSaleItem.qty)).scalar()) or 0
    total_unit_terpakai_servis = (
        db.query(func.sum(ServiceOrderPart.qty))
        .filter(ServiceOrderPart.status == "DIPAKAI")
        .scalar()
    ) or 0
    total_stok_fisik_unit = (db.query(func.sum(Sparepart.qty)).scalar()) or 0

    return {
        "modal_disetor_servis": float(m_servis),
        "modal_disetor_penjualan": float(m_sales),
        "total_modal_disetor": float(total_modal_disetor),
        "total_belanja_pengadaan": float(total_belanja_batch),
        "valuasi_stok_aktif": float(total_valuasi_stok),
        "sisa_dana_kas_part": float(sisa_dana_kas_part),
        "total_unit_terjual_pos": int(total_unit_terjual_pos),
        "total_unit_terpakai_servis": int(total_unit_terpakai_servis),
        "total_stok_fisik_unit": int(total_stok_fisik_unit),
    }
