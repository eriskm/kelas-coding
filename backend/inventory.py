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
def catat_pakai(db: Session, sparepart_id: int, qty: int, service_order_id: int = None,
                harga_satuan=None, keterangan: str = None, oleh: str = None):
    """Pemakaian sparepart: decrement ATOMIK (hanya bila qty cukup) + link unit.

    Mengikuti Project A: guard `qty >= n` di level query; bila tidak ada baris yang
    terpengaruh → StockConflict (409).
    """
    qty = int(qty or 0)
    if qty <= 0:
        raise InventoryError("Qty harus lebih dari 0")
    part = _part(db, sparepart_id)
    if service_order_id is not None:
        from models import ServiceOrder
        unit = db.query(ServiceOrder).filter(ServiceOrder.id == service_order_id).first()
        if unit is None:
            raise InventoryError("Unit tidak ditemukan")
    sebelum = int(part.qty or 0)
    if qty > sebelum:
        raise StockConflict(sparepart_id, qty, sebelum)

    from models import Sparepart, StockMove
    affected = (db.query(Sparepart)
                .filter(Sparepart.id == sparepart_id, Sparepart.qty >= qty)
                .update({Sparepart.qty: Sparepart.qty - qty}, synchronize_session=False))
    if affected != 1:
        db.rollback()
        raise StockConflict(sparepart_id, qty, _qty(db, sparepart_id))
    db.flush()

    move = StockMove(sparepart_id=sparepart_id, aksi=AKSI_PAKAI, qty=qty,
                     qty_sebelum=sebelum, qty_sesudah=sebelum - qty, selisih=-qty,
                     service_order_id=service_order_id,
                     keterangan=keterangan or ("Pemakaian part x%d" % qty), oleh=oleh)
    db.add(move)
    db.flush()

    usage = None
    if service_order_id is not None:
        from models import ServiceOrderPart
        harga = to_decimal(harga_satuan) if harga_satuan is not None else to_decimal(
            getattr(part, "harga_jual", 0))
        usage = ServiceOrderPart(service_order_id=service_order_id, sparepart_id=sparepart_id,
                                 qty=qty, harga_satuan=harga, status=STATUS_DIPAKAI,
                                 stock_move_id=move.id, oleh=oleh)
        db.add(usage)
        db.flush()
        move.service_order_part_id = usage.id

    journal.record(db, journal.DOMAIN_INVENTORY, EVENT_PAKAI,
                   entity_type="stock_move", entity_id=move.id, amount=None, actor=oleh,
                   ref_type="service_order", ref_code=str(service_order_id),
                   details={"aksi": AKSI_PAKAI, "qty": qty, "qty_sebelum": sebelum,
                            "qty_sesudah": sebelum - qty,
                            "service_order_id": service_order_id,
                            "service_order_part_id": getattr(usage, "id", None)})
    db.flush()
    db.refresh(move)
    return {"move": move, "usage": usage, "qty_sebelum": sebelum,
            "qty_sesudah": sebelum - qty}


# ---------------- Pembatalan pemakaian (IDEMPOTEN) ----------------
def batalkan_pakai(db: Session, service_order_part_id: int, oleh: str = None,
                   alasan: str = None):
    """Batalkan pemakaian: qty kembali + jurnal BATAL. **Idempoten**.

    Bila pemakaian sudah DIBATALKAN, fungsi mengembalikan hasil yang sama tanpa
    menambah qty lagi (A: hanya baris berstatus 'Dipakai' yang diproses).
    """
    from models import ServiceOrderPart, Sparepart, StockMove
    usage = (db.query(ServiceOrderPart)
             .filter(ServiceOrderPart.id == service_order_part_id).first())
    if usage is None:
        raise InventoryError("Entri pemakaian tidak ditemukan")
    if (usage.status or "").upper() == STATUS_DIBATALKAN and usage.cancel_move_id:
        move = db.query(StockMove).filter(StockMove.id == usage.cancel_move_id).first()
        return {"idempotent": True, "move": move, "usage": usage,
                "qty_sebelum": getattr(move, "qty_sebelum", None),
                "qty_sesudah": getattr(move, "qty_sesudah", None),
                "pengembalian": 0}

    part = _part(db, usage.sparepart_id)
    sebelum = int(part.qty or 0)
    qty = int(usage.qty or 0)
    affected = (db.query(Sparepart)
                .filter(Sparepart.id == usage.sparepart_id)
                .update({Sparepart.qty: Sparepart.qty + qty}, synchronize_session=False))
    if affected != 1:
        db.rollback()
        raise StockConflict(usage.sparepart_id, qty, sebelum)
    db.flush()

    move = StockMove(sparepart_id=usage.sparepart_id, aksi=AKSI_BATAL, qty=qty,
                     qty_sebelum=sebelum, qty_sesudah=sebelum + qty, selisih=qty,
                     service_order_id=usage.service_order_id,
                     service_order_part_id=usage.id, pakai_move_id=usage.stock_move_id,
                     keterangan=(alasan or ("Batal pakai part x%d" % qty)), oleh=oleh)
    db.add(move)
    db.flush()
    usage.status = STATUS_DIBATALKAN
    usage.cancel_move_id = move.id

    journal.record(db, journal.DOMAIN_INVENTORY, EVENT_BATAL,
                   entity_type="stock_move", entity_id=move.id, amount=None, actor=oleh,
                   ref_type="service_order_part", ref_code=str(usage.id),
                   details={"aksi": AKSI_BATAL, "qty": qty, "qty_sebelum": sebelum,
                            "qty_sesudah": sebelum + qty,
                            "pakai_move_id": usage.stock_move_id, "alasan": alasan})
    db.flush()
    db.refresh(move)
    return {"idempotent": False, "move": move, "usage": usage,
            "qty_sebelum": sebelum, "qty_sesudah": sebelum + qty, "pengembalian": qty}


# ---------------- Riwayat (read-only) ----------------
def moves(db: Session, sparepart_id=None, service_order_id=None, limit: int = 100):
    from models import StockMove
    q = db.query(StockMove)
    if sparepart_id is not None:
        q = q.filter(StockMove.sparepart_id == sparepart_id)
    if service_order_id is not None:
        q = q.filter(StockMove.service_order_id == service_order_id)
    rows = q.order_by(StockMove.id.desc()).limit(limit).all()
    out = []
    for m in rows:
        p = _part(db, m.sparepart_id)
        out.append({"id": m.id, "sparepart_id": m.sparepart_id,
                    "sparepart_label": "%s %s" % (getattr(p, "merek", "") or "",
                                                   getattr(p, "jenis", "") or ""),
                    "aksi": m.aksi, "qty": m.qty, "qty_sebelum": m.qty_sebelum,
                    "qty_sesudah": m.qty_sesudah, "selisih": m.selisih,
                    "service_order_id": m.service_order_id,
                    "service_order_part_id": m.service_order_part_id,
                    "pakai_move_id": m.pakai_move_id, "keterangan": m.keterangan,
                    "oleh": m.oleh, "waktu": m.waktu})
    return out


def pemakaian_unit(db: Session, service_order_id: int):
    """Riwayat pemakaian part untuk satu unit (ADAPT `servis_part`)."""
    from models import ServiceOrderPart
    rows = (db.query(ServiceOrderPart)
            .filter(ServiceOrderPart.service_order_id == service_order_id)
            .order_by(ServiceOrderPart.id.desc()).all())
    out = []
    for u in rows:
        p = _part(db, u.sparepart_id)
        out.append({"id": u.id, "service_order_id": u.service_order_id,
                    "sparepart_id": u.sparepart_id,
                    "label": "%s %s" % (getattr(p, "merek", "") or "",
                                        getattr(p, "jenis", "") or ""),
                    "qty": u.qty, "harga_satuan": u.harga_satuan, "status": u.status,
                    "stock_move_id": u.stock_move_id, "cancel_move_id": u.cancel_move_id,
                    "oleh": u.oleh, "created_at": u.created_at})
    return out