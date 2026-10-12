"""Dashboard endpoints - data untuk star cards & charts."""
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from dependencies import get_db_session
from finance import compute_finance_core
import cash
from money import HUNDRED, PCT_10, PCT_30, ZERO, to_decimal
from models import Expense, KasEntry, KasPeriod, Payment, Refund, ServiceOrder, User
from routers.auth import get_authenticated_user
from statusflow import kewajiban, lunas_moment, payment_summary
import schemas

router = APIRouter(prefix="/api", tags=["dashboard"])

# Batas periode kas (WIB, jam server). Periode TIDAK auto-tutup;
# baris OPEN terakhir selalu dianggap periode aktif.
PERIOD_HOUR = 16


def _period_bounds(now: datetime):
    """Batas [start, end) periode kas yang memuat `now`."""
    start = now.replace(hour=PERIOD_HOUR, minute=0, second=0, microsecond=0)
    if now < start:
        start -= timedelta(days=1)
    return start, start + timedelta(days=1)


def boleh_lihat_kas_besar(user) -> bool:
    """v4 #11: Kas BESAR (Saldo Aset + Master Kas) hanya Admin & Pengelola.

    Satu-satunya definisi visibilitas posisi kas besar. Dipakai oleh
    `compute_finance` (dan endpoint lain) supaya tidak ada celah baca lewat
    endpoint yang berbeda.
    """
    try:
        from authority import ROLE_ADMIN, ROLE_PENGELOLA, canonical_role
        return canonical_role(user) in (ROLE_ADMIN, ROLE_PENGELOLA)
    except Exception:  # noqa: BLE001
        return False


def ringkasan_titipan_dp(db: Session, start: datetime = None, end: datetime = None) -> dict:
    """Ringkasan **Titipan DP** — pisah dari Omzet, Laba, dan Distribusi.

    DP bukan pendapatan: uang customer yang belum menjadi pembayaran transaksi.
    Empat angka, semuanya TURUNAN dari data yang sudah ada (tanpa kolom baru,
    tanpa ledger baru):

        Diterima     = Σ Payment(kind='DP')
        Dipakai      = DP milik unit yang transaksinya sudah SETTLED (LUNAS)
        Dikembalikan = Σ Refund(jenis='DP')
        Saldo        = Diterima − Dipakai − Dikembalikan

    "Dipakai" dihitung dari Payment Ledger, bukan dari kolom baru: begitu unit
    LUNAS, DP-nya sudah jadi bagian dari pembayaran penuh (event CASH menulis
    pelunasan sebesar SISA, bukan sebesar total — jadi tidak ada double count).
    Saldo titipan bersifat **lintas periode**: Tutup Kas tidak menghapus
    apa pun, dan angka ini tidak dibatasi periode kas, jadi DP yang belum
    selesai otomatis terbawa ke periode berikutnya.

    `berjalan` = DP yang **DITERIMA pada periode [start, end) tapi unitnya belum
    SETTLED**. DP milik unit yang sudah LUNAS TIDAK boleh ditambah lagi — saat
    pelunasan, nilainya sudah tercakup di Omzet (Omzet = kewajiban = total
    pembayaran), meski uang fisiknya tetap tercatat di Mutasi Kas sebagai baris
    DP dan baris pelunasan.
    """
    from statusflow import payment_summary

    pays_by_order = {}
    for p in db.query(Payment).all():
        pays_by_order.setdefault(p.service_order_id, []).append(p)

    diterima = ZERO
    dipakai = ZERO
    berjalan = ZERO
    for o in db.query(ServiceOrder).all():
        rows = pays_by_order.get(o.id) or []
        dp_order = ZERO
        dp_periode = ZERO
        for p in rows:
            if (getattr(p, "kind", "") or "").strip().upper() == "DP":
                nilai = to_decimal(p.amount)
                dp_order += nilai
                if start is not None and end is not None:
                    ca = getattr(p, "created_at", None)
                    if ca is not None and start <= ca < end:
                        dp_periode += nilai
        if dp_order <= ZERO:
            continue
        diterima += dp_order
        s = payment_summary(o, rows)
        if s["payment_status"] == "LUNAS":
            dipakai += dp_order
        else:
            # Masih titipan: uangnya ada di Laci & TERWAKILI di ledger kas, tapi
            # belum jadi Omzet (unit belum LUNAS). Dilacak di panel ini.
            berjalan += dp_periode

    dikembalikan = ZERO
    for r in db.query(Refund).all():
        if (getattr(r, "jenis", "") or "").strip().upper() == "DP":
            dikembalikan += to_decimal(r.nominal)

    return {
        "diterima": diterima,
        "dipakai": dipakai,
        "dikembalikan": dikembalikan,
        # TIDAK di-clamp ke 0: saldo harus PERSIS sama dengan penjumlahan
        # seluruh mutasi (UAT #7). Saldo negatif berarti ada refund DP yang
        # melebihi DP yang masih tertahan — itu informasi yang harus terlihat,
        # bukan ditutup diam-diam.
        "saldo": diterima - dipakai - dikembalikan,
        "berjalan": berjalan,
        "mutasi": mutasi_titipan_dp(db, pays_by_order),
    }


def mutasi_titipan_dp(db: Session, pays_by_order: dict = None) -> list:
    """Daftar mutasi Titipan DP + saldo berjalan, untuk panel "Titipan DP".

    SEMUA diturunkan dari `payments` + `refunds` — tidak ada tabel/kolom/ledger
    baru, jadi tidak mungkin terjadi mutasi ganda: daftar ini dihitung ulang
    setiap request dari data yang sama, sehingga reload halaman atau request
    berulang menghasilkan angka yang identik.

    Tiga jenis mutasi:
      MASUK  — setiap Payment(kind='DP'): uang customer masuk sebagai titipan.
      KELUAR — setiap Refund(jenis='DP'): DP dikembalikan ke customer.
      DIPAKAI — saat unitnya SETTLED (LUNAS), DP-nya diselesaikan jadi
                pembayaran transaksi. Satu baris per unit, dihitung dari
                Payment Ledger (bukan dari status CASH), jadi tidak mungkin
                terhitung dua kali walau status diperbarui berkali-kali.
    """
    from statusflow import lunas_moment, payment_summary

    if pays_by_order is None:
        pays_by_order = {}
        for p in db.query(Payment).all():
            pays_by_order.setdefault(p.service_order_id, []).append(p)

    items = []
    for o in db.query(ServiceOrder).all():
        rows = pays_by_order.get(o.id) or []
        dp_rows = [p for p in rows
                   if (getattr(p, "kind", "") or "").strip().upper() == "DP"]
        if not dp_rows:
            continue
        cust = getattr(o, "customer", None)
        for p in dp_rows:
            ca = getattr(p, "created_at", None) or datetime.min
            items.append({
                "tgl": ca.date().isoformat() if hasattr(ca, "date") else None,
                "waktu": ca.isoformat() if hasattr(ca, "isoformat") else None,
                "no_servis": o.no_servis,
                "pelanggan": (getattr(cust, "name", None) or "-"),
                "unit": o.device or "-",
                "jenis": "MASUK",
                "label": "DP Masuk",
                "masuk": to_decimal(p.amount),
                "keluar": ZERO,
            })
        if payment_summary(o, rows)["payment_status"] != "LUNAS":
            continue
        dipakai = sum(to_decimal(p.amount) for p in dp_rows)
        mm = lunas_moment(o, rows) or datetime.min
        items.append({
            "tgl": mm.date().isoformat() if hasattr(mm, "date") else None,
            "waktu": mm.isoformat() if hasattr(mm, "isoformat") else None,
            "no_servis": o.no_servis,
            "pelanggan": (getattr(cust, "name", None) or "-"),
            "unit": o.device or "-",
            "jenis": "DIPAKAI",
            "label": "Dipakai untuk Pelunasan",
            "masuk": ZERO,
            "keluar": dipakai,
        })

    for r in db.query(Refund).all():
        if (getattr(r, "jenis", "") or "").strip().upper() != "DP":
            continue
        o = getattr(r, "service_order", None)
        cust = getattr(o, "customer", None) if o is not None else None
        ca = getattr(r, "created_at", None) or datetime.min
        items.append({
            "tgl": ca.date().isoformat() if hasattr(ca, "date") else None,
            "waktu": ca.isoformat() if hasattr(ca, "isoformat") else None,
            "no_servis": (getattr(o, "no_servis", None) or getattr(r, "refund_no", None) or "-"),
            "pelanggan": (getattr(cust, "name", None) or "-"),
            "unit": (getattr(o, "device", None) or "-"),
            "jenis": "KEMBALI",
            "label": "Pengembalian DP",
            "masuk": ZERO,
            "keluar": to_decimal(r.nominal),
        })

    urut = {"MASUK": 0, "DIPAKAI": 1, "KEMBALI": 2}
    items.sort(key=lambda it: (str(it["waktu"] or ""), urut.get(it["jenis"], 9)))
    saldo = ZERO
    for it in items:
        saldo += to_decimal(it["masuk"]) - to_decimal(it["keluar"])
        it["saldo"] = saldo
    items.reverse()          # terbaru di atas
    return items[:200]


def batas_periode(p) -> tuple:
    """Batas efektif satu periode kas.

    ATURAN BISNIS: periode berjalan DARI SAAT DIBUKA sampai DITUTUP. `end_at`
    bukan batas pemotongan data — selama periode masih OPEN, semua transaksi
    sejak `start_at` termasuk, berapa lama pun telat ditutup. Jam 16:00 hanya
    PATOKAN PENGINGAT untuk segera menutup kas, bukan pemotong periode.

    Hanya periode CLOSED yang punya batas atas yang jelas; nilainya diisi
    `closing.tutup_periode()` dengan waktu penutupan yang sebenarnya.
    """
    if p is None:
        return None, None
    start = getattr(p, "start_at", None)
    if (getattr(p, "status", "") or "").strip().upper() == "CLOSED":
        return start, getattr(p, "end_at", None)
    return start, datetime.max


def get_active_period(db: Session) -> KasPeriod:
    """Ambil periode OPEN terakhir; bootstrap bila belum ada sama sekali."""
    p = (
        db.query(KasPeriod)
        .filter(KasPeriod.status == "OPEN")
        .order_by(KasPeriod.id.desc())
        .first()
    )
    if p:
        return p
    now = datetime.now()
    start, end = _period_bounds(now)
    p = KasPeriod(start_at=start, end_at=end, status="OPEN")
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _expense_moment(e) -> Optional[datetime]:
    if getattr(e, "created_at", None):
        return e.created_at
    if getattr(e, "tanggal", None):
        return datetime(e.tanggal.year, e.tanggal.month, e.tanggal.day, 12, 0, 0)
    return None


def compute_finance(db: Session, start: datetime, end: datetime, lihat_kas_besar: bool = True) -> dict:
    """Satu-satunya sumber hitungan keuangan (dipakai overview & Tutup Kas).

    P2-05 / Financial SSOT:
      - OMZET = penjualan SETTLED/LUNAS dalam periode (DP bukan Omzet, bukan Laba);
      - MODAL = Part + Jasa + Lain-lain (3 komponen terpisah, cohort Omzet);
      - BEBAN = Gaji + Operasional (beku sekali per periode / OD-001);
      - LABA BERSIH = OMZET - MODAL PART - MODAL JASA - MODAL LAIN - BEBAN.
    Statistik kas manual (opening/masuk/keluar) tetap dipertahankan.
    """

    def num(v):
        """P2-02 / Q10: nilai uang selalu Decimal (tanpa jalur float)."""
        return to_decimal(v)

    # ---- Financial SSOT (P2-05) ----
    core = compute_finance_core(db, start, end)
    omset = core["omset"]
    modal_part = core["modal_part"]
    modal_jasa = core["modal_jasa"]
    modal_lain = core["modal_lainnya"]
    total_modal = core["total_modal"]
    laba_kotor = omset - total_modal
    beban_gaji = core["beban_gaji"]
    beban_ops = core["beban_operasional"]
    beban_lain = ZERO  # SSOT-4: kategori lain bukan Beban
    total_beban = core["total_beban"]

    # FIN-MIRROR-4 (rumus A-1, `app.py:376`): ambang CTS/CTO di Proyek A
    # dibandingkan terhadap `laba_kotor = laba_servis + laba_tambahan`, yaitu
    # laba kotor PLUS transaksi kas manual. Versi sebelumnya memakai laba
    # kotor tanpa `tambahan`, sehingga ambang milestone bisaachievement lebih
    # tinggi daripada yang dihitung Project A.
    _tambahan = to_decimal(core.get("tambahan", 0))
    laba_kotor = laba_kotor + _tambahan

    in_orders = []
    pays = db.query(Payment).all()
    in_pays = [p for p in pays
               if p.created_at is not None and start <= p.created_at < end]

    cts_target = beban_gaji
    cts_progress = (laba_kotor / cts_target * HUNDRED) if cts_target > 0 else (HUNDRED if laba_kotor > 0 else ZERO)
    cts_ok = bool(laba_kotor >= cts_target) if cts_target > 0 else True

    cto_target = beban_gaji + beban_ops
    cto_progress = (laba_kotor / cto_target * HUNDRED) if cto_target > 0 else (HUNDRED if laba_kotor > 0 else ZERO)
    cto_ok = bool(laba_kotor >= cto_target) if cto_target > 0 else True

    # FIN-MIRROR-4: `tambahan` sudah masuk lewat `compute_finance_core`, sehingga
    # SSOT-5 tetap berlaku tanpa pengurangan ganda.
    laba_bersih = omset - modal_part - modal_jasa - modal_lain - total_beban

    # P2-07 / SSOT-6: TIDAK lagi digate CTO. Alokasi HANYA terbentuk saat
    # Distribusi sudah TERBENTUK otomatis saat CTO tercapai (lihat
    # `distribution.pastikan_otomatis`), bukan lagi saat Tutup Kas. Gate CTO
    # sekarang justru menentukan apakah distribusi boleh terbentuk.
    import distribution as _dist
    from models import KasPeriod
    _periode_key = core["periode"]
    # WAJIB lewat `kas_period_id`. Admin boleh menutup Kas lebih dari sekali sehari,
    # jadi dua Kas Period bisa bertanggal sama — masing-masing punya baris
    # Distribution sendiri. Kalau hanya dicari lewat tanggal, baris periode lain
    # bisa ikut terbaca dan angka alokasi yang tampil jadi milik periode yang
    # salah.
    _pid = (db.query(KasPeriod).filter(KasPeriod.start_at == start).first() or {})
    _pid = getattr(_pid, "id", None)
    _row_dist = _dist.sudah_ada(db, _periode_key, kas_period_id=_pid)
    if _row_dist is None and _pid is not None:
        # Baris distribusi yang dibuat sebelum `kas_period_id` jadi identitas
        # tidak punya kolom terisi — cari lewat tanggal sebagai jaring pengaman.
        _row_dist = _dist.sudah_ada(db, _periode_key)
    _preview = _dist.preview(laba_bersih)
    alokasi_ok = _row_dist is not None
    # Alasan singkat kalau CTO sudah tercapai tapi distribusi belum jalan —
    # supaya UI bisa menjelaskan kenapa, bukan hanya diam saja.
    _dist_alasan = None
    if not alokasi_ok:
        if not cto_ok:
            _dist_alasan = _dist.ALASAN_BELUM_SIAP
        elif not _preview.get("eligible"):
            _dist_alasan = _preview.get("alasan")
        elif cash.saldo_laci(db) < (to_decimal(_preview["cash_out"])
                                    + to_decimal(_preview["kas_aset"])):
            _dist_alasan = _dist.ALASAN_KAS_KURANG
    if _row_dist is not None:
        _al = _dist.alokasi_dari(_row_dist)
        karyawan = _al["karyawan"]
        pengelola = _al["pengelola"]
        investor = _al["investor"]
        kas_aset = _al["kas_aset"]
    else:
        karyawan = pengelola = investor = kas_aset = ZERO

    # Jurnal kas manual periode aktif (di luar servis & beban).
    # 'Saldo Awal' dikecualikan dari baris (dihitung lintas periode sebagai opening).
    def _kas_moment(k) -> Optional[datetime]:
        if getattr(k, "created_at", None):
            return k.created_at
        if getattr(k, "tanggal", None):
            return datetime(k.tanggal.year, k.tanggal.month, k.tanggal.day, 12, 0, 0)
        return None

    kas_masuk = ZERO
    kas_keluar = ZERO
    opening = ZERO
    # v4 #9: Buku Kas hanya menghitung mutasi yang memang arus periode:
    # - layer LACI (bukan posisi Kas Aset Besar), dan
    # - sumber yang diizinkan (MANUAL / CASH_OUT / REFUND_DP / FAILED_CANCEL).
    # Mutasi turunan (PAYMENT/MODAL/BEBAN/TRANSFER/INJEKSI/REKONSILIASI) hanya
    # memengaruhi posisi Master Kas supaya tidak double count.
    for k in db.query(KasEntry).filter(KasEntry.layer == cash.LAYER_LACI).all():
        sumber = (getattr(k, "sumber", None) or cash.SUMBER_MANUAL)
        if sumber not in cash.SUMBER_BUKU_KAS:
            continue
        is_opening = (k.kategori or "") == "Saldo Awal"
        val = num(k.nominal)
        signed = val if (k.jenis or "").strip().lower() == "masuk" else -val
        if is_opening:
            opening += signed
            continue
        m = _kas_moment(k)
        if m is not None and start <= m < end:
            if (k.jenis or "").strip().lower() == "masuk":
                kas_masuk += val
            else:
                kas_keluar += val

    total_masuk = omset + kas_masuk
    total_keluar = total_modal + total_beban + kas_keluar
    saldo = opening + total_masuk - total_keluar

    # Titipan DP dihitung lebih dulu: dipakai untuk panel Titipan DP dan untuk
    #Turunan Kas Awal versi OPERASIONAL (Saldo Laci dikurangi titipan berjalan).
    # DP sendiri TETAP ada di ledger kas (uangnya nyata di laci) — yang dipisah
    # hanya tampilannya, supaya kartu akrual bersih sementara Mutasi Kas & rekonsiliasi
    # fisik tetap jujur.
    _titipan = ringkasan_titipan_dp(db, start, end)
    _kas_awal = cash.saldo_laci_sampai(db, start)

    out = {
        "periode": core["periode"],
        "n_settled": core["n_settled"],
        "n_bayar": len(in_pays),
        "n_order_bayar": core["n_settled"],
        "omset": omset,
        "modal_part": modal_part,
        "modal_jasa": modal_jasa,
        "modal_lainnya": modal_lain,
        "total_modal": total_modal,
        "laba_kotor": laba_kotor,
        "beban_gaji": beban_gaji,
        "beban_operasional": beban_ops,
        "beban_lainnya": beban_lain,
        "total_beban": total_beban,
        "cts_target": cts_target,
        "cts_progress": round(cts_progress, 2),
        "cts_tercapai": cts_ok,
        "cto_target": cto_target,
        "cto_progress": round(cto_progress, 2),
        "cto_tercapai": cto_ok,
        "laba_bersih": laba_bersih,
        "kas_masuk_manual": kas_masuk,
        "kas_keluar_manual": kas_keluar,
        "opening": opening,
        "total_masuk": total_masuk,
        "total_keluar": total_keluar,
        "saldo": saldo,
        # Owner Cash Model v4: posisi aset kas (terpisah dari Buku Kas).
        # `kas_aset_awal` = saldo Laci FISIK pada awal periode (dipakai baris
        # "Kas Aset Awal" di Mutasi Kas dan pembanding rekonsiliasi).
        "kas_aset_awal": _kas_awal,
        # Versi AKRUAL untuk Conditions Kas: uang DP adalah kewajiban pelanggan,
        # bukan kas toko, jadi dikurangi agar baris "Kas Kecil/Laci" sejajar dengan
        # Omzet/Modal/Beban (yang semuanya sudah bebas dari DP).
        "kas_aset_awal_operasional": max(
            ZERO, _kas_awal - _titipan["saldo"]),
        "saldo_laci": cash.saldo_laci(db),
        "label_laci": cash.LABEL[cash.LAYER_LACI],
        # SSOT-7 / v4 #11: posisi Kas BESAR hanya untuk Admin & Pengelola.
        # Role lain TIDAK menerima key-nya sama sekali (bukan diisi 0), supaya
        # tidak bisa dibaca lewat response mana pun.
        "titipan_dp": _titipan,
        # P2-07: pratinjau (belum terbentuk) — hanya untuk display, bukan pembukuan.
        "alokasi_preview": {
            "karyawan": _preview["karyawan"], "pengelola": _preview["pengelola"],
            "investor": _preview["investor"], "kas_aset": _preview["kas_aset"],
            "cash_out": _preview["cash_out"], "eligible": _preview["eligible"],
        },
        "alokasi_terbentuk": alokasi_ok,
        "distribusi_alasan": _dist_alasan,
        "distribusi_trigger": "CTO tercapai",
        "alokasi": {
            "karyawan": karyawan,
            "pengelola": pengelola,
            "investor": investor,
            "kas_aset": kas_aset,
        },
    }
    # SSOT-7 / v4 #11: posisi Kas BESAR hanya untuk Admin & Pengelola. Role lain
    # TIDAK menerima key-nya sama sekali (bukan diisi 0), supaya tidak bisa dibaca
    # lewat endpoint mana pun.
    if lihat_kas_besar:
        out.update({
            "saldo_aset": cash.saldo_kas_aset(db),
            "master_kas": cash.master_kas(db),
            "label_aset": cash.LABEL[cash.LAYER_ASET],
        })
    return out


@router.get("/period", response_model=schemas.KasPeriodOut)
def get_period(db: Session = Depends(get_db_session)):
    """Periode kas aktif (bootstrap otomatis bila belum ada)."""
    return get_active_period(db)


@router.get("/overview")
def get_overview(db: Session = Depends(get_db_session),
                 user: User = Depends(get_authenticated_user)):
    """Data untuk star cards + insight. Finansial = agregat periode kas aktif."""
    period = get_active_period(db)
    fin = compute_finance(db, *batas_periode(period),
                          lihat_kas_besar=boleh_lihat_kas_besar(user))

    orders = db.query(ServiceOrder).all()
    total = len(orders)
    selesai = sum(1 for o in orders if o.status == "DONE")
    # P2-15: status kanonis baru (DIAGNOSAlegacy == ANALISA, tidak aktif lagi).
    aktif = sum(1 for o in orders if o.status in ("DITERIMA", "ANALISA", "KONFIRMASI",
                                                 "WAIT PART", "REPAIR"))
    gagal_batal = sum(1 for o in orders if o.status in ("FAILED", "CANCEL"))
    _all_pays = db.query(Payment).all()
    _by_order = {}
    for _p in _all_pays:
        _by_order.setdefault(_p.service_order_id, []).append(_p)
    lunas = sum(1 for o in orders
                if payment_summary(o, _by_order.get(o.id, []))["payment_status"] == "LUNAS")

    def pct_txt(p, ok):
        return "TERCAPAI" if ok else (str(p).replace(".", ",") + "%")

    _awal = getattr(period, "start_at", None)
    _batas = getattr(period, "end_at", None)
    # Periode berjalan sampai DITUTUP. Kalau end_at sudah terlewat (belum
    # ditutup), periode ini tetap berlaku & perlu segera ditutup.
    _lewat = bool(_batas is not None and _batas < datetime.now())
    _sub_periode = "dibuka %s" % (_awal.strftime("%d/%m %H:%M") if _awal else "-")
    _sub_periode += " • belum ditutup (segera tutup kas)" if _lewat else ""

    return {
        "period": {
            "id": period.id,
            "start_at": _awal.isoformat() if _awal else None,
            "end_at": _batas.isoformat() if _batas else None,
            "berlaku_sampai": ("ditutup" if _lewat or _batas is None else _batas.isoformat()),
            "lewat_jam_16": _lewat,
        },
        "finance": fin,
        "star_cards": [
            {"key": "omset", "label": "Omset Periode", "value": fin["omset"],
             "sub": str(fin["n_bayar"]) + " pembayaran • " + _sub_periode},
            {"key": "laba_kotor", "label": "Laba Kotor", "value": fin["laba_kotor"],
             "sub": "Omset − modal (Part+Jasa+Lain)"},
            {"key": "beban", "label": "Total Beban", "value": fin["total_beban"],
             "sub": "Gaji + operasional + lainnya"},
            {"key": "laba_bersih", "label": "Laba Bersih", "value": fin["laba_bersih"],
             "sub": "Kotor − total beban" + (" • alokasi terbentuk" if fin["alokasi_terbentuk"] else "")},
            {"key": "cts", "label": "Target Gaji (CTS)", "value": fin["cts_target"],
             "progress": fin["cts_progress"], "tercapai": fin["cts_tercapai"],
             "sub": pct_txt(fin["cts_progress"], fin["cts_tercapai"]) + " dari beban gaji"},
            {"key": "cto", "label": "Target Operasional (CTO)", "value": fin["cto_target"],
             "progress": fin["cto_progress"], "tercapai": fin["cto_tercapai"],
             "sub": pct_txt(fin["cto_progress"], fin["cto_tercapai"]) + " dari gaji+ops"},
        ],
        "insight": [
            {"value": total, "label": "Unit Masuk", "color": "text-cyan-600"},
            {"value": selesai, "label": "Unit Selesai", "color": "text-green-600"},
            {"value": lunas, "label": "Unit Lunas", "color": "text-emerald-600"},
            {"value": aktif, "label": "Unit Aktif", "color": "text-amber-600"},
        ],
        "stats": {"total": total, "selesai": selesai, "aktif": aktif,
                  "gagal_batal": gagal_batal, "lunas": lunas},
    }


@router.get("/statistics/status")
def get_status_stats(db: Session = Depends(get_db_session)):
    """Tren 7 hari real + hitungan per status saat ini (pengganti dummy)."""
    today = datetime.now().date()
    days = [today - timedelta(days=i) for i in range(6, -1, -1)]
    categories = [d.strftime("%a") for d in days]
    orders = db.query(ServiceOrder).all()
    _pay_rows = db.query(Payment).all()
    _pay_by_order = {}
    for _p in _pay_rows:
        _pay_by_order.setdefault(_p.service_order_id, []).append(_p)
    lunas_days = []
    for o in orders:
        m = lunas_moment(o, _pay_by_order.get(o.id, []))
        s = payment_summary(o, _pay_by_order.get(o.id, []))
        if s["payment_status"] == "LUNAS" and m is not None:
            lunas_days.append(m.date())
    masuk, selesai, pending = [], [], []
    pending_set = {"DITERIMA", "ANALISA", "KONFIRMASI", "WAIT PART", "REPAIR"}
    for d in days:
        created = [o for o in orders
                   if o.created_at is not None and o.created_at.date() == d]
        masuk.append(len(created))
        selesai.append(sum(1 for cd in lunas_days if cd == d))
        pending.append(sum(1 for o in created if (o.status or "") in pending_set))
    by_status = []
    for name in ["DITERIMA", "ANALISA", "KONFIRMASI", "WAIT PART",
                 "REPAIR", "DONE", "CASH", "CANCEL", "FAILED"]:
        by_status.append({"name": name,
                          "value": db.query(ServiceOrder).filter(ServiceOrder.status == name).count()})
    return {
        "categories": categories,
        "series": [
            {"name": "Masuk", "data": masuk},
            {"name": "Selesai", "data": selesai},
            {"name": "Pending", "data": pending},
        ],
        "by_status": by_status,
    }


@router.get("/statistics/damage")
def get_damage_stats(db: Session = Depends(get_db_session)):
    """Tren kerusakan real: agregat damagetype 6 teratas (pengganti angka statis)."""
    counts: dict = {}
    for (dt,) in db.query(ServiceOrder.damagetype).all():
        name = (dt or "").strip()
        if not name:
            continue
        counts[name] = counts.get(name, 0) + 1
    top = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:6]
    return {
        "categories": [k for k, _ in top],
        "data": [v for _, v in top],
    }
