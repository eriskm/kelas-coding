"""Service orders endpoints (FINAL LOCK: 3 dimensi terpisah)."""
import random
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from dependencies import get_db_session
from models import Payment, ServiceOrder, Customer, StatusHistory, User, WarrantyClaim
import cash
import journal
import notifications as notif_mod
from routers import payments as payments_mod
from money import ZERO, to_decimal
from authority import (Action, check, is_closing_status, require_authority,
                      sanitize_finance_payload)
from routers.auth import can_edit_finance, get_authenticated_user, require_admin
from statusflow import (
    INITIAL_PATHS,
    SERVICE_STATUSES,
    TERMINAL_STATUSES,
    cek_dp_vs_estimasi,
    check_initial_path,
    check_transition,
    dp_total,
    lock_lunas_moment,
    order_profit,
    payment_summary,
)
import schemas

router = APIRouter(prefix="/api/orders", tags=["orders"])

# Subset aktif checklist (selaras frontend ACTIVE_*): key pensiun
# (lcd_pecah/lcd_terbuka/frame_gompal/box/charger) difilter saat tulis.
# Klaim tidak difilter (form klaim masih memakai daftar penuh).
CHECK_FISIK_KEYS = {"frame_bengkok", "tombol_tidak_ada", "bekas_air"}
CHECK_LEN_KEYS = {"unit_saja", "case", "sim_card", "memory_card"}


def _clean_checklist(values, allowed):
    """Saring key checklist ke subset aktif (None → list kosong)."""
    try:
        return [v for v in (values or []) if v in allowed]
    except TypeError:
        return []


def _generate_no_servis() -> str:
    return "SV-" + datetime.now().strftime("%Y%m%d") + "-" + str(random.randint(1000, 9999))


def _actor(user) -> str:
    try:
        return (getattr(user, "display_name", None) or getattr(user, "username", None) or "sistem")
    except Exception:
        return "sistem"


def _pastikan_distribusi(db: Session, oleh: str = None) -> dict:
    """Bentuk Distribusi Laba OTOMATIS kalau target operasional (CTO) tercapai.

    Memakai helper yang sama dari modul `distribution` supaya aturan "70% keluar
    permanen, 30% Hak Kas Aset pindah ke Saldo Aset" hanya ada di satu tempat.
    Idempoten: kalau periode ini sudah punya Distribution, tidak ada yang berubah.
    """
    import distribution as dist_mod
    from routers.dashboard import (batas_periode, compute_finance,
                                   get_active_period)
    p = get_active_period(db)
    fin = compute_finance(db, *batas_periode(p))
    return dist_mod.pastikan_otomatis(
        db, p.start_at.date().isoformat(), fin.get("laba_bersih", 0),
        cto_tercapai=bool(fin.get("cto_tercapai")),
        kas_period_id=p.id, oleh=oleh)


def _log_transition(db: Session, order_id: int, dari, ke, oleh, catatan=""):
    db.add(StatusHistory(service_order_id=order_id, dari_status=dari,
                         ke_status=ke, oleh=oleh, waktu=datetime.now(),
                         catatan=(catatan or "") or None))


def _attach_summary(db: Session, order):
    """Tempel ringkasan pembayaran (derive) ke objek response."""
    pays = db.query(Payment).filter(Payment.service_order_id == order.id).all()
    s = payment_summary(order, pays)
    order.payment_status = s["payment_status"]
    order.total_bayar = s["total_bayar"]
    order.sisa = s["sisa"]
    return s


def _refresh_money(db: Session, order):
    """Hitung ulang laba_bersih per-order dari sumbernya (bukan input user).

    Laba = Omzet − modal_* bila CASH+LUNAS (event realisasi), selain itu 0.
    Dipanggil setiap ada peristiwa uang (receive/update/payment).
    """
    try:
        pays = db.query(Payment).filter(Payment.service_order_id == order.id).all()
        order.laba_bersih = order_profit(order, pays)
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
    return order


@router.get("/technicians")
def list_technicians(db: Session = Depends(get_db_session)):
    """Daftar teknisi dari data nyata: nama unik di service_orders + pengguna
    aktif ber-role teknisi/admin. Kontrak tetap list[str] agar UI tak berubah."""
    names = set()
    try:
        rows = db.query(ServiceOrder.technician).filter(
            ServiceOrder.technician.isnot(None),
            ServiceOrder.technician != "",
        ).distinct().all()
        for (t,) in rows:
            t = (t or "").strip()
            if t:
                names.add(t)
    except Exception:
        pass
    try:
        users = db.query(User).filter(User.active == 1).all()
        for u in users:
            if (getattr(u, "role", "") or "").strip().upper() in (
                "TEKNISI", "ADMIN", "SUPERADMIN",
            ):
                disp = (getattr(u, "display_name", "") or "").strip()
                if disp:
                    names.add(disp)
    except Exception:
        pass
    return sorted(names)


@router.get("/history/{phone}")
def order_history(phone: str, db: Session = Depends(get_db_session)):
    customers = db.query(Customer).filter(Customer.phone == phone).all()
    if not customers:
        return []
    cids = [c.id for c in customers]
    return (
        db.query(ServiceOrder)
        .filter(ServiceOrder.customer_id.in_(cids))
        .order_by(ServiceOrder.created_at.desc())
        .limit(20)
        .all()
    )


@router.post("/receive", response_model=schemas.ServiceOrderOut, status_code=201)
def receive_unit(data: schemas.ServiceReceiveIn, db: Session = Depends(get_db_session),
                 user: User = Depends(require_authority(Action.ORDER_CREATE))):
    """Daftarkan unit servis baru (buat customer + service order sekaligus).

    FINAL: initial path operasional (TITIP/PERBAIKAN/SPAREPART/TUNGGU),
    bukan dropdown status bebas. Tanpa initial_path → DITERIMA (legacy).

    Alur keuangan: Teknisi tidak boleh menetapkan harga final (closing
    adalah wewenang Admin).
    """
    if not can_edit_finance(user) and data.final_price is not None:
        raise HTTPException(status_code=403,
                            detail="Hanya Admin yang boleh menetapkan Harga Final")
    path_key = (data.initial_path or "").strip().upper() or None
    if path_key is not None:
        target, chain, err = check_initial_path(path_key, {
            "repair_plan": data.repair_plan,
            "estimate": data.estimate,
            "technician": data.technician,
            "final_price": data.final_price,
        })
        if err:
            raise HTTPException(status_code=400, detail=err)
        st = target
    else:
        st = (data.status or "DITERIMA").strip() or "DITERIMA"
        if st not in SERVICE_STATUSES:
            raise HTTPException(status_code=400,
                                detail="Status tidak valid: %s. Pilihan: %s" % (st, ", ".join(SERVICE_STATUSES)))
        ok, msg = check_transition("", st)
        if not ok:
            raise HTTPException(status_code=400, detail=msg)
        chain = ["DITERIMA"]
    dp_amount = ZERO
    try:
        dp_amount = to_decimal(data.dp)
    except (TypeError, ValueError):
        dp_amount = ZERO
    if dp_amount < 0:
        raise HTTPException(status_code=400, detail="DP tidak boleh negatif")
    # OD-LOCK-04: DP tidak boleh melebihi estimasi biaya transaksi.
    _ok, _pesan = cek_dp_vs_estimasi(dp_amount, data.estimate)
    if not _ok:
        raise HTTPException(status_code=400, detail=_pesan)
    try:
        customer = None
        if data.customer_phone:
            customer = (
                db.query(Customer)
                .filter(Customer.phone == data.customer_phone)
                .order_by(Customer.id.desc())
                .first()
            )
        if not customer:
            customer = Customer(name=data.customer_name, phone=data.customer_phone)
            db.add(customer)
            db.flush()
        elif data.customer_name and data.customer_name.strip() and customer.name != data.customer_name.strip():
            # Opsi (a): nomor WA sama = identitas sama → koreksi nama terbaru.
            # Tidak membuat customer baru; No. Servis dan histori order lain tidak berubah.
            customer.name = data.customer_name.strip()
            db.flush()

        order = ServiceOrder(
            no_servis=_generate_no_servis(),
            customer_id=customer.id,
            device=data.device,
            damagetype=data.damagetype,
            device_password=data.device_password,
            imei=(data.imei or "").strip() or None,
            check_fisik=_clean_checklist(data.check_fisik, CHECK_FISIK_KEYS),
            check_len=(_clean_checklist(data.check_len, CHECK_LEN_KEYS)
                       if data.check_len is not None else ["unit_saja"]),
            repair_plan=data.repair_plan,
            technician=data.technician,
            status=st,
            unit_status="DI TOKO",
            estimate=data.estimate or 0,
            payment=dp_amount,
            final_price=data.final_price,
            service_date=date.today(),
            warranty_months=1 if st == "DONE" else None,
        )
        db.add(order)
        db.flush()
        if dp_amount > 0:
            # DP receive dicatat di jurnal payments agar masuk omset/kas.
            # Kolom legacy `payment` tetap diisi sebagai arsip; payment_summary
            # mengurangkan porsi yang sudah ada di jurnal (anti double-count).
            _dp_row = Payment(service_order_id=order.id, kind="DP",
                              amount=dp_amount, method="CASH",
                              note="DP awal (pendaftaran unit)",
                              created_at=order.created_at or datetime.now())
            db.add(_dp_row)
            db.flush()
            # v4 #1: DP diterima di toko -> SALDO LACI bertambah.
            cash.catat_penerimaan(db, _dp_row, actor=_actor(user))
        _prev = None
        _note = ("initial path: %s" % INITIAL_PATHS[path_key]["label"]) if path_key else "pendaftaran unit"
        for _step in chain:
            _log_transition(db, order.id, _prev, _step, _actor(user), _note)
            _prev = _step
        # P2-13: notifikasi unit baru dicatat dalam transaksi yang sama (outbox +
        # journal); anti-duplikat dijamin notifications.kirim (FIX-30).
        notif_mod.kirim(db, notif_mod.EVENT_UNIT_BARU, ref_type="service_order",
                        ref_code=order.id,
                        data={"no_servis": order.no_servis, "device": order.device,
                              "customer": getattr(customer, "name", None),
                              "analisa": getattr(order, "analisa", None),
                              "tindakan": getattr(order, "tindakan", None)},
                        actor=_actor(user))
        db.commit()
    except IntegrityError:
        # Tabrakan no_servis acak (sangat jarang): ulangi sekali dengan nomor baru.
        db.rollback()
        try:
            order = ServiceOrder(
                no_servis=_generate_no_servis(),
                customer_id=customer.id,
                device=data.device,
                damagetype=data.damagetype,
                device_password=data.device_password,
                imei=(data.imei or "").strip() or None,
                check_fisik=_clean_checklist(data.check_fisik, CHECK_FISIK_KEYS),
                check_len=(_clean_checklist(data.check_len, CHECK_LEN_KEYS)
                           if data.check_len is not None else ["unit_saja"]),
                repair_plan=data.repair_plan,
                technician=data.technician,
                status=st,
                unit_status="DI TOKO",
                estimate=data.estimate or 0,
                payment=dp_amount,
                final_price=data.final_price,
                service_date=date.today(),
                warranty_months=1 if st == "DONE" else None,
            )
            db.add(order)
            db.flush()
            if dp_amount > 0:
                db.add(Payment(service_order_id=order.id, kind="DP",
                               amount=dp_amount, method="CASH",
                               note="DP awal (pendaftaran unit)",
                               created_at=order.created_at or datetime.now()))
                db.flush()
            _prev = None
            _note = ("initial path: %s" % INITIAL_PATHS[path_key]["label"]) if path_key else "pendaftaran unit"
            for _step in chain:
                _log_transition(db, order.id, _prev, _step, _actor(user), _note)
                _prev = _step
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(status_code=409,
                                detail="Gagal membuat No. Servis unik, coba lagi")
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail="Gagal mendaftarkan servis: %s" % exc)
    db.refresh(order)
    _refresh_money(db, order)
    db.refresh(order)
    _attach_summary(db, order)
    return order


DEFAULT_PAGE = 1
DEFAULT_LIMIT = 10
MAX_LIMIT = 10


def _summaries(db: Session, orders):
    """Ringkasan pembayaran per order (satu query payments untuk semua id)."""
    ids = [o.id for o in orders]
    pays = db.query(Payment).filter(Payment.service_order_id.in_(ids)).all() if ids else []
    by_order = {}
    for p in pays:
        by_order.setdefault(p.service_order_id, []).append(p)
    return {o.id: payment_summary(o, by_order.get(o.id, [])) for o in orders}


def _to_list_schema(o, summ=None):
    summ = summ or {"payment_status": None, "total_bayar": None, "sisa": None}
    return schemas.ServiceOrderList(
        id=o.id,
        no_servis=o.no_servis,
        customer_id=o.customer_id,
        device=o.device,
        brand=o.brand,
        model=o.model,
        damagetype=o.damagetype,
        imei=o.imei,
        check_fisik=list(o.check_fisik or []),
        check_len=list(o.check_len) if o.check_len is not None else ["unit_saja"],
        technician=o.technician,
        status=o.status,
        unit_status=o.unit_status,
        taken_at=o.taken_at,
        estimate=o.estimate,
        payment=o.payment,
        service_date=o.service_date,
        final_price=o.final_price,
        part_cost=o.part_cost,
        modal_jasa=o.modal_jasa,
        modal_lainnya=o.modal_lainnya,
        tanpa_modal=bool(getattr(o, "tanpa_modal", False)),
        laba_bersih=getattr(o, "laba_bersih", 0) or 0,
        lunas_date=o.lunas_date,
        lunas_at=o.lunas_at,
        warranty_months=o.warranty_months,
        payment_status=summ.get("payment_status"),
        total_bayar=summ.get("total_bayar"),
        sisa=summ.get("sisa"),
        created_at=o.created_at,
        customer_name=o.customer.name if o.customer else None,
        customer_phone=o.customer.phone if o.customer else None,
    )


def _page_clamp(page: int, limit: int):
    page = max(DEFAULT_PAGE, page)
    limit = min(MAX_LIMIT, max(1, limit))
    return page, limit


#: Status yang datanya sudah final -> diarsipkan saat periode kas ditutup.
#: CATATAN: `FAILED` SENGAJA TIDAK ada di sini. Unitnya masih ada di toko --
#: belum diambil pelanggan dan pekerjaannya belum selesai, jadi masih harus
#: kelihatan di daftar dan bisa ditindaklanjuti.
STATUS_DIARSIPKAN = ("CASH", "CANCEL")


def _momen_terminal():
    """Waktu order mencapai status finalnya.

    `lunas_at` dipakai untuk CASH (dikunci saat event CASH). Untuk CANCEL kolom
    itu NULL, jadi diambil dari `status_history` -- waktu transisi ke status
    yang sekarang dimiliki order. `created_at` hanyacadangan terakhir supaya
    order tanpa riwayat sama sekali tidak sampai hilang dari daftar.
    """
    from sqlalchemy import func, select
    from models import StatusHistory
    sub = (
        select(func.max(StatusHistory.waktu))
        .where(StatusHistory.service_order_id == ServiceOrder.id,
               StatusHistory.ke_status == ServiceOrder.status)
        .correlate(ServiceOrder)
        .scalar_subquery()
    )
    return func.coalesce(ServiceOrder.lunas_at, sub, ServiceOrder.created_at)


def _saring_belum_diarsipkan(db, qry):
    """Sembunyikan order CASH/CANCEL yang periodenya sudah CLOSED.

    Batas arsip adalah **Tutup Kas**, bukan status CASH: begitu periode ditutup,
    unit yang sudah final hilang dari halaman Transaksi karena angkanya sudah
    tersimpan di snapshot periode kas tersebut.

    Order yang masih berjalan (DITERIMA, ANALISA, KONFIRMASI, WAIT PART, REPAIR,
    DONE) TETAP tampil -- statusnya belum final dan masih perlu ditindaklanjuti.

    Order CASH/CANCEL yang jatuh di periode yang masih OPEN tetap tampil, karena
    uangnya memang belum pernah diarsipkan.
    """
    from sqlalchemy import and_, or_
    from models import KasPeriod
    closed = (
        db.query(KasPeriod.start_at, KasPeriod.end_at)
        .filter(KasPeriod.status == "CLOSED",
                KasPeriod.start_at.isnot(None),
                KasPeriod.end_at.isnot(None))
        .all()
    )
    if not closed:
        return qry
    momen = _momen_terminal()
    dalam = or_(*[and_(momen >= a, momen <= b) for a, b in closed])
    return qry.filter(~and_(ServiceOrder.status.in_(STATUS_DIARSIPKAN), dalam))


@router.get("", response_model=schemas.ServiceOrderPage)
def list_orders(
    db: Session = Depends(get_db_session),
    page: int = DEFAULT_PAGE,
    limit: int = DEFAULT_LIMIT,
    riwayat: bool = False,
):
    """Daftar servis order dengan pagination (backend-side).

    Order CASH/CANCEL yang periodenya sudah DITUTUP disembunyikan -- batas arsip
    adalah Tutup Kas, bukan status CASH. Order yang masih berjalan tetap tampil.
    Param `riwayat` diterima untuk kompatibilitas klien lama tapi diabaikan.
    """
    page, limit = _page_clamp(page, limit)
    qry = _saring_belum_diarsipkan(db, db.query(ServiceOrder))
    total = qry.count()
    rows = (
        qry.options(joinedload(ServiceOrder.customer))
        .order_by(ServiceOrder.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )
    total_pages = (total + limit - 1) // limit if total else 1
    sums = _summaries(db, rows)
    items = [_to_list_schema(o, sums.get(o.id)) for o in rows]
    return schemas.ServiceOrderPage(
        total=total,
        page=page,
        limit=limit,
        total_pages=total_pages,
        items=items,
    )


@router.get("/latest", response_model=list[schemas.ServiceOrderList])
def latest_orders(db: Session = Depends(get_db_session), limit: int = 10,
                  riwayat: bool = False):
    """Daftar order terbaru. Sama seperti halaman Transaksi: order CASH/CANCEL yang
    periodenya sudah ditutup tidak ikut ditampilkan."""
    limit = min(100, max(1, limit))
    qry = _saring_belum_diarsipkan(db, db.query(ServiceOrder))
    rows = (
        qry.options(joinedload(ServiceOrder.customer))
        .order_by(ServiceOrder.created_at.desc())
        .limit(limit)
        .all()
    )
    result = []
    sums = _summaries(db, rows)
    for o in rows:
        result.append(_to_list_schema(o, sums.get(o.id)))
    return result


@router.get("/{order_id}", response_model=schemas.ServiceOrderOut)
def get_order(order_id: int, db: Session = Depends(get_db_session)):
    order = db.query(ServiceOrder).filter(ServiceOrder.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Service order tidak ditemukan")
    _attach_summary(db, order)
    return order


@router.post("", response_model=schemas.ServiceOrderOut, status_code=201)
def create_order(data: schemas.ServiceOrderCreate, db: Session = Depends(get_db_session),
                 user: User = Depends(require_authority(Action.ORDER_CREATE))):
    customer = db.query(Customer).filter(Customer.id == data.customer_id).first()
    if not customer:
        raise HTTPException(status_code=400, detail="Customer tidak ditemukan")
    dump = data.model_dump()
    st = (dump.get("status") or "DITERIMA").strip() or "DITERIMA"
    if st == "RECEIVED":
        st = "DITERIMA"
    if st not in SERVICE_STATUSES:
        raise HTTPException(status_code=400,
                            detail="Status tidak valid: %s. Pilihan: %s" % (st, ", ".join(SERVICE_STATUSES)))
    dump["status"] = st
    dump.setdefault("unit_status", "DI TOKO")
    if isinstance(dump.get("check_fisik"), list):
        dump["check_fisik"] = _clean_checklist(dump["check_fisik"], CHECK_FISIK_KEYS)
    if isinstance(dump.get("check_len"), list):
        dump["check_len"] = _clean_checklist(dump["check_len"], CHECK_LEN_KEYS)
    # Ringkasan derive — bukan kolom DB, jangan teruskan ke ORM.
    dump.pop("payment_status", None)
    dump.pop("total_bayar", None)
    dump.pop("sisa", None)
    # laba_bersih dihitung backend (bukan input user).
    dump.pop("laba_bersih", None)
    try:
        pay0 = to_decimal(dump.get("payment"))
    except (TypeError, ValueError):
        pay0 = ZERO
    if pay0 < 0:
        raise HTTPException(status_code=400, detail="DP tidak boleh negatif")
    # OD-LOCK-04: jalur input lain (POST /api/orders) juga wajib dijaga.
    _ok, _pesan = cek_dp_vs_estimasi(pay0, dump.get("estimate"))
    if not _ok:
        raise HTTPException(status_code=400, detail=_pesan)
    order = ServiceOrder(**dump)
    db.add(order)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409,
                            detail="No. Servis sudah dipakai / gagal simpan, coba lagi")
    db.refresh(order)
    if pay0 > 0:
        # Samakan dengan receive: DP awal masuk jurnal agar terbaca omset/kas.
        db.add(Payment(service_order_id=order.id, kind="DP", amount=pay0,
                       method="CASH", note="DP awal (dibuat via API)",
                       created_at=order.created_at or datetime.now()))
        db.commit()
        db.refresh(order)
    _log_transition(db, order.id, None, st, _actor(user), "dibuat via API")
    db.commit()
    db.refresh(order)
    _attach_summary(db, order)
    return order


@router.put("/{order_id}", response_model=schemas.ServiceOrderOut)
def update_order(order_id: int, data: schemas.ServiceOrderUpdate,
                 db: Session = Depends(get_db_session),
                 user: User = Depends(require_authority(Action.ORDER_UPDATE))):
    order = db.query(ServiceOrder).filter(ServiceOrder.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Service order tidak ditemukan")
    old_status = order.status
    payload = data.model_dump(exclude_unset=True)
    note = (payload.pop("status_note", None) or "").strip()
    # Identitas nota tidak boleh diubah lewat update (jaga relasi & histori):
    # customer via PUT /api/customers, no_servis tidak bisa diubah sama sekali.
    if "no_servis" in payload and (payload["no_servis"] or "") != (order.no_servis or ""):
        raise HTTPException(status_code=400,
                            detail="No. Servis tidak dapat diubah")
    payload.pop("no_servis", None)
    # Penanda "Tanpa Modal (sengaja 0)" harus konsisten dengan angkanya: kalau
    # ada modal yang terisi, penanda itu tidak boleh aktif. Menolak lebih baik
    # daripada diam-diam mengabaikannya -- kalau ditolak diam-diam, unit yang
    # modalnya sudah terisi bisa ikut diperlakukan seolah-olah tanpa modal.
    if payload.get("tanpa_modal") is not None:
        _total_modal = sum(to_decimal(
            payload.get(k, getattr(order, k, 0)) or 0)
            for k in ("part_cost", "modal_jasa", "modal_lainnya"))
        if payload.get("tanpa_modal") and _total_modal > ZERO:
            raise HTTPException(
                status_code=400,
                detail="Tidak bisa menandai 'Tanpa Modal' kalau Modal sudah "
                       "terisi (total Rp %s). Kosongkan modalnya dulu, atau "
                       "uncheck penanda tersebut."
                       % _total_modal)
    if "customer_id" in payload and payload["customer_id"] not in (None, order.customer_id):
        raise HTTPException(status_code=400,
                            detail="Pelanggan tidak dapat dipindah via update servis")
    payload.pop("customer_id", None)
    if isinstance(payload.get("check_fisik"), list):
        payload["check_fisik"] = _clean_checklist(payload["check_fisik"], CHECK_FISIK_KEYS)
    if isinstance(payload.get("check_len"), list):
        payload["check_len"] = _clean_checklist(payload["check_len"], CHECK_LEN_KEYS)
    # Masa garansi toko hanya 0 (tidak garansi) / 1 / 3 / 6 bulan.
    if "warranty_months" in payload and payload["warranty_months"] not in (0, 1, 3, 6):
        raise HTTPException(status_code=400,
                            detail="Masa garansi tidak valid. Pilihan: 1, 3, 6 bulan atau 0 (tidak garansi)")
    new_status = payload.get("status")
    if new_status is not None:
        new_status = (new_status or "").strip()
        if not new_status:
            raise HTTPException(status_code=400, detail="Status tidak boleh kosong")
        ok, msg = check_transition(order.status, new_status, note)
        if not ok:
            raise HTTPException(status_code=400, detail=msg)
        # P2-01 / OD-014: role tanpa authority closing tidak boleh mengubah status closing.
        if new_status != old_status and is_closing_status(new_status):
            check(user, Action.ORDER_STATUS_CLOSING)
        # Guard per status (nama label Indonesia).
        if new_status == "KONFIRMASI":
            missing = []
            plan = payload.get("repair_plan", order.repair_plan)
            if not (plan or "").strip():
                missing.append("Rencana Perbaikan")
            est = payload.get("estimate", order.estimate)
            if not (est or 0) > 0:
                missing.append("Estimasi Biaya")
            if missing:
                raise HTTPException(status_code=400,
                                    detail="Status KONFIRMASI wajib melengkapi: " + ", ".join(missing))
        elif new_status == "REPAIR":
            tech = payload.get("technician", order.technician)
            if not (tech or "").strip():
                raise HTTPException(status_code=400,
                                    detail="Status REPAIR wajib melengkapi: Teknisi Penanggung Jawab")
        elif new_status == "DONE":
            missing = []
            plan = payload.get("repair_plan", order.repair_plan)
            if not (plan or "").strip():
                missing.append("Perbaikan / Tindakan Perbaikan")
            tech = payload.get("technician", order.technician)
            if not (tech or "").strip():
                missing.append("Teknisi Penanggung Jawab")
            # Harga Final wajib diisi sebelum DONE. Tanpa ini unit bisa "selesai"
            # tanpa tahu total harga pelanggan, dan karena `kewajiban()` memakai
            # final_price ?? estimate, harga 0 ikut terhitung sebagai omzet 0 --
            # unitnya lenyap dari laporan tanpa pernah ada angkanya.
            harga = payload.get("final_price", order.final_price)
            if not (to_decimal(harga or 0) > ZERO):
                missing.append("Harga Final (total pembayaran pelanggan)")
            if missing:
                raise HTTPException(status_code=400,
                                    detail="Status DONE wajib melengkapi: " + ", ".join(missing))
            if payload.get("part_cost") is None and order.part_cost is None:
                payload["part_cost"] = 0
            if payload.get("modal_jasa") is None and order.modal_jasa is None:
                payload["modal_jasa"] = 0
            # Jaring pengaman: Modal TIDAK BOLEH tersimpan NULL. Baris NULL
            # membuat unit tidak bisa pindah ke CASH selamanya dan merusak
            # perhitungan laba. Kosong dari form berarti "tidak ada modal" = 0.
            for _kol in ("part_cost", "modal_jasa", "modal_lainnya"):
                if _kol in payload and payload[_kol] is None:
                    payload[_kol] = 0
        elif new_status == "CASH":
            # Owner Cash Model (P2-15): CASH = event realisasi transaksi +
            # serah-terima unit, mengikuti Project A.
            #   - WAJIB hanya dari DONE (transisi sudah dijaga SERVICE_TRANSITIONS)
            #   - WAJIB ada Tindakan (meniru Project A)
            #   - WAJIB Modal Part & Modal Jasa SUDAH DIISI (boleh bernilai 0)
            #
            # ATURAN BISNIS: Modal Part dan Modal Jasa wajib DIISI, tapi TIDAK
            # harus lebih dari nol. Servis yang hanya ganti LCD / software tidak
            # punya Modal Part — sebelumnya user dipaksa mengetik angka 1 supaya
            # lolos validasi, dan angka itu justru ikut menguras Kas Laci saat
            # CASH (uang fiktif). Sekarang 0 = "tidak ada modal", dan
            # `cash.catat_modal` sudah otomatis melewati komponen bernilai 0.
            #
            # Yang tetap ditolak adalah kolom KOSONG (None) — supaya tetap jelas
            # bagian mana yang memang belum dihitung.
            missing = []
            plan = payload.get("repair_plan", order.repair_plan)
            if not (plan or "").strip():
                missing.append("Tindakan Perbaikan")
            if payload.get("part_cost", order.part_cost) is None:
                missing.append("Modal Part")
            if payload.get("modal_jasa", order.modal_jasa) is None:
                missing.append("Modal Jasa")
            if missing:
                raise HTTPException(
                    status_code=400,
                    detail="Status CASH wajib melengkapi: " + ", ".join(missing))
        elif new_status in ("FAILED", "CANCEL"):
            if not note:
                label = ("Alasan kegagalan" if new_status == "FAILED"
                         else "Alasan pembatalan")
                raise HTTPException(status_code=400,
                                    detail="Status %s wajib menyertakan %s (catatan)" % (new_status, label))
        payload["status"] = new_status
    # P2-01 / ADAPT app.py:2079-2084: role tanpa authority finance mempertahankan
    # nilai lama. Dijalankan SELALU (di luar blok status) agar request tanpa
    # status tidak bisa melewati proteksi FINANCE_FIELDS.
    payload, _ignored_finance = sanitize_finance_payload(user, payload, order)
    # P2-04 / Q3+Q17 (Owner: opsi B): kenaikan DP dari form unit dicerminkan ke
    # Payment Ledger. Kolom legacy `payment` tetap diisi untuk tampilan UI,
    # tetapi settlement hanya boleh berasal dari ledger yang tercatat.
    _dp_mirror = None
    if "payment" in payload:
        try:
            _dp_legacy_baru = to_decimal(payload.get("payment"))
        except (TypeError, ValueError):
            _dp_legacy_baru = ZERO
        if _dp_legacy_baru < 0:
            raise HTTPException(status_code=400, detail="DP tidak boleh negatif")
        _dp_legacy_lama = to_decimal(getattr(order, "payment", 0))
        # OD-LOCK-04: total DP unit (legacy + jurnal) tidak boleh melebihi
        # estimasi. Estimasi yang dipakai adalah nilai yang akan berlaku setelah
        # update ini, jadi_user yang menurunkan estimasi atau menaikkan DP
        # sama-sama tertangkap.
        _est_baru = payload.get("estimate", getattr(order, "estimate", None))
        _jurnal_dp = dp_total(
            db.query(Payment)
              .filter(Payment.service_order_id == order.id).all())
        _dp_total_baru = max(_dp_legacy_baru, _dp_legacy_lama) + max(
            ZERO, _jurnal_dp - _dp_legacy_lama)
        _ok, _pesan = cek_dp_vs_estimasi(_dp_total_baru, _est_baru)
        if not _ok:
            raise HTTPException(status_code=400, detail=_pesan)
        # Delta = kenaikan yang diminta vs nilai legacy saat ini.
        # BUKAN vs total ledger: data legacy bisa sudah punya DP tanpa baris ledger,
        # dan menghitung dari ledger akan membuat entri DP palsu.
        _delta_dp = _dp_legacy_baru - _dp_legacy_lama
        if _delta_dp > 0:
            try:
                _pay_dp = Payment(service_order_id=order.id, kind="DP",
                                  amount=_delta_dp, method="CASH",
                                  note="DP dari form unit (dicerminkan ke ledger)")
                db.add(_pay_dp)
                db.flush()
                # v4 #1: kenaikan DP dari form unit juga masuk SALDO LACI.
                cash.catat_penerimaan(db, _pay_dp, actor=_actor(user))
                journal.record(
                    db, journal.DOMAIN_PAYMENT, journal.PAYMENT_CREATED,
                    entity_type="PAYMENT", entity_id=_pay_dp.id, amount=_delta_dp,
                    actor=_actor(user), source=journal.SOURCE_API,
                    ref_type="NO_SERVIS", ref_code=(order.no_servis or None),
                    details={"kind": "DP", "sumber": "form unit",
                             "dp_legacy_sebelum": str(_dp_legacy_lama)})
                _dp_mirror = {"delta": str(_delta_dp),
                              "legacy_sebelum": str(_dp_legacy_lama),
                              "legacy_setelah": str(_dp_legacy_baru)}
            except Exception as _exc:  # noqa: BLE001
                db.rollback()
                raise HTTPException(status_code=500,
                                    detail="Gagal mencatat DP ke ledger: %s" % _exc)
        # tidak ada kenaikan: kolom legacy dibiarkan apa adanya (tidak diubah),
    for key, val in payload.items():
        setattr(order, key, val)
    # P2-15 (Owner 1A): `warranty_months` = KONFIGURASI/input, boleh terisi
    # sebelum CASH. Yang "aktif" (window garansi) baru pada CASH karena
    # `taken_at` diisi saat event CASH (lihat `_origin_warranty_start`).
    if order.status == "DONE" and order.warranty_months is None:
        order.warranty_months = 1
    # P2-15 (Owner Cash Model): SATU transaksi untuk seluruh event status.
    # Semua efek (WA, Modal, Payment Ledger, serah-terima, laba, notifikasi)
    # baru dipersistkan SATU KALI di akhir. Kegagalan salah satu langkah
    # membatalkan semuanya — tidak ada state setengah / CASH tanpa pelunasan.
    db.flush()
    if new_status is not None and new_status != old_status:
        _log_transition(db, order.id, old_status, new_status, _actor(user), note)
        _cust = getattr(order, "customer", None)
        if new_status == "DONE":
            # P2-13 + OD-019: WA "Selesai" saat pekerjaan selesai — konfirmasi
            # ke konsumen unit siap diambil (meniru Project A: WA di DONE).
            notif_mod.catat_wa_selesai(db, order, actor=_actor(user))
            # Modal TIDAK lagi keluar di DONE. Sesuai keputusan Owner: Modal
            # Part/Jasa/Lain dikeluarkan dari hitungan kas saat status CASH
            # (uangnya benar-benar keluar saat transaksi terealisasi), bukan
            # saat pekerjaan selesai. Barisnya dipindah ke cabang CASH di bawah.
            # Catat_modal sendiri idempoten per komponen, jadi replay aman.
        elif new_status == "CASH":
            # ── Owner Cash Model: CASH = event realisasi (dari DONE) ──
            # Semua langkah berikut dalam SATU transaksi: kegagalan di salah
            # satu langkah membatalkan semuanya (tidak ada state setengah).
            _cash_when = datetime.now()
            _now_cash = _cash_when
            # (1) Payment Ledger Pelunasan Tunai untuk sisa tagihan.
            #     Memakai helper SSOT yang sama dengan POST /api/payments ->
            #     tidak ada jalur tulis payment kedua (FIX-27), dan mutasi
            #     Saldo Laci (`cash.catat_penerimaan`) tepat satu kali.
            _pays_pre = db.query(Payment).filter(
                Payment.service_order_id == order.id).all()
            _sisa = to_decimal(payment_summary(order, _pays_pre).get("sisa") or 0)
            if _sisa > 0:
                payments_mod.catat_payment(
                    db, order, "PELUNASAN", _sisa, method="CASH",
                    note="Pelunasan otomatis saat status Cash", actor=_actor(user),
                    when=_cash_when, allow_settled=True)
            else:
                # Sudah ada pelunasan di ledger (replay CASH / koreksi): JANGAN
                # tulis baris baru. `statusflow.payment_summary` menjumlahkan
                # semua baris, jadi satu barisdobel = uang fiktif di Buku Kas.
                journal.record(
                    db, journal.DOMAIN_PAYMENT, journal.PAYMENT_SETTLED,
                    entity_type="SERVICE_ORDER", entity_id=order.id,
                    amount=to_decimal(payment_summary(order, _pays_pre).get("total_bayar") or 0),
                    actor=_actor(user), source=journal.SOURCE_API,
                    ref_type="NO_SERVIS", ref_code=(order.no_servis or None),
                    details={"catatan": "replay CASH: tidak ada pelunasan baru"})
            # (2) LUNAS + lunas_at = waktu event CASH (dibaca dari ledger).
            _pays = db.query(Payment).filter(
                Payment.service_order_id == order.id).all()
            if payment_summary(order, _pays)["payment_status"] == "LUNAS":
                lock_lunas_moment(order, when=_cash_when)
            # (2b) Modal Part/Jasa/Lain keluar dari SALDO LACI di CASH.
            # Keputusan Owner: kas hanya berkurang saat transaksi terealisasi,
            # bukan saat pekerjaan selesai (DONE). Idempoten per komponen lewat
            # ref_type+ref_id di cash.catat_modal, jadi replay tidak dobel.
            cash.catat_modal(db, order, actor=_actor(user))
            # (3) Serah-terima unit (CASH otomatis berarti customer mengambil).
            order.unit_status = "DIAMBIL"
            order.taken_at = _now_cash
            # (4) Realisasi Laba transaksi = Omzet - Modal3 (gate: CASH + LUNAS).
            order.laba_bersih = order_profit(order, _pays)
            # (5) Notifikasi Kas Masuk (event financial; WA Selesai sudah di DONE).
            notif_mod.kirim(db, notif_mod.EVENT_KAS_MASUK, ref_type="service_order",
                            ref_code=order.id,
                            data={"no_servis": order.no_servis, "device": order.device,
                                  "customer": getattr(_cust, "name", None),
                                  "technician": order.technician,
                                  "harga_jual": order.final_price,
                                  "laba": str(order.laba_bersih),
                                  "sisa_dilunasi": str(_sisa)},
                            actor=_actor(user))
    # (6) DISTRIBUSI OTOMATIS: event CASH menaikkan Laba Kotor, jadi ini salah
    #     satu jalur yang bisa membuat CTO tercapai. Idempoten per periode kas.
    try:
        _pastikan_distribusi(db, _actor(user))
    except Exception:  # noqa: BLE001
        # Distribusi tidak boleh menggagalkan transaksi servis.
        db.rollback()
    db.commit()
    # Konsistensi momen lunas: kolom `payment` masih bisa ditulis UI (arsip DP),
    # jadi kunci momen LUNAS bila ringkasan sudah LUNAS (untuk garansi & kas).
    # CATATAN: untuk status CASH, `lunas_at` SUDAH dikunci dengan waktu event
    # CASH di atas — blok berikut tidak mengubahnya (lock_lunas_moment idempotent).
    try:
        pays = db.query(Payment).filter(Payment.service_order_id == order.id).all()
        if payment_summary(order, pays)["payment_status"] == "LUNAS":
            if lock_lunas_moment(order):
                db.commit()
    except Exception:
        pass
    db.refresh(order)
    _attach_summary(db, order)
    return order


@router.delete("/{order_id}")
def delete_order(order_id: int, db: Session = Depends(get_db_session),
                 admin: User = Depends(require_admin)):
    """Hapus order — khusus Admin. Diblokir bila sudah ada uang/klaim/status
    status terminal (DONE/CASH/FAILED/CANCEL) — gunakan alur riwayat/arsip, bukan hapus, agar jurnal aman)."""
    order = db.query(ServiceOrder).filter(ServiceOrder.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Service order tidak ditemukan")
    n_pay = db.query(Payment).filter(Payment.service_order_id == order.id).count()
    if n_pay:
        raise HTTPException(status_code=409,
                            detail="Order sudah memiliki %d pembayaran tercatat, tidak dapat dihapus" % n_pay)
    n_claim = db.query(WarrantyClaim).filter(
        WarrantyClaim.service_order_id == order.id).count()
    if n_claim:
        raise HTTPException(status_code=409,
                            detail="Order memiliki klaim garansi, tidak dapat dihapus")
    if (order.status or "") in TERMINAL_STATUSES or (order.status or "") == "DONE":
        raise HTTPException(status_code=409,
                            detail="Order %s tidak dapat dihapus (gunakan riwayat/arsip)" % order.status)
    db.delete(order)
    db.commit()
    return {"ok": True}


@router.post("/{order_id}/handover", response_model=schemas.ServiceOrderOut)
def handover_unit(order_id: int, db: Session = Depends(get_db_session),
                  user: User = Depends(require_authority(Action.ORDER_HANDOVER))):
    """Serahkan unit ke konsumen: DI TOKO → DIAMBIL (+ taken_at). Idempoten.

    Hanya untuk order terminal (DONE/CASH/FAILED/CANCEL) — unit yang masih dalam
    proses tidak dapat diserahkan."""
    order = db.query(ServiceOrder).filter(ServiceOrder.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Service order tidak ditemukan")
    if (order.unit_status or "DI TOKO") == "DIAMBIL":
        _attach_summary(db, order)
        return order
    if (order.status or "") not in TERMINAL_STATUSES:
        raise HTTPException(status_code=400,
                            detail="Unit hanya dapat diserahkan setelah status %s (kini: %s)"
                            % ("/".join(TERMINAL_STATUSES), order.status or "-"))
    order.unit_status = "DIAMBIL"
    order.taken_at = datetime.now()
    db.commit()
    db.refresh(order)
    _attach_summary(db, order)
    return order


@router.get("/{order_id}/history", response_model=list[schemas.StatusHistoryOut])
def order_history_timeline(order_id: int, db: Session = Depends(get_db_session)):
    order = db.query(ServiceOrder).filter(ServiceOrder.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Service order tidak ditemukan")
    return (
        db.query(StatusHistory)
        .filter(StatusHistory.service_order_id == order_id)
        .order_by(StatusHistory.waktu.asc(), StatusHistory.id.asc())
        .all()
    )
