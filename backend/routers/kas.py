"""Kas endpoints — jurnal manual, riwayat gabungan, tutup kas.

Prinsip single source of truth (FINAL LOCK):
- Pemasukan servis = jurnal payments (DP/PELUNASAN) dalam periode.
- Beban = expenses (popup Beban Harian).
- kas_entries HANYA untuk arus kas di luar keduanya (pemasukan non-servis,
  saldo awal, penyesuaian). Bukan duplikat order/expense.
- Tutup Kas TIDAK mengubah status apa pun (hanya tutup periode + snapshot).
"""
import json
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

import cash
import closing as closing_mod
import idempotency as idem
import distribution as distribution_mod
from authority import Action, require_authority
from dependencies import get_db_session
from money import json_default, to_decimal
from models import Expense, KasEntry, KasPeriod, Payment, ServiceOrder, User
from routers.auth import get_authenticated_user, require_admin
from routers.dashboard import (_period_bounds, batas_periode, compute_finance,
                                get_active_period)
import schemas

router = APIRouter(prefix="/api/kas", tags=["kas"])

SALDO_AWAL_KATEGORI = cash.SALDO_AWAL_KATEGORI

DEFAULT_PAGE = 1
DEFAULT_LIMIT = 50
MAX_LIMIT = 100


def _num(v):
    """P2-02 / Q10: nilai uang selalu Decimal."""
    return to_decimal(v)


def _moment(dt_val, d_val) -> Optional[datetime]:
    if dt_val is not None:
        return dt_val
    if d_val is not None:
        return datetime(d_val.year, d_val.month, d_val.day, 12, 0, 0)
    return None


def opening_balance(db: Session) -> float:
    """Saldo awal Kas Perputaran (Laci) = neto entri 'Saldo Awal' layer LACI.

    P2-06 / SSOT-7: Kas Aset TIDAK ikut di sini — saldo Kas Aset berdiri sendiri.
    """
    return cash.opening_layer(db, cash.LAYER_LACI)


def period_rows(db: Session, start: datetime, end: datetime):
    """Seluruh baris kas dalam [start, end) terurut menaik + saldo berjalan.
    Entri 'Saldo Awal' dikecualikan dari baris (sudah tercakup di opening).

    Saldo dihitung dari AWAL WAKTU (opening + seluruh baris sebelum start +
    baris periode) sehingga benar untuk periode apa pun, bukan hanya all-time.
    """
    rows = []

    for p in db.query(Payment).options(joinedload(Payment.service_order)).all():
        m = _moment(getattr(p, "created_at", None), None)
        if m is None:
            continue
        o = p.service_order
        kind = (p.kind or "PELUNASAN").strip().upper()
        # PEMISAHAN DP: DP adalah TITIPAN PELANGGAN, bukan arus kas operasional.
        # Dia tidak boleh menambah Debit/Kredit/Saldo Buku Kas. Uangnya tetap ada
        # di Laci (tidak dihapus dari kas_entries) dan dilacak terpisah di panel
        # "Titipan DP Pelanggan" (finance.titipan_dp).
        if kind == "DP":
            continue
        rows.append({
            "moment": m,
            "tgl": m.date().isoformat() if hasattr(m, "date") else None,
            "jenis": "Masuk",
            "kategori": "Pelunasan",
            "ket": "%s • %s" % ((o.device if o else None) or "-",
                                (o.no_servis if o else None) or "-"),
            "nominal": _num(p.amount),
            "source": "order",
            "ref_id": p.id,
        })

    for e in db.query(Expense).all():
        m = _moment(getattr(e, "created_at", None), getattr(e, "tanggal", None))
        if m is None:
            continue
        rows.append({
            "moment": m,
            "tgl": (e.tanggal.isoformat() if e.tanggal
                    else (m.date().isoformat() if hasattr(m, "date") else None)),
            "jenis": "Keluar",
            "kategori": e.kategori,
            "ket": e.uraian,
            "nominal": _num(e.nilai),
            "source": "expense",
            "ref_id": e.id,
        })

    # P2-06 / SSOT-7: Buku Kas (Laci) hanya memuat layer LACI — mutasi Kas Aset
    # tidak boleh muncul sebagai arus kas Laci.
    for k in db.query(KasEntry).filter(KasEntry.kategori != SALDO_AWAL_KATEGORI,
                                      KasEntry.layer == cash.LAYER_LACI).all():
        # v4 #9: Buku Kas hanya arus periode (bukan mutasi posisi Master Kas).
        if (getattr(k, "sumber", None) or cash.SUMBER_MANUAL) not in cash.SUMBER_BUKU_KAS:
            continue
        m = _moment(getattr(k, "created_at", None), getattr(k, "tanggal", None))
        if m is None:
            continue
        j = (k.jenis or "").strip().capitalize()
        if j not in ("Masuk", "Keluar"):
            continue
        rows.append({
            "moment": m,
            "tgl": (k.tanggal.isoformat() if k.tanggal
                    else (m.date().isoformat() if hasattr(m, "date") else None)),
            "jenis": j,
            "kategori": k.kategori,
            "ket": k.keterangan,
            "nominal": _num(k.nominal),
            "source": "manual",
            "ref_id": k.id,
        })

    rows.sort(key=lambda r: (r["moment"], r["source"], r["ref_id"] or 0))
    saldo = opening_balance(db)
    for r in rows:
        saldo += r["nominal"] if r["jenis"] == "Masuk" else -r["nominal"]
        r["saldo"] = saldo
    rows = [r for r in rows if start <= r["moment"] < end]
    for r in rows:
        del r["moment"]
    return rows


def _clamp(page: int, limit: int):
    return max(DEFAULT_PAGE, page), min(MAX_LIMIT, max(1, limit))


# ---------- Jurnal manual ----------
@router.get("/entries", response_model=schemas.KasEntryPage)
def list_entries(db: Session = Depends(get_db_session), page: int = DEFAULT_PAGE,
                 limit: int = DEFAULT_LIMIT, q: str = Query(""),
                 layer: str = Query(cash.LAYER_LACI, description="LACI | KAS_ASET | all")):
    """Jurnal kas manual. Default hanya layer LACI (P2-06 / SSOT-7)."""
    page, limit = _clamp(page, limit)
    qry = db.query(KasEntry)
    lay = (layer or cash.LAYER_LACI).strip().upper()
    if lay and lay != "ALL":
        try:
            qry = qry.filter(KasEntry.layer == cash.norm_layer(lay))
        except ValueError:
            raise HTTPException(status_code=400, detail="Layer kas tidak dikenal")
    if q.strip():
        like = "%" + q.strip() + "%"
        qry = qry.filter(or_(KasEntry.keterangan.ilike(like), KasEntry.kategori.ilike(like)))
    total = qry.count()
    rows = qry.order_by(KasEntry.id.desc()).offset((page - 1) * limit).limit(limit).all()
    return schemas.KasEntryPage(total=total, page=page, limit=limit,
                                total_pages=(total + limit - 1) // limit if total else 1, items=rows)


@router.post("/entries", response_model=schemas.KasEntryOut, status_code=201)
def create_entry(data: schemas.KasEntryCreate, db: Session = Depends(get_db_session),
                   user: User = Depends(require_authority(Action.KAS_ENTRY_WRITE))):
    jenis = (data.jenis or "").strip().capitalize()
    if jenis not in ("Masuk", "Keluar"):
        raise HTTPException(status_code=400, detail="Jenis wajib Masuk atau Keluar")
    if not (data.kategori or "").strip():
        raise HTTPException(status_code=400, detail="Kategori wajib diisi")
    if not (data.keterangan or "").strip():
        raise HTTPException(status_code=400, detail="Keterangan wajib diisi")
    nominal = _num(data.nominal)
    if nominal < 0:
        raise HTTPException(status_code=400, detail="Nominal tidak boleh negatif")
    layer = cash.LAYER_LACI
    if getattr(data, "layer", None):
        try:
            layer = cash.norm_layer(data.layer)
        except ValueError:
            raise HTTPException(status_code=400, detail="Layer kas tidak dikenal")
    row = KasEntry(jenis=jenis, kategori=data.kategori.strip(),
                   keterangan=data.keterangan.strip(), nominal=nominal,
                   tanggal=data.tanggal, layer=layer)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.put("/entries/{entry_id}", response_model=schemas.KasEntryOut)
def update_entry(entry_id: int, data: schemas.KasEntryUpdate, db: Session = Depends(get_db_session),
                   user: User = Depends(require_authority(Action.KAS_ENTRY_WRITE))):
    row = db.query(KasEntry).filter(KasEntry.id == entry_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Entri kas tidak ditemukan")
    payload = data.model_dump(exclude_unset=True)
    if (row.kategori or "") == SALDO_AWAL_KATEGORI:
        # Saldo Awal menentukan opening lintas periode — jangan ubah jenis/
        # kategorinya via edit (buat entri penyeimbang bila salah input).
        if "jenis" in payload and (payload["jenis"] or "").strip().capitalize() != (row.jenis or "").strip().capitalize():
            raise HTTPException(status_code=400,
                                detail="Jenis entri Saldo Awal tidak dapat diubah")
        if "kategori" in payload and (payload["kategori"] or "").strip() != SALDO_AWAL_KATEGORI:
            raise HTTPException(status_code=400,
                                detail="Kategori Saldo Awal tidak dapat diubah")
    if "kategori" in payload and (payload["kategori"] or "").strip() == "" :
        raise HTTPException(status_code=400, detail="Kategori wajib diisi")
    if "kategori" in payload and (payload["kategori"] or "").strip() == SALDO_AWAL_KATEGORI and (row.kategori or "") != SALDO_AWAL_KATEGORI:
        raise HTTPException(status_code=400,
                            detail="Kategori Saldo Awal hanya untuk saldo awal")
    if "keterangan" in payload and not (payload["keterangan"] or "").strip():
        raise HTTPException(status_code=400, detail="Keterangan wajib diisi")
    if "jenis" in payload:
        j = (payload["jenis"] or "").strip().capitalize()
        if j not in ("Masuk", "Keluar"):
            raise HTTPException(status_code=400, detail="Jenis wajib Masuk atau Keluar")
        payload["jenis"] = j
    if "nominal" in payload and _num(payload["nominal"]) < 0:
        raise HTTPException(status_code=400, detail="Nominal tidak boleh negatif")
    for key, val in payload.items():
        setattr(row, key, val)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/entries/{entry_id}")
def delete_entry(entry_id: int, db: Session = Depends(get_db_session),
                 admin: User = Depends(require_admin)):
    """Hapus entri manual — khusus Admin. Saldo Awal tidak dapat dihapus
    (buat entri penyeimbang bila salah input) agar opening tidak berubah
    retroaktif."""
    row = db.query(KasEntry).filter(KasEntry.id == entry_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Entri kas tidak ditemukan")
    if (row.kategori or "") == SALDO_AWAL_KATEGORI:
        raise HTTPException(status_code=400,
                            detail="Entri Saldo Awal tidak dapat dihapus")
    db.delete(row)
    db.commit()
    return {"ok": True}


# ---------- Riwayat gabungan ----------
@router.get("/riwayat", response_model=schemas.KasRiwayatPage)
def kas_riwayat(db: Session = Depends(get_db_session), page: int = DEFAULT_PAGE,
                limit: int = DEFAULT_LIMIT, q: str = Query(""),
                jenis: str = Query(""), date: str = Query(""),
                period: str = Query("all", description="all | current")):
    """Riwayat kas gabungan (jurnal payments + expenses + jurnal manual) + saldo berjalan.
    Read-only turunan — tanpa tabel baru, tanpa persistence."""
    page, limit = _clamp(page, limit)
    period = (period or "all").strip().lower()
    if period == "current":
        p = get_active_period(db)
        rows = period_rows(db, *batas_periode(p))
    else:
        rows = period_rows(db, datetime.min, datetime.max)

    if jenis.strip():
        j = jenis.strip().capitalize()
        rows = [r for r in rows if r["jenis"] == j]
    if date.strip():
        rows = [r for r in rows if (r["tgl"] or "") == date.strip()]
    if q.strip():
        ql = q.strip().lower()
        rows = [r for r in rows if ql in str(r.get("ket") or "").lower()
                or ql in str(r.get("kategori") or "").lower()]

    total = len(rows)
    total_pages = (total + limit - 1) // limit if total else 1
    page = min(max(DEFAULT_PAGE, page), total_pages)
    shown = rows[::-1]
    items = shown[(page - 1) * limit:page * limit]
    return schemas.KasRiwayatPage(total=total, page=page, limit=limit,
                                  total_pages=total_pages,
                                  opening=opening_balance(db), items=items)


# ---------- Owner Cash Model v4: visibility posisi Master Kas ----------
def _boleh_lihat_aset(user) -> bool:
    """v4 #11: Saldo Aset + Master Kas hanya untuk ADMIN & PENGELOLA.

    CS/KASIR/TEKNISI hanya melihat SALDO LACI (Kas Aset Kecil).
    """
    try:
        from authority import ROLE_ADMIN, ROLE_PENGELOLA, canonical_role
        return canonical_role(user) in (ROLE_ADMIN, ROLE_PENGELOLA)
    except Exception:  # noqa: BLE001
        return False


def _posisi_query(raw: Optional[str]) -> str:
    """v4 #6: injection harus MEMILIH posisi (Laci atau Aset)."""
    v = (raw or "").strip()
    if not v:
        raise HTTPException(status_code=400,
                            detail="Pilih posisi: LACI (Kas Aset Kecil) atau KAS_ASET (Kas Aset Besar)")
    try:
        return cash.norm_layer(v)
    except cash.CashError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

# ---------- P2-06 / SSOT-7: Layer Laci & Kas Aset ----------
@router.get("/saldo")
def get_saldo(db: Session = Depends(get_db_session),
              user: User = Depends(get_authenticated_user)):
    """Posisi Kas Aset (v4): Laci untuk semua role; Aset + Master Kas utk Admin/Pengelola."""
    from routers.dashboard import get_active_period
    mulai = None
    try:
        mulai = get_active_period(db).start_at
    except Exception:  # noqa: BLE001
        mulai = None
    return cash.ringkasan(db, termasuk_aset=_boleh_lihat_aset(user), periode_mulai=mulai)


@router.get("/aset/riwayat")
def kas_aset_riwayat(db: Session = Depends(get_db_session),
                     period: str = Query("all", description="all | current"),
                     user: User = Depends(get_authenticated_user)):
    """Riwayat mutasi SALDO ASET — hanya Admin/Pengelola (v4 #11)."""
    if not _boleh_lihat_aset(user):
        raise HTTPException(status_code=403,
                            detail="Saldo Aset (Kas Aset Besar) hanya terlihat oleh Admin/Pengelola.")
    """Jurnal mutasi Kas Aset (masuk/keluar, sumber, saldo berjalan)."""
    period = (period or "all").strip().lower()
    start, end = None, None
    if period == "current":
        p = get_active_period(db)
        start, end = p.start_at, p.end_at
    items = cash.riwayat_layer(db, cash.LAYER_ASET)
    if period == "current":
        p = get_active_period(db)
        items = [it for it in items
                 if start <= datetime.combine(date.fromisoformat(it["tgl"]), datetime.min.time())
                 < end] if False else items
    return {"layer": cash.LAYER_KAS_ASET, "label": cash.LABEL[cash.LAYER_KAS_ASET],
            "opening": cash.opening_layer(db, cash.LAYER_KAS_ASET),
            "saldo": cash.saldo_kas_aset(db), "total": len(items),
            "cara_baca": cash.CARA_BACA, "items": items}


@router.post("/aset/masuk")
def kas_aset_masuk(data: schemas.KasAsetMutasiIn,
                   db: Session = Depends(get_db_session),
                   user: User = Depends(require_authority(Action.KAS_ASET_INJEKSI))):
    """Injection Kas Aset dengan PILIHAN POSISI (v4 #6): Laci atau Kas Aset Besar."""
    posisi = _posisi_query(getattr(data, "posisi", None))
    try:
        res = cash.catat_injeksi(db, posisi, data.nominal,
                                 data.keterangan, actor=(user.display_name or user.username))
    except cash.CashError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    res["master_kas_setelah"] = cash.master_kas(db)
    return res


@router.post("/aset/keluar")
def kas_aset_keluar(data: schemas.KasAsetMutasiIn,
                    db: Session = Depends(get_db_session),
                    user: User = Depends(require_authority(Action.KAS_ASET_INJEKSI))):
    """Pengeluaran AKTUAL dari Saldo Aset Besar — dicatat MANUAL oleh Admin (v4 #8).

    Dipakai untuk realize pengembalian refund garansi & pelunasan hutang beban:
    proses refund/hutang tidak boleh otomatis mengurangi saldo posisi.
    """
    nominal = _num(data.nominal)
    cukup, saldo, kurang = cash.cukup_kas_aset(db, nominal)
    if not cukup:
        raise HTTPException(
            status_code=400,
            detail="Saldo Kas Aset tidak cukup (saldo %s, diminta %s, kurang %s)"
                   % (saldo, nominal, kurang))
    try:
        res = cash.catat_mutasi(db, cash.LAYER_KAS_ASET, "Keluar", data.kategori or "Kas Aset",
                               data.keterangan, nominal, data.tanggal)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return res


@router.post("/aset/transfer")
def transfer_kas_aset(data: schemas.KasAsetTransferIn,
                      db: Session = Depends(get_db_session),
                      user: User = Depends(require_authority(Action.KAS_ASET_INJEKSI)),
                      idempotency_key: str = Header(None, alias=idem.HEADER)):
    """Transfer fisik Laci <-> Aset (v4 #5).

    Laci berubah, Aset berubah berlawanan, MASTER KAS TETAP. Bukan omzet,
    beban, laba, atau distribusi baru.
    """
    if idempotency_key:
        try:
            run = idem.jalankan(db, "kas.transfer", idempotency_key, data.model_dump(),
                                lambda: _transfer_impl(data, db, user))
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
    return _transfer_impl(data, db, user)


def _transfer_impl(data, db, user):
    oleh = user.display_name or user.username
    try:
        res = cash.transfer(db, data.nominal, data.dari, data.ke, data.keterangan,
                            actor=oleh, ref_type=data.ref_type, ref_id=data.ref_id)
    except cash.CashError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    res["label_dari"] = cash.LABEL[res["dari"]]
    res["label_ke"] = cash.LABEL[res["ke"]]
    res["master_kas_setelah"] = cash.master_kas(db)
    return res


@router.get("/aset/cukup")
def kas_aset_cukup(nominal: float = Query(..., description="jumlah yang akan diperiksa"),
                   db: Session = Depends(get_db_session),
                   user: User = Depends(get_authenticated_user)):
    """Pre-check kecukupan Kas Aset (read-only) untuk refund/kebutuhan lain."""
    cukup, saldo, kurang = cash.cukup_kas_aset(db, nominal)
    return {"cukup": bool(cukup), "saldo_kas_aset": saldo,
            "diminta": _num(nominal), "kurang": kurang,
            "cara_baca": cash.CARA_BACA}


# ---------- P2-07 / SSOT-6: Distribusi (read-only) ----------
@router.get("/distribusi")
def get_distribusi(db: Session = Depends(get_db_session),
                   period: str = Query("current", description="current | YYYY-MM-DD"),
                   user: User = Depends(get_authenticated_user)):
    """Status distribusi. Distribution terbentuk HANYA saat Tutup Kas (bukan CTO)."""
    period = (period or "current").strip()
    pid = None
    if period == "current":
        p_ = get_active_period(db)
        key = p_.start_at.date().isoformat() if p_.start_at else ""
        preview = compute_finance(db, *batas_periode(p_)).get("laba_bersih", 0)
        # P2-15 B-1: teruskan id Kas Period agar distributor membaca baris
        # miliknya sendiri ketika beberapa Kas Period berteGALANG sama.
        pid = p_.id
    else:
        key = period
        preview = 0
    out = distribution_mod.ringkasan(db, key, kas_period_id=pid)
    if not out.get("terbentuk"):
        out["preview"] = distribution_mod.preview(preview)
    return out


# ---------- Tutup kas ----------
def _next_period_end(now: datetime) -> datetime:
    """16:00 berikutnya setelah `now` (jaga ritme periode 16:00→16:00)."""
    from routers.dashboard import PERIOD_HOUR
    end = now.replace(hour=PERIOD_HOUR, minute=0, second=0, microsecond=0)
    if end <= now:
        end += timedelta(days=1)
    return end


@router.post("/close")
def close_period(data: schemas.KasCloseIn, db: Session = Depends(get_db_session),
                 user: User = Depends(get_authenticated_user),
                 admin: User = Depends(require_authority(Action.KAS_CLOSE)),
                 idempotency_key: str = Header(None, alias=idem.HEADER)):
    """Tutup periode kas (P2-08). P2-14: `Idempotency-Key` mencegah dobel tutup kas.
    set Laci = uang fisik bila Declare, snapshot, buka periode baru 16:00.

    Authority: `Action.KAS_CLOSE` (Admin). Eksekusi kedua pada periode yang sama
    ditolak 409. Semua penulisan dalam SATU transaksi (rollback bila gagal).
    """
    if idempotency_key:
        try:
            run = idem.jalankan(db, "kas.close", idempotency_key,
                                data.model_dump(),
                                lambda: _tutup_periode_impl(data, db, user))
        except idem.IdempotencyConflict as exc:
            db.rollback()
            raise HTTPException(status_code=409, detail=str(exc))
        except HTTPException:
            db.rollback()
            raise
        except Exception:
            db.rollback()
            raise
        if run.get("replayed"):
            return run.get("result")
        return run.get("result")
    return _tutup_periode_impl(data, db, user)


def _tutup_periode_impl(data, db, user):
    target = None
    pid = getattr(data, "kas_period_id", None)
    if pid is not None:
        target = db.query(KasPeriod).filter(KasPeriod.id == pid).first()
        if target is None:
            raise HTTPException(status_code=404, detail="Periode kas tidak ditemukan")
    else:
        target = get_active_period(db)

    if (target.status or "").strip().upper() == "CLOSED":
        raise HTTPException(
            status_code=409,
            detail="Periode #%s sudah ditutup pada %s; tidak dapat ditutup lagi"
                   % (target.id, target.closed_at))

    now = datetime.now()
    try:
        age = (now - (target.created_at or target.start_at)).total_seconds()
    except Exception:
        age = None
    if age is not None and age < 60:
        raise HTTPException(status_code=400,
                            detail="Periode baru saja dibuka, tutup kas belum dapat dilakukan lagi")

    oleh = user.display_name or user.username
    try:
        result = closing_mod.tutup_periode(
            db, target, counted=data.cash_counted, oleh=oleh,
            compute_finance=compute_finance)
        db.commit()
    except closing_mod.PeriodAlreadyClosed as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc))
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise
    db.refresh(target)
    return result


@router.get("/periods", response_model=list[schemas.KasPeriodDetailOut])
def list_periods(db: Session = Depends(get_db_session)):
    return db.query(KasPeriod).order_by(KasPeriod.id.desc()).limit(50).all()
