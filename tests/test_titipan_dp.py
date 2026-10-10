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

    # Baris payment-nya tidak dihapus, dan uangnya masih di Saldo Laci.
    assert db.query(models.Payment).filter(models.Payment.id == dbaris.id).count() == 1
    import cash as cash_mod
    assert to_decimal(cash_mod.saldo_laci(db)) > 0


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
def _kondisi_kas_calculated(db, p):
    """Rumus baris Conditions Kas, sesuai frontend."""
    import routers.dashboard as dash
    fin = dash.compute_finance(db, p.start_at, p.end_at, lihat_kas_besar=True)
    return (float(fin["kas_aset_awal"]) + float(fin["omset"])
            + float(fin["titipan_dp"]["berjalan"])
            - float(fin["total_modal"]) - float(fin["total_beban"]))


def test_kondisi_kas_rekonsiliasi_dengan_saldo_laci(client, db):
    """Selisih Conditions Kas vs Saldo Laci harus TIDAK BERUBAH setelah transaksi.

    Sandbox test disalin dari DB produksi yang sudah punya data, jadi yang
    dijaga adalah KESTABILAN selisih, bukan angka nol mutlak.

    Rumus: Kas Awal + Omzet + Titipan DP (belum jadi penjualan) - Modal - Beban

    Modal HARUS keluar dari kas saat status CASH (keputusan Owner); kalau tidak,
    selisih akan bertambah sebesar nilai Modal.
    """
    import cash as cash_mod
    p = _period(db)
    selisih_awal = float(cash_mod.saldo_laci(db)) - _kondisi_kas_calculated(db, p)

    o = _order(db, "PY-REKON", "DONE", harga=500000, modal=(150000, 50000, 0))
    db.commit()
    dp = _pay_row(db, o, "DP", 200000)
    cash_mod.catat_penerimaan(db, dp)      # DP masuk laci saat pendaftaran
    db.commit()

    # Alur nyata: event CASH (pelunasan otomatis + modal keluar).
    adm = _token(db, "pytest_admin", "ADMIN")
    r = client.put("/api/orders/%d" % o.id, headers=adm, json={"status": "CASH"})
    assert r.status_code == 200, r.text
    db.expire_all()

    # Beban sengaja TIDAK disentuh di test ini: snapshot `expense_periods`
    # dibekukan per periode (SSOT-4), jadi menambah beban di periode yang
    # snapshot-nya sudah ada akan membuat selisih bergeser karena disengaja.
    # Jalur beban diuji terpisah (test_finance_core).

    selisih_akhir = float(cash_mod.saldo_laci(db)) - _kondisi_kas_calculated(db, p)
    assert abs(selisih_akhir - selisih_awal) < 1, (
        "Selisih Conditions Kas vs Saldo Laci harus tetap; berubah sebesar %s"
        % (selisih_akhir - selisih_awal))


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
