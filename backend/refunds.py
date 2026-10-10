# -*- coding: utf-8 -*-
"""P2-10 — Domain Refund: 3 jenis, 3 sumber dana, 1 efek finansial (Q9).

Owner Locks (Q9 / OD-016 / FIX-17b):
  1. Refund DP           — authority Admin/Kasir (`Action.REFUND_DP`),
                           dana dari **Laci (Kas Perputaran)**, berbasis DP diterima.
  2. Refund Garansi      — authority **Admin** (`Action.REFUND_GARANSI`),
                           dana dari **Kas Aset** + pre-check kecukupan,
                           nominal full/partial sesuai kesepakatan.
  3. Failed → Cancel     — authority Admin/Kasir (`Action.FAILED_CANCEL`),
                           dana dari **Laci**, BUKAN refund garansi.

Aturan yang dijaga di modul ini:
- **SATU efek finansial per refund** (tidak ada debit ganda seperti A
  `app.py:2296`+`2303`). Satu refund = satu baris `kas_entries` + satu journal.
- **Laci & Kas Aset tidak pernah dijumlahkan** (SSOT-7): refund dari Laci hanya
  menyentuh layer `LACI`, refund garansi hanya `KAS_ASET`.
- Tidak mengubah definisi Omzet/Laba/Beban (out of scope roadmap P2-10).
- Tidak ada `commit` di modul: pemanggil (router) yang mengatur transaksi → atomic.
"""
from __future__ import annotations

import secrets
from datetime import datetime

from sqlalchemy.orm import Session

import cash
import journal
from money import ZERO, quantize, to_decimal

JENIS_DP = "DP"
JENIS_GARANSI = "GARANSI"
JENIS_FAILED_CANCEL = "FAILED_CANCEL"

#: Sumber dana per jenis — TIDAK boleh tertukar (Q9).
SUMBER_DANA = {
    JENIS_DP: cash.LAYER_LACI,
    JENIS_GARANSI: cash.LAYER_ASET,
    JENIS_FAILED_CANCEL: cash.LAYER_LACI,
}

KATEGORI = {
    JENIS_DP: "Refund DP",
    JENIS_GARANSI: "Refund Garansi",
    JENIS_FAILED_CANCEL: "Refund Failed-Cancel",
}

EVENT_REFUND = "REFUND_DITERBITKAN"

#: Sumber mutasi posisi kas per jenis refund (v4).
SUMBER_BY_JENIS = {
    JENIS_DP: cash.SUMBER_REFUND_DP,
    JENIS_FAILED_CANCEL: cash.SUMBER_FAILED_CANCEL,
}


class RefundError(ValueError):
    """Syarat refund tidak terpenuhi (dinaikkan sebelum efek apa pun ditulis)."""


class RefundKurangKas(ValueError):
    """Pre-check sumber dana tidak mencukupi."""

    def __init__(self, saldo, diminta):
        self.saldo = saldo
        self.diminta = diminta
        self.kurang = quantize(diminta - saldo)
        super().__init__("Saldo %s tidak cukup untuk refund %s (kurang %s)" % (
            cash.LABEL[cash.norm_layer(SUMBER_DANA[JENIS_GARANSI])], diminta, self.kurang))


def _no_refund(jenis: str) -> str:
    return "RFD-%s-%s" % (jenis[:2], datetime.now().strftime("%Y%m%d")) + "-" + secrets.token_hex(3)


def dp_diterima(db: Session, order_id: int):
    """Total DP yang benar-benar diterima (dari jurnal payments — Q3/Q17)."""
    from models import Payment
    rows = (db.query(Payment)
            .filter(Payment.service_order_id == order_id)
            .all())
    total = ZERO
    for r in rows:
        if (r.kind or "").strip().upper() == "DP":
            total += to_decimal(r.amount)
    return quantize(total)


def total_diterima(db: Session, order_id: int):
    """Total seluruh pembayaran diterima untuk satu unit."""
    from models import Payment
    rows = db.query(Payment).filter(Payment.service_order_id == order_id).all()
    return quantize(sum((to_decimal(r.amount) for r in rows), ZERO))


def sudah_refund(db: Session, jenis: str, order_id=None, claim_id=None):
    """Total nominal yang SUDAH dikembalikan untuk scope yang sama."""
    from models import Refund
    q = db.query(Refund).filter(Refund.jenis == jenis)
    if order_id is not None:
        q = q.filter(Refund.service_order_id == order_id)
    if claim_id is not None:
        q = q.filter(Refund.warranty_claim_id == claim_id)
    return quantize(sum((to_decimal(r.nominal) for r in q.all()), ZERO))


def _catat(db: Session, jenis: str, nominal, layer: str, keterangan: str,
           alasan=None, order_id=None, claim_id=None, oleh: str = None,
           otomatis: bool = True):
    """Tulis SATU refund + (opsional) SATU efek saldo + SATU journal (tanpa commit).

    v4 #8: untuk refund GARANSI (`otomatis=False`) proses tidak boleh otomatis
    mengurangi saldo posisi — pengeluaran aktual dicatat manual oleh Admin
    (`POST /api/kas/aset/keluar`). Pre-check tetap memverifikasi Saldo Aset.
    """
    from models import Refund

    n = quantize(to_decimal(nominal))
    if n <= ZERO:
        raise RefundError("Nominal refund harus lebih besar dari nol")

    if layer == cash.LAYER_KAS_ASET:
        cukup, saldo, kurang = cash.cukup_kas_aset(db, n)
        if not cukup:
            raise RefundKurangKas(saldo, n)
    else:
        # Laci: cukup dengan saldo Laci (tanpa menggabungkannya dengan Kas Aset).
        saldo_laci = cash.saldo_laci(db)
        if saldo_laci < n:
            raise RefundError("Saldo Kas Perputaran (Laci) tidak cukup untuk refund %s "
                              "(saldo %s, diminta %s)" % (n, saldo_laci, n))

    row = Refund(refund_no=_no_refund(jenis), jenis=jenis,
                 service_order_id=order_id, warranty_claim_id=claim_id,
                 nominal=n, sumber_dana=layer, alasan=alasan, oleh=oleh)
    db.add(row)
    db.flush()

    # SATU-SATUNYA efek saldo untuk refund ini (kecuali v4 #8 non-otomatis).
    mutasi = None
    if otomatis:
        mutasi = cash.catat_mutasi(db, layer, "Keluar", KATEGORI[jenis], keterangan, n,
                                   sumber=SUMBER_BY_JENIS.get(jenis, cash.SUMBER_MANUAL),
                                   ref_type="refund", ref_id=row.id, check_saldo=False)
        row.kas_entry_id = mutasi["id"]
    else:
        journal.record(db, journal.DOMAIN_FINANCE, EVENT_REFUND,
                       entity_type="refund", entity_id=row.id, amount=n, actor=oleh,
                       ref_type="kas_aset", ref_code=str(layer),
                       details={"jenis": jenis, "sumber_dana": "SALDO_ASET_BESAR",
                                "nominal": str(n),
                                "pengeluaran_aktual": "MANUAL oleh Admin (POST /api/kas/aset/keluar)"})

    journal.record(db, journal.DOMAIN_FINANCE, EVENT_REFUND,
                   entity_type="refund", entity_id=row.id, amount=n,
                   actor=oleh,
                   ref_type=("kas_entry" if mutasi else layer),
                   ref_code=str((mutasi or {}).get("id") or layer),
                   details={"jenis": jenis, "sumber_dana": layer, "nominal": str(n),
                            "service_order_id": order_id,
                            "warranty_claim_id": claim_id,
                            "efek_saldo": ("otomatis" if mutasi
                                           else "manual oleh Admin (v4 #8)")})
    db.flush()
    db.refresh(row)
    return row, mutasi


# ---------------- 1. Refund DP (Admin/Kasir, dana LACI) ----------------
def refund_dp(db: Session, service_order_id: int, nominal=None, alasan=None,
              oleh: str = None):
    """Refund DP — berbasis DP diterima. Dana dari Laci (SSOT-7 terpisah)."""
    from models import ServiceOrder
    order = db.query(ServiceOrder).filter(ServiceOrder.id == service_order_id).first()
    if order is None:
        raise RefundError("Unit servis tidak ditemukan")

    dasar = dp_diterima(db, service_order_id)
    if dasar <= ZERO:
        raise RefundError("Tidak ada DP diterima pada unit ini — refund DP tidak berlaku")

    n = quantize(to_decimal(nominal)) if nominal is not None else dasar
    if n <= ZERO:
        raise RefundError("Nominal refund harus lebih besar dari nol")
    if n > dasar:
        raise RefundError("Nominal refund DP %s melebihi DP diterima %s" % (n, dasar))
    sisa = quantize(dasar - sudah_refund(db, JENIS_DP, order_id=service_order_id))
    if n > sisa:
        raise RefundError("Sisa DP yang belum direfund %s lebih kecil dari nominal %s"
                          % (sisa, n))

    keterangan = "Refund DP unit %s (%s)" % (order.no_servis, order.device or "-")
    return _catat(db, JENIS_DP, n, cash.LAYER_LACI, keterangan, alasan=alasan,
                  order_id=service_order_id, oleh=oleh, otomatis=True)


# ---------------- 2. Refund Garansi (Admin, dana KAS_ASET) ----------------
def refund_garansi(db: Session, warranty_claim_id: int, nominal=None, alasan=None,
                   oleh: str = None):
    """Refund Klaim Garansi — nominal kesepakatan. Dana dari Kas Aset + pre-check."""
    from models import WarrantyClaim
    claim = db.query(WarrantyClaim).filter(WarrantyClaim.id == warranty_claim_id).first()
    if claim is None:
        raise RefundError("Klaim garansi tidak ditemukan")

    if nominal is not None:
        n = quantize(to_decimal(nominal))
    else:
        n = quantize(to_decimal(claim.customer_cost))
        if n <= ZERO:
            raise RefundError("Nominal kesepakatan wajib diisi (biaya pelanggan klaim kosong)")

    keterangan = "Refund garansi klaim %s (unit %s)" % (
        claim.claim_no, getattr(claim.service_order, "no_servis", "-"))
    # v4 #8: sumber dana SALDO ASET BESAR; pengeluaran aktual dicatat manual Admin.
    return _catat(db, JENIS_GARANSI, n, cash.LAYER_ASET, keterangan, alasan=alasan,
                  order_id=claim.service_order_id, claim_id=warranty_claim_id, oleh=oleh,
                  otomatis=False)


# ---------------- 3. Failed -> Cancel (Admin/Kasir, dana LACI) ----------------
def refund_failed_cancel(db: Session, service_order_id: int, nominal=None,
                         alasan=None, oleh: str = None):
    """Failed → Cancel — dana dari Laci. BUKAN refund garansi (Q9 titik 3)."""
    from models import ServiceOrder
    order = db.query(ServiceOrder).filter(ServiceOrder.id == service_order_id).first()
    if order is None:
        raise RefundError("Unit servis tidak ditemukan")

    dasar = dp_diterima(db, service_order_id)
    if dasar <= ZERO:
        dasar = total_diterima(db, service_order_id)
    if dasar <= ZERO:
        raise RefundError("Tidak ada dana diterima pada unit ini — Failed → Cancel tidak berlaku")

    n = quantize(to_decimal(nominal)) if nominal is not None else dasar
    if n <= ZERO:
        raise RefundError("Nominal refund harus lebih besar dari nol")
    # Plafond: tidak boleh melebihi dana yang benar-benar diterima.
    if n > dasar:
        raise RefundError("Nominal Failed → Cancel %s melebihi dana diterima %s" % (n, dasar))
    sisa = quantize(dasar - sudah_refund(db, JENIS_FAILED_CANCEL, order_id=service_order_id))
    if n > sisa:
        raise RefundError("Sisa dana yang belum dikembalikan %s lebih kecil dari nominal %s"
                          % (sisa, n))

    keterangan = "Failed → Cancel unit %s (%s)" % (order.no_servis, order.device or "-")
    return _catat(db, JENIS_FAILED_CANCEL, n, cash.LAYER_LACI, keterangan,
                  alasan=alasan, order_id=service_order_id, oleh=oleh, otomatis=True)


# ---------------- Pre-check (read-only) ----------------
def precheck_dp(db: Session, service_order_id: int):
    dasar = dp_diterima(db, service_order_id)
    refunded = sudah_refund(db, JENIS_DP, order_id=service_order_id)
    return {"jenis": JENIS_DP, "sumber_dana": cash.LAYER_LACI, "dasar": dasar,
            "sudah_refund": refunded, "sisa": quantize(dasar - refunded),
            "bisa_refund": bool(quantize(dasar - refunded) > ZERO)}


def precheck_garansi(db: Session, warranty_claim_id: int, nominal=None):
    from models import WarrantyClaim
    claim = db.query(WarrantyClaim).filter(WarrantyClaim.id == warranty_claim_id).first()
    dasar = quantize(to_decimal(getattr(claim, "customer_cost", 0))) if claim else ZERO
    n = quantize(to_decimal(nominal)) if nominal is not None else dasar
    saldo = cash.saldo_kas_aset(db)
    return {"jenis": JENIS_GARANSI, "sumber_dana": cash.LAYER_ASET,
            "dasar": dasar, "diminta": n, "saldo_kas_aset": saldo,
            "cukup": bool(n <= ZERO or saldo >= n), "claim_found": claim is not None}