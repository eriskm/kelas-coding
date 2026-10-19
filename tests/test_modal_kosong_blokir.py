# -*- coding: utf-8 -*-
"""Modal yang diisi SETELAH unit CASH harus tetap keluar dari Laci.

Owner (kas periode 4, 2026-10-19): "ada urutan distribusi uang yang belum
sesuai ... sudah keluar Harga Final di Mutasi ini sudah dianggap uang
masuk, padahal secara real belum".

Yang sebenarnya terjadi (bukti dari DB):

    SV-20261019-2550   Masuk 350.000   Modal Keluar        0
    SV-20261019-6923   Masuk 450.000   Modal Keluar        0

Uangnya masuk benar (Payment PELUNASAN tercatat, jadi LUNAS - itu yang
dipakai Nota Garansi). Yang HILANG adalah modal keluar. Penyebabnya
`cash.catat_modal` idempoten berdasarkan KEHADIRAN entri per komponen:
waktu unit pertama kali jadi CASH, modalnya masih kosong sehingga tidak
ada yang dicatat; setelah Admin mengisi modal, `catat_modal` melihat
"sudah pernah" lalu MELewatkannya.

`cash.catat_modal_selisih` sudah dibuat untuk menutup lubang itu, tapi
hanya dipanggil dari `closing.py:140` -- yaitu HANYA saat Tutup Kas.
Selama periode berjalan, Mutasi Kas tetap salah dan distribusi ikut
dihitung dari laba yang terlalu besar.

Test ini mengunci:
  - modal diisi belakangan pada unit CASH -> tercatat keluar dari Laci;
  - berulang / idempoten -> tidak pernah dobel;
  - modal yang dikoreksi -> tercatat selisihnya, bukan angka penuh.

Plus: Tutup Kas harus MEMBLOKIR (bukan sekadar peringatan) selama masih
ada unit CASH bermodal kosong tanpa centang "Tanpa Modal".
"""
from datetime import datetime, timedelta
from decimal import Decimal

import pytest


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Helper
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _bersihkan(db):
    """Hanya order milik test ini (prefix MKK-), bukan order lain.

    `KasEntry` WAJIB ikut dihapus: entri Modal disimpan dengan `ref_id` =
    id order, dan SQLite bisa memakai ulang id itu. Kalau tidak dihapus,
    sisa entri test sebelumnya ikut terhitung dan test gagal bukan karena
    salahnya fitur.
    """
    import models
    from cash import SUMBER_MODAL
    ids = [i[0] for i in db.query(models.ServiceOrder.id).filter(
        models.ServiceOrder.no_servis.like("MKK-%")).all()]
    if ids:
        db.query(models.KasEntry).filter(
            models.KasEntry.sumber == SUMBER_MODAL,
            models.KasEntry.ref_id.in_(ids)).delete(synchronize_session=False)
        db.query(models.Payment).filter(
            models.Payment.service_order_id.in_(ids)).delete(
            synchronize_session=False)
        db.query(models.ServiceOrder).filter(
            models.ServiceOrder.id.in_(ids)).delete(synchronize_session=False)
    db.commit(); db.expunge_all()


def _auth(db):
    import models
    u = db.query(models.User).filter(
        models.User.username == "pytest_admin").first()
    if u is None:
        u = models.User(username="pytest_admin", display_name="Pytest Admin",
                        role="ADMIN", passcode_hash="x", passcode_salt="y",
                        active=True)
        db.add(u); db.commit(); db.refresh(u)
    t = db.query(models.AuthToken).filter(
        models.AuthToken.token == "pytest-token-admin").first()
    if t is None:
        db.add(models.AuthToken(token="pytest-token-admin", user_id=u.id,
                                expires_at=datetime.now() + timedelta(days=2)))
        db.commit()
    db.expunge_all()
    return {"Authorization": "Bearer pytest-token-admin"}


@pytest.fixture(autouse=True)
def _bersihkan_setelah_test(db):
    """Bersihkan order test ini SETELAH tiap test.

    Sandbox DB dipakai bersama antar-test dalam satu sesi pytest. Order
    CASH bermodal kosong yang tertinggal dari test ini akan membuat
    `test_periode_kas` (dan test close lain) gagal, karena Tutup Kas
    memang diblokir selama unit seperti itu ada.
    """
    yield
    _bersihkan(db)


def _order_cash(db, no, part=0, jasa=0, lain=0, tanpa_modal=0, harga=500000,
                status="CASH"):
    """Unit CASH. `taken_at` dipakai sebagai momen periode."""
    import models
    c = db.query(models.Customer).filter(
        models.Customer.name == "MKK").first()
    if c is None:
        c = models.Customer(name="MKK", phone="0800", created_at=datetime.now())
        db.add(c); db.flush()
    o = models.ServiceOrder(
no_servis=no, customer_id=c.id, device="MKK", status=status,
        unit_status="DIAMBIL" if status == "CASH" else "DI TOKO", service_date=datetime.now().date(),
        created_at=datetime.now(), taken_at=datetime.now(),
        final_price=Decimal(harga), estimate=Decimal(harga),
        repair_plan="x", technician="B", warranty_months=1,
        part_cost=Decimal(part), modal_jasa=Decimal(jasa),
        modal_lainnya=Decimal(lain), tanpa_modal=tanpa_modal,
        laba_bersih=Decimal(0), lunas_at=datetime.now(),
        lunas_date=datetime.now().date())
    db.add(o)
    db.flush()
    return o


def _modal_entries(db, order_id):
    """Entri kas kategori MODAL untuk satu unit (tanpa DP/pembayaran)."""
    import models
    from cash import SUMBER_MODAL
    return db.query(models.KasEntry).filter(
        models.KasEntry.sumber == SUMBER_MODAL,
        models.KasEntry.ref_id == order_id).all()


def _total_modal_keluar(db, order_id, kode):
    import models
    from cash import SUMBER_MODAL
    tot = 0
    for e in db.query(models.KasEntry).filter(
            models.KasEntry.sumber == SUMBER_MODAL,
            models.KasEntry.ref_type == kode,
            models.KasEntry.ref_id == order_id).all():
        n = Decimal(str(e.nominal or 0))
        tot += n if (e.jenis or "").lower() == "keluar" else -n
    return tot


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# 1. Modal diisi SETELAH CASH harus tercatat keluar dari Laci
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def test_modal_diisi_setelah_cash_tercatat_keluar(client, db):
    auth = _auth(db)
    _bersihkan(db)

    o = _order_cash(db, "MKK-LAMBAT-1", part=0, jasa=0)
    oid = o.id
    db.commit(); db.expunge_all()

    # Sebelum modal diisi: belum ada modal keluar (memang belum ada biaya).
    assert _total_modal_keluar(db, oid, "MODAL_PART") == 0

    # Admin mengisi modal Part SETELAH unit sudah CASH.
    r = client.put("/api/orders/%d" % oid, headers=auth,
                   json={"part_cost": 200000, "modal_jasa": 50000})
    assert r.status_code == 200, r.text

    db.expunge_all()
    assert _total_modal_keluar(db, oid, "MODAL_PART") == 200000, \
        "Modal Part yang diisi setelah CASH harus keluar dari Laci"
    assert _total_modal_keluar(db, oid, "MODAL_JASA") == 50000, \
        "Modal Jasa yang diisi setelah CASH harus keluar dari Laci"


def test_catch_up_modal_arahnya_KELUAR_bukan_masuk(client, db):
    """Modal harus MENGURANGI Laci. Arahnya tidak boleh terbalik.

    `cash.catat_modal_selisih` pernah menulis "Masuk" untuk selisih positif,
    sehingga catch-up modal justru menambah saldo Laci. Itu kebalikan dari
    OD-LOCK-01 dan tidak terlihat sampai Tutup Kas pertama yang punya
    selisih modal tertunda.
    """
    auth = _auth(db)
    _bersihkan(db)

    o = _order_cash(db, "MKK-ARAH", part=0, jasa=0)
    oid = o.id
    db.commit(); db.expunge_all()

    r = client.put("/api/orders/%d" % oid, headers=auth, json={"part_cost": 200000})
    assert r.status_code == 200, r.text
    db.expunge_all()

    entri = [e for e in _modal_entries(db, oid) if e.ref_type == "MODAL_PART"]
    assert entri, "entri Modal Part harus dibuat"
    for e in entri:
        assert (e.jenis or "").lower() == "keluar", \
            "modal yang belum tercatat harus KELUAR dari Laci, dapat jenis=%r" % e.jenis


def test_modal_dikoreksi_turun_menghasilkan_masuk(client, db):
    """Modal dikoreksi turun -> bagian yang kelewat KEMBALI ke Laci."""
    auth = _auth(db)
    _bersihkan(db)

    o = _order_cash(db, "MKK-ARAH-TURUN", part=300000, jasa=0)
    oid = o.id
    # Rekam modal penuh seperti yang terjadi saat event CASH.
    import cash as _cash
    db.expunge_all()
    o2 = db.query(__import__("models").ServiceOrder).get(oid)
    _cash.catat_modal(db, o2, actor="test")
    db.commit(); db.expunge_all()

    assert _total_modal_keluar(db, oid, "MODAL_PART") == 300000

    r = client.put("/api/orders/%d" % oid, headers=auth, json={"part_cost": 100000})
    assert r.status_code == 200, r.text
    db.expunge_all()

    # 300.000 keluar, 200.000 kembali -> net 100.000 keluar.
    assert _total_modal_keluar(db, oid, "MODAL_PART") == 100000, \
        "modal tercatat harus menyesuaikan koreksi (net 100.000 keluar)"
    ada_masuk = [e for e in _modal_entries(db, oid)
                 if (e.jenis or "").lower() == "masuk"]
    assert ada_masuk, "koreksi turun harus punya entri Masuk pengembalian"


def test_modal_diisi_berulang_tidak_doblir(client, db):
    """Simpan ulang nilai yang sama -> tetap satu entri, bukan dua."""
    auth = _auth(db)
    _bersihkan(db)

    o = _order_cash(db, "MKK-IDEMPOTEN", part=0, jasa=0)
    oid = o.id
    db.commit(); db.expunge_all()

    for _ in range(3):
        r = client.put("/api/orders/%d" % oid, headers=auth,
                       json={"part_cost": 150000})
        assert r.status_code == 200, r.text
    db.expunge_all()

    assert _total_modal_keluar(db, oid, "MODAL_PART") == 150000, \
        "menyimpan modal yang sama berulang tidak boleh menggandakan keluar"
    n = len([e for e in _modal_entries(db, oid)
             if e.ref_type == "MODAL_PART" and (e.jenis or "").lower() == "keluar"])
    assert n == 1, "harus tepat 1 entri Keluar Modal Part, dapat %d" % n


def test_koreksi_modal_setelah_cash_mencatat_selisih(client, db):
    """Naik dari 100.000 ke 300.000 -> hanya tambahan 200.000 yang keluar."""
    auth = _auth(db)
    _bersihkan(db)

    o = _order_cash(db, "MKK-KOREKSI", part=100000, jasa=0)
    oid = o.id
    db.commit(); db.expunge_all()

    r = client.put("/api/orders/%d" % oid, headers=auth, json={"part_cost": 300000})
    assert r.status_code == 200, r.text
    db.expunge_all()

    assert _total_modal_keluar(db, oid, "MODAL_PART") == 300000, \
        "total modal tercatat harus sama dengan modal sekarang (300.000)"


def test_modal_nol_tidak_menghasilkan_mutasi(client, db):
    """Modal 0 tetap 0 -- tidak ada entri bodily untuk angka nol."""
    auth = _auth(db)
    _bersihkan(db)

    o = _order_cash(db, "MKK-NOL", part=0, jasa=0)
    oid = o.id
    db.commit(); db.expunge_all()

    r = client.put("/api/orders/%d" % oid, headers=auth,
                   json={"part_cost": 0, "modal_jasa": 0})
    assert r.status_code == 200, r.text
    db.expunge_all()

    assert _modal_entries(db, oid) == [], \
        "modal 0 tidak boleh membuat entri kas"


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# 2. Tutup Kas MEMBLOKIR unit modal kosong
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _periode_legal(db):
    """Buat periode aktif yang umurnya > 60 detik (guard 'terlalu baru')."""
    import models
    from datetime import datetime as dt
    p = db.query(models.KasPeriod).filter(
        models.KasPeriod.status == "OPEN").first()
    if p is None:
        p = models.KasPeriod(status="OPEN", created_at=dt.now() - timedelta(days=1),
                             start_at=dt.now() - timedelta(days=1))
        db.add(p)
    # Mundurkan supaya guard usia tidak menutupi guard modal.
    lama = dt.now() - timedelta(days=2)
    p.created_at = lama
    p.start_at = lama
    db.commit(); db.expunge_all()
    return p


def test_tutup_kas_diblokir_oleh_modal_kosong(client, db):
    auth = _auth(db)
    _bersihkan(db)
    _order_cash(db, "MKK-BLOKIR", part=0, jasa=0)
    db.commit(); db.expunge_all()
    _periode_legal(db)

    r = client.post("/api/kas/close", headers=auth, json={})
    assert r.status_code == 400, \
        "Tutup Kas harus DITOLAK (400) karena ada unit CASH modal kosong, got %s: %s" \
        % (r.status_code, r.text)
    assert "MKK-BLOKIR" in r.text, \
        "pesan harus menyebut nomor unit yang modalnya kosong: %s" % r.text


def test_tutup_kas_lolos_kalau_modal_sudah_terisi(client, db):
    """Unit bermodal tidak boleh masuk daftar yang memblokir Tutup Kas.

    Diuji lewat helper, BUKAN lewat HTTP: memanggil `POST /api/kas/close`
    yang berhasil akan benar-benar MENUTUP periode di sandbox, dan itu
    merusak semua test yang dijalankan setelahnya.
    """
    from routers.kas import _modal_kosong_items
    auth = _auth(db)
    _bersihkan(db)
    _order_cash(db, "MKK-AMAN-1", part=200000, jasa=0)
    _order_cash(db, "MKK-AMAN-2", part=0, jasa=150000)
    db.commit(); db.expunge_all()

    kosong, _ = _modal_kosong_items(db, None, None)
    assert not any(str(x["no_servis"]).startswith("MKK-") for x in kosong), \
        "unit yang sudah punya modal tidak boleh diblokir: %s" % kosong


def test_tutup_kas_lolos_kalau_sengaja_tanpa_modal(client, db):
    """Centang 'Tanpa Modal (sengaja 0)' = jalur yang sudah disetujui Owner."""
    from routers.kas import _modal_kosong_items
    auth = _auth(db)
    _bersihkan(db)
    _order_cash(db, "MKK-SENGJAJA", part=0, jasa=0, tanpa_modal=1)
    db.commit(); db.expunge_all()

    kosong, _ = _modal_kosong_items(db, None, None)
    assert not any(str(x["no_servis"]).startswith("MKK-") for x in kosong), \
        "unit bertanda Tanpa Modal tidak boleh diblokir: %s" % kosong


def test_guard_memblokir_hanya_yang_benar_benar_kosong(client, db):
    """Semua kombinasi modal harus diklasifikasikan dengan benar."""
    from routers.kas import _modal_kosong_items
    auth = _auth(db)
    _bersihkan(db)
    _order_cash(db, "MKK-X0", part=0, jasa=0)                                   # blokir
    _order_cash(db, "MKK-X1", part=1, jasa=0)                                    # lolos
    _order_cash(db, "MKK-X2", part=0, jasa=0, tanpa_modal=1)                     # lolos
    _order_cash(db, "MKK-X3", part=0, jasa=0, lain=1000)                         # lolos
    _order_cash(db, "MKK-X4", part=0, jasa=0, status="DONE")                     # lolos
    db.commit(); db.expunge_all()

    kosong, _ = _modal_kosong_items(db, None, None)
    punya = set(str(x["no_servis"]) for x in kosong)
    assert "MKK-X0" in punya, kosong
    for bebas in ("MKK-X1", "MKK-X2", "MKK-X3", "MKK-X4"):
        assert bebas not in punya, \
            "%s seharusnya tidak memblokir Tutup Kas, tapi masuk daftar: %s" % (bebas, kosong)
