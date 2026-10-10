"""Warranty claim endpoints.

Prinsip: Claim = record/proses BARU yang mengacu ke servis lama.
Servis lama tidak diubah (histori/audit). Setiap claim punya Claim ID
sendiri (CLM-...) dan berelasi ke service_orders via service_order_id.
Claim berulang untuk servis yang sama diperbolehkan.
"""
import calendar
import random
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_

from dependencies import get_db_session
from models import Payment, ServiceOrder, Customer, WarrantyClaim, User, KasPeriod
from authority import Action, require_authority
from routers.auth import require_admin
from statusflow import kewajiban, payment_summary
import schemas

router = APIRouter(prefix="/api/claims", tags=["claims"])

DEFAULT_WARRANTY_DAYS = 30
DEFAULT_PAGE = 1
DEFAULT_LIMIT = 10
MAX_LIMIT = 10



def _origin_payment_status(db: Session, origin: ServiceOrder) -> str:
    """Status pembayaran unit asal, DITURUNKAN dari jurnal payments (bukan kolom legacy).

    Q3/Q17: settlement SSOT = Payment Ledger. Status legacy tidak pernah jadi sumber.
    """
    rows = db.query(Payment).filter(Payment.service_order_id == origin.id).all()
    return payment_summary(origin, rows)["payment_status"]


def _cek_syarat_garansi(db: Session, origin: ServiceOrder):
    """Syarat pembuatan record warranty/claim (Owner Locks P2-09).

    Return (ok, http_status, pesan, konteks). Menolak bila:
      - unit belum SETTLED/LUNAS (dari jurnal payments);
      - `warranty_months == 0` (Tanpa Garansi) -> tidak ada arsip garansi (OD-004).
    """
    status_bayar = _origin_payment_status(db, origin)
    bulan = getattr(origin, "warranty_months", None)
    if status_bayar != "LUNAS":
        return (False, 409,
                "Transaksi belum SETTLED/LUNAS sehingga tidak dapat dibuat record garansi",
                {"payment_status": status_bayar, "warranty_months": bulan})
    if bulan == 0:
        return (False, 409,
                "Unit tanpa garansi (Tanpa Garansi) tidak membuat arsip garansi",
                {"payment_status": status_bayar, "warranty_months": bulan})
    return (True, 200, None, {"payment_status": status_bayar, "warranty_months": bulan})


def _generate_claim_no() -> str:
    return "CLM-" + datetime.now().strftime("%Y%m%d") + "-" + str(random.randint(1000, 9999))


def _as_date(v):
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    return v


def _origin_warranty_start(o):
    """Awal garansi: tanggal unit diambil, fallback momen lunas, fallback tanggal terima."""
    taken = _as_date(getattr(o, "taken_at", None))
    if taken is not None:
        return taken
    return getattr(o, "lunas_date", None) or o.service_date


def _add_months(d, months: int):
    """Tambah N bulan kalender (aman untuk akhir bulan, mis. 31 Jan + 1 bln)."""
    m = d.month - 1 + months
    y = d.year + m // 12
    m = m % 12 + 1
    last = calendar.monthrange(y, m)[1]
    return d.replace(year=y, month=m, day=min(d.day, last))


def _origin_warranty(origin, fallback_days: int):
    """Selesaikan (start, end, status, months, days) dari setting toko di servis asal.

    months None (data lama) -> fallback_days. 0 = tidak garansi (EXPIRED).
    Setting toko selalu menang; fallback hanya untuk data legacy.
    """
    start = _origin_warranty_start(origin)
    months = getattr(origin, "warranty_months", None)
    if months is None:
        s, e, st = _warranty_window(start, fallback_days)
        return s, e, st, None, fallback_days
    if months == 0 or start is None:
        return start, start, "EXPIRED", 0, 0
    end = _add_months(start, months)
    days = (end - start).days
    try:
        status = "EXPIRED" if date.today() > end else "VALID"
    except Exception:
        status = "VALID"
    return start, end, status, months, days


def _warranty_window(service_date, warranty_days: int):
    """Hitung (start, end, status) garansi dari tanggal servis asal."""
    days = warranty_days or DEFAULT_WARRANTY_DAYS
    start = service_date
    end = None
    if start:
        # date + timedelta tanpa import tambahan (hindari dependensi baru)
        try:
            from datetime import timedelta
            end = start + timedelta(days=days)
        except Exception:
            end = start
    status = "VALID"
    try:
        today = date.today()
        if end is not None and today > end:
            status = "EXPIRED"
    except Exception:
        pass
    return start, end, status


def _claim_to_out(c: WarrantyClaim) -> schemas.ClaimOut:
    o = c.service_order
    cust = c.customer
    return schemas.ClaimOut(
        id=c.id,
        claim_no=c.claim_no,
        service_order_id=c.service_order_id,
        customer_id=c.customer_id,
        claim_date=c.claim_date,
        received_by=c.received_by,
        warranty_days=c.warranty_days,
        warranty_start=c.warranty_start,
        warranty_end=c.warranty_end,
        warranty_status=c.warranty_status,
        complaint=c.complaint,
        physical_condition=c.physical_condition,
        completeness=c.completeness,
        cs_note=c.cs_note,
        check_fisik=list(c.check_fisik or []),
        check_len=list(c.check_len) if c.check_len is not None else ["unit_saja"],
        inspection_result=c.inspection_result,
        cause=c.cause,
        matches_previous=c.matches_previous,
        drop_indication=c.drop_indication,
        liquid_indication=c.liquid_indication,
        third_party_work=c.third_party_work,
        action_needed=c.action_needed,
        tech_note=c.tech_note,
        technician=c.technician,
        tech_recommendation=c.tech_recommendation,
        decision=c.decision,
        reject_reason=c.reject_reason,
        claim_status=c.claim_status,
        customer_cost=c.customer_cost,
        internal_cost=c.internal_cost,
        resolusi=getattr(c, "resolusi", None),
        origin_payment_status=getattr(c, "origin_payment_status", None),
        origin_warranty_months=getattr(c, "origin_warranty_months", None),
        created_at=c.created_at,
        origin_no_servis=o.no_servis if o else None,
        origin_device=o.device if o else None,
        origin_damage=o.damagetype if o else None,
        origin_plan=o.repair_plan if o else None,
        origin_service_date=o.service_date if o else None,
        origin_technician=o.technician if o else None,
        customer_name=cust.name if cust else (o.customer.name if o and o.customer else None),
        customer_phone=cust.phone if cust else (o.customer.phone if o and o.customer else None),
        origin_imei=o.imei if o else None,
    )


def _lookup_to_item(o: ServiceOrder, warranty_days: int = DEFAULT_WARRANTY_DAYS) -> schemas.ClaimLookupItem:
    claims = getattr(o, "warranty_claims", []) or []
    start, end, status, months, days = _origin_warranty(o, warranty_days)
    return schemas.ClaimLookupItem(
        id=o.id,
        no_servis=o.no_servis,
        service_date=o.service_date,
        customer_name=o.customer.name if o.customer else None,
        customer_phone=o.customer.phone if o.customer else None,
        device=o.device,
        imei=o.imei,
        damagetype=o.damagetype,
        repair_plan=o.repair_plan,
        technician=o.technician,
        status=o.status,
        warranty_days=days,
        warranty_months=months,
        warranty_start=start,
        warranty_end=end,
        warranty_status=status,
        claim_count=len(claims),
        claims=[{"claim_no": c.claim_no, "claim_status": c.claim_status,
                 "decision": c.decision, "claim_date": str(c.claim_date) if c.claim_date else None}
                for c in claims],
    )


@router.get("/lookup", response_model=list[schemas.ClaimLookupItem])
def lookup_origin(
    q: str = Query("", description="No. servis / nota / WA / IMEI / nama customer"),
    warranty_days: int = Query(DEFAULT_WARRANTY_DAYS),
    db: Session = Depends(get_db_session),
):
    """Cari servis asal untuk klaim (tidak membuat data apa pun)."""
    keyword = (q or "").strip()
    if len(keyword) < 2:
        return []
    like = f"%{keyword}%"
    rows = (
        db.query(ServiceOrder)
        .options(joinedload(ServiceOrder.customer))
        .outerjoin(Customer, ServiceOrder.customer_id == Customer.id)
        .filter(or_(
            ServiceOrder.no_servis.ilike(like),
            ServiceOrder.device.ilike(like),
            ServiceOrder.imei.ilike(like),
            Customer.name.ilike(like),
            Customer.phone.ilike(like),
        ))
        .order_by(ServiceOrder.created_at.desc())
        .limit(20)
        .all()
    )
    return [_lookup_to_item(o, warranty_days) for o in rows]


@router.post("/receive", response_model=schemas.ClaimOut, status_code=201)
def receive_claim(data: schemas.ClaimReceiveIn, db: Session = Depends(get_db_session),
                   user: User = Depends(require_authority(Action.CLAIM_WRITE))):
    """Buat record claim baru dari servis asal. Servis lama TIDAK diubah."""
    origin = (
        db.query(ServiceOrder)
        .options(joinedload(ServiceOrder.customer))
        .filter(ServiceOrder.id == data.service_order_id)
        .first()
    )
    if not origin:
        raise HTTPException(status_code=404, detail="Servis asal tidak ditemukan")
    # P2-09 / Owner Locks: garansi hanya dari transaksi SETTLED/LUNAS + bergaransi.
    ok, http_status, pesan, ctx = _cek_syarat_garansi(db, origin)
    if not ok:
        raise HTTPException(status_code=http_status, detail=pesan)
    days = data.warranty_days or DEFAULT_WARRANTY_DAYS
    start, end, wstatus, months, cdays = _origin_warranty(origin, days)

    claim_no = _generate_claim_no()
    for _ in range(5):  # hindari tabrakan nomor acak
        if not db.query(WarrantyClaim).filter(WarrantyClaim.claim_no == claim_no).first():
            break
        claim_no = _generate_claim_no()

    claim = WarrantyClaim(
        claim_no=claim_no,
        service_order_id=origin.id,
        customer_id=origin.customer_id,
        claim_date=data.claim_date or date.today(),
        received_by=(data.received_by or "").strip() or None,
        warranty_days=cdays,
        warranty_start=start,
        warranty_end=end,
        warranty_status=wstatus,
        complaint=(data.complaint or "").strip() or None,
        physical_condition=(data.physical_condition or "").strip() or None,
        completeness=(data.completeness or "").strip() or None,
        cs_note=(data.cs_note or "").strip() or None,
        check_fisik=list(data.check_fisik or []),
        check_len=list(data.check_len) if data.check_len is not None else ["unit_saja"],
        decision="BELUM_DIPUTUSKAN",
        claim_status="MASUK",
        customer_cost=0,
        internal_cost=0,
        # P2-09: audit snapshot unit asal (servis lama tetap tidak diubah).
        origin_payment_status=ctx["payment_status"],
        origin_warranty_months=ctx["warranty_months"],
    )
    db.add(claim)
    db.commit()
    db.refresh(claim)
    return _claim_to_out(claim)


def _page_clamp(page: int, limit: int):
    page = max(DEFAULT_PAGE, page)
    limit = min(MAX_LIMIT, max(1, limit))
    return page, limit


@router.get("", response_model=schemas.ClaimPage)
def list_claims(db: Session = Depends(get_db_session), page: int = DEFAULT_PAGE, limit: int = DEFAULT_LIMIT):
    page, limit = _page_clamp(page, limit)
    total = db.query(WarrantyClaim).count()
    rows = (
        db.query(WarrantyClaim)
        .options(joinedload(WarrantyClaim.service_order), joinedload(WarrantyClaim.customer))
        .order_by(WarrantyClaim.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )
    total_pages = (total + limit - 1) // limit if total else 1
    return schemas.ClaimPage(total=total, page=page, limit=limit,
                             total_pages=total_pages,
                             items=[_claim_to_out(c) for c in rows])


@router.get("/warranty-summary")
def warranty_summary(db: Session = Depends(get_db_session)):
    """Daftar garansi aktif: servis CASH + LUNAS + bergaransi **yang periodenya
    sudah ditutup**.

    Batas arsip adalah TUTUP KAS, bukan status CASH: unit yang baru CASH di
    periode kas yang masih OPEN belum muncul di sini — menunggu Tutup Kas.
    Settlement dibaca dari `lunas_at`/`lunas_date`, sama seperti financial core
    (`finance.settled_orders`), jadi satu order masuk tepat satu periode.
    """
    from datetime import timedelta as _td
    candidates = (
        db.query(ServiceOrder)
        .filter(ServiceOrder.status == "CASH", ServiceOrder.warranty_months != 0)
        .order_by(ServiceOrder.lunas_date.desc().nullslast(), ServiceOrder.id.desc())
        .limit(400)
        .all()
    )
    # Saring LUNAS via jurnal payments (derive, bukan status).
    ids = [o.id for o in candidates]
    pays = db.query(Payment).filter(Payment.service_order_id.in_(ids)).all() if ids else []
    by_order = {}
    for p in pays:
        by_order.setdefault(p.service_order_id, []).append(p)
    lunas = [o for o in candidates
             if payment_summary(o, by_order.get(o.id, []))["payment_status"] == "LUNAS"][:200]
    # Saring lagi: hanya periode kas yang sudah CLOSED.
    closed_periods = db.query(KasPeriod).filter(
        KasPeriod.status == "CLOSED").all()
    orders = []
    for o in lunas:
        m = getattr(o, "lunas_at", None)
        if m is None:
            ld = getattr(o, "lunas_date", None)
            if ld is None:
                continue
            m = datetime(ld.year, ld.month, ld.day, 12, 0, 0)
        if any(p.start_at <= m < p.end_at for p in closed_periods):
            orders.append(o)
    oids = [o.id for o in orders]
    # Satu query untuk klaim terbaru tiap order (hindari N+1).
    latest_by_order = {}
    if oids:
        for c in (db.query(WarrantyClaim)
                    .filter(WarrantyClaim.service_order_id.in_(oids))
                    .order_by(WarrantyClaim.claim_date.desc(),
                              WarrantyClaim.id.desc()).all()):
            latest_by_order.setdefault(c.service_order_id, c)
    cids = [o.customer_id for o in orders]
    names = {}
    if cids:
        from models import Customer
        for c in db.query(Customer).filter(Customer.id.in_(cids)).all():
            names[c.id] = (c.name, c.phone)
    items = []
    for o in orders:
        # Fallback awal garansi SAMA dengan receive path:
        # taken_at → lunas_date → service_date.
        mulai = _origin_warranty_start(o)
        months = o.warranty_months
        if mulai is None:
            akhir = None
        elif months is None:
            akhir = mulai + _td(days=30)  # legacy: 30 hari
        else:
            akhir = _add_months(mulai, months)
        latest = latest_by_order.get(o.id)
        nm, ph = names.get(o.customer_id, (None, None))
        items.append({
            "service_order_id": o.id,
            "no": o.no_servis,
            "nama": nm,
            "phone": ph,
            "device": o.device,
            "mulai": mulai.isoformat() if mulai else None,
            "akhir": akhir.isoformat() if akhir else None,
            "damage": o.damagetype,
            "plan": o.repair_plan,
            "price": o.final_price if o.final_price not in (None,) else o.estimate,
            "klaim": ({
                "tgl": latest.claim_date.isoformat() if latest.claim_date else None,
                "keluhan": latest.complaint,
                "tindakan": latest.action_needed,
                "status": latest.claim_status,
            } if latest else None),
        })
    return {"items": items}


@router.get("/warranty/detail/{service_id}")
def warranty_detail(service_id: int, db: Session = Depends(get_db_session)):
    """Warranty history satu unit (read-only).

    Menjawab: apakah unit punya garansi, statusnya, masa berlakunya, dan riwayat
    klaimnya. Siklus garansi TIDAK memakai status service order (Q2).
    """
    origin = db.query(ServiceOrder).filter(ServiceOrder.id == service_id).first()
    if not origin:
        raise HTTPException(status_code=404, detail="Servis asal tidak ditemukan")
    status_bayar = _origin_payment_status(db, origin)
    start, end, wstatus, months, days = _origin_warranty(origin, DEFAULT_WARRANTY_DAYS)
    rows = (db.query(WarrantyClaim)
            .filter(WarrantyClaim.service_order_id == service_id)
            .order_by(WarrantyClaim.claim_date.desc(), WarrantyClaim.id.desc())
            .all())
    hari_lagi = None
    if end is not None:
        delta = (end - date.today()).days
        hari_lagi = max(0, delta)
    return {
        "service_order_id": origin.id,
        "no_servis": origin.no_servis,
        "device": origin.device,
        "status_order": origin.status,
        "payment_status": status_bayar,
        "settled": status_bayar == "LUNAS",
        "warranty_months": months,
        "warranty_start": start.isoformat() if start else None,
        "warranty_end": end.isoformat() if end else None,
        "warranty_status": wstatus,
        "sisa_hari": hari_lagi,
        "tanpa_garansi": (months == 0),
        "bisa_klaim": bool(status_bayar == "LUNAS" and months != 0),
        "total_klaim": len(rows),
        "klaim": [_claim_to_out(c) for c in rows],
        "catatan": "Siklus garansi terpisah dari status service order (Q2).",
    }


@router.get("/by-service/{service_id}", response_model=list[schemas.ClaimOut])
def claims_by_service(service_id: int, db: Session = Depends(get_db_session)):
    """Histori claim untuk satu servis asal (claim berulang tetap terlacak)."""
    rows = (
        db.query(WarrantyClaim)
        .options(joinedload(WarrantyClaim.service_order), joinedload(WarrantyClaim.customer))
        .filter(WarrantyClaim.service_order_id == service_id)
        .order_by(WarrantyClaim.created_at.desc())
        .all()
    )
    return [_claim_to_out(c) for c in rows]


@router.get("/{claim_id}", response_model=schemas.ClaimOut)
def get_claim(claim_id: int, db: Session = Depends(get_db_session)):
    c = db.query(WarrantyClaim).filter(WarrantyClaim.id == claim_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Claim tidak ditemukan")
    return _claim_to_out(c)


@router.put("/{claim_id}", response_model=schemas.ClaimOut)
def update_claim(claim_id: int, data: schemas.ClaimUpdate, db: Session = Depends(get_db_session),
                   user: User = Depends(require_authority(Action.CLAIM_WRITE))):
    """Update workflow claim: verifikasi, inspeksi teknisi, keputusan, status, biaya.

    Validasi: keputusan DITOLAK wajib menyertakan reject_reason.
    Tidak menyentuh tabel service_orders / customers.
    """
    c = db.query(WarrantyClaim).filter(WarrantyClaim.id == claim_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Claim tidak ditemukan")
    payload = data.model_dump(exclude_unset=True)

    if "claim_status" in payload and payload["claim_status"] not in schemas.CLAIM_STATUSES:
        raise HTTPException(status_code=400,
                            detail="claim_status tidak valid. Pilihan: " + ", ".join(schemas.CLAIM_STATUSES))
    if "decision" in payload and payload["decision"] not in schemas.CLAIM_DECISIONS:
        raise HTTPException(status_code=400,
                            detail="decision tidak valid. Pilihan: " + ", ".join(schemas.CLAIM_DECISIONS))

    # P2-09: resolusi klaim (repair / replace / refund). Dampak uang REFUND
    # sengaja TIDAK dihitung di tahap ini (P2-10).
    if "resolusi" in payload:
        res = (payload["resolusi"] or "").strip().upper()
        if res == "":
            payload["resolusi"] = None
        elif res not in schemas.CLAIM_RESOLUSI:
            raise HTTPException(status_code=400,
                                detail="resolusi tidak valid. Pilihan: "
                                       + ", ".join(schemas.CLAIM_RESOLUSI))
        else:
            payload["resolusi"] = res

    new_decision = payload.get("decision", c.decision)
    new_reason = payload.get("reject_reason", c.reject_reason)
    if new_decision == "DITOLAK" and not (new_reason or "").strip():
        raise HTTPException(status_code=400, detail="Claim DITOLAK wajib menyertakan alasan penolakan (reject_reason)")

    for key, val in payload.items():
        setattr(c, key, val)
    db.commit()
    db.refresh(c)
    return _claim_to_out(c)


@router.delete("/{claim_id}")
def delete_claim(claim_id: int, db: Session = Depends(get_db_session),
                 admin=Depends(require_admin)):
    """Hapus claim — khusus Admin. Claim SELESAI/DITUTUP tidak dapat dihapus."""
    c = db.query(WarrantyClaim).filter(WarrantyClaim.id == claim_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Claim tidak ditemukan")
    if (c.claim_status or "") in ("SELESAI", "DITUTUP"):
        raise HTTPException(status_code=409,
                            detail="Claim %s tidak dapat dihapus" % c.claim_status)
    db.delete(c)
    db.commit()
    return {"ok": True}
