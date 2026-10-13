"""Kas endpoints — jurnal manual, riwayat gabungan, tutup kas.

Prinsip single source of truth (FINAL LOCK):
- Pemasukan servis = jurnal payments (DP/PELUNASAN) dalam periode.
- Beban = expenses (popup Beban Harian).
- kas_entries HANYA untuk arus kas di luar keduanya (pemasukan non-servis,
  saldo awal, penyesuaian). Bukan duplikat order/expense.
- Rincian Arus Kas memakai allow-list `cash.SUMBER_BARIS_KAS` yang LEBIH LEBAR
  dari `cash.SUMBER_BUKU_KAS` milik `compute_finance`: modal & pelepasan titipan
  DP wajib tampil sebagai baris, kalau tidak tabelnya tidak akan cocok dengan
  Conditions Kas (kartu) di atasnya.
- Tutup Kas TIDAK mengubah status apa pun (hanya tutup periode + snapshot).
"""
import json
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

import cash
import closing as closing_mod
import idempotency as idem
import distribution as distribution_mod
from authority import Action, require_authority
from dependencies import get_db_session
from money import ZERO, json_default, to_decimal
from models import Expense, KasEntry, KasPeriod, Payment, ServiceOrder, User
from routers.auth import get_authenticated_user, require_admin
from routers.dashboard import (_period_bounds, batas_periode, compute_finance,
                                get_active_period)
import schemas

router = APIRouter(prefix="/api/kas", tags=["kas"])

SALDO_AWAL_KATEGORI = cash.SALDO_AWAL_KATEGORI

#: Kategori baris DP di Mutasi Kas. Labelnya menegaskan DP bukan Omzet supaya
#: tidak salah baca saat membandingkan tabel ini dengan kartu Conditions Kas.
KATEGORI_DP = "DP / Uang Titipan (bukan Omzet)"

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


def period_rows(db: Session, start: datetime, end: datetime, with_opening: bool = False):
    """Seluruh baris kas dalam [start, end) terurut menaik + saldo berjalan.

    Sifat laporan ini **FISIS**: memuat setiap perpindahan uang di laci, supaya
    kolom Saldo Berjalan selalu sama dengan `cash.saldo_laci()` dan bisa dipakai
    merekonsiliasi uang fisik saat Tutup Kas.

    Tiga sumber, masing-masing tepat satu kali (tidak ada yang terhitung dobel):
      1. `payments`   -> DP + pelunasan (DP berlabel "DP / Uang Titipan").
      2. `expenses`   -> beban gaji & operasional.
      3. `kas_entries`-> layer LACI dengan `sumber` di `cash.SUMBER_BARIS_KAS`
                        (modal, cash-out distribusi, transfer masuk/keluar laci,
                        penyesuaian rekonsiliasi, refund, entri manual).
      Sumber `PAYMENT` & `BEBAN` DIKECUALIKAN dari (3) karena sudah diambil
      langsung oleh (1) dan (2).

    Saldo dihitung dari AWAL WAKTU (opening + seluruh baris sebelum `start` +
    baris periode) sehingga benar untuk periode apa pun, bukan hanya all-time.
    Entri kategori "Saldo Awal" tidak jadi baris karena sudah tercakup di opening.

    `with_opening=True` mengembalikan `(rows, opening)` di mana `opening` adalah
    saldo tepat SEBELUM baris pertama periode — nilainya dijamin sama dengan
    saldo baris pertama dan dengan `cash.saldo_laci_sampai(db, start)`.
    """
    rows = []
    _seq = 0

    for p in db.query(Payment).options(joinedload(Payment.service_order)).all():
        m = _moment(getattr(p, "created_at", None), None)
        if m is None:
            continue
        o = p.service_order
        kind = (p.kind or "PELUNASAN").strip().upper()
        # DP = UANG TITIPAN yang benar-benar diterima kasir, jadi tetap menjadi
        # baris Masuk (uangnya ada di laci & wajib direkonsiliasi). Yang berbeda
        # hanya LKALANYA: DP tidak pernah menambah Omzet/Laba — itu ditangani di
        # `compute_finance`, bukan di sini. Pelunasan atas unit yang sama hanya
        # sebesar SISA, jadi DP + sisa = kewajiban, tanpa dobel.
        is_dp = kind == "DP"
        rows.append({
            "moment": m,
            "tgl": m.date().isoformat() if hasattr(m, "date") else None,
            "jenis": "Masuk",
            "kategori": KATEGORI_DP if is_dp else "Pelunasan",
            "ket": ("%s • %s" % ((o.device if o else None) or "-",
                                 (o.no_servis if o else None) or "-")) if not is_dp
                   else ("DP / Uang Titipan (bukan Omzet) — %s • %s"
                         % ((o.device if o else None) or "-",
                            (o.no_servis if o else None) or "-")),
            "nominal": _num(p.amount),
            "source": "dp" if is_dp else "order",
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

    # Buku Kas (Laci) hanya memuat layer LACI — mutasi Kas Aset tidak boleh
    # muncul sebagai arus kas Laci. Cukup sisi LACI dari sepasang entri transfer,
    # karena sisi KAS_ASET terfilter di sini: Master Kas tetap utuh, tidak dobel.
    for k in db.query(KasEntry).filter(KasEntry.kategori != SALDO_AWAL_KATEGORI,
                                      KasEntry.layer == cash.LAYER_LACI).all():
        if (getattr(k, "sumber", None) or cash.SUMBER_MANUAL) not in cash.SUMBER_BARIS_KAS:
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

    # Urut WAKTU. `created_at` bawaan SQLite/MySQL hanya presisi detik, jadi
    # beberapa entri bisa berbagi detik yang sama. Tie-break memakai `_seq`
    # (urutan penulisan di dalam satu request) supaya saldo tetap mengikuti
    # kronologi.
    # CATATAN UAT: tie-break lama memakai `source` ("manual" < "order"), sehingga
    # baris bisa terbalik dan kolom Saldo terlihat melompat acak.
    for r in rows:
        _seq += 1
        r["_seq"] = _seq
    rows.sort(key=lambda r: (r["moment"], r["_seq"]))
    saldo = opening_balance(db)
    opening = None
    for r in rows:
        if opening is None and r["moment"] >= start:
            opening = saldo
        saldo += r["nominal"] if r["jenis"] == "Masuk" else -r["nominal"]
        r["saldo"] = saldo
    if opening is None:
        opening = saldo          # periode tanpa baris -> opening = saldo akhir
    rows = [r for r in rows if start <= r["moment"] < end]
    for r in rows:
        del r["moment"]
        del r["_seq"]
    return (rows, opening) if with_opening else rows


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
    # Jurnal manual "Penjualan Service" menaikkan Laba Kotor, jadi bisa membuat
    # CTO tercapai -> distribusi terbentuk otomatis. Idempoten per periode.
    try:
        _pastikan_distribusi(db, actor=getattr(user, "display_name", None)
                            or getattr(user, "username", None))
    except Exception:  # noqa: BLE001
        db.rollback()
    return row


def _pastikan_distribusi(db: Session, actor: str = None) -> dict:
    """Distribusi Laba otomatis saat CTO tercapai (lihat `orders` untuk penjelasan)."""
    import distribution as dist_mod
    from routers.dashboard import (batas_periode, compute_finance,
                                   get_active_period)
    p = get_active_period(db)
    fin = compute_finance(db, *batas_periode(p))
    return dist_mod.pastikan_otomatis(
        db, p.start_at.date().isoformat(), fin.get("laba_bersih", 0),
        cto_tercapai=bool(fin.get("cto_tercapai")),
        kas_period_id=p.id, oleh=actor)


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


# ---------- Riwayat / Mutasi Kas ----------
def _riwayat(db, page, limit, q, jenis, date, period):
    """Bagian (1) Ringkasan + (2) Mutasi Kas. Dipakai /riwayat dan /mutasi."""
    page, limit = _clamp(page, limit)
    period = (period or "all").strip().lower()
    if period == "current":
        p = get_active_period(db)
        rows, opening = period_rows(db, *batas_periode(p), with_opening=True)
    else:
        rows, opening = period_rows(db, datetime.min, datetime.max, with_opening=True)

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
    shown = rows[::-1]                      # terbaru di atas
    items = shown[(page - 1) * limit:page * limit]
    # Total SELURUH hasil filter (bukan 1 halaman) supaya bisa dibandingkan
    # dengan kartu ringkasan dan dengan Saldo Akhir.
    tot_masuk = sum((_num(r["nominal"]) for r in rows if r["jenis"] == "Masuk"), Decimal("0"))
    tot_keluar = sum((_num(r["nominal"]) for r in rows if r["jenis"] == "Keluar"), Decimal("0"))
    # Saldo akhir = saldo baris TERAKHIR secara kronologis (bukan baris terakhir
    # yang tampil), supaya tetap benar walau difilter.
    saldo_akhir = rows[-1]["saldo"] if rows else opening
    return dict(total=total, page=page, limit=limit, total_pages=total_pages,
                opening=opening, total_masuk=tot_masuk, total_keluar=tot_keluar,
                saldo_akhir=saldo_akhir, items=items)


def _rekonsiliasi(db, period):
    """Bagian (3) Rekonsiliasi Tutup Kas.

    Menampilkan empat angka: Saldo Sistem (ledger saat ini), Saldo Fisik (hasil
    hitung uang yang dideklarasikan saat Tutup Kas), Selisih, dan Penyesuaian
    (entri yang dicatat sistem untuk menutup selisih itu).

    Sumber declaration = `kas_periods.snapshot`, jadi historis periode tertutup
    tetap terbaca tanpa mengubah atau menghapus apa pun. Saldo Fisik untuk
    periode yang belum ditutup = None ("belum dideklarasi").
    """
    import json

    from money import json_default

    p = get_active_period(db) if period == "current" else get_active_period(db)
    snap = None
    if p is not None:
        try:
            snap = json.loads(p.snapshot) if p.snapshot else None
        except (TypeError, ValueError):
            snap = None
    rec = (snap or {}).get("rekonsiliasi") or {}
    sistem = cash.saldo_laci(db)
    fisik = snap.get("cash_counted") if snap else None
    selisih = rec.get("selisih")
    return schemas.KasRekonsiliasiOut(
        saldo_sistem=sistem,
        saldo_fisik=(None if fisik is None else _num(fisik)),
        selisih=(None if selisih is None else _num(selisih)),
        penyesuaian=bool(rec.get("penyesuaian")),
        sudah_ditutup=bool(snap),
        periode=((snap or {}).get("period") or {}).get("start_at") or (
            p.start_at.isoformat() if p is not None else None),
        catatan="Saldo Fisik & Selisih muncul setelah Tutup Kas. "
                "Penyesuaian sudah tercermin sebagai baris di Mutasi Kas "
                "(sumber Penyesuaian Rekonsiliasi) — jangan dihitung dua kali.",
    )


@router.get("/riwayat", response_model=schemas.KasRiwayatPage)
def kas_riwayat(db: Session = Depends(get_db_session), page: int = DEFAULT_PAGE,
                limit: int = DEFAULT_LIMIT, q: str = Query(""),
                jenis: str = Query(""), date: str = Query(""),
                period: str = Query("all", description="all | current")):
    """Mutasi Kas + Ringkasan Kas Laci. Read-only turunan — tanpa tabel baru."""
    return schemas.KasRiwayatPage(
        **_riwayat(db, page, limit, q, jenis, date, period),
        rekonsiliasi=_rekonsiliasi(db, period))


@router.get("/rekonsiliasi", response_model=schemas.KasRekonsiliasiOut)
def kas_rekonsiliasi(db: Session = Depends(get_db_session),
                     period: str = Query("current", description="all | current")):
    """Bagian (3) Rekonsiliasi Tutup Kas (read-only)."""
    return _rekonsiliasi(db, period)


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


# ---------- P2-07 / SSOT-6: Distribusi ----------
@router.get("/distribusi")
def get_distribusi(db: Session = Depends(get_db_session),
                   period: str = Query("current", description="current | YYYY-MM-DD"),
                   user: User = Depends(get_authenticated_user)):
    """Status distribusi + alasan kalau belum terbentuk.

    Distribusi terbentuk OTOMATIS begitu CTO tercapai (Laba Kotor >= Beban),
    bukan lagi saat Tutup Kas.
    """
    period = (period or "current").strip()
    pid = None
    preview = 0
    cto = False
    if period == "current":
        p_ = get_active_period(db)
        key = p_.start_at.date().isoformat() if p_.start_at else ""
        fin = compute_finance(db, *batas_periode(p_))
        preview = fin.get("laba_bersih", 0)
        cto = bool(fin.get("cto_tercapai"))
        # P2-15 B-1: teruskan id Kas Period agar distributor membaca baris
        # miliknya sendiri ketika beberapa Kas Period bertegang sama.
        pid = p_.id
    else:
        key = period
    out = distribution_mod.ringkasan(db, key, kas_period_id=pid)
    if not out.get("terbentuk"):
        out["preview"] = distribution_mod.preview(preview)
        out["cto_tercapai"] = cto
        out["alasan"] = _alasan_distribusi(db, preview, cto, key, pid)
    return out


@router.get("/modal-kosong")
def modal_kosong(
    db: Session = Depends(get_db_session),
    period: str = Query("current", description="current | YYYY-MM-DD"),
    user: User = Depends(get_authenticated_user),
):
    """Daftar order CASH yang Modalnya masih kosong semua (read-only, tidak menulis).

    Untuk PERINGATAN KERAS sebelum Tutup Kas -- bukan pemblokiran, tapi
    Owner menegaskan: unit modal-kosong BELUM masuk Omzet/Transaksi. Jadi ini
    harus diperbaiki sebelum periode ditutup. Dulu keterangan di sini
    berbunyi "modal 0 itu sah" -- itu tidak lagi sesuai aturan Owner.

    Simulasi (harga 500.000, modal sebenarnya 300.000 tapi dicatat 0):
      - laba terbaca 500.000, bukan 200.000;
      - CTO bisa tercapai lebih awal dan memicu distribution lebih besar;
      - saat Tutup Kas, uang fisik laci justru LEBIH BESAR dari sistem, dan
        selisihnya muncul seolah-olah uang hilang -- padahal itu modal yang
        belum dicatat.

    Yang dihitung hanya order berstatus CASH di periode berjalan: order DONE
    masih aman karena modalnya belum menarik dari Laci sama sekali.

    CATATAN: momen terminal TIDAK cukup pakai `lunas_at`. Order yang_price Finalnya kosong (0) dan tidak punya payment TIDAK PERNAH dikunci `lunas_at` --
    di `orders.py` lock hanya jalan bila `payment_status == "LUNAS"`. Order seperti itu statusnya sudah CASH tapi `lunas_at`-nya NULL, jadi kalau
    difilter `lunas_at IS NOT NULL` dia justru LEWAT dari peringatan ini.
    Karena itu dipakai rantai yang sama dengan filter arsip di router orders.
    """
    import models as _models
    from sqlalchemy import func
    from models import StatusHistory
    if period == "current":
        p = get_active_period(db)
        start, end = batas_periode(p)
        pid = p.id
    else:
        p = db.query(_models.KasPeriod).filter(
            _models.KasPeriod.start_at.date() == datetime.strptime(period, "%Y-%m-%d").date()
        ).first()
        start, end = batas_periode(p)
        pid = p.id if p is not None else None

    sub = (
        select(func.max(StatusHistory.waktu))
        .where(StatusHistory.service_order_id == _models.ServiceOrder.id,
               StatusHistory.ke_status == _models.ServiceOrder.status)
        .correlate(_models.ServiceOrder)
        .scalar_subquery()
    )
    momen = func.coalesce(_models.ServiceOrder.lunas_at, sub,
                          _models.ServiceOrder.taken_at,
                          _models.ServiceOrder.created_at)

    q = db.query(_models.ServiceOrder).filter(
        _models.ServiceOrder.status == "CASH")
    if start is not None:
        q = q.filter(momen >= start)
    if end is not None:
        q = q.filter(momen <= end)
    rows = q.all()

    kosong = []
    for o in rows:
        total = (to_decimal(o.part_cost or 0) + to_decimal(o.modal_jasa or 0)
                 + to_decimal(o.modal_lainnya or 0))
        if total <= ZERO:
            kosong.append({
                "id": o.id, "no_servis": o.no_servis,
                "harga": str(o.final_price or 0),
                "lunas_at": o.lunas_at.isoformat() if o.lunas_at else None,
            })
    return {
        "jumlah": len(kosong),
        "total_cash": len(rows),
        "items": kosong,
        "keterangan": "Modal kosong berarti unit ini BELUM masuk Omzet/Transaksi: "
                      "tanpa modal tidak ada biaya yang tercatat, sehingga "
                      "Harga Final-nya akan salah dianggap seluruhnya sebagai "
                      "laba. Peringatan keras -- isi Modal Part & Modal Jasa "
                      "sebelum kas ditutup.",
    }


def _alasan_distribusi(db, laba_bersih, cto, key, pid):
    """Kenapa distribusi belum terbentuk (atau None kalau sudah / boleh)."""
    if distribution_mod.sudah_ada(db, key, pid) is not None:
        return None
    if not cto:
        return distribution_mod.ALASAN_BELUM_SIAP
    hit = distribution_mod.hitung(laba_bersih)
    if not hit.get("eligible"):
        return hit.get("alasan")
    total = hit["cash_out"] + hit["kas_aset"]
    if cash.saldo_laci(db) < total:
        return "%s (butuh %s, ada %s)" % (
            distribution_mod.ALASAN_KAS_KURANG, total, cash.saldo_laci(db))
    return None


@router.post("/distribusi/jalankan")
def jalankan_distribusi(
        db: Session = Depends(get_db_session),
        user: User = Depends(require_authority(Action.KAS_ENTRY_WRITE))):
    """Jalankan distribusi sekarang (tombol manual).

    Dipakai saat periode sudah mencapai CTO tetapi pemicu otomatis belum
    berjalan — misalnya data yang sudah terlanjur CASH sebelum aturan ini aktif.
    Memakai gatekeeper yang sama (`pastikan_otomatis`), jadi aturannya persis
    sama dengan otomatis: idempoten per periode, dan tidak jalan kalau Saldo
    Laci tidak cukup untuk seluruh porsi.
    """
    p = get_active_period(db)
    fin = compute_finance(db, *batas_periode(p))
    try:
        res = distribution_mod.pastikan_otomatis(
            db, p.start_at.date().isoformat(), fin.get("laba_bersih", 0),
            cto_tercapai=bool(fin.get("cto_tercapai")),
            kas_period_id=p.id,
            oleh=getattr(user, "display_name", None) or user.username)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"jalankan": bool(res.get("dibentuk")), "alasan": res.get("alasan"),
            "alokasi": {k: str(v) for k, v in (res.get("alokasi") or {}).items()},
            "saldo_laci": str(cash.saldo_laci(db)),
            "saldo_kas_aset": str(cash.saldo_kas_aset(db)),
            "master_kas": str(cash.master_kas(db))}


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
