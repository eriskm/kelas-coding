"""P2-12 — endpoint Inventory (ADAPT dari `stock_moves`/`servis_part` Project A).

Authority: `Action.SPAREPART_WRITE` (matrix B yang sudah LOCKED sejak P2-01).

Semua operasi tulis (qty + journal stok + journal audit + link unit) berjalan dalam
SATU transaksi: `commit()` hanya setelah modul sukses, `rollback()` pada kegagalan.
"""
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

import idempotency as idem
import inventory as inv_mod
from authority import Action, require_authority
from dependencies import get_db_session
from models import User
from routers.auth import get_authenticated_user

router = APIRouter(prefix="/api/inventory", tags=["inventory"])

DEFAULT_LIMIT = 100
MAX_LIMIT = 500


def _err(exc):
    return HTTPException(status_code=400, detail=str(exc))


def _dengan_idem(db, scope: str, key: str, payload, aksi):
    """Jalankan aksi endpoint dengan proteksi Idempotency-Key (P2-14)."""
    if not key:
        return aksi()
    try:
        run = idem.jalankan(db, scope, key, payload, aksi)
    except idem.IdempotencyConflict as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc))
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise
    return run.get("result")


@router.post("/masuk")
def barang_masuk(sparepart_id: int = Query(...), qty: int = Query(...),
                 keterangan: str = Query("", description="mis. pembelian/pemasok/retur"),
                 db: Session = Depends(get_db_session),
                 user: User = Depends(require_authority(Action.SPAREPART_WRITE)),
                 idempotency_key: str = Header(None, alias=idem.HEADER)):
    """Barang masuk: qty bertambah + jurnal MASUK. P2-14: idempotency key."""
    return _dengan_idem(db, "inventory.masuk", idempotency_key,
                        {"sparepart_id": sparepart_id, "qty": qty, "keterangan": keterangan},
                        lambda: _masuk_impl(sparepart_id, qty, keterangan, db, user))


def _masuk_impl(sparepart_id, qty, keterangan, db, user):
    oleh = user.display_name or user.username
    try:
        res = inv_mod.catat_masuk(db, sparepart_id, qty, keterangan, oleh)
    except inv_mod.StockConflict as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc))
    except inv_mod.InventoryError as exc:
        db.rollback()
        raise _err(exc)
    except Exception:
        db.rollback()
        raise
    db.commit()
    return {"aksi": inv_mod.AKSI_MASUK, "sparepart_id": sparepart_id, "qty": qty,
            "qty_sebelum": res["qty_sebelum"], "qty_sesudah": res["qty_sesudah"],
            "stock_move_id": res["move"].id}


@router.post("/pakai")
def pakai_part(sparepart_id: int = Query(...), qty: int = Query(...),
               service_order_id: int = Query(None),
               harga_satuan: float = Query(None, description="default = harga jual part"),
               db: Session = Depends(get_db_session),
               user: User = Depends(require_authority(Action.SPAREPART_WRITE)),
               idempotency_key: str = Header(None, alias=idem.HEADER)):
    """Pemakaian sparepart: decrement ATOMIK bila qty cukup. P2-14: idempotency key."""
    return _dengan_idem(db, "inventory.pakai", idempotency_key,
                        {"sparepart_id": sparepart_id, "qty": qty,
                         "service_order_id": service_order_id, "harga_satuan": harga_satuan},
                        lambda: _pakai_impl(sparepart_id, qty, service_order_id,
                                            harga_satuan, db, user))


def _pakai_impl(sparepart_id, qty, service_order_id, harga_satuan, db, user):
    """Pemakaian sparepart: decrement ATOMIK bila qty cukup.

    409 bila stok berubah saat diproses (meniru `rowcount != 1` Project A).
    """
    oleh = user.display_name or user.username
    try:
        res = inv_mod.catat_pakai(db, sparepart_id, qty, service_order_id,
                                  harga_satuan, None, oleh)
    except inv_mod.StockConflict as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc))
    except inv_mod.InventoryError as exc:
        db.rollback()
        raise _err(exc)
    except Exception:
        db.rollback()
        raise
    db.commit()
    return {"aksi": inv_mod.AKSI_PAKAI, "sparepart_id": sparepart_id, "qty": qty,
            "qty_sebelum": res["qty_sebelum"], "qty_sesudah": res["qty_sesudah"],
            "service_order_id": service_order_id,
            "service_order_part_id": getattr(res["usage"], "id", None),
            "stock_move_id": res["move"].id}


@router.post("/pakai/{service_order_part_id}/batal")
def batal_pakai(service_order_part_id: int, alasan: str = Query(""),
                db: Session = Depends(get_db_session),
                user: User = Depends(require_authority(Action.SPAREPART_WRITE)),
                idempotency_key: str = Header(None, alias=idem.HEADER)):
    """Batalkan pemakaian: stok kembali (idempoten). P2-14: idempotency key."""
    return _dengan_idem(db, "inventory.batal", idempotency_key,
                        {"service_order_part_id": service_order_part_id, "alasan": alasan},
                        lambda: _batal_impl(service_order_part_id, alasan, db, user))


def _batal_impl(service_order_part_id, alasan, db, user):
    oleh = user.display_name or user.username
    try:
        res = inv_mod.batalkan_pakai(db, service_order_part_id, oleh, alasan)
    except inv_mod.StockConflict as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc))
    except inv_mod.InventoryError as exc:
        db.rollback()
        raise _err(exc)
    except Exception:
        db.rollback()
        raise
    db.commit()
    return {"aksi": inv_mod.AKSI_BATAL, "idempotent": bool(res["idempotent"]),
            "service_order_part_id": service_order_part_id,
            "pengembalian": res["pengembalian"],
            "qty_sebelum": res["qty_sebelum"], "qty_sesudah": res["qty_sesudah"],
            "stock_move_id": getattr(res["move"], "id", None)}


@router.get("/moves")
def list_moves(sparepart_id: int = Query(None), service_order_id: int = Query(None),
               limit: int = DEFAULT_LIMIT,
               db: Session = Depends(get_db_session),
               user: User = Depends(get_authenticated_user)):
    """Jurnal pergerakan stok (read-only)."""
    return {"items": inv_mod.moves(db, sparepart_id, service_order_id,
                                   min(MAX_LIMIT, max(1, limit)))}


@router.get("/pemakaian/{service_order_id}")
def pemakaian(service_order_id: int, db: Session = Depends(get_db_session),
               user: User = Depends(get_authenticated_user)):
    """Riwayat pemakaian sparepart untuk satu unit (read-only)."""
    return {"service_order_id": service_order_id,
            "items": inv_mod.pemakaian_unit(db, service_order_id)}


# ---------------- Retur Cacat Pabrik (Defective Parts) ----------------
from pydantic import BaseModel
from typing import Optional


class DefectReportCreate(BaseModel):
    sparepart_id: Optional[int] = None
    qty: int = 1
    alasan_cacat: str
    batch_id: Optional[int] = None
    service_order_id: Optional[int] = None
    service_order_part_id: Optional[int] = None


class DefectStatusUpdate(BaseModel):
    status: str
    note: Optional[str] = None


class DefectResolveCreate(BaseModel):
    resolusi: str  # GANTI_BARANG | POTONG_NOTA | DITOLAK
    note: Optional[str] = None


@router.post("/defects", status_code=201)
def lapor_part_cacat(
    data: DefectReportCreate,
    db: Session = Depends(get_db_session),
    user: User = Depends(require_authority(Action.SPAREPART_DEFECT_REPORT))
):
    """Lapor sparepart cacat pabrik:
    - Bisa dilaporkan oleh Teknisi saat servis unit, atau Admin Sparepart saat kelola stok.
    """
    oleh = user.display_name or user.username
    try:
        defect = inv_mod.catat_retur_cacat(
            db=db,
            sparepart_id=data.sparepart_id,
            qty=data.qty,
            alasan_cacat=data.alasan_cacat,
            batch_id=data.batch_id,
            service_order_id=data.service_order_id,
            service_order_part_id=data.service_order_part_id,
            oleh=oleh
        )
        db.commit()
    except inv_mod.StockConflict as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc))
    except inv_mod.InventoryError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))

    return {
        "success": True,
        "id": defect.id,
        "no_retur": defect.no_retur,
        "sparepart_id": defect.sparepart_id,
        "supplier": defect.supplier,
        "qty": defect.qty,
        "modal_satuan": float(defect.modal_satuan or 0),
        "status": defect.status
    }


@router.get("/defects")
def list_part_cacat(
    status: Optional[str] = Query(None, description="Filter status: MENUNGGU, DIKIRIM, GANTI_BARANG, POTONG_NOTA, DITOLAK, ALL"),
    limit: int = Query(DEFAULT_LIMIT),
    db: Session = Depends(get_db_session),
    user: User = Depends(get_authenticated_user)
):
    """Daftar riwayat klaim part cacat ke supplier."""
    items = inv_mod.list_defects(db, status=status, limit=min(MAX_LIMIT, max(1, limit)))
    return {"items": items}


@router.put("/defects/{defect_id}/status")
def update_status_cacat(
    defect_id: int,
    data: DefectStatusUpdate,
    db: Session = Depends(get_db_session),
    user: User = Depends(require_authority(Action.SPAREPART_DEFECT_RESOLVE))
):
    """Update status kirim part cacat ke supplier (mis. MENUNGGU -> DIKIRIM)."""
    oleh = user.display_name or user.username
    try:
        defect = inv_mod.update_status_retur(
            db=db,
            defect_id=defect_id,
            status_baru=data.status,
            note=data.note,
            oleh=oleh
        )
        db.commit()
    except inv_mod.InventoryError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    return {"success": True, "id": defect.id, "status": defect.status}


@router.post("/defects/{defect_id}/resolve")
def selesaikan_klaim_cacat(
    defect_id: int,
    data: DefectResolveCreate,
    db: Session = Depends(get_db_session),
    user: User = Depends(require_authority(Action.SPAREPART_DEFECT_RESOLVE))
):
    """Menyelesaikan klaim retur:
    - GANTI_BARANG: Unit fisik baru dari supplier tiba -> stok fisik bertambah.
    - POTONG_NOTA: Uang dikembalikan / nota belanja dipotong -> stok tidak bertambah.
    - DITOLAK: Supplier menolak garansi -> dicatat rugi.
    """
    oleh = user.display_name or user.username
    try:
        defect = inv_mod.resolusi_retur(
            db=db,
            defect_id=defect_id,
            resolusi=data.resolusi,
            note=data.note,
            oleh=oleh
        )
        db.commit()
    except inv_mod.InventoryError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "success": True,
        "id": defect.id,
        "no_retur": defect.no_retur,
        "status": defect.status,
        "resolusi_note": defect.resolusi_note
    }
