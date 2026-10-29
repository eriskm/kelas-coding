# -*- coding: utf-8 -*-
"""P2-12 — Inventory: stok, barang masuk/keluar, pemakaian part, jurnal (ID-09).

Business behavior yang di-MIRROR dari Project A (`app.py:2900-2991`):
- pemakaian part untuk unit: **decrement ATOMIK** dengan guard `qty >= n`
  (A: `UPDATE ... WHERE qty >= %s` + **409** bila baris tidak terpengaruh);
- jurnal `stock_moves` dengan `qty_sebelum/qty_sesudah/selisih` (A `2936`, `2979`);
- link part ↔ unit (A `servis_part`) → `service_order_parts`;
- pembatalan pemakaian mengembalikan qty dan **tidak dobel** (A: hanya untuk baris
  berstatus masih Dipakai).

Yang TIDAK di-mirror / dijaga:
- `part_cost` tetap input manual (scope P2-12 (e)); stok tidakmengikuti uang Modal Part;
- stok TIDAK memengaruhi Financial Core (Omzet/Modal/Laba) — ini bukan aturan baru,
  Financial Core P2-05 hanya membaca cohort SETTLED + modal money;
- `stock_moves` & `service_order_parts` append-only (Q14, tanpa hard delete);
- semua penulisan (qty, movement, link, journal) dalam SATU transaksi: modul tidak
  melakukan `commit`; pemanggil (router) yang commit/rollback.
"""
from __future__ import annotations

from sqlalchemy import or_
from sqlalchemy.orm import Session

import journal
from money import ZERO, to_decimal

AKSI_MASUK = "MASUK"
AKSI_PAKAI = "PAKAI"
AKSI_BATAL = "BATAL"
AKSI_RETUR_CACAT = "RETUR_CACAT"
AKSI_GANTI_SUPPLIER = "GANTI_SUPPLIER"

STATUS_RETUR_MENUNGGU = "MENUNGGU"
STATUS_RETUR_DIKIRIM = "DIKIRIM"
STATUS_RETUR_GANTI_BARANG = "GANTI_BARANG"
STATUS_RETUR_POTONG_NOTA = "POTONG_NOTA"
STATUS_RETUR_DITOLAK = "DITOLAK"

STATUS_DIPAKAI = "DIPAKAI"
STATUS_DIBATALKAN = "DIBATALKAN"

EVENT_MASUK = "STOK_MASUK"
EVENT_PAKAI = "STOK_PAKAI"
EVENT_BATAL = "STOK_PAKAI_DIBATALKAN"


class InventoryError(ValueError):
    """Input/urutan pergerakan stok tidak valid."""


class StockConflict(Exception):
    """Stok berubah saat diproses → 409 (menerjemahkan `rowcount != 1` Project A)."""

    def __init__(self, sparepart_id, qty_diminta, qty_kini):
        self.sparepart_id = sparepart_id
        self.qty_diminta = qty_diminta
        self.qty_kini = qty_kini
        super().__init__("Stok berubah saat diproses, coba lagi (stok kini %s, diminta %s)"
                         % (qty_kini, qty_diminta))


def _part(db: Session, sparepart_id: int):
    from models import Sparepart
    part = db.query(Sparepart).filter(Sparepart.id == sparepart_id).first()
    if part is None:
        raise InventoryError("Part tidak ditemukan di stok")
    return part


def _qty(db: Session, sparepart_id: int) -> int:
    from models import Sparepart
    return int(db.query(Sparepart.qty).filter(Sparepart.id == sparepart_id).scalar() or 0)


def _catat(db: Session, part, aksi: str, qty: int, keterangan: str, oleh: str = None,
           service_order_id=None, service_order_part_id=None, pakai_move_id=None):
    """Tulis SATU journal pergerakan stok (append-only)."""
    from models import StockMove
    move = StockMove(sparepart_id=part.id, aksi=aksi, qty=qty,
                     qty_sebelum=_qty(db, part.id), qty_sesudah=_qty(db, part.id),
                     selisih=qty if aksi == AKSI_MASUK else -qty,
                     service_order_id=service_order_id,
                     service_order_part_id=service_order_part_id,
                     pakai_move_id=pakai_move_id, keterangan=keterangan, oleh=oleh)
    db.add(move)
    db.flush()
    return move


# ---------------- Barang masuk (pembelian/pemasok) ----------------
def catat_masuk(db: Session, sparepart_id: int, qty: int, keterangan: str = None,
                oleh: str = None):
    """Barang masuk: qty bertambah + jurnal MASUK. Tanpa efek ke financial core."""
    from models import StockMove
    qty = int(qty or 0)
    if qty <= 0:
        raise InventoryError("Qty harus lebih dari 0")
    part = _part(db, sparepart_id)
    sebelum = int(part.qty or 0)
    # increment atomik: guard id agar tidak bentrok dengan baris lain
    from models import Sparepart
    affected = (db.query(Sparepart)
                .filter(Sparepart.id == sparepart_id)
                .update({Sparepart.qty: Sparepart.qty + qty}, synchronize_session=False))
    if affected != 1:
        db.rollback()
        raise StockConflict(sparepart_id, qty, sebelum)
    db.flush()
    part = _part(db, sparepart_id)
    move = StockMove(sparepart_id=sparepart_id, aksi=AKSI_MASUK, qty=qty,
                     qty_sebelum=sebelum, qty_sesudah=sebelum + qty, selisih=qty,
                     keterangan=keterangan or "Barang masuk", oleh=oleh)
    db.add(move)
    journal.record(db, journal.DOMAIN_INVENTORY, EVENT_MASUK,
                   entity_type="stock_move", amount=None, actor=oleh,
                   ref_type="sparepart", ref_code=str(sparepart_id),
                   details={"aksi": AKSI_MASUK, "qty": qty,
                            "qty_sebelum": sebelum, "qty_sesudah": sebelum + qty,
                            "keterangan": keterangan or "Barang masuk"})
    db.flush()
    db.refresh(move)
    return {"move": move, "qty_sebelum": sebelum, "qty_sesudah": sebelum + qty,
            "sparepart": part}


# ---------------- Pemakaian part (decrement ATOMIK) ----------------
def catat_pakai(db: Session, sparepart_id: int = None, qty: int = 1, service_order_id: int = None,
                harga_satuan=None, modal_beli=None, is_external: bool = False,
                part_name: str = None, note: str = None, oleh: str = None):
    """Pemakaian sparepart untuk unit servis (decrement ATOMIK & batch FIFO)."""
    from models import ServiceOrder, ServiceOrderPart, Sparepart, SparepartBatch, StockMove
    from money import ZERO, to_decimal

    qty = int(qty or 0)
    if qty <= 0:
        raise InventoryError("Qty harus lebih dari 0")

    unit = None
    if service_order_id is not None:
        unit = db.query(ServiceOrder).filter(ServiceOrder.id == service_order_id).first()
        if unit is None:
            raise InventoryError("Unit servis tidak ditemukan")
        if (unit.status or "").upper() == "CASH":
            raise InventoryError("Tidak dapat menambah part pada transaksi yang sudah CASH")

    if is_external:
        if not (part_name or "").strip():
            raise InventoryError("Nama part luar wajib diisi")
        modal = to_decimal(modal_beli or 0)
        harga = to_decimal(harga_satuan or 0)
        usage = ServiceOrderPart(
            service_order_id=service_order_id,
            sparepart_id=None,
            batch_id=None,
            part_name=(part_name or "").strip(),
            qty=qty,
            modal_beli=modal,
            harga_satuan=harga,
            is_external=True,
            note=note,
            status=STATUS_DIPAKAI,
            oleh=oleh
        )
        db.add(usage)
        db.flush()

        if unit is not None:
            active_parts = (db.query(ServiceOrderPart)
                            .filter(ServiceOrderPart.service_order_id == unit.id,
                                    ServiceOrderPart.status == STATUS_DIPAKAI).all())
            tot_cost = sum(to_decimal(p.modal_beli) * p.qty for p in active_parts)
            unit.part_cost = tot_cost
            if getattr(unit, "tanpa_modal", False) and tot_cost > ZERO:
                unit.tanpa_modal = False
            db.flush()

        return {
            "move": None,
            "usage": usage,
            "part_cost": unit.part_cost if unit else modal * qty,
            "qty_sebelum": 0,
            "qty_sesudah": 0
        }

    # Kasus normal: dari inventaris toko
    if not sparepart_id:
        raise InventoryError("Sparepart toko wajib dipilih")

    part = _part(db, sparepart_id)
    sebelum = int(part.qty or 0)
    if qty > sebelum:
        raise StockConflict(sparepart_id, qty, sebelum)

    # FIFO Batch Depletion
    batch_id = None
    modal = to_decimal(getattr(part, "harga_beli", 0))

    batches = (db.query(SparepartBatch)
               .filter(SparepartBatch.sparepart_id == sparepart_id,
                       SparepartBatch.qty_sisa > 0,
                       SparepartBatch.status == "ACTIVE")
               .order_by(SparepartBatch.tanggal_masuk.asc(), SparepartBatch.id.asc())
               .all())

    if batches:
        b = batches[0]
        take = min(qty, b.qty_sisa)
        b.qty_sisa -= take
        if b.qty_sisa == 0:
            b.status = "DEPLETED"
        batch_id = b.id
        modal = to_decimal(b.harga_beli)
    elif modal_beli is not None:
        modal = to_decimal(modal_beli)

    # Decrement atomik pada master sparepart
    affected = (db.query(Sparepart)
                .filter(Sparepart.id == sparepart_id, Sparepart.qty >= qty)
                .update({Sparepart.qty: Sparepart.qty - qty}, synchronize_session=False))
    if affected != 1:
        db.rollback()
        raise StockConflict(sparepart_id, qty, _qty(db, sparepart_id))
    db.flush()

    ket = note or ("Pemakaian part servis x%d" % qty if service_order_id else "Pemakaian part x%d" % qty)
    move = StockMove(
        sparepart_id=sparepart_id,
        aksi=AKSI_PAKAI,
        qty=qty,
        qty_sebelum=sebelum,
        qty_sesudah=sebelum - qty,
        selisih=-qty,
        service_order_id=service_order_id,
        keterangan=ket,
        oleh=oleh
    )
    db.add(move)
    db.flush()

    usage = None
    p_name = (part_name or part.jenis or "").strip()
    harga = to_decimal(harga_satuan) if harga_satuan is not None else to_decimal(getattr(part, "harga_jual", 0))

    if service_order_id is not None:
        usage = ServiceOrderPart(
            service_order_id=service_order_id,
            sparepart_id=sparepart_id,
            batch_id=batch_id,
            part_name=p_name,
            qty=qty,
            modal_beli=modal,
            harga_satuan=harga,
            is_external=False,
            note=note,
            status=STATUS_DIPAKAI,
            stock_move_id=move.id,
            oleh=oleh
        )
        db.add(usage)
        db.flush()
        move.service_order_part_id = usage.id

        if unit is not None:
            active_parts = (db.query(ServiceOrderPart)
                            .filter(ServiceOrderPart.service_order_id == unit.id,
                                    ServiceOrderPart.status == STATUS_DIPAKAI).all())
            tot_cost = sum(to_decimal(p.modal_beli) * p.qty for p in active_parts)
            unit.part_cost = tot_cost
            if getattr(unit, "tanpa_modal", False) and tot_cost > ZERO:
                unit.tanpa_modal = False
            db.flush()

    journal.record(db, journal.DOMAIN_INVENTORY, EVENT_PAKAI,
                   entity_type="stock_move", entity_id=move.id, amount=None, actor=oleh,
                   ref_type="service_order", ref_code=str(service_order_id),
                   details={"aksi": AKSI_PAKAI, "qty": qty, "qty_sebelum": sebelum,
                            "qty_sesudah": sebelum - qty,
                            "service_order_id": service_order_id,
                            "batch_id": batch_id,
                            "modal_beli": float(modal),
                            "service_order_part_id": getattr(usage, "id", None)})
    db.flush()
    db.refresh(move)
    return {
        "move": move,
        "usage": usage,
        "part_cost": unit.part_cost if unit else modal * qty,
        "qty_sebelum": sebelum,
        "qty_sesudah": sebelum - qty
    }


# ---------------- Pembatalan pemakaian (IDEMPOTEN) ----------------
def batalkan_pakai(db: Session, service_order_part_id: int, oleh: str = None,
                    alasan: str = None):
    """Batalkan pemakaian: qty kembali ke stok & batch + recompute part_cost."""
    from models import ServiceOrder, ServiceOrderPart, Sparepart, SparepartBatch, StockMove
    from money import ZERO, to_decimal

    usage = (db.query(ServiceOrderPart)
             .filter(ServiceOrderPart.id == service_order_part_id).first())
    if usage is None:
        raise InventoryError("Entri pemakaian tidak ditemukan")
    if (usage.status or "").upper() == STATUS_DIBATALKAN:
        move = db.query(StockMove).filter(StockMove.id == usage.cancel_move_id).first() if usage.cancel_move_id else None
        return {"idempotent": True, "move": move, "usage": usage,
                "qty_sebelum": getattr(move, "qty_sebelum", None),
                "qty_sesudah": getattr(move, "qty_sesudah", None),
                "pengembalian": 0}

    unit = None
    if usage.service_order_id:
        unit = db.query(ServiceOrder).filter(ServiceOrder.id == usage.service_order_id).first()
        if unit and (unit.status or "").upper() == "CASH":
            raise InventoryError("Tidak dapat membatalkan part pada transaksi yang sudah CASH")

    move = None
    sebelum = 0
    qty = int(usage.qty or 1)

    if not usage.is_external and usage.sparepart_id:
        part = _part(db, usage.sparepart_id)
        sebelum = int(part.qty or 0)

        # Restore batch
        if usage.batch_id:
            b = db.query(SparepartBatch).filter(SparepartBatch.id == usage.batch_id).first()
            if b:
                b.qty_sisa += qty
                b.status = "ACTIVE"
                db.flush()

        # Increment master part
        db.query(Sparepart).filter(Sparepart.id == usage.sparepart_id).update(
            {Sparepart.qty: Sparepart.qty + qty}, synchronize_session=False
        )
        db.flush()

        move = StockMove(
            sparepart_id=usage.sparepart_id,
            aksi=AKSI_BATAL,
            qty=qty,
            qty_sebelum=sebelum,
            qty_sesudah=sebelum + qty,
            selisih=qty,
            service_order_id=usage.service_order_id,
            service_order_part_id=usage.id,
            pakai_move_id=usage.stock_move_id,
            keterangan=alasan or "Batal pasang part servis",
            oleh=oleh
        )
        db.add(move)
        db.flush()
        usage.cancel_move_id = move.id

    usage.status = STATUS_DIBATALKAN
    db.flush()

    if unit is not None:
        active_parts = (db.query(ServiceOrderPart)
                        .filter(ServiceOrderPart.service_order_id == unit.id,
                                ServiceOrderPart.status == STATUS_DIPAKAI).all())
        tot_cost = sum(to_decimal(p.modal_beli) * p.qty for p in active_parts)
        unit.part_cost = tot_cost
        db.flush()

    journal.record(db, journal.DOMAIN_INVENTORY, EVENT_BATAL,
                   entity_type="stock_move", entity_id=move.id if move else None, amount=None, actor=oleh,
                   ref_type="service_order_part", ref_code=str(usage.id),
                   details={"aksi": AKSI_BATAL, "qty": qty,
                            "service_order_id": usage.service_order_id,
                            "pakai_move_id": usage.stock_move_id, "alasan": alasan})
    db.flush()
    return {
        "idempotent": False,
        "move": move,
        "usage": usage,
        "part_cost": unit.part_cost if unit else Decimal("0"),
        "qty_sebelum": sebelum,
        "qty_sesudah": sebelum + qty,
        "pengembalian": qty
    }


# ---------------- Riwayat (read-only) ----------------
def moves(db: Session, sparepart_id=None, service_order_id=None, limit: int = 100):
    from models import StockMove, ServiceOrder, Sparepart
    q = db.query(StockMove)
    if sparepart_id is not None:
        q = q.filter(StockMove.sparepart_id == sparepart_id)
    if service_order_id is not None:
        q = q.filter(StockMove.service_order_id == service_order_id)
    rows = q.order_by(StockMove.id.desc()).limit(limit).all()
    out = []
    for m in rows:
        p = db.query(Sparepart).filter(Sparepart.id == m.sparepart_id).first() if m.sparepart_id else None
        p_label = ("%s %s" % (getattr(p, "merek", "") or "", getattr(p, "jenis", "") or "")).strip() if p else (m.keterangan or "Part")
        so_no = None
        if m.service_order_id:
            so = db.query(ServiceOrder.no_servis).filter(ServiceOrder.id == m.service_order_id).first()
            if so:
                so_no = so[0]
        out.append({
            "id": m.id,
            "sparepart_id": m.sparepart_id,
            "sparepart_label": p_label,
            "aksi": m.aksi,
            "qty": m.qty,
            "qty_sebelum": m.qty_sebelum,
            "qty_sesudah": m.qty_sesudah,
            "selisih": m.selisih,
            "service_order_id": m.service_order_id,
            "no_servis": so_no,
            "service_order_part_id": m.service_order_part_id,
            "pakai_move_id": m.pakai_move_id,
            "keterangan": m.keterangan or (f"Servis #{so_no}" if so_no else "-"),
            "oleh": m.oleh,
            "waktu": m.waktu.strftime("%Y-%m-%d %H:%M") if getattr(m, "waktu", None) else "-"
        })
    return out


def pemakaian_unit(db: Session, service_order_id: int):
    """Riwayat pemakaian part untuk satu unit (ADAPT `servis_part`)."""
    from models import ServiceOrderPart, Sparepart
    rows = (db.query(ServiceOrderPart)
            .filter(ServiceOrderPart.service_order_id == service_order_id)
            .order_by(ServiceOrderPart.id.asc()).all())
    out = []
    for u in rows:
        p = db.query(Sparepart).filter(Sparepart.id == u.sparepart_id).first() if u.sparepart_id else None
        p_name = u.part_name or (("%s %s" % (getattr(p, "merek", "") or "", getattr(p, "jenis", "") or "")).strip() if p else "Part Manual")
        out.append({
            "id": u.id,
            "service_order_id": u.service_order_id,
            "sparepart_id": u.sparepart_id,
            "batch_id": u.batch_id,
            "label": p_name,
            "part_name": p_name,
            "merek": getattr(p, "merek", "-") if p else "Luar/Manual",
            "qty": u.qty,
            "modal_beli": float(u.modal_beli or 0),
            "harga_satuan": float(u.harga_satuan or 0),
            "is_external": bool(u.is_external),
            "status": u.status,
            "stock_move_id": u.stock_move_id,
            "cancel_move_id": u.cancel_move_id,
            "note": u.note,
            "oleh": u.oleh,
            "created_at": u.created_at.strftime("%Y-%m-%d %H:%M") if u.created_at else "-"
        })
    return out


# ---------------- Retur / Garansi Sparepart Cacat Pabrik ----------------
def catat_retur_cacat(
    db: Session,
    sparepart_id: int = None,
    qty: int = 1,
    alasan_cacat: str = "",
    batch_id: int = None,
    service_order_id: int = None,
    service_order_part_id: int = None,
    oleh: str = None
):
    """Mencatat part cacat pabrik:
    - Jika dari service_order_part:
      * Lepas part dari ServiceOrder (status = 'DIRETUR_CACAT')
      * Recompute ServiceOrder.part_cost (biaya servis tidak terbebani part rusak)
    - Jika langsung dari stok fisik toko:
      * Kurangi Sparepart.qty dan batch FIFO (keluar dari rak siap jual ke karantina retur)
    - Catat StockMove (aksi = 'RETUR_CACAT')
    - Buat SparepartDefect (status = 'MENUNGGU')
    """
    from datetime import datetime
    from decimal import Decimal
    import secrets
    from models import Sparepart, SparepartBatch, ServiceOrder, ServiceOrderPart, StockMove, SparepartDefect
    from money import ZERO, to_decimal

    qty = int(qty or 1)
    if qty <= 0:
        raise InventoryError("Qty harus lebih dari 0")
    if not (alasan_cacat or "").strip():
        raise InventoryError("Alasan / gejala cacat pabrik wajib diisi")

    part = None
    batch = None
    unit = None
    usage = None
    modal = Decimal("0")
    supplier_name = None

    if service_order_part_id is not None:
        usage = db.query(ServiceOrderPart).filter(ServiceOrderPart.id == service_order_part_id).first()
        if not usage:
            raise InventoryError("Entri pemakaian part servis tidak ditemukan")
        if (usage.status or "").upper() != STATUS_DIPAKAI:
            raise InventoryError(f"Part servis ini sudah berstatus {usage.status}")

        service_order_id = usage.service_order_id
        unit = db.query(ServiceOrder).filter(ServiceOrder.id == service_order_id).first()
        if unit and (unit.status or "").upper() == "CASH":
            raise InventoryError("Tidak dapat retur part pada transaksi yang sudah CASH")

        sparepart_id = usage.sparepart_id
        batch_id = usage.batch_id
        modal = to_decimal(usage.modal_beli or 0)
        qty = usage.qty or 1

        usage.status = "DIRETUR_CACAT"
        usage.note = (f"{usage.note or ''} [Retur cacat: {alasan_cacat}]").strip()
        db.flush()

        if unit is not None:
            active_parts = (db.query(ServiceOrderPart)
                            .filter(ServiceOrderPart.service_order_id == unit.id,
                                    ServiceOrderPart.status == STATUS_DIPAKAI).all())
            tot_cost = sum((to_decimal(p.modal_beli) * p.qty for p in active_parts), ZERO)
            unit.part_cost = tot_cost
            db.flush()

    if sparepart_id:
        part = _part(db, sparepart_id)
        if not modal:
            modal = to_decimal(getattr(part, "harga_beli", 0))

    if batch_id:
        batch = db.query(SparepartBatch).filter(SparepartBatch.id == batch_id).first()
        if batch:
            supplier_name = batch.supplier
            if not modal:
                modal = to_decimal(batch.harga_beli)

    move = None
    if service_order_part_id is None and sparepart_id:
        sebelum = int(part.qty or 0)
        if qty > sebelum:
            raise StockConflict(sparepart_id, qty, sebelum)

        if not batch_id:
            active_batches = (db.query(SparepartBatch)
                              .filter(SparepartBatch.sparepart_id == sparepart_id,
                                      SparepartBatch.qty_sisa > 0,
                                      SparepartBatch.status == "ACTIVE")
                              .order_by(SparepartBatch.tanggal_masuk.asc(), SparepartBatch.id.asc())
                              .all())
            if active_batches:
                b = active_batches[0]
                take = min(qty, b.qty_sisa)
                b.qty_sisa -= take
                if b.qty_sisa == 0:
                    b.status = "DEPLETED"
                batch_id = b.id
                supplier_name = b.supplier
                modal = to_decimal(b.harga_beli)

        affected = (db.query(Sparepart)
                    .filter(Sparepart.id == sparepart_id, Sparepart.qty >= qty)
                    .update({Sparepart.qty: Sparepart.qty - qty}, synchronize_session=False))
        if affected != 1:
            db.rollback()
            raise StockConflict(sparepart_id, qty, _qty(db, sparepart_id))
        db.flush()

        move = StockMove(
            sparepart_id=sparepart_id,
            aksi=AKSI_RETUR_CACAT,
            qty=qty,
            qty_sebelum=sebelum,
            qty_sesudah=sebelum - qty,
            selisih=-qty,
            service_order_id=service_order_id,
            keterangan=f"Karantina part cacat: {alasan_cacat}",
            oleh=oleh
        )
        db.add(move)
        db.flush()
    elif service_order_part_id is not None:
        p_qty = int(getattr(part, "qty", 0)) if part else 0
        move = StockMove(
            sparepart_id=sparepart_id,
            aksi=AKSI_RETUR_CACAT,
            qty=qty,
            qty_sebelum=p_qty,
            qty_sesudah=p_qty,
            selisih=0,
            service_order_id=service_order_id,
            service_order_part_id=service_order_part_id,
            keterangan=f"Part cacat servis #{unit.no_servis if unit else service_order_id}: {alasan_cacat}",
            oleh=oleh
        )
        db.add(move)
        db.flush()

    ts = datetime.now().strftime("%Y%m%d")
    rnd = secrets.token_hex(2).upper()
    no_retur = f"RET-{ts}-{rnd}"

    defect = SparepartDefect(
        no_retur=no_retur,
        sparepart_id=sparepart_id,
        batch_id=batch_id,
        service_order_id=service_order_id,
        service_order_part_id=service_order_part_id,
        supplier=supplier_name or getattr(batch, "supplier", None) or "Supplier Umum",
        qty=qty,
        modal_satuan=modal,
        alasan_cacat=alasan_cacat.strip(),
        status=STATUS_RETUR_MENUNGGU,
        oleh=oleh,
        stock_move_id=move.id if move else None,
        created_at=datetime.now()
    )
    db.add(defect)
    db.flush()
    db.refresh(defect)

    journal.record(db, journal.DOMAIN_INVENTORY, "SPAREPART_DEFECT_REPORTED",
                   entity_type="sparepart_defect", entity_id=defect.id, amount=float(modal * qty), actor=oleh,
                   ref_type="sparepart_defect", ref_code=no_retur,
                   details={"alasan": alasan_cacat, "qty": qty, "supplier": defect.supplier,
                            "service_order_id": service_order_id})
    db.flush()
    return defect


def update_status_retur(db: Session, defect_id: int, status_baru: str, note: str = None, oleh: str = None):
    from models import SparepartDefect
    defect = db.query(SparepartDefect).filter(SparepartDefect.id == defect_id).first()
    if not defect:
        raise InventoryError("Klaim retur tidak ditemukan")
    if defect.status in ("GANTI_BARANG", "POTONG_NOTA", "DITOLAK"):
        raise InventoryError("Klaim retur yang sudah selesai tidak dapat diubah statusnya")

    status_baru = (status_baru or "").upper().strip()
    if status_baru not in ("MENUNGGU", "DIKIRIM"):
        raise InventoryError(f"Status tidak valid: {status_baru}")

    defect.status = status_baru
    if note:
        defect.resolusi_note = (f"{defect.resolusi_note or ''}\n[{status_baru}] {note}").strip()
    db.flush()
    return defect


def resolusi_retur(db: Session, defect_id: int, resolusi: str, note: str = None, oleh: str = None):
    """Menyelesaikan klaim retur:
    - GANTI_BARANG: Supplier mengganti unit fisik baru. Stok fisik Sparepart.qty bertambah (+qty).
    - POTONG_NOTA: Supplier mengembalikan uang / memotong nota belanja. Stok fisik tidak bertambah.
    - DITOLAK: Supplier menolak klaim. Kerugian dicatat.
    """
    from datetime import datetime
    from models import Sparepart, SparepartBatch, StockMove, SparepartDefect
    from money import ZERO, to_decimal

    defect = db.query(SparepartDefect).filter(SparepartDefect.id == defect_id).first()
    if not defect:
        raise InventoryError("Klaim retur tidak ditemukan")
    if defect.status in ("GANTI_BARANG", "POTONG_NOTA", "DITOLAK"):
        raise InventoryError("Klaim retur sudah diselesaikan sebelumnya")

    resolusi = (resolusi or "").upper().strip()
    if resolusi not in ("GANTI_BARANG", "POTONG_NOTA", "DITOLAK"):
        raise InventoryError(f"Resolusi tidak valid: {resolusi}")

    resolve_move = None
    if resolusi == "GANTI_BARANG":
        part = db.query(Sparepart).filter(Sparepart.id == defect.sparepart_id).first()
        if part:
            sebelum = int(part.qty or 0)
            part.qty = sebelum + defect.qty

            if defect.batch_id:
                b = db.query(SparepartBatch).filter(SparepartBatch.id == defect.batch_id).first()
                if b:
                    b.qty_sisa += defect.qty
                    if b.status == "DEPLETED":
                        b.status = "ACTIVE"
            db.flush()

            resolve_move = StockMove(
                sparepart_id=part.id,
                aksi=AKSI_GANTI_SUPPLIER,
                qty=defect.qty,
                qty_sebelum=sebelum,
                qty_sesudah=sebelum + defect.qty,
                selisih=defect.qty,
                service_order_id=defect.service_order_id,
                keterangan=f"Ganti unit baru supplier ({defect.no_retur}): {note or 'Unit normal diterima'}",
                oleh=oleh
            )
            db.add(resolve_move)
            db.flush()

    defect.status = resolusi
    defect.resolusi_note = (f"{defect.resolusi_note or ''}\n[{resolusi}] {note or ''}").strip()
    defect.admin_penanggungjawab = oleh
    defect.resolve_move_id = resolve_move.id if resolve_move else None
    defect.resolved_at = datetime.now()
    db.flush()

    journal.record(db, journal.DOMAIN_INVENTORY, f"SPAREPART_DEFECT_{resolusi}",
                   entity_type="sparepart_defect", entity_id=defect.id, amount=float(defect.modal_satuan * defect.qty),
                   actor=oleh, ref_type="sparepart_defect", ref_code=defect.no_retur,
                   details={"resolusi": resolusi, "note": note, "qty": defect.qty})
    db.flush()
    return defect


def list_defects(db: Session, status: str = None, limit: int = 100):
    from models import SparepartDefect, Sparepart, ServiceOrder
    q = db.query(SparepartDefect)
    if status and status.upper() != "ALL":
        q = q.filter(SparepartDefect.status == status.upper())
    rows = q.order_by(SparepartDefect.id.desc()).limit(limit).all()

    out = []
    for d in rows:
        p = db.query(Sparepart).filter(Sparepart.id == d.sparepart_id).first()
        p_label = ("%s %s" % (getattr(p, "merek", "") or "", getattr(p, "jenis", "") or "")).strip() if p else "Part"
        so_no = None
        if d.service_order_id:
            so = db.query(ServiceOrder.no_servis).filter(ServiceOrder.id == d.service_order_id).first()
            if so:
                so_no = so[0]
        out.append({
            "id": d.id,
            "no_retur": d.no_retur,
            "sparepart_id": d.sparepart_id,
            "sparepart_label": p_label,
            "supplier": d.supplier or "-",
            "qty": d.qty,
            "modal_satuan": float(d.modal_satuan or 0),
            "total_modal": float((d.modal_satuan or 0) * d.qty),
            "alasan_cacat": d.alasan_cacat,
            "status": d.status,
            "resolusi_note": d.resolusi_note,
            "service_order_id": d.service_order_id,
            "service_order_part_id": d.service_order_part_id,
            "no_servis": so_no,
            "oleh": d.oleh,
            "admin_penanggungjawab": d.admin_penanggungjawab,
            "created_at": d.created_at.strftime("%Y-%m-%d %H:%M") if d.created_at else "-",
            "resolved_at": d.resolved_at.strftime("%Y-%m-%d %H:%M") if d.resolved_at else None
        })
    return out
