"""Dashboard endpoints - data untuk star cards & charts."""
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from dependencies import get_db_session
from finance import compute_finance_core
import cash
from money import HUNDRED, PCT_10, PCT_30, ZERO, quantize, to_decimal
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
        from authority import (ROLE_ADMIN, ROLE_PENGELOLA, ROLE_SUPERADMIN,
                          canonical_role)
        return canonical_role(user) in (ROLE_SUPERADMIN, ROLE_ADMIN, ROLE_PENGELOLA)
    except Exception:  # noqa: BLE001
        return False


def _refund_dp_by_order(db: Session) -> dict:
    """Total DP yang sudah dikembalikan ke customer, dikelompok per unit."""
    out = {}
    for r in db.query(Refund).all():
        if (getattr(r, "jenis", "") or "").strip().upper() == "DP":
            out[r.service_order_id] = out.get(r.service_order_id, ZERO) + to_decimal(r.nominal)
    return out


def _dp_terpakai(db: Session, o, rows, dp_order) -> Decimal:
    """DP yang benar-benar berubah jadi pembayaran transaksi untuk satu unit.

    HANYA sebesar kewajiban unit. Kalau DP-nya melebihi kewajiban, sisanya
    BUKAN terpakai -- itu uang customer yang masih wajib dikembalikan, jadi
    tetap menjadi titipan. Tanpa aturan ini, DP Rp1.000.000 pada unit dengan
    kewajiban Rp200.000 akan dianggap habis dan Rp800.000-nya hilang dari
    Laporan Titipan DP, padahal uangnya masih ada di laci.
    """
    if dp_order <= ZERO:
        return ZERO
    if payment_summary(o, rows)["payment_status"] != "LUNAS":
        return ZERO
    return min(dp_order, to_decimal(kewajiban(o)))


def _dp_ditahan(dp_order, terpakai, dikembalikan) -> Decimal:
    """Sisa DP unit yang masih dipegang untuk customer (dijepit di 0)."""
    sisa = dp_order - (terpakai or ZERO) - (dikembalikan or ZERO)
    return sisa if sisa > ZERO else ZERO


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

    Angka di atas adalah SEJARAB penuh dan tidak pernah dihapus — dipakai untuk
    rekonsiliasi dan audit. Yang ditampilkan ke Owner di panel "Laporan Titipan DP"
    adalah kunci `live`: hanya DP yang masih ditahan. Begitu tidak ada yang
    tertahan (semua LUNAS atau sudah dikembalikan), panel kosong — itulah
    "dikosongkan" tanpa menghapus data atau mengganggu saldo Laci.

    `berjalan` = DP yang **DITERIMA pada periode [start, end) tapi unitnya belum
    SETTLED**. DP milik unit yang sudah LUNAS TIDAK boleh ditambah lagi — saat
    pelunasan, nilainya sudah tercakup di Omzet (Omzet = kewajiban = total
    pembayaran), meski uang fisiknya tetap tercatat di Mutasi Kas sebagai baris
    DP dan baris pelunasan.
    """

    pays_by_order = {}
    for p in db.query(Payment).all():
        pays_by_order.setdefault(p.service_order_id, []).append(p)

    refund_by_order = _refund_dp_by_order(db)

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
        # HANYA sebesar kewajiban yang dianggap jadi pembayaran transaksi.
        # Kelebihannya tetap ditahan: uang customer yang belum wajib
        # dikembalikan (Owner) -- tidak boleh hilang dari Laporan Titipan DP.
        terpakai = _dp_terpakai(db, o, rows, dp_order)
        dipakai += terpakai
        if _dp_ditahan(dp_order, terpakai, refund_by_order.get(o.id)) > ZERO:
            berjalan += dp_periode

    dikembalikan = sum(refund_by_order.values())

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
        # Hanya DP yang MASIH DITAHAN. Owner: begitu tidak ada Saldo Titipan,
        # panel dikosongkan -- jadi Tutup Kas otomatis membersihkannya tanpa
        # menghapus satu baris pun dari `payments` / ledger kas.
        "live": mutasi_titipan_dp(db, pays_by_order, live_only=True),
    }


def mutasi_titipan_dp(db: Session, pays_by_order: dict = None, live_only: bool = False) -> list:
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

    `live_only=True` → hanya mutasi DP yang **MASIH DITAHAN** customer. Unit yang
    sudah LUNAS atau DP-nya sudah dikembalikan tidak muncul lagi, jadi begitu
    tidak ada titipan yang tertahan panel benar-benar kosong (Owner: "jika sudah
    tidak ada Saldo Titipan, sebaiknya data ini dikosongkan saja"). Angka riwayat
    sendiri TIDAK dihapus dari database — hanya tidak ditampilkan; uang DP yang
    sudah jadi pembayaran tetap tercatat penuh di `payments` dan ledger kas.
    """
    from statusflow import lunas_moment

    if pays_by_order is None:
        pays_by_order = {}
        for p in db.query(Payment).all():
            pays_by_order.setdefault(p.service_order_id, []).append(p)

    refund_by_order = _refund_dp_by_order(db)

    def masih_ditahan(o, rows, dp_order):
        """Sisa DP yang benar-benar masih dipegang untuk unit ini.

        Sudah LUNAS -> sisa 0 (semua DP-nya jadi pembayaran transaksi).
        Belum LUNAS -> dikurangi DP yang sudah dikembalikan ke customer.
        Overpaid    -> hanya sebesar kewajiban yang dianggap terpakai, jadi
                       kelebihan bayarnya tetap dipegang sampai dikembalikan.
        """
        return _dp_ditahan(dp_order, _dp_terpakai(db, o, rows, dp_order),
                           refund_by_order.get(o.id))

    items = []
    for o in db.query(ServiceOrder).all():
        rows = pays_by_order.get(o.id) or []
        dp_rows = [p for p in rows
                   if (getattr(p, "kind", "") or "").strip().upper() == "DP"]
        if not dp_rows:
            continue
        dp_order = sum(to_decimal(p.amount) for p in dp_rows)
        if live_only and masih_ditahan(o, rows, dp_order) <= ZERO:
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
        terpakai = _dp_terpakai(db, o, rows, dp_order)
        if terpakai <= ZERO:
            continue
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
            "keluar": terpakai,
        })

    for r in db.query(Refund).all():
        if (getattr(r, "jenis", "") or "").strip().upper() != "DP":
            continue
        o = getattr(r, "service_order", None)
        if live_only and o is not None:
            rows = pays_by_order.get(o.id) or []
            dp_rows = [p for p in rows
                       if (getattr(p, "kind", "") or "").strip().upper() == "DP"]
            dp_order = sum(to_decimal(p.amount) for p in dp_rows)
            if dp_order <= ZERO or masih_ditahan(o, rows, dp_order) <= ZERO:
                continue
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


def _kondisi_kas_akhir(kas_awal_operasional, omset, total_modal, total_beban,
                      alokasi_terbentuk, laba_bersih, alokasi) -> Decimal:
    """OD-LOCK-12: nilai akhir kolom Saldo di tabel "Kondisi Kas Operasional".

    Meniru PERSIS urutan baris tabelnya (lihat `renderKondisiKas` di
    `frontend/script.js`), supaya angka yang dilihat Admin = angka yang
    dicatat ke Hutang Beban:

        saldo = Kas Kecil/Laci (operasional, bebas DP)
              + Omzet
              - Total Modal (Part+Jasa+Lain)
              - Total Beban (Gaji & OPS)
              - Bagi Hasil 100%  <- HANYA kalau distribusi sudah TERBENTUK

    Baris "Kas Besar (Pengelola)" adalah baris POSISI: tidak ikut menambah
    saldo berjalan, jadi sengaja tidak dipakai di sini.

    PerGKAT: baris Bagi Hasil hanya digambar kalau `alokasi_terbentuk` DAN
    `laba_bersih > 0`. Kalau distribusi belum terbentuk, sedangkan 100% Laba
    Bersih tetap dipotong, tabel akan terlihat lebih minus daripada reality.
    """
    saldo = to_decimal(kas_awal_operasional)
    saldo += to_decimal(omset)
    saldo -= to_decimal(total_modal)
    saldo -= to_decimal(total_beban)
    laba = to_decimal(laba_bersih)
    if alokasi_terbentuk and laba > ZERO:
        for kunci in ("karyawan", "pengelola", "investor", "kas_aset"):
            saldo -= to_decimal((alokasi or {}).get(kunci) or 0)
    return quantize(saldo)


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
    beban_gaji = core["beban_gaji"]
    beban_ops = core["beban_operasional"]
    beban_lain = ZERO  # SSOT-4: kategori lain bukan Beban
    total_beban = core["total_beban"]

    # SSOT-5 / SSOT-1: Laba Kotor dan Laba Bersih TIDAK dihitung ulang di sini.
    # Satu-satunya tempat Hitungnya adalah `finance.compute_finance_core`
    # (finance.py), dengan rumus Owner:
    #     LABA KOTOR  = OMSET - TOTAL MODAL
    #     LABA BERSIH = LABA KOTOR - TOTAL BEBAN
    #
    # Versi sini pernah menambah `tambahan` (transaksi kas manual) ke Laba Kotor
    # lalu menghitung ulang Laba Bersih sendiri TANPA `tambahan` -- dua
    # penyimpangan dari rumus Owner sekaligus. Sekarang keduanya dibaca apa
    # adanya dari core, jadi mustahil lagi melenceng.
    #
    # `tambahan` tetap diambil hanya sebagai informasi (angka kas manual periode
    # berjalan); ia tidak masuk Omzet, Modal, Beban, maupun laba.
    _tambahan = to_decimal(core.get("tambahan", 0))
    laba_kotor = to_decimal(core["laba_kotor"])
    laba_bersih = to_decimal(core["laba_bersih"])

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
        # Wajib diinisialisasi: dipakai `_kondisi_kas_akhir` (OD-LOCK-12) di
        # bawah. Tanpa branch ini, distributor yang belum terbentuk membuat
        # UnboundLocalError saat halaman Keuangan dibuka.
        _al = {}
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
        # Dikecposure supaya rumus Laba Kotor dan Laba Bersih bisa diaudit dari
        # luar: Laba Kotor TIDAK memakainya, Laba Bersih memakainya.
        "tambahan": _tambahan,
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
        # OD-LOCK-12: nilai AKHIR tabel "Kondisi Kas Operasional" (kolom Saldo
        # baris paling bawah) — persis yang dibaca Admin di halaman Keuangan.
        # Dihitung di SATU tempat supaya angka di layar, angka yang offered ke
        # form input Hutang Beban, dan angka yang dicatat ke DB tidak mungkin
        # berbeda. `frontend/script.js:renderKondisiKas` memakai formula yang
        # sama dengan urutan baris tabelnya.
        "kondisi_kas_akhir": _kondisi_kas_akhir(
            kas_awal_operasional=max(ZERO, _kas_awal - _titipan["saldo"]),
            omset=omset, total_modal=total_modal, total_beban=total_beban,
            alokasi_terbentuk=alokasi_ok,
            laba_bersih=laba_bersih,
            alokasi=_al),
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
        # Berapa kali laba sudah dialokasikan di periode ini. 1 = baru terbentuk,
        # >1 = ada top-up karena laba naik lagi setelahnya. Ditampilkan oleh UI
        # supaya kenaikan angka terlihat wajar, bukan melompat tanpa sebab.
        "distribusi_jumlah_alokasi": _dist.jumlah_alokasi(db, _row_dist),
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
             "sub": "Omset LUNAS − modal (Part+Jasa+Lain)"},
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
