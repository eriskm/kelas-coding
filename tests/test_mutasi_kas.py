# -*- coding: utf-8 -*-
"""Mutasi Kas (Rincian Arus Kas) — 10 skenario wajib hasil audit.

Test ini mengunci apa yang SEHARUSNYA terjadi pada Mutasi Kas, Laci, dan
Hutang Beban. Semua lewat jalur API/public yang sama dengan aplikasi.

Skenario:
  1. DP tunai menambah saldo kas TAPI tidak menambah omzet/laba.
  2. Pelunasan setelah DP tidak menggandakan penerimaan uang (DP + sisa = kewajiban).
  3. Modal dan beban mengurangi kas tepat satu kali.
  4. Defisit (laba kotor 200rb vs beban 605rb) menambah Hutang Beban.
  5. Hutang Beban terakumulasi antar periode kalau belum dibayar.
  6. Pembayaran Hutang Beban mengurangi kewajiban tepat satu kali.
  7. Tutup Kas + REKONSILIASI tidak menghasilkan selisih ganda.
  8. Saldo awal / berjalan / akhir konsisten satu sama lain.
  9. Transfer Laci <-> Aset tidak menggandakan uang & Master Kas tetap.
 10. Tidak ada regresi pada omzet, laba, distribusi, garansi, periode historis.

Catatan: sandbox test = SALINAN DB produksi (lihat conftest), jadi hampir
semua pemeriksaan memakai DELTA, bukan angka absolut.
"""
from datetime import datetime, timedelta

from money import ZERO, to_decimal


# ─────────────────────────── helper ───────────────────────────
def _user(db, username, role):
    import models
    u = db.query(models.User).filter(models.User.username == username).first()
    if u is None:
        u = models.User(username=username, display_name=username, role=role,
                        passcode_hash="x", passcode_salt="y", active=True)
        db.add(u)
        db.commit()
        db.refresh(u)
    return u


def _token(db, username, role):
    import models
    _user(db, username, role)
    u = db.query(models.User).filter(models.User.username == username).first()
    tok = "pytest-token-" + username
    t = db.query(models.AuthToken).filter(models.AuthToken.token == tok).first()
    if t is None:
        t = models.AuthToken(token=tok, user_id=u.id,
                             expires_at=datetime.now() + timedelta(days=2))
        db.add(t)
        db.commit()
    return {"Authorization": "Bearer " + tok}


def _cust(db):
    import models
    c = db.query(models.Customer).filter(
        models.Customer.name == "Pytest Customer").first()
    if c is None:
        c = models.Customer(name="Pytest Customer", phone="080000000001",
                            created_at=datetime.now())
        db.add(c)
        db.commit()
        db.refresh(c)
    return c


def _order(db, no, status="DONE", harga=500000, modal=(0, 0, 0)):
    import models
    c = _cust(db)
    o = models.ServiceOrder(
        no_servis=no, customer_id=c.id, device="PY", status=status,
        service_date=datetime.now().date(), final_price=to_decimal(harga),
        estimate=to_decimal(harga), repair_plan="x", technician="Budi",
        warranty_months=1, created_at=datetime.now(),
        part_cost=to_decimal(modal[0]), modal_jasa=to_decimal(modal[1]),
        modal_lainnya=to_decimal(modal[2]))
    db.add(o)
    db.commit()
    db.refresh(o)
    return o


def _saldo_laci(db):
    import cash
    return to_decimal(cash.saldo_laci(db))


def _api_mutasi(client, auth, page=1, limit=100):
    r = client.get("/api/kas/riwayat?period=current&page=%d&limit=%d"
                   % (page, limit), headers=auth)
    assert r.status_code == 200, r.text
    return r.json()


def _n_entry(db, sumber=None, ref_type=None, ref_id=None):
    """Hitung baris kas_entries layer LACI dengan kriteria tertentu."""
    import cash
    M = cash._entry_model()
    q = db.query(M).filter(M.layer == cash.LAYER_LACI)
    if sumber is not None:
        q = q.filter(M.sumber == sumber)
    if ref_type is not None:
        q = q.filter(M.ref_type == ref_type)
    if ref_id is not None:
        q = q.filter(M.ref_id == ref_id)
    return q.count()


def _cp(client, db, method, url, headers=None, **kw):
    """Panggil endpoint lalu commit session `db`.

    Session `db` dan session milik TestClient itu BERBEDA. Setelah `db` melakukan
    query, transaksinya masih terbuka dan SQLite akan menolak write dari session
    lain ("database is locked"). Commit di sini melepas read-lock itu.
    """
    db.commit()
    fn = client.get if method == "get" else (
        client.post if method == "post" else client.put)
    return fn(url, headers=headers, **kw)


def _isolated_db():
    """Session ke SQLite BARU yang hanya berisi tabel kosong.

    Dipakai skenario yang angkanya harus PERSIS (mis. defisit 405.000) atau yang
    mengubah state global (rekonsiliasi, transfer, hutang). Sandbox utama
    dipakai BERSAMA dengan file test lain, jadi menulis ke sana bisa merusak
    test yang lain — skenario stateful harus jalan di sini.
    """
    import os
    import tempfile

    from database import Base
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    folder = tempfile.mkdtemp(prefix="mutasi_iso_")
    eng = create_engine("sqlite:///%s" % os.path.join(folder, "iso.db"))
    Base.metadata.create_all(bind=eng)
    return sessionmaker(bind=eng)()


def _iso_beban(s, saat, daftar):
    """Buat beban + catat_beban (ledger & tabel expense selalu sinkron)."""
    import cash
    import models
    out = []
    for nama, kat, nilai in daftar:
        e = models.Expense(kategori=kat, uraian=nama, nilai=to_decimal(nilai),
                           created_at=saat)
        s.add(e)
        s.flush()
        cash.catat_beban(s, e)
        out.append(e)
    return out


def _iso_order(s, no, saat, harga=1000000, modal=(0, 0, 0), status="CASH"):
    import models
    c = s.query(models.Customer).filter(
        models.Customer.name == "ISO").first()
    if c is None:
        c = models.Customer(name="ISO", phone="0800", created_at=saat)
        s.add(c)
        s.flush()
    o = models.ServiceOrder(
        no_servis=no, customer_id=c.id, device="PY", status=status,
        unit_status="DIAMBIL", service_date=saat.date(), taken_at=saat,
        final_price=to_decimal(harga), estimate=to_decimal(harga),
        repair_plan="x", technician="Budi", warranty_months=1, created_at=saat,
        part_cost=to_decimal(modal[0]), modal_jasa=to_decimal(modal[1]),
        modal_lainnya=to_decimal(modal[2]))
    s.add(o)
    s.flush()
    return o


def models_payment(s, order_id, kind, amount, saat):
    """Baris Payment Ledger (dipakai test terisolasi)."""
    import models
    p = models.Payment(service_order_id=order_id, kind=kind,
                       amount=to_decimal(amount), method="CASH",
                       note="iso", created_at=saat)
    s.add(p)
    s.flush()
    return p


def _id_entri_tertinggi(db):
    """Id entri kas terakhir -- penanda 'mulai dari sini' saat menghitung delta."""
    import cash
    M = cash._entry_model()
    return db.query(M.id).order_by(M.id.desc()).first()[0] or 0


def _pengaruh_distribusi_laci(db, id_entri_awal):
    """_total uang Laci yang keluar karena distribusi sejak `id_entri_awal`.

    Top-up Distribusi membuat_order_ yang menambah laba bisa MEMGERAKKAN uang
    distribusi dari periode yang Distribution-nya sudah formed. Jadi assertion
    "delta Laci == masuk - keluar unit ini" harus memperhitungkan itu; kalau
    tidak, test ini mengukur efek samping fitur, bukan perilaku unit.
    """
    import cash
    M = cash._entry_model()
    total = ZERO
    for k in db.query(M).filter(
            M.id > id_entri_awal,
            M.sumber.in_([cash.SUMBER_CASH_OUT, cash.SUMBER_DISTRIBUSI_ASET])).all():
        if (k.layer or "") != cash.LAYER_LACI:
            continue
        if (k.jenis or "").lower() == "keluar":
            total += to_decimal(k.nominal)
    return total


# ─────────── 1. DP tunai: kas naik, omzet/laba tidak ───────────
def test_1_dp_tunai_meningkatkan_kas_tanpa_omzet(client, db):
    """DP 250rb harus jadi uang masuk di Mutasi Kas, TAPI Omzet tetap 0."""
    import cash
    import routers.dashboard as dash
    from routers.dashboard import batas_periode, get_active_period

    adm = _token(db, "pytest_admin", "ADMIN")
    p = get_active_period(db)
    o = _order(db, "PY-S1-DP", "REPAIR", harga=500000)

    laci_awal = _saldo_laci(db)
    omzet_awal = to_decimal(dash.compute_finance(db, *batas_periode(p))["omset"])
    laba_awal = to_decimal(dash.compute_finance(db, *batas_periode(p))["laba_bersih"])

    r = _cp(client, db, "post", "/api/payments", headers=adm,
             json={"service_order_id": o.id, "kind": "DP",
                   "amount": 250000, "method": "CASH"})
    assert r.status_code in (200, 201), r.text
    db.expire_all()

    # (a) Kas naik sebesar DP.
    assert _saldo_laci(db) - laci_awal == to_decimal(250000), \
        "DP tunai harus menambah Saldo Laci sebesar nominalnya"

    # (b) Ada baris DP di Mutasi Kas dengan label uang titipan.
    data = _api_mutasi(client, adm)
    baris_dp = [x for x in data["items"]
                if x["source"] == "dp" and x["nominal"] == 250000]
    assert baris_dp, "DP harus muncul sebagai baris Masuk di Mutasi Kas"
    assert "Titipan" in (baris_dp[0]["kategori"] or ""), \
        "Baris DP harus berlabel jelas sebagai uang titipan (bukan Omzet)"
    assert baris_dp[0]["jenis"] == "Masuk"

    # (c) DP punya tepat satu entri kas (tidak dobel).
    import models
    pay_id = db.query(models.Payment).filter(
        models.Payment.service_order_id == o.id).first().id
    assert _n_entry(db, cash.SUMBER_PAYMENT, "payment", pay_id) == 1

    # (d) Omzet & laba TIDAK bergerak (dibanding DELTA — sandbox berisi data lain).
    fin = dash.compute_finance(db, *batas_periode(p))
    assert to_decimal(fin["omset"]) == omzet_awal, \
        "DP belum LUNAS -> Omzet tidak boleh naik"
    assert to_decimal(fin["laba_bersih"]) == laba_awal, \
        "DP tidak boleh mengubah Laba Bersih"


# ─────────── 2. Pelunasan setelah DP tidak menggandakan ───────────
def test_2_pelunasan_setelah_dp_tidak_menggandakan(client, db):
    """DP 200rb + pelunasan sisa 300rb = kewajiban 500rb, TANPA dobel."""
    import cash
    import models
    from statusflow import kewajiban

    adm = _token(db, "pytest_admin", "ADMIN")
    o = _order(db, "PY-S2-DP-PELUNAS", "DONE", harga=500000,
               modal=(200000, 100000, 0))

    laci_awal = _saldo_laci(db)
    id_entri_awal = _id_entri_tertinggi(db)
    r = _cp(client, db, "post", "/api/payments", headers=adm,
            json={"service_order_id": o.id, "kind": "DP",
                  "amount": 200000, "method": "CASH"})
    assert r.status_code in (200, 201), r.text
    db.expire_all()
    # DP masuk penuh; kalau ada distribusi ikut terbentuk, pengaruhnya
    # ditambahkan ke sisi ekspektasi (lihat _pengaruh_distribusi_laci).
    assert (_saldo_laci(db) - laci_awal
            == to_decimal(200000) - _pengaruh_distribusi_laci(db, id_entri_awal))

    rc = _cp(client, db, "put", "/api/orders/%d" % o.id, headers=adm,
             json={"status": "CASH"})
    assert rc.status_code == 200, rc.text
    db.expire_all()

    # Masuk kas untuk unit ini harus PERSIS sebesar kewajiban: DP 200rb + sisa
    # 300rb. Modal 300rb juga keluar saat CASH, jadi delta bersihnya lebih kecil.
    masuk = _saldo_awal_pakai(db, o.id, "Masuk")
    keluar = _saldo_awal_pakai(db, o.id, "Keluar")
    assert masuk == to_decimal(kewajiban(o)), \
        "Uang masuk unit = DP 200rb + pelunasan sisa 300rb = 500rb"
    assert keluar == to_decimal(300000), "Modal keluar 300rb saat CASH"
    # DELTA BERSIH unit ini tetap masuk - keluar._distribusi (kalau terjadi)
    # dikurangi supaya tidak ikut terhitung sebagai milik unit ini.
    assert (_saldo_laci(db) - laci_awal
            == masuk - keluar - _pengaruh_distribusi_laci(db, id_entri_awal))

    # Baris pelunasan hanya SEKALI meski event CASH diulang.
    pelunasan = db.query(models.Payment).filter(
        models.Payment.service_order_id == o.id,
        models.Payment.kind == "PELUNASAN").first()
    assert pelunasan is not None
    n_pay = _n_entry(db, cash.SUMBER_PAYMENT, "payment", pelunasan.id)
    assert n_pay == 1
    _cp(client, db, "put", "/api/orders/%d" % o.id, headers=adm,
        json={"status": "CASH", "status_note": "replay"})
    db.expire_all()
    assert _n_entry(db, cash.SUMBER_PAYMENT, "payment", pelunasan.id) == n_pay, \
        "Replay CASH tidak boleh menambah baris pelunasan"
    assert (_saldo_laci(db) - laci_awal
            == masuk - keluar - _pengaruh_distribusi_laci(db, id_entri_awal)), \
        "Replay tidak boleh mengubah saldo lagi"


def _saldo_awal_pakai(db, order_id, jenis):
    """Total nominal entri kas LACI milik satu unit pada jenis tertentu."""
    import cash
    from models import Payment
    M = cash._entry_model()
    pay_ids = [p.id for p in db.query(Payment).filter(
        Payment.service_order_id == order_id).all()]
    total = ZERO
    # Sumber PAYMENT: pakai id payment.
    for k in db.query(M).filter(M.layer == cash.LAYER_LACI,
                                M.sumber == cash.SUMBER_PAYMENT,
                                M.ref_type == "payment",
                                M.ref_id.in_(pay_ids)).all():
        if (k.jenis or "").lower() == jenis.lower():
            total += to_decimal(k.nominal)
    # Sumber MODAL: ref_type = komponen, ref_id = order id.
    for k in db.query(M).filter(M.layer == cash.LAYER_LACI,
                                M.sumber == cash.SUMBER_MODAL,
                                M.ref_id == order_id).all():
        if (k.jenis or "").lower() == jenis.lower():
            total += to_decimal(k.nominal)
    return total


# ─────────── 3. Modal & beban mengurangi kas tepat 1x ───────────
def test_3_modal_dan_beban_kurangi_kas_satu_kali(client, db):
    """Modal part/jasa + beban: satu entri per kejadian, replay aman."""
    import cash
    import models

    adm = _token(db, "pytest_admin", "ADMIN")
    laci_awal = _saldo_laci(db)
    n_modal_awal = _n_entry(db, cash.SUMBER_MODAL)
    id_entri_awal = _id_entri_tertinggi(db)

    o = _order(db, "PY-S3-MODAL", "DONE", harga=800000,
               modal=(300000, 100000, 20000))
    rc = _cp(client, db, "put", "/api/orders/%d" % o.id, headers=adm,
             json={"status": "CASH"})
    assert rc.status_code == 200, rc.text
    db.expire_all()

    # CASH juga menulis pelunasan sebesar sisa (kewajiban penuh, tanpa DP),
    # jadi delta kas = masuk kewajiban - modal. Pengaruh distribusi (kalau
    # terpicu) dikurangi agar assertion tetap mengukur unit ini saja.
    dist = _pengaruh_distribusi_laci(db, id_entri_awal)
    delta = _saldo_laci(db) - laci_awal
    assert delta == to_decimal(800000) - to_decimal(420000) - dist, \
        "Kas masuk pelunasan 800rb, keluar modal 420rb"

    assert _n_entry(db, cash.SUMBER_MODAL) - n_modal_awal == 3, \
        "Modal Part/Jasa/Lain = tepat 3 entri baru"

    # Replay tidak menambah apa pun.
    _cp(client, db, "put", "/api/orders/%d" % o.id, headers=adm,
        json={"status": "CASH", "status_note": "replay"})
    db.expire_all()
    assert _n_entry(db, cash.SUMBER_MODAL) - n_modal_awal == 3
    assert (_saldo_laci(db) - laci_awal
            == delta - (_pengaruh_distribusi_laci(db, id_entri_awal) - dist))

    # Beban: 1 entri per baris expense, panggilan kedua idempoten.
    e = models.Expense(kategori="Gaji", uraian="S3 gaji",
                       nilai=to_decimal(150000), created_at=datetime.now())
    db.add(e)
    db.commit()
    db.refresh(e)
    n_beban_awal = _n_entry(db, cash.SUMBER_BEBAN)
    cash.catat_beban(db, e)
    db.commit()
    db.expire_all()
    assert _n_entry(db, cash.SUMBER_BEBAN) == n_beban_awal + 1

    cash.catat_beban(db, e)          # panggil lagi = harus idempoten
    db.commit()
    db.expire_all()
    assert _n_entry(db, cash.SUMBER_BEBAN) == n_beban_awal + 1, \
        "Beban yang sama tidak boleh dicatat dua kali"


# ─────────── 4. Defisit beban -> Hutang Beban ───────────
def test_4_defisit_beban_menambah_hutang(client, db):
    """Laba kotor 200rb vs beban 605rb -> defisit 405rb jadi Hutang Beban.

    Angka di sini WAJIB absolut (605.000 - 200.000 = 405.000), jadi skenarionya
    dibangun di DB SQLite kosong yang terisolasi — bukan di sandbox yang disalin
    dari DB produksi (yang `compute_finance_core`-nya bersifat agregat).
    """
    import cash
    import expense_debt as debt_mod
    import models
    from money import ZERO as MONEY_ZERO

    s = _isolated_db()
    mulai = datetime(2026, 3, 1)
    akhir = datetime(2026, 3, 31)

    c = models.Customer(name="S4", phone="0800", created_at=mulai)
    s.add(c)
    s.flush()
    o = models.ServiceOrder(
        no_servis="S4-DEFISIT", customer_id=c.id, device="PY", status="CASH",
        unit_status="DIAMBIL", service_date=mulai.date(),
        # Kohort Omzet = status CASH + `cash_moment()` (taken_at) di periode.
        taken_at=mulai,
        final_price=to_decimal(1000000), estimate=to_decimal(1000000),
        repair_plan="x", technician="Budi", warranty_months=1,
        created_at=mulai,
        part_cost=to_decimal(500000), modal_jasa=to_decimal(300000),
        modal_lainnya=to_decimal(0))
    s.add(o)
    s.flush()
    # ATURAN OWNER (FIN-MIRROR-6): Omzet hanya dari transaksi yang SUDAH LUNAS.
    # Order di atas sengaja belum punya baris pelunasan; tanpa baris di bawah
    # Omzet-nya nol dan angka defisit test ini berubah.
    s.add(models.Payment(service_order_id=o.id, kind="PELUNASAN",
                         amount=to_decimal(1000000), method="CASH",
                         note="lunas", created_at=mulai))
    s.flush()
    # Beban dibuat lewat jalur aplikasi: expense + catat_beban (ledger sinkron).
    for nama, kat, nilai in (("Gaji A", "Gaji", 200000),
                             ("Gaji B", "Gaji", 200000),
                             ("Sewa", "Operasional", 170000),
                             ("Pulsa", "Operasional", 5000),
                             ("Listrik", "Operasional", 14000),
                             ("Internet", "Operasional", 16000)):
        e = models.Expense(kategori=kat, uraian=nama, nilai=to_decimal(nilai),
                           created_at=mulai)
        s.add(e)
        s.flush()
        cash.catat_beban(s, e)
    s.commit()

    hit = debt_mod.hitung_defisit(s, mulai, akhir)
    laba_kotor = to_decimal(hit["omset"]) - to_decimal(hit["total_modal"])
    beban = to_decimal(hit["beban"])
    defisit = to_decimal(hit["defisit"])

    # Angka yang diminta skenario.
    assert to_decimal(hit["omset"]) == to_decimal(1000000), "Omzet = 1.000.000"
    assert to_decimal(hit["total_modal"]) == to_decimal(800000), \
        "Modal Part 500rb + Jasa 300rb = 800.000"
    assert laba_kotor == to_decimal(200000), \
        "Laba kotor = 1.000.000 - 800.000 = 200.000"
    assert beban == to_decimal(605000), "Beban periode = 605.000"
    assert defisit == to_decimal(405000), \
        "Defisit = 605.000 - 200.000 = 405.000"

    # Saldo Kas Aset = 0 -> tidak ada yang bisa menutup defisit -> penuh jadi hutang.
    assert to_decimal(cash.saldo_kas_aset(s)) == MONEY_ZERO

    hutang_awal = to_decimal(debt_mod.saldo_hutang(s))
    laci_awal = to_decimal(cash.saldo_laci(s))
    res = debt_mod.proses_defisit(s, mulai, akhir, kas_period_id=None,
                                  oleh="pytest")
    s.commit()
    s.expire_all()

    assert to_decimal(debt_mod.saldo_hutang(s)) - hutang_awal == to_decimal(405000), \
        "Defisit 405.000 harus ditambah ke Hutang Beban (bukan dibayar)"
    assert to_decimal(cash.saldo_laci(s)) == laci_awal, \
        "Pembentukan Hutang Beban tidak boleh mengurangi Saldo Laci"
    assert to_decimal(res["periode_row"].hutang_baru) == to_decimal(405000)
    assert to_decimal(res["periode_row"].hutang_akhir) == hutang_awal + to_decimal(405000)
    assert to_decimal(res["periode_row"].defisit) == to_decimal(405000)

    # Idempoten per periode.
    debt_mod.proses_defisit(s, mulai, akhir, kas_period_id=None, oleh="pytest")
    s.commit()
    s.expire_all()
    assert to_decimal(debt_mod.saldo_hutang(s)) - hutang_awal == to_decimal(405000)
    s.close()



# ─────────── 5. Hutang Beban terakumulasi antar periode ───────────
def test_5_hutang_beban_terakumulasi(client, db):
    """Belum dibayar -> saldo hutang bertambah, tidak ter-reset tiap periode."""
    import expense_debt as debt_mod
    from models import ExpenseDebtEntry

    s = _isolated_db()          # stateful -> DB terisolasi, tidak pollute sandbox
    hutang_awal = to_decimal(debt_mod.saldo_hutang(s))
    s.add(ExpenseDebtEntry(tipe="HUTANG", nominal=to_decimal(300000),
                           saldo_setelah=to_decimal(0), periode="2026-01-01"))
    s.commit()
    s.expire_all()
    assert to_decimal(debt_mod.saldo_hutang(s)) - hutang_awal == to_decimal(300000)

    # Periode berikutnya menambah lagi; carry forward tidak dihapus.
    s.add(ExpenseDebtEntry(tipe="HUTANG", nominal=to_decimal(150000),
                           saldo_setelah=to_decimal(0), periode="2026-01-02"))
    s.commit()
    s.expire_all()
    assert to_decimal(debt_mod.saldo_hutang(s)) - hutang_awal == to_decimal(450000), \
        "Hutang Beban periode lama harus terbawa (akumulatif)"
    s.close()


# ─────────── 6. Pelunasan hutang mengurangi kewajiban 1x ───────────
def test_6_pelunasan_hutang_beban_satu_kali(client, db):
    """Pelunasan hutang: kewajiban turun TEPAT SEKALI.

    v4 #8: sumber dana = SALDO ASET BESAR dan pengeluaran aktual dicatat MANUAL
    oleh Admin. Jadi proses pelunasan hanya mengurangi kewajiban; uangnya baru
    keluar saat Admin mencatat mutasi Kas Aset.
    """
    import cash
    import expense_debt as debt_mod
    from models import ExpenseDebtEntry

    s = _isolated_db()          # stateful -> DB terisolasi
    s.add(ExpenseDebtEntry(tipe="HUTANG", nominal=to_decimal(300000),
                           saldo_setelah=to_decimal(0), periode="2026-01-01"))
    s.add(ExpenseDebtEntry(tipe="HUTANG", nominal=to_decimal(200000),
                           saldo_setelah=to_decimal(0), periode="2026-01-03"))
    s.commit()
    s.expire_all()

    hutang_awal = to_decimal(debt_mod.saldo_hutang(s))
    assert hutang_awal == to_decimal(500000)
    laci_awal = to_decimal(cash.saldo_laci(s))
    aset_awal = to_decimal(cash.saldo_kas_aset(s))
    # Beri saldo Aset supaya pelunasan boleh jalan (sumber dana = Kas Aset).
    cash.catat_injeksi(s, cash.LAYER_ASET, to_decimal(800000), "modal awal")
    s.commit()
    s.expire_all()

    res = debt_mod.lunas_hutang(s, nominal=None, periode="2026-01-03",
                                oleh="pytest")
    s.commit()
    s.expire_all()

    # Pelunasan tanpa nominal = lunasi SELURUH sisa.
    assert to_decimal(res["saldo_hutang"]) == to_decimal(0)
    assert to_decimal(debt_mod.saldo_hutang(s)) == to_decimal(0)
    # Kewajiban turun, tapi uang TIDAK otomatis keluar dari posisi mana pun.
    assert to_decimal(cash.saldo_laci(s)) == laci_awal, \
        "Pelunasan hutang tidak boleh menyentuh Saldo Laci"
    assert to_decimal(cash.saldo_kas_aset(s)) == \
        aset_awal + to_decimal(800000), \
        "v4 #8: pengeluaran aktual dicatat MANUAL oleh Admin, bukan otomatis"

    # Sisa hutang sudah 0 -> pelunasan kedua harus DITOLAK.
    n_lunas = s.query(ExpenseDebtEntry).filter(
        ExpenseDebtEntry.tipe == "PELUNASAN").count()
    assert n_lunas == 1
    try:
        debt_mod.lunas_hutang(s, nominal=None, oleh="pytest")
        raise AssertionError("Pelunasan kedua seharusnya DITOLAK")
    except debt_mod.DebtError:
        pass
    s.commit()
    s.expire_all()
    assert s.query(ExpenseDebtEntry).filter(
        ExpenseDebtEntry.tipe == "PELUNASAN").count() == n_lunas, \
        "Hutang yang sudah lunas tidak boleh dilunasi dua kali"
    s.close()


# ─────────── 7. Tutup Kas + REKONSILIASI tidak selisih ganda ───────────
def test_7_rekonsiliasi_tidak_menghasilkan_selisih_ganda(client, db):
    """Jalankan rekonsiliasi berkali-kali untuk periode sama -> 1 penyesuaian."""
    import cash
    from routers.kas import period_rows

    s = _isolated_db()          # stateful -> DB terisolasi
    mulai = datetime(2026, 4, 1)
    # Bangun saldo Laci yang pasti dan tidak nol supaya selisihnya nyata.
    _iso_beban(s, mulai, [("S7 uji rekonsiliasi", "Operasional", 1000)])
    s.commit()
    s.expire_all()
    target = to_decimal(cash.saldo_laci(s))
    assert target == to_decimal(-1000)

    # Deklarasikan fisik 0 -> sistem mencatat penyesuaian SEKALI.
    r1 = cash.rekonsiliasi_laci(s, to_decimal(0), actor="pytest",
                                ref_type="periode", ref_id="PY-S7")
    s.commit()
    s.expire_all()
    assert r1.get("penyesuaian") is not None, "Selisih harus menghasilkan penyesuaian"
    M = cash._entry_model()
    assert s.query(M).filter(M.layer == cash.LAYER_LACI,
                             M.sumber == cash.SUMBER_REKONSILIASI,
                             M.ref_type == "periode",
                             M.ref_id == "PY-S7").count() == 1
    assert to_decimal(cash.saldo_laci(s)) == to_decimal(0), \
        "Setelah penyesuaian, Saldo Laci harus sama dengan fisik"
    saldo_setelah_1 = to_decimal(cash.saldo_laci(s))

    # Panggil LAGI untuk periode yang sama -> tidak boleh menambah penyesuaian.
    r2 = cash.rekonsiliasi_laci(s, to_decimal(0), actor="pytest",
                                ref_type="periode", ref_id="PY-S7")
    s.commit()
    s.expire_all()
    assert r2.get("penyesuaian") is None, \
        "Rekonsiliasi ulang tidak boleh mencatat penyesuaian kedua"
    assert s.query(M).filter(M.layer == cash.LAYER_LACI,
                             M.sumber == cash.SUMBER_REKONSILIASI,
                             M.ref_type == "periode",
                             M.ref_id == "PY-S7").count() == 1, \
        "Hanya boleh ada SATU entri penyesuaian per periode"
    assert to_decimal(cash.saldo_laci(s)) == saldo_setelah_1

    # Penyesuaian harus TERLACAK di Mutasi Kas.
    assert cash.SUMBER_REKONSILIASI in cash.SUMBER_BARIS_KAS
    rows = period_rows(s, datetime.min, datetime.max)
    assert any((r["kategori"] == cash.KATEGORI[cash.SUMBER_REKONSILIASI])
               for r in rows), \
        "Penyesuaian rekonsiliasi harus terlihat di Mutasi Kas"
    # Dan ikut terhitung di saldo berjalan (bukan cuma tampilan).
    assert to_decimal(rows[-1]["saldo"]) == to_decimal(cash.saldo_laci(s))
    s.close()


# ─────────── 8. Saldo awal / berjalan / akhir konsisten ───────────
def test_8_saldo_awal_berjalan_akhir_konsisten(client, db):
    """Saldo Awal + Total Masuk - Total Keluar = Saldo Akhir = saldo_laci().

    Dijalankan di DB terisolasi supaya seluruh angka bisa dikontrol: di sandbox
    bersama ada baris `payments`/`expenses` yang ditulis langsung oleh fixture
    test lain tanpa melalui `cash.*`, sehingga ledger dan tabel memang wajar
    berbeda. Yang diuji di sini adalah INVARIAN produk, bukan keterbacaan data.
    """
    import cash
    from routers.kas import period_rows

    s = _isolated_db()
    mulai = datetime(2026, 5, 1)
    # Skenario bercampur: DP + pelunasan + modal + beban + transfer + injeksi.
    o = _iso_order(s, "S8-1", mulai, harga=1000000, modal=(400000, 200000, 0),
                   status="DONE")
    _iso_beban(s, mulai, [("Gaji S8", "Gaji", 300000),
                          ("Sewa S8", "Operasional", 120000)])
    s.commit()
    s.expire_all()

    # DP + pelunasan + modal, semuanya lewat modul kas.
    dp = models_payment(s, o.id, "DP", 300000, mulai)
    cash.catat_penerimaan(s, dp)
    pel = models_payment(s, o.id, "PELUNASAN", 700000, mulai)
    cash.catat_penerimaan(s, pel)
    cash.catat_modal(s, o)
    cash.catat_injeksi(s, cash.LAYER_ASET, 500000, "modal awal")
    s.commit()
    s.expire_all()

    saldo_laci = to_decimal(cash.saldo_laci(s))

    rows, opening = period_rows(s, datetime.min, datetime.max, with_opening=True)
    assert rows, "Harus ada baris mutasi"
    masuk = sum((to_decimal(r["nominal"]) for r in rows
                 if r["jenis"] == "Masuk"), ZERO)
    keluar = sum((to_decimal(r["nominal"]) for r in rows
                  if r["jenis"] == "Keluar"), ZERO)

    assert to_decimal(opening) == to_decimal(0)
    assert to_decimal(opening) + masuk - keluar == to_decimal(rows[-1]["saldo"]), \
        "Saldo akhir harus = Saldo Awal + Masuk - Keluar"
    assert to_decimal(rows[-1]["saldo"]) == saldo_laci, \
        "Saldo baris terakhir WAJIB sama dengan saldo_laci() (Mutasi Kas 100% lengkap)"
    assert masuk == to_decimal(1000000), "Masuk = DP 300rb + pelunasan 700rb"
    assert keluar == to_decimal(1020000), "Keluar = beban 420rb + modal 600rb"
    # Injeksi 500rb masuk ke Kas ASET, jadi TIDAK boleh muncul di Mutasi Kas Laci.
    assert to_decimal(cash.saldo_kas_aset(s)) == to_decimal(500000)

    # Tiap langkah hanya bergerak sebesar nominal baris itu (tidak melompat).
    for a, b in zip(rows, rows[1:]):
        d = (to_decimal(b["nominal"]) if b["jenis"] == "Masuk"
             else -to_decimal(b["nominal"]))
        assert to_decimal(a["saldo"]) + d == to_decimal(b["saldo"]), \
            "Saldo Berjalan harus bergerak tepat sebesar nominal baris"

    # Opening = sumber yang sama dengan yang dipakai dashboard.
    # Periodenya dibuat eksplisit (mulai 2030) supaya semua data test — yang
    # created_at-nya "sekarang" — berada SEBELUM periode, dan perbandingan
    # opening-vs-dashboard deterministik.
    import models
    s.add(models.KasPeriod(start_at=datetime(2030, 1, 1, 0, 0),
                           end_at=datetime(2030, 1, 2, 0, 0), status="OPEN"))
    s.commit()
    s.expire_all()
    from routers.dashboard import batas_periode, get_active_period
    from routers.kas import period_rows as _pr
    p = get_active_period(s)
    _, opening_p = _pr(s, *batas_periode(p), with_opening=True)
    assert to_decimal(opening_p) == to_decimal(cash.saldo_laci_sampai(s, p.start_at)), \
        "Saldo Awal Mutasi Kas harus dari sumber yang sama dengan dashboard"
    assert to_decimal(opening_p) == to_decimal(cash.saldo_laci(s)), \
        "Semua data ada sebelum periode -> opening = saldo saat ini"
    s.close()


# ─────────── 9. Transfer Laci <-> Aset tidak menggandakan ───────────
def test_9_transfer_laci_aset_tidak_menggandakan(client, db):
    """Transfer memindahkan lokasi uang: Master Kas tetap, tidak dobel di Mutasi."""
    import cash
    from routers.kas import period_rows

    s = _isolated_db()          # stateful -> DB terisolasi
    cash.catat_injeksi(s, cash.LAYER_ASET, to_decimal(500000), "modal awal")
    s.commit()
    s.expire_all()

    laci_awal = to_decimal(cash.saldo_laci(s))
    aset_awal = to_decimal(cash.saldo_kas_aset(s))
    master_awal = to_decimal(cash.master_kas(s))

    cash.transfer(s, to_decimal(120000), cash.LAYER_ASET, cash.LAYER_LACI,
                  "S9 tarik ke laci")
    s.commit()
    s.expire_all()

    assert to_decimal(cash.saldo_laci(s)) - laci_awal == to_decimal(120000)
    assert to_decimal(cash.saldo_kas_aset(s)) - aset_awal == -to_decimal(120000)
    assert to_decimal(cash.master_kas(s)) == master_awal, \
        "Transfer tidak boleh mengubah Master Kas"

    # Hanya SATU sisi (Laci) yang boleh muncul di Mutasi Kas.
    M = cash._entry_model()
    n_entri = s.query(M).filter(M.layer == cash.LAYER_LACI,
                                M.sumber == cash.SUMBER_TRANSFER).count()
    rows = period_rows(s, datetime.min, datetime.max)
    n_baris = sum(1 for x in rows
                  if x["kategori"] == cash.KATEGORI[cash.SUMBER_TRANSFER])
    assert n_entri == 1, "Seharusnya ada 1 entri LACI untuk 1 transfer"
    assert n_baris == n_entri, \
        ("Transfer harus muncul tepat satu kali per entri LACI (tidak dobel); "
         "baris=%d entri=%d" % (n_baris, n_entri))
    assert to_decimal(cash.master_kas(s)) == master_awal
    s.close()


# ─────────── 11. Modal boleh 0 (tapi wajib terisi) ───────────
def test_11_modal_boleh_nol_tapi_wajib_terisi(client, db):
    """Aturan Owner: Modal Part & Jasa WAJIB DIISI, tapi BOLEH bernilai 0.

    Servis yang hanya ganti LCD / software tidak punya Modal Part. Sebelumnya
    user dipaksa mengetik angka 1 supaya lolos, dan angka itu ikut menguras Kas
    Laci sebagai uang fiktif.
    """
    from fastapi import HTTPException
    import routers.orders as ords
    adm = _token(db, "pytest_admin", "ADMIN")

    # (a) Modal 0 pada kedua komponen -> LOLOS status CASH.
    for part, jasa in ((0, 250000), (0, 0), (150000, 0)):
        o = _order(db, "PY-S11-%d-%d" % (part, jasa), "DONE",
                   harga=500000, modal=(part, jasa, 0))
        rc = _cp(client, db, "put", "/api/orders/%d" % o.id, headers=adm,
                 json={"status": "CASH"})
        assert rc.status_code == 200, \
            "Modal %s/%s harus boleh 0 (HTTP %s: %s)" % (
                part, jasa, rc.status_code, rc.text[:80])
    db.expire_all()

    # (b) Kolom KOSONG (null) tetap ditolak — "belum dihitung" != "memang nol".
    o2 = _order(db, "PY-S11-KOSONG", "DONE", harga=500000,
                modal=(100000, 100000, 0))
    rc2 = _cp(client, db, "put", "/api/orders/%d" % o2.id, headers=adm,
              json={"part_cost": None, "status": "CASH"})
    assert rc2.status_code == 400, "Modal Part kosong harus ditolak"
    assert "Modal Part" in (rc2.json().get("detail") or "")

    rc3 = _cp(client, db, "put", "/api/orders/%d" % o2.id, headers=adm,
              json={"modal_jasa": None, "status": "CASH"})
    assert rc3.status_code == 400, "Modal Jasa kosong harus ditolak"
    assert "Modal Jasa" in (rc3.json().get("detail") or "")


def test_12_modal_nol_tidak_menguras_kas(client, db):
    """Modal 0 tidak boleh membuat entri kas keluar sama sekali."""
    import cash as cash_mod
    laci_awal = _saldo_laci(db)
    n_modal_awal = _n_entry(db, cash_mod.SUMBER_MODAL)
    id_entri_awal = _id_entri_tertinggi(db)

    adm = _token(db, "pytest_admin", "ADMIN")
    o = _order(db, "PY-S12-MODAL0", "DONE", harga=400000,
               modal=(0, 150000, 0))
    rc = _cp(client, db, "put", "/api/orders/%d" % o.id, headers=adm,
             json={"status": "CASH"})
    assert rc.status_code == 200, rc.text
    db.expire_all()

    # Hanya 1 entri modal (Jasa); Part 0 tidak boleh ikut.
    assert _n_entry(db, cash_mod.SUMBER_MODAL) - n_modal_awal == 1, \
        "Modal Part 0 tidak boleh membuat entri kas"
    # Dan kas hanya keluar sebesar modal yang benar-benar ada.
    assert (_saldo_laci(db) - laci_awal
            == to_decimal(400000) - to_decimal(150000)
            - _pengaruh_distribusi_laci(db, id_entri_awal))


# ─────────── 10. Tidak ada regresi di modul lain ───────────
def test_10_tanpa_regresi_omzet_laba_distribusi_garansi_periode(client, db):
    """Guard ringan: modul lain tetap hidup & bentuk datanya tidak berubah."""
    import distribution as dist_mod
    from routers.dashboard import batas_periode, compute_finance, get_active_period

    adm = _token(db, "pytest_admin", "ADMIN")
    p = get_active_period(db)

    # Omzet & laba: struktur & consistency.
    fin = compute_finance(db, *batas_periode(p), lihat_kas_besar=True)
    assert fin["total_masuk"] == fin["omset"] + fin["kas_masuk_manual"], \
        "Total Masuk = Omzet + kas manual (DP tidak boleh masuk sini)"
    assert fin["total_keluar"] == (fin["total_modal"] + fin["total_beban"]
                                   + fin["kas_keluar_manual"])
    assert fin["omset"] >= to_decimal(0)

    # Distribusi: preview selalu punya rasio lengkap.
    preview = dist_mod.preview(to_decimal(100000))
    assert set(preview) >= {"karyawan", "pengelola", "investor", "kas_aset", "cash_out"}

    # Garansi: endpoint tidak boleh 500.
    r = client.get("/api/warranty-claims", headers=adm)
    assert r.status_code < 500, r.text

    # Periode historis: periode tertutup tetap terbaca (Q14).
    r = client.get("/api/kas/periods", headers=adm)
    assert r.status_code == 200, r.text

    # Endpoint baru Mutasi Kas & Rekonsiliasi hidup.
    r = client.get("/api/kas/rekonsiliasi?period=current", headers=adm)
    assert r.status_code == 200, r.text
    assert "saldo_sistem" in r.json()
