# -*- coding: utf-8 -*-
"""P2-15 (Owner Cash Model) — CASH sebagai event realisasi transaksi.

Aturan yang diuji (meniru Project A):
  1. DONE bukan terminal realization: LUNAS di DONE BELUM masuk Omzet/Laba.
  2. CASH hanya boleh dari DONE (transisi) dan hanya oleh Admin/Kasir.
  3. Event CASH = SATU transaksi: sisanya dilunasi via Payment Ledger, LUNAS
     terkunci pada waktu CASH, unit jadi DIAMBIL, laba dihitung, notifikasi
     Kas Masuk terbit. Kegagalan satu langkah membatalkan semuanya.
  4. Replay CASH idempoten: tidak ada payment / mutasi / notifikasi ganda.
  5. Garansi aktif mulai CASH; `warranty_months` boleh dikonfigurasi di DONE.
"""
from datetime import date, datetime, timedelta

from money import ZERO as ZERO_SAFE, to_decimal


def _order(db, no, harga, modal=(0, 0, 0), status="DONE", dp=0):
    import models
    cust = db.query(models.Customer).filter(
        models.Customer.name == "Pytest Customer").first()
    o = models.ServiceOrder(
        no_servis=no, customer_id=cust.id, device="PY", brand="PY", model="M1",
        status=status, service_date=date.today(),
        final_price=to_decimal(harga), estimate=to_decimal(harga),
        repair_plan="Ganti LCD", technician="Budi", warranty_months=1,
        part_cost=to_decimal(modal[0]), modal_jasa=to_decimal(modal[1]),
        modal_lainnya=to_decimal(modal[2]), payment=to_decimal(dp),
    )
    db.add(o)
    db.commit()
    db.refresh(o)
    return o


def _dp(db, order, nominal, kind="DP"):
    import models
    p = models.Payment(service_order_id=order.id, kind=kind,
                       amount=to_decimal(nominal), method="CASH", note="dp")
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _patch_cash(db, order):
    """Patches DB session agar catat_payment ikut flush (sama seperti API)."""
    return db


# ───────────────────────────── 1. gate realisasi ─────────────────────────────
def test_done_lunas_belum_masuk_omzet(client, db, auth):
    """DONE + LUNAS belum boleh masuk Omzet.

    Diuji lewat DELTA, bukan absolut: sandbox test disalin dari DB produksi
    yang bisa jadi sudah punya order CASH lain (data UAT), jadi angka Omzet
    total tidak boleh dijadikan 0. Yang diperiksa: order DONE ini sendiri
    tidak menambah Omzet.
    """
    import finance
    from models import KasPeriod
    now = datetime.now()
    start = now.replace(hour=16, minute=0, second=0, microsecond=0)
    if now < start:
        start -= timedelta(days=1)
    p = db.query(KasPeriod).filter(KasPeriod.status == "OPEN").first()
    if p is None:
        p = KasPeriod(start_at=start, end_at=start + timedelta(days=1), status="OPEN")
        db.add(p)
        db.commit()
    p.start_at, p.end_at = start, start + timedelta(days=1)
    db.commit()

    before = finance.compute_finance_core(db, p.start_at, p.end_at)["omset"]

    o = _order(db, "PY-CASH-DONE", 500000, modal=(200000, 50000, 0))
    _dp(db, o, 500000, kind="PELUNASAN")  # LUNAS, tapi belum CASH
    db.commit()

    after = finance.compute_finance_core(db, p.start_at, p.end_at)["omset"]
    assert after == before, "DONE + LUNAS belum boleh direalisasikan sebagai Omzet"
    assert o.status != "CASH"


def test_cash_masuk_omzet(client, db, auth):
    import finance
    from models import KasPeriod
    o = _order(db, "PY-OMZET-CASH2", 500000, modal=(200000, 50000, 0))
    _dp(db, o, 500000, kind="PELUNASAN")
    from statusflow import lock_lunas_moment
    lock_lunas_moment(o, datetime.now())
    o.status = "CASH"
    o.taken_at = datetime.now()
    db.commit()

    now = datetime.now()
    start = now.replace(hour=16, minute=0, second=0, microsecond=0)
    if now < start:
        start -= timedelta(days=1)
    p = db.query(KasPeriod).filter(KasPeriod.status == "OPEN").first()
    if p is None:
        p = KasPeriod(start_at=start, end_at=start + timedelta(days=1), status="OPEN")
        db.add(p)
        db.commit()
    p.start_at, p.end_at = start, start + timedelta(days=1)
    db.commit()

    core = finance.compute_finance_core(db, p.start_at, p.end_at)
    assert core["omset"] >= 500000, "CASH harus merealisasikan Omzet"
    assert core["total_modal"] >= 250000


# ────────────────────── 2. transisi & authority CASH ────────────────────────
def test_transisi_cash_hanya_dari_done(client, db, auth):
    r = client.post("/api/orders", headers=auth, json={
        "customer_id": db.query(__import__("models").Customer).first().id,
        "no_servis": "PY-CASH-TRANSISI", "device": "PY", "brand": "PY",
        "model": "M1", "damagetype": "LCD", "estimate": 0, "payment": 0,
        "laba_bersih": 0, "initial_path": "TITIP",
    })
    assert r.status_code in (200, 201), r.text
    oid = r.json()["id"]
    assert client.put("/api/orders/%d" % oid, headers=auth,
                        json={"status": "CASH", "status_note": "x"}).status_code == 400


def test_teknisi_tidak_boleh_cash(client, db):
    import models
    from database import SessionLocal
    s = SessionLocal()
    try:
        u = s.query(models.User).filter(models.User.username == "pytest_teknisi").first()
        if u is None:
            u = models.User(username="pytest_teknisi", display_name="Pytest Teknisi",
                            role="TEKNISI", passcode_hash="x", passcode_salt="y", active=True)
            s.add(u)
            s.commit()
            s.refresh(u)
        s.add(models.AuthToken(token="pytest-token-teknisi", user_id=u.id,
                               expires_at=datetime.now() + timedelta(days=2)))
        s.commit()
    finally:
        s.close()
    o = _order(db, "PY-CASH-TEK", 300000)
    tech = {"Authorization": "Bearer pytest-token-teknisi"}
    r = client.put("/api/orders/%d" % o.id, headers=tech, json={"status": "CASH"})
    assert r.status_code in (400, 403), r.text


# ────────────────────────── 3. event CASH atomik ─────────────────────────────
def test_event_cash_lengkap(client, db, auth):
    import models
    import notifications as notif_mod
    o = _order(db, "PY-CASH-EVENT", 800000, modal=(300000, 100000, 20000), dp=300000)
    dp_row = _dp(db, o, 300000, kind="DP")
    import cash as cash_mod
    # DP tunai = uang nyata di laci -> harus jadi mutasi Saldo Laci (bukan Omzet).
    # Dicatat manual di sini karena `_dp` hanya menulis baris Payment Ledger.
    cash_mod.catat_penerimaan(db, dp_row)
    db.commit()
    before_laci = _saldo_laci(db)

    # Catatan: event CASH bisa memicu DISTRIBUSI OTOMATIS kalau CTO tercapai
    # (keputusan Owner). Kalau itu terjadi, 100% laba periode keluar dari Laci
    # (70% cash-out + 30% Hak Kas Aset), jadi delta harus diperhitungkan supaya
    # test ini tetap menguji event CASH-nya saja.
    import distribution as dist_mod
    from routers.dashboard import get_active_period
    _p = get_active_period(db)
    _kunci = _p.start_at.date().isoformat()
    d_awal = dist_mod.sudah_ada(db, _kunci, _p.id)
    _id_awal = d_awal.id if d_awal is not None else None

    r = client.put("/api/orders/%d" % o.id, headers=auth, json={"status": "CASH"})
    assert r.status_code == 200, r.text
    db.expire_all()

    pays = db.query(models.Payment).filter(models.Payment.service_order_id == o.id).all()
    assert sum(to_decimal(p.amount) for p in pays) == to_decimal(800000)
    assert o.status == "CASH"
    assert o.unit_status == "DIAMBIL"
    assert o.taken_at is not None
    assert o.lunas_at is not None
    # Laba = Omzet - Modal3 (800rb - 300rb - 100rb - 20rb = 380rb)
    assert to_decimal(o.laba_bersih) == to_decimal(380000)
    # Saldo LACI pada event CASH = pelunasan sisa (500rb) - Modal3 (420rb).
    # Keputusan Owner: Modal keluar dari kas saat CASH, bukan saat DONE.
    # DP 300rb SUDAH masuk laci sejak diterima (dicatat sebelum `before_laci`).
    d_akhir = dist_mod.sudah_ada(db, _kunci, _p.id)
    tergakar = ZERO_SAFE
    if d_akhir is not None and d_akhir.id != _id_awal:
        # OD-LOCK-11.5: saat CASH yang keluar dari Laci HANYA 70% (cash_out).
        # 30% Hak Kas Aset masih di Laci sampai Tutup Kas, jadi tidak ikut
        # dihitung sebagai yang tergakar sekarang.
        tergakar = to_decimal(d_akhir.cash_out)

    assert _saldo_laci(db) - before_laci == to_decimal(500000 - 420000) - tergakar
    # DP punya tepat satu entri kas "Penerimaan Pembayaran" — tidak dobel.
    import cash as cash_mod
    dp_pay = db.query(models.Payment).filter(
        models.Payment.service_order_id == o.id,
        models.Payment.kind == "DP").first()
    assert db.query(models.KasEntry).filter(
        models.KasEntry.sumber == cash_mod.SUMBER_PAYMENT,
        models.KasEntry.ref_type == "payment",
        models.KasEntry.ref_id == dp_pay.id).count() == 1
    # Dan tidak ada sumber "DP_RELEASE" lagi — DP langsung jadi baris Masuk.
    assert not hasattr(cash_mod, "SUMBER_DP_RELEASE")
    # NOTIFIKASI Kas Masuk terbit (WA Selesai sudah di DONE)
    ev = db.query(models.Notification).filter(
        models.Notification.event == notif_mod.EVENT_KAS_MASUK,
        models.Notification.ref_code == str(o.id)).all()
    assert ev, "EVENT_KAS_MASUK harus terbit pada CASH"


def test_event_cash_gagal_tidak_meninggalkan_state_setengah(client, db, auth):
    """CASH tanpa Tindakan/Modal harus ditolak DAN tidak mengubah status/payment."""
    import models
    o = _order(db, "PY-CASH-GAGAL", 900000, modal=(0, 0, 0))
    o.repair_plan = ""
    o.technician = ""
    db.commit()
    n_pay_awal = db.query(models.Payment).filter(
        models.Payment.service_order_id == o.id).count()

    r = client.put("/api/orders/%d" % o.id, headers=auth, json={"status": "CASH"})
    assert r.status_code == 400, r.text
    db.expire_all()
    assert o.status == "DONE", "Status tidak boleh berubah saat CASH gagal"
    assert o.taken_at is None
    assert db.query(models.Payment).filter(
        models.Payment.service_order_id == o.id).count() == n_pay_awal


# ─────────────────────────── 4. replay CASH idempoten ────────────────────────
def test_replay_cash_idempoten(client, db, auth):
    import models
    o = _order(db, "PY-CASH-REPLAY", 400000, modal=(150000, 50000, 0))
    r1 = client.put("/api/orders/%d" % o.id, headers=auth, json={"status": "CASH"})
    assert r1.status_code == 200, r1.text
    db.expire_all()
    n1 = db.query(models.Payment).filter(models.Payment.service_order_id == o.id).count()
    laba1 = to_decimal(o.laba_bersih)
    taken1 = o.taken_at

    # Replay: CASH -> CASH (tanpa catatan harus ditolak; dengan catatan = koreksi)
    r2 = client.put("/api/orders/%d" % o.id, headers=auth, json={"status": "CASH"})
    assert r2.status_code == 400, "CASH terminal tidak boleh diulang tanpa catatan"
    db.expire_all()
    n2 = db.query(models.Payment).filter(models.Payment.service_order_id == o.id).count()
    assert n1 == n2, "Replay tidak boleh membuat payment ganda"
    assert to_decimal(o.laba_bersih) == laba1
    assert o.taken_at == taken1


# ─────────── 5. garansi: masuk halaman Garansi setelah TUTUP KAS ──────────────
def test_warranty_muncul_setelah_tutup_kas(client, db, auth):
    """Batas arsip = Tutup Kas.

    - Setelah CASH: `taken_at` terisi (mulai masa garansi), tapi unit BELUM
      muncul di halaman Garansi selama periode kasnya masih OPEN.
    - Setelah periode kas CLOSED: unit muncul di warranty-summary.

    Test ini sengaja memakai state periode sendiri: semua periode yang memuat
    `now` dipaksa OPEN dulu (fase "belum tampil"), lalu satu periode dipaksa
    CLOSED (fase "tampil"). Jadi tidak bergantung pada test lain yang sudah
    menutup periode lebih dulu.
    """
    import models
    from datetime import datetime, timedelta

    def _periodes_meliputi(momen):
        out = []
        for p in db.query(models.KasPeriod).all():
            if p.start_at <= momen < p.end_at:
                out.append(p)
        return out

    o = _order(db, "PY-CASH-GARANSI", 600000, modal=(100000, 50000, 0))
    _dp(db, o, 600000, kind="PELUNASAN")
    assert o.warranty_months == 1  # konfigurasi boleh di DONE
    assert o.taken_at is None      # garansi belum aktif

    assert client.put("/api/orders/%d" % o.id, headers=auth,
                        json={"status": "CASH"}).status_code == 200
    db.expire_all()
    assert o.taken_at is not None, "taken_at = mulai garansi"

    # --- fase 1: periode memuat settlement dipaksa OPEN -> belum tampil ---
    momen = o.lunas_at
    for p in _periodes_meliputi(momen):
        p.status = "OPEN"
    db.commit()
    r = client.get("/api/claims/warranty-summary", headers=auth)
    assert r.status_code == 200, r.text
    ids_open = [it["service_order_id"] for it in r.json().get("items", [])]
    assert o.id not in ids_open, "CASH di periode OPEN belum boleh masuk Garansi"

    # --- fase 2: periode ditutup -> baru boleh tampil ---
    menutup = _periodes_meliputi(momen)
    if not menutup:
        start = momen.replace(hour=16, minute=0, second=0, microsecond=0)
        if momen < start:
            start -= timedelta(days=1)
        menutup = [models.KasPeriod(start_at=start,
                                    end_at=start + timedelta(days=1),
                                    status="OPEN")]
        db.add(menutup[0])
    for p in menutup:
        p.status = "CLOSED"
        p.closed_at = datetime.now()
    db.commit()

    r2 = client.get("/api/claims/warranty-summary", headers=auth)
    assert r2.status_code == 200, r2.text
    ids_closed = [it["service_order_id"] for it in r2.json().get("items", [])]
    assert o.id in ids_closed, "Setelah periode CLOSED unit harus muncul di Garansi"


def test_transaksi_tampil_status_cash(client, db, auth):
    """CASH di periode yang MASIH OPEN tetap tampil di halaman Transaksi.

   _ATURAN_: batas arsip adalah Tutup Kas, bukan status CASH. Order CASH baru
    disembunyikan setelah periodenya DITUTUP. Test lama pernah asserting
    bahwa semua CASH selalu tampil -- itu sudah tidak sesuai aturan Owner.
    """
    from datetime import datetime, timedelta
    import models

    # Periode deterministik: satu CLOSED di masa lalu + satu OPEN yang mencakup
    # "sekarang", supaya test ini tidak bergantung pada periode sisa test lain.
    db.query(models.KasPeriod).delete(synchronize_session=False)
    db.commit()
    db.add(models.KasPeriod(start_at=datetime(2000, 1, 1, 16), end_at=datetime(2000, 1, 2, 16),
                            status="CLOSED", created_at=datetime(2000, 1, 1, 8)))
    db.add(models.KasPeriod(start_at=datetime.now() - timedelta(days=1),
                            end_at=datetime.now() + timedelta(days=365),
                            status="OPEN", created_at=datetime.now() - timedelta(days=1)))
    db.commit()
    db.expunge_all()

    # (1) CASH di periode OPEN -> harus tampil.
    o = _order(db, "PY-CASH-OPEN", 300000, modal=(100000, 20000, 0))
    _dp(db, o, 300000, kind="PELUNASAN")
    assert client.put("/api/orders/%d" % o.id, headers=auth,
                      json={"status": "CASH"}).status_code == 200
    db.expire_all()
    assert o.status == "CASH" and o.unit_status == "DIAMBIL"

    res = client.get("/api/orders?page=1&limit=100", headers=auth)
    assert res.status_code == 200, res.text
    ids = [it["id"] for it in res.json()["items"]]
    assert o.id in ids, "Order CASH di periode OPEN harus tampil"

    latest = client.get("/api/orders/latest?limit=100", headers=auth)
    assert latest.status_code == 200, latest.text
    assert o.id in [it["id"] for it in latest.json()]

    # (2) CASH yang periodenya sudah DITUTUP -> tidak boleh tampil lagi.
    o2 = _order(db, "PY-CASH-ARSIP", 300000, modal=(100000, 20000, 0))
    _dp(db, o2, 300000, kind="PELUNASAN")
    assert client.put("/api/orders/%d" % o2.id, headers=auth,
                      json={"status": "CASH"}).status_code == 200
    db.expire_all()
    # Mundurkan momen terminalnya ke dalam periode CLOSED.
    db.query(models.ServiceOrder).filter(models.ServiceOrder.id == o2.id).update(
        {"lunas_at": datetime(2000, 1, 1, 20)})
    db.commit()
    db.expire_all()

    res2 = client.get("/api/orders?page=1&limit=100", headers=auth)
    ids2 = [it["id"] for it in res2.json()["items"]]
    assert o2.id not in ids2, "Order CASH periode CLOSED harus diarsipkan"
    assert o.id in ids2, "Order CASH periode OPEN tidak boleh ikut hilang"
    assert o2.id not in [it["id"] for it in
                         client.get("/api/orders/latest?limit=100", headers=auth).json()]

    # (3) Order yang BELUM final tetap tampil walau dibuat sebelum periode ditutup.
    o3 = _order(db, "PY-MASIH-DONE", 300000, modal=(100000, 20000, 0), status="DONE")
    db.commit()
    ids3 = [it["id"] for it in
            client.get("/api/orders?page=1&limit=100", headers=auth).json()["items"]]
    assert o3.id in ids3, "Order DONE belum final harus tetap tampil"

    # (4) FAILED TIDAK ikut diarsipkan, walaupun periodenya sudah ditutup.
    #     Alasannya bisnis: unitnya masih ada di toko -- belumTakenOut oleh
    #     pelanggan dan pekerjaannya belum selesai, jadi masih harus kelihatan
    #     dan bisa ditindaklanjuti (reparasi ulang / ambil unit / batalkan).
    o4 = _order(db, "PY-FAILED-DITOKO", 300000, modal=(100000, 20000, 0))
    db.query(models.ServiceOrder).filter(models.ServiceOrder.id == o4.id).update(
        {"status": "FAILED", "unit_status": "DI TOKO",
         "lunas_at": datetime(2000, 1, 1, 20)})   # di dalam periode CLOSED
    db.commit()
    db.expire_all()
    ids4 = [it["id"] for it in
            client.get("/api/orders?page=1&limit=100", headers=auth).json()["items"]]
    assert o4.id in ids4, "Order FAILED (unit masih di toko) harus tetap tampil"

    # (5) Alur nyata: DITERIMA -> ... -> FAILED (reparasi/part gagal), lalu
    #     pelanggan ambil unit -> user ubah ke CANCEL.
    #     Momen yang dipakai filter adalah SAAT masuk CANCEL, bukan saat FAILED
    #     (yang lebih lama). Kalau momen terminalnya salah pilih, order ini akan
    #     tetap nongol meski periodenya sudah ditutup.
    o5 = _order(db, "PY-FAILED-LALU-CANCEL", 300000, modal=(100000, 20000, 0))
    db.query(models.ServiceOrder).filter(models.ServiceOrder.id == o5.id).update(
        {"status": "FAILED", "unit_status": "DI TOKO",
         "lunas_at": datetime(2000, 1, 1, 20)})       # GAGAL saat periode CLOSED
    db.commit()
    db.add(models.StatusHistory(service_order_id=o5.id, dari_status="FAILED",
                                ke_status="CANCEL", oleh="pytest",
                                waktu=datetime.now(), catatan="Unit diambil pelanggan"))
    db.commit()
    oid5 = o5.id
    db.expunge_all()
    ids5 = [it["id"] for it in
            client.get("/api/orders?page=1&limit=100", headers=auth).json()["items"]]
    assert oid5 in ids5, "Masih FAILED -- harus tampil karena unitnya belum diambil"

    # Saatnya diubah ke CANCEL -> harus diarsipkan.
    assert client.put("/api/orders/%d" % oid5, headers=auth, json={
        "status": "CANCEL", "status_note": "Unit diambil pelanggan"}).status_code == 200
    db.expire_all()
    ids6 = [it["id"] for it in
            client.get("/api/orders?page=1&limit=100", headers=auth).json()["items"]]
    assert oid5 not in ids6, "Order CANCEL (unit sudah diambil) harus diarsipkan"

    # Order ID-nya masih bisa dibuka -- disembunyikan, bukan dihapus.
    det = client.get("/api/orders/%d" % oid5, headers=auth)
    assert det.status_code == 200 and det.json()["status"] == "CANCEL"


def _saldo_laci(db):
    """Saldo Laci terkini (Cash Model v4 #1: penerimaan masuk Laci)."""
    import cash
    return to_decimal(cash.saldo_laci(db))
