# -*- coding: utf-8 -*-
"""Pencatatan Titipan DP terpisah dari Omzet/Laba/Distribusi + guard Kas Besar.

Semua angka TITIPAN DP adalah TURUNAN dari `payments` + `refunds` yang sudah ada.
Tidak ada kolom baru, tidak ada ledger baru, tidak ada perubahan pada Payment
Ledger / Financial Core / mekanisme Tutup Kas (FR-01 & FR-02 utuh).

Yang diuji:
1. DP tidak pernah masuk Omzet (sebelum maupun sesudah pelunasan).
2. Empat angka ringkasan: diterima / dipakai / dikembalikan / saldo.
3. DP yang belum selesai TETAP ada setelah Tutup Kas (dibawa ke periode berikut).
4. DP dikembalikan (refund) mengurangi saldo titipan, satu efek kas saja.
5. Kas Besar (saldo + master) tidak terkirim ke role tanpa authority —
   di /api/overview maupun /api/kas/saldo.
"""
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import and_, or_

from money import to_decimal


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


def _order(db, no, status, harga=500000, modal=(0, 0, 0)):
    import models
    cust = db.query(models.Customer).filter(
        models.Customer.name == "Pytest Customer").first()
    o = models.ServiceOrder(
        no_servis=no, customer_id=cust.id, device="PY", status=status,
        service_date=datetime.now().date(), final_price=to_decimal(harga),
        estimate=to_decimal(harga), repair_plan="x", technician="Budi",
        warranty_months=1, created_at=datetime.now(),
        part_cost=to_decimal(modal[0]), modal_jasa=to_decimal(modal[1]),
        modal_lainnya=to_decimal(modal[2]),
    )
    db.add(o)
    db.commit()
    db.refresh(o)
    return o


def _pay(db, order, kind, amount):
    import models
    db.add(models.Payment(service_order_id=order.id, kind=kind,
                          amount=to_decimal(amount), created_at=datetime.now()))
    db.commit()


def _titipan(db):
    import routers.dashboard as dash
    return dash.ringkasan_titipan_dp(db)


def _period(db):
    from datetime import datetime as _dt
    import models
    now = _dt.now()
    start = now.replace(hour=16, minute=0, second=0, microsecond=0)
    if now < start:
        start -= timedelta(days=1)
    p = db.query(models.KasPeriod).filter(models.KasPeriod.status == "OPEN").first()
    if p is None:
        p = models.KasPeriod(start_at=start, end_at=start + timedelta(days=1),
                            status="OPEN")
        db.add(p)
        db.commit()
    p.start_at, p.end_at = start, start + timedelta(days=1)
    db.commit()
    return p


# ───────────────── 1. DP terpisah dari Omzet ─────────────────
def test_dp_tidak_pernah_masuk_omzet(client, db):
    import routers.dashboard as dash
    p = _period(db)
    o = _order(db, "PY-DP-OMSET", "DONE", modal=(150000, 50000, 0))
    _pay(db, o, "DP", 200000)
    db.commit()

    # DELTA, bukan absolut: sandbox menyalin DB produksi yang bisa sudah punya
    # order CASH lain (data UAT), jadi Omzet total tidak boleh dijadikan 0.
    core = dash.compute_finance(db, p.start_at, p.end_at, lihat_kas_besar=True)
    omset_awal = to_decimal(core["omset"])
    _pay(db, o, "PELUNASAN", 300000)
    db.commit()
    core_dp = dash.compute_finance(db, p.start_at, p.end_at, lihat_kas_besar=True)
    assert to_decimal(core_dp["omset"]) == omset_awal, \
        "DP + pelunasan sebagian belum boleh masuk Omzet (status belum CASH)"

    # Setelah CASH, Omzet bertambah sebesar SISA pelunasan — bukan kewajiban
    # penuh ditambah DP (lalu-lagi).
    adm = _token(db, "pytest_admin", "ADMIN")
    assert client.put("/api/orders/%d" % o.id, headers=adm,
                        json={"status": "CASH"}).status_code == 200
    db.expire_all()
    core2 = dash.compute_finance(db, p.start_at, p.end_at, lihat_kas_besar=True)
    # Omzet naik sebesar KEWAJIBAN (500rb), bukan kewajiban + DP (700rb).
    # Inilah arti "tidak dobel": DP bagian dari kewajiban, bukan tambahan.
    assert to_decimal(core2["omset"]) - omset_awal == to_decimal(500000), \
        "Omzet += kewajiban saja; DP tidak boleh dihitung lagi di atasnya"


# ───────────────── 2. empat angka ringkasan ─────────────────
def test_ringkasan_titipan_empat_angka(client, db):
    base = {k: to_decimal(v) for k, v in _titipan(db).items()}

    # unit masih jalan: DP diterima, belum terpakai -> saldo naik
    a = _order(db, "PY-DP-KOSONG", "REPAIR")
    _pay(db, a, "DP", 150000)
    t = _titipan(db)
    assert t["diterima"] - base["diterima"] == to_decimal(150000)
    assert t["dipakai"] - base["dipakai"] == to_decimal(0)
    assert t["saldo"] - base["saldo"] == to_decimal(150000)

    # unit dilunasi: DP jadi terpakai, saldo turun kembali
    _pay(db, a, "PELUNASAN", 500000)
    t2 = _titipan(db)
    assert t2["diterima"] - base["diterima"] == to_decimal(150000)
    assert t2["dipakai"] - base["dipakai"] == to_decimal(150000)
    assert t2["saldo"] - base["saldo"] == to_decimal(0), \
        "DP terpakai tidak boleh tersisa sebagai saldo titipan"


# ───────────────── 3. dibawa ke periode berikutnya setelah Tutup Kas ─────────────────
def test_titipan_terbawa_setelah_tutup_kas(client, db):
    """DP di periode LAMA tetap ada di ringkasan setelah periode itu ditutup.

    Dibuktikan secara struktural, TIDAK dengan menutup periode aktif bersama —
    supaya test ini tidak merusak test lain yang memakai periode itu. Yang
    dijamin oleh implementasi:
      (a) ringkasan titipan tidak dibatasi periode kas, dan
      (b) Tutup Kas tidak menghapus baris apa pun (Q14).
    """
    import models
    base = {k: to_decimal(v) for k, v in _titipan(db).items()}
    p = _period(db)                       # periode kas AKTIF (berisi now)
    lama = p.start_at - timedelta(days=1)  # periode sebelumnya

    a = _order(db, "PY-DP-CARRY", "REPAIR")
    _pay(db, a, "DP", 250000)             # belum dilunasi -> masih titipan
    dbaris = db.query(models.Payment).filter(
        models.Payment.service_order_id == a.id).first()
    dbaris.created_at = lama             # dicatat di periode SEBELUM aktif
    db.add(models.KasPeriod(start_at=lama - timedelta(hours=8),
                            end_at=p.start_at, status="CLOSED",
                            closed_at=lama))
    db.commit()

    # Di luar periode aktif, tapi TETAP masuk saldo titipan.
    t = _titipan(db)
    assert t["diterima"] - base["diterima"] == to_decimal(250000)
    assert t["saldo"] - base["saldo"] == to_decimal(250000), \
        "DP periode lama harus terbawa ke periode berikutnya"

    # Baris payment-nya tidak dihapus, dan DP-nya tetap tercatat penuh di Laporan
    # Titipan DP maupun di ledger kas (uangnya nyata ada di laci).
    assert db.query(models.Payment).filter(models.Payment.id == dbaris.id).count() == 1
    import cash as cash_mod
    assert to_decimal(cash_mod.dp_diterima(db, a.id)) == to_decimal(250000)


# ───────────────── 3b. DP = TITIPAN: tidak pernah masuk ledger kas ─────────────────
def test_dp_tunai_masuk_kas_tanpa_meningkatkan_omzet(client, db):
    """DP tunai menambah Saldo Laci (uangnya nyata), tapi TIDAK menambah Omzet.

    Dilakukan lewat DELTA karena sandbox disalin dari DB produksi.
    """
    import models
    import routers.dashboard as dash
    import cash as cash_mod
    from routers.dashboard import batas_periode, get_active_period

    adm = _token(db, "pytest_admin", "ADMIN")
    p = get_active_period(db)
    a = _order(db, "PY-DP-TERPISAH", "REPAIR", harga=400000)
    db.commit()
    laci_awal = cash_mod.saldo_laci(db)
    omzet_awal = to_decimal(dash.compute_finance(db, *batas_periode(p))["omset"])

    r = client.post("/api/payments", headers=adm,
                    json={"service_order_id": a.id, "kind": "DP",
                          "amount": 250000, "method": "CASH"})
    assert r.status_code in (200, 201), r.text
    db.expire_all()

    assert to_decimal(cash_mod.saldo_laci(db)) - laci_awal == to_decimal(250000), \
        "DP tunai harus menambah Saldo Laci supaya bisa direkonsiliasi"
    pay_id = db.query(models.Payment).filter(
        models.Payment.service_order_id == a.id).first().id
    entri = db.query(models.KasEntry).filter(
        models.KasEntry.ref_type == "payment",
        models.KasEntry.ref_id == pay_id).all()
    assert len(entri) == 1, "DP harus punya tepat satu entri kas (tidak dobel)"
    assert to_decimal(dash.compute_finance(db, *batas_periode(p))["omset"]) == omzet_awal, \
        "DP belum LUNAS -> Omzet tidak boleh naik"
    # Tetap tercatat penuh sebagai titipan.
    assert to_decimal(cash_mod.dp_diterima(db, a.id)) == to_decimal(250000)


def test_dp_dan_pelunasan_tidak_menggandakan_kewajiban(client, db):
    """DP 200rb + pelunasan sisa 300rb = kewajiban 500rb, tercatat SATU KALI.

    DP masuk laci saat diterima (sebelum `laci_awal`), pelunasan sebesar SISA
    saat CASH. Jumlahnya persis kewajiban penuh, tanpa dobel.
    """
    import models
    import cash as cash_mod
    from money import ZERO
    from statusflow import kewajiban

    o = _order(db, "PY-DP-PELUNAS2", "DONE", harga=500000,
               modal=(150000, 50000, 0))
    dp = _pay_row(db, o, "DP", 200000)
    cash_mod.catat_penerimaan(db, dp)
    db.commit()
    laci_awal = cash_mod.saldo_laci(db)

    adm = _token(db, "pytest_admin", "ADMIN")
    r = client.put("/api/orders/%d" % o.id, headers=adm, json={"status": "CASH"})
    assert r.status_code == 200, r.text
    db.expire_all()

    pay_ids = [p.id for p in db.query(models.Payment).filter(
        models.Payment.service_order_id == o.id).all()]
    masuk = sum((to_decimal(e.nominal) for e in db.query(models.KasEntry).filter(
        models.KasEntry.jenis == "Masuk",
        models.KasEntry.ref_type == "payment",
        models.KasEntry.ref_id.in_(pay_ids)).all()), ZERO)
    assert to_decimal(masuk) == to_decimal(kewajiban(o)), \
        "Total masuk kas untuk unit = DP 200rb + sisa 300rb = kewajiban 500rb"

    # Replay CASH tidak boleh menambah penerimaan lagi.
    client.put("/api/orders/%d" % o.id, headers=adm,
               json={"status": "CASH", "status_note": "replay"})
    db.expire_all()
    assert len(db.query(models.Payment).filter(
        models.Payment.service_order_id == o.id).all()) == 2, \
        "Replay tidak boleh menambah baris payment"
    # CASH: pelunasan sisa 300rb masuk, modal 200rb keluar -> netto +100rb.
    modal = to_decimal(o.part_cost) + to_decimal(o.modal_jasa) + to_decimal(o.modal_lainnya)
    assert to_decimal(cash_mod.saldo_laci(db)) - laci_awal == \
        to_decimal(kewajiban(o)) - to_decimal(200000) - modal


def test_refund_dp_kurangi_kas_dan_titipan(client, db):
    """Refund DP mengurangi Saldo Laci (uang keluar) DAN Saldo Titipan DP.

    DP ada di laci sejak diterima, jadi pengembalikannya memang mengurangi kas —
    satu efek, bukan nol dan bukan dua kali.
    """
    import models
    import cash as cash_mod
    o = _order(db, "PY-DP-REFUND-LACI", "REPAIR")
    dp = _pay_row(db, o, "DP", 300000)
    cash_mod.catat_penerimaan(db, dp)
    db.commit()
    laci_awal = cash_mod.saldo_laci(db)

    adm = _token(db, "pytest_admin", "ADMIN")
    r = client.post("/api/refunds/dp", headers=adm,
                    json={"service_order_id": o.id, "nominal": 100000,
                          "alasan": "batal sebagian"})
    assert r.status_code in (200, 201), r.text
    db.expire_all()

    assert to_decimal(cash_mod.saldo_laci(db)) - laci_awal == -to_decimal(100000), \
        "Refund DP harus mengurangi Saldo Laci sebesar nominalnya"
    ref = db.query(models.Refund).filter(models.Refund.service_order_id == o.id).first()
    assert ref.kas_entry_id is not None, "Refund DP harus punya satu entri kas"


# ───────────────── 4. DP dikembalikan ─────────────────
def test_dp_dikembalikan_kurangi_saldo_titipan(client, db):
    import models
    base = {k: to_decimal(v) for k, v in _titipan(db).items()}
    o = _order(db, "PY-DP-REFUND", "REPAIR")
    _pay(db, o, "DP", 300000)

    from routers.auth import hash_passcode
    admin = db.query(models.User).filter(
        models.User.username == "pytest_admin").first()
    adm = _token(db, "pytest_admin", "ADMIN")
    r = client.post("/api/refunds/dp", headers=adm,
                    json={"service_order_id": o.id, "nominal": 100000,
                          "alasan": "batal sebagian"})
    assert r.status_code in (200, 201), r.text
    db.expire_all()

    t = _titipan(db)
    assert t["diterima"] - base["diterima"] == to_decimal(300000)
    assert t["dikembalikan"] - base["dikembalikan"] == to_decimal(100000)
    assert t["saldo"] - base["saldo"] == to_decimal(200000), \
        "DP dikembalikan harus mengurangi saldo titipan"


# ───────────────── 5. guard Kas Besar per role ─────────────────
def test_kas_besar_tidak_terbaca_role_tanpa_authority(client, db):
    adm = _token(db, "pytest_admin", "ADMIN")
    kasir = _token(db, "pytest_kasir", "KASIR")

    # Admin/Pengelola: posisi Kas Besar ikut terkirim.
    ov_admin = client.get("/api/overview", headers=adm)
    assert ov_admin.status_code == 200, ov_admin.text
    f_admin = ov_admin.json()["finance"]
    assert "saldo_aset" in f_admin and "master_kas" in f_admin

    # Kasir: key-nya TIDAK ADA sama sekali (bukan 0).
    ov_kasir = client.get("/api/overview", headers=kasir)
    assert ov_kasir.status_code == 200, ov_kasir.text
    f_kasir = ov_kasir.json()["finance"]
    assert "saldo_aset" not in f_kasir, "Kasir tidak boleh menerima saldo_aset"
    assert "master_kas" not in f_kasir, "Kasir tidak boleh menerima master_kas"
    # Yang tetap boleh: Kas Kecil/Laci.
    assert "saldo_laci" in f_kasir and "kas_aset_awal" in f_kasir

    # Endpoint saldo & rincian tetap 403 (tidak berubah).
    assert client.get("/api/kas/aset/riwayat", headers=kasir).status_code == 403
    s_kasir = client.get("/api/kas/saldo", headers=kasir)
    assert s_kasir.status_code == 200
    assert "aset" not in s_kasir.json() and "master_kas" not in s_kasir.json()


def test_baris_dp_tidak_masuk_buku_kas_operasional(client, db):
    """DP tidak boleh muncul sebagai baris Debit/Kredit di Arus Kas."""
    o = _order(db, "PY-DP-TAG", "REPAIR")
    _pay(db, o, "DP", 120000)
    _period(db)
    adm = _token(db, "pytest_admin", "ADMIN")
    r = client.get("/api/kas/riwayat?period=current&limit=200", headers=adm)
    assert r.status_code == 200, r.text
    kategori = [it.get("kategori") for it in r.json()["items"]]
    assert "DP" not in kategori, \
        "DP titipan tidak boleh tampil di rincian Buku Kas operasional"


def test_mutasi_titipan_dp_terderivasi_dan_stabil(client, db):
    """Daftar mutasi DP harus identik setiap kali dihitung (tidak bisa dobel)."""
    import routers.dashboard as dash
    o = _order(db, "PY-DP-MUT", "DONE", modal=(150000, 50000, 0))
    _pay(db, o, "DP", 200000)
    db.commit()

    a = dash.mutasi_titipan_dp(db)
    b = dash.mutasi_titipan_dp(db)
    assert [x["no_servis"] for x in a] == [x["no_servis"] for x in b]
    assert [x["jenis"] for x in a] == [x["jenis"] for x in b]
    assert [x["saldo"] for x in a] == [x["saldo"] for x in b]

    # Setelah unit LUNAS, ada baris DIPAKAI tepat satu untuk unit itu.
    _pay(db, o, "PELUNASAN", 300000)
    adm = _token(db, "pytest_admin", "ADMIN")
    assert client.put("/api/orders/%d" % o.id, headers=adm,
                        json={"status": "CASH"}).status_code == 200
    db.expire_all()
    dipakai = [x for x in dash.mutasi_titipan_dp(db)
               if x["no_servis"] == o.no_servis and x["jenis"] == "DIPAKAI"]
    assert len(dipakai) == 1, "Pemakaian DP harus tercatat tepat satu kali"
    assert to_decimal(dipakai[0]["keluar"]) == to_decimal(200000)

    # Reload / request ulang tidak menambah apa pun.
    ulang = [x for x in dash.mutasi_titipan_dp(db)
             if x["no_servis"] == o.no_servis and x["jenis"] == "DIPAKAI"]
    assert len(ulang) == 1, "Reload halaman tidak boleh menambah mutasi DP"

# ───────────────── 6. Kondisi Kas rekonsiliasi dengan Saldo Laci ─────────────────


def test_kondisi_kas_rekonsiliasi_dengan_saldo_laci(client, db):
    """Conditions Kas harus PERSIS sama dengan Saldo Laci (selisih = 0).

    Dijalankan di DB SQLite terisolasi, bukan di sandbox bersama. Sandbox itu
    dipakai 90+ test lain yang semuanya menambah order, beban, dan
    mend-holderi-formed distributors sekaligus — sehingga "selisih harus tetap"
    (yang dulu dipakai) tidak lagi bisa dibedakan dari gangguan antar-test.

    Di DB kosong selisihnya bisa dinilai ABSOLUT, dan itu pemeriksaan yang jauh
    lebih ketat: Conditions Kas = Saldo Awal + Omzet - Modal - Beban - Distribusi.

    Yang diverifikasi:
      - Modal keluar dari kas saat status CASH (bukan saat DONE).
      - DP tidak dihitung dua kali (sudah tercakup di Omzet).
      - Distribusi 100% laba keluar dari Laci saat CTO tercapai.
    """
    import os
    import tempfile
    from datetime import datetime as _dt, timedelta as _td

    import cash as cash_mod
    import models as _m
    from routers.dashboard import compute_finance as _cf
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from database import Base

    folder = tempfile.mkdtemp(prefix="rekon_iso_")
    eng = create_engine("sqlite:///%s" % os.path.join(folder, "iso.db"))
    Base.metadata.create_all(bind=eng)
    s = sessionmaker(bind=eng)()

    mulai = _dt(2026, 6, 1)
    s.add(_m.KasPeriod(start_at=mulai, end_at=mulai + _td(days=1), status="OPEN"))
    s.add(_m.Customer(name="Rekon", phone="0800", created_at=mulai))
    s.commit()
    s.expire_all()
    pid = s.query(_m.KasPeriod).first().id
    cid = s.query(_m.Customer).first().id
    batas = (mulai, mulai + _td(days=1))

    def calc():
        fin = _cf(s, *batas, lihat_kas_besar=True)
        al = fin.get("alokasi") or {}
        dist = to_decimal(0)
        if fin.get("alokasi_terbentuk"):
            dist = sum((to_decimal(al.get(k) or 0) for k in
                        ("karyawan", "pengelola", "investor", "kas_aset")),
                       to_decimal(0))
        # + DP periode ini yang belum jadi Omzet: uangnya ada di Laci tapi belum
        # jadi pendapatan. Saat unit LUNAS nilai ini keluar (sudah masuk Omzet).
        dp_berjalan = to_decimal((fin.get("titipan_dp") or {}).get("berjalan") or 0)
        return (to_decimal(fin["kas_aset_awal"]) + to_decimal(fin["omset"])
                + dp_berjalan
                - to_decimal(fin["total_modal"]) - to_decimal(fin["total_beban"])
                - dist)

    def cek(label):
        s.expire_all()
        laci = to_decimal(cash_mod.saldo_laci(s))
        nilai_kondisi = calc()
        assert abs(laci - nilai_kondisi) < to_decimal("1"), (
            "Selisih Conditions Kas vs Saldo Laci setelah %s: %s" % (label, laci - nilai_kondisi))
        return laci

    # 0. Kondisi awal: laci kosong.
    cek("kondisi awal")

    # 1. DP 200rb masuk laci, Omzet BELUM naik (unit belum CASH).
    o = _m.ServiceOrder(
        no_servis="REKON-1", customer_id=cid, device="PY", status="DONE",
        unit_status="SIAP", service_date=mulai.date(), taken_at=mulai,
        final_price=to_decimal(500000), estimate=to_decimal(500000),
        repair_plan="x", technician="T", warranty_months=1, created_at=mulai,
        part_cost=to_decimal(150000), modal_jasa=to_decimal(50000),
        modal_lainnya=to_decimal(0))
    s.add(o)
    s.flush()
    dp = _m.Payment(service_order_id=o.id, kind="DP",
                    amount=to_decimal(200000), method="CASH", created_at=mulai)
    s.add(dp)
    s.flush()
    cash_mod.catat_penerimaan(s, dp)
    s.commit()
    assert to_decimal(cash_mod.saldo_laci(s)) == to_decimal(200000)
    cek("DP masuk (belum LUNAS)")

    # 2. CASH: pelunasan sisa 300rb masuk, modal 200rb keluar, laba terbentuk.
    pel = _m.Payment(service_order_id=o.id, kind="PELUNASAN",
                     amount=to_decimal(300000), method="CASH", created_at=mulai)
    s.add(pel)
    s.flush()
    cash_mod.catat_penerimaan(s, pel)
    cash_mod.catat_modal(s, o)
    s.commit()
    s.refresh(o)
    o.status = "CASH"
    o.taken_at = mulai
    s.commit()
    # Laci = 200.000 (DP) + 300.000 (pelunasan) - 200.000 (modal) = 300.000
    assert to_decimal(cash_mod.saldo_laci(s)) == to_decimal(300000)
    cek("setelah CASH (modal keluar)")

    # 3. Tambahkan beban 100rb -> harus tetap sinkron.
    e = _m.Expense(kategori="Operasional", uraian="Rekon-listrik",
                   nilai=to_decimal(100000), created_at=mulai)
    s.add(e)
    s.flush()
    cash_mod.catat_beban(s, e)
    s.commit()
    assert to_decimal(cash_mod.saldo_laci(s)) == to_decimal(200000)
    cek("setelah beban")

    # 4. Distribusi otomatis saat CTO tercapai: 100% laba keluar dari Laci,
    #    tapi hanya 70% yang benar-benar hilang dari Master Kas.
    import distribution as _dist
    p = s.query(_m.KasPeriod).first()
    fin = _cf(s, *batas, lihat_kas_besar=True)
    master_sebelum = to_decimal(cash_mod.master_kas(s))
    laci_sebelum = to_decimal(cash_mod.saldo_laci(s))
    res = _dist.pastikan_otomatis(s, p.start_at.date().isoformat(),
                                  fin["laba_bersih"],
                                  cto_tercapai=bool(fin["cto_tercapai"]),
                                  kas_period_id=p.id, oleh="pytest")
    s.commit()
    assert res["dibentuk"] is True, "CTO tercapai -> distribusi harus terbentuk"
    al = res["alokasi"]
    assert to_decimal(cash_mod.saldo_laci(s)) == laci_sebelum - to_decimal(al["total"]), \
        "Seluruh porsi (70% + 30%) harus keluar dari Laci"
    assert to_decimal(cash_mod.master_kas(s)) == master_sebelum - to_decimal(al["cash_out"]), \
        "Master Kas hanya turun 70% (Hak Kas Aset pindah lokasi, bukan keluar)"
    cek("setelah distribusi")
    s.close()


def test_modal_keluar_pada_status_cash(client, db):
    """Owner: Modal keluar dari kas saat CASH, bukan saat DONE."""
    import models
    import cash as cash_mod
    o = _order(db, "PY-MODAL-CASH", "DONE", harga=500000, modal=(150000, 50000, 0))
    _pay_row(db, o, "DP", 200000)
    db.commit()
    n_awal = db.query(models.KasEntry).filter(
        models.KasEntry.sumber == "MODAL").count()

    # DONE -> CASH. Neither DONE (via receive/path) nor status alone triggers
    # modal cash-out; only the CASH event does.
    adm = _token(db, "pytest_admin", "ADMIN")
    r = client.put("/api/orders/%d" % o.id, headers=adm, json={"status": "CASH"})
    assert r.status_code == 200, r.text
    db.expire_all()

    n_akhir = db.query(models.KasEntry).filter(
        models.KasEntry.sumber == "MODAL").count()
    assert n_akhir > n_awal, "Modal harus tercatat sebagai mutasi kas saat CASH"
    # Idempoten: replay CASH tidak menambah mutasi modal lagi.
    r2 = client.put("/api/orders/%d" % o.id, headers=adm,
                    json={"status": "CASH", "status_note": "koreksi"})
    assert r2.status_code == 200, r2.text
    db.expire_all()
    n_replay = db.query(models.KasEntry).filter(
        models.KasEntry.sumber == "MODAL").count()
    assert n_replay == n_akhir, "Replay CASH tidak boleh menggandakan mutasi modal"


def _pay_row(db, order, kind, amount):
    import models
    r = models.Payment(service_order_id=order.id, kind=kind,
                       amount=to_decimal(amount), created_at=datetime.now())
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


def _beban(db, kategori, nilai):
    import models
    import cash as cash_mod
    e = models.Expense(kategori=kategori, uraian="b", nilai=to_decimal(nilai),
                       created_at=datetime.now())
    db.add(e)
    db.commit()
    db.refresh(e)
    cash_mod.catat_beban(db, e)
    db.commit()
    return e
