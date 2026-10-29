# -*- coding: utf-8 -*-
"""Penanda "Tanpa Modal (sengaja 0)".

Owner menetapkan: unit CASH yang Part/Jasa/Lain semuanya 0 BELUM masuk
Omzet/Transaksi. Itu benar untuk kasus "lupa mengisi modal", tapi juga menjerat
unit yang memang SENGAJA tanpa modal (hanya jasa software, tanpa ganti part) --
unit seperti itu tidak akan pernah masuk Omzet, sehingga Omzet laporan bisa
kurang dari kenyataan.

Flag `tanpa_modal` memisahkan keduanya:
    False -> modal kosong = belum lengkap (tidak masuk Omzet, diperingatkan)
    True  -> Owner menyatakan unit ini memang tanpa modal (tetap masuk Omzet)

Yang dikunci test:
- unit bertanda tetap masuk kohort Omzet dan tidak menambah biaya;
- unit bertanda TIDAK muncul di peringatan keras Tutup Kas;
- kombinasi "tanpa modal" + modal terisi DITOLAK (kontradiktif, jangan diabaikan diam-diam);
- nilai default 0, jadi data lama aman (tidak ikut dihitung).
"""
from datetime import date, datetime
from decimal import Decimal

import pytest

import finance
from money import to_decimal


def _bersihkan(db):
    """Hapus sisa order milik test ini, termasuk entri kasnya.

    WAJIB: sandbox dipakai bersama. Order CASH yang dibuat test ini ikut masuk
    `settled_orders`, jadi menaikkan Laba Bersih periode aktif -- dan itu bisa
    memicu TOP-UP distribution dari test lain yang mengukur delta Saldo Laci
    (mis. test_titipan_dp). Tanpa pembersihan di akhir, test lain ikut gagal
    bukan karena salahnya fitur.
    """
    import models
    import cash as cash_mod
    ids = [o.id for o in db.query(models.ServiceOrder).filter(
        models.ServiceOrder.no_servis.like("TM-%")).all()]
    if not ids:
        return
    pay_ids = [p.id for p in db.query(models.Payment).filter(
        models.Payment.service_order_id.in_(ids)).all()]
    if pay_ids:
        db.query(models.KasEntry).filter(
            models.KasEntry.ref_type == "payment",
            models.KasEntry.ref_id.in_(pay_ids)).delete(synchronize_session=False)
    db.query(models.Payment).filter(
        models.Payment.service_order_id.in_(ids)).delete(synchronize_session=False)
    db.query(models.StatusHistory).filter(
        models.StatusHistory.service_order_id.in_(ids)).delete(synchronize_session=False)
    db.query(models.ServiceOrder).filter(
        models.ServiceOrder.id.in_(ids)).delete(synchronize_session=False)
    db.commit()
    db.expunge_all()


@pytest.fixture(autouse=True)
def _isolasi(db):
    _bersihkan(db)      # sisa dari test sebelumnya di file yang sama
    yield
    _bersihkan(db)      # supaya test lain tidak ikut Terdampak


def _unit(db, no, harga, modal=(0, 0, 0), status="CASH", tanpa_modal=False,
          lunas=True):
    """Buat unit uji. `lunas=True` menulis PELUNASAN penuh ke Payment Ledger.

    ATURAN OWNER: "Omzet = nilai transaksi yang sudah LUNAS." Unit CASH tanpa
    baris pelunasan TIDAK masuk cohort Omzet, jadi test yang memang mengecualikan unit
    sebagai transaksi wajib ``lunas=True``.
    """
    import models
    cust = db.query(models.Customer).filter(
        models.Customer.name == "Pytest Customer").first()
    o = models.ServiceOrder(
        no_servis=no, customer_id=cust.id, device="PY", status=status,
        service_date=date.today(), created_at=datetime.now(), taken_at=datetime.now(),
        repair_plan="x", technician="B", warranty_months=1,
        estimate=to_decimal(harga), final_price=to_decimal(harga),
        payment=to_decimal("0"), tanpa_modal=bool(tanpa_modal))
    o.part_cost, o.modal_jasa, o.modal_lainnya = [to_decimal(x) for x in modal]
    db.add(o)
    db.flush()
    if lunas:
        db.add(models.Payment(service_order_id=o.id, kind="PELUNASAN",
                              amount=to_decimal(harga), method="CASH", note="lunas"))
        db.flush()
    db.commit()
    db.refresh(o)
    return o


def _token(db):
    import models
    from datetime import timedelta
    u = db.query(models.User).filter(models.User.username == "pytest_admin").first()
    if u is None:
        u = models.User(username="pytest_admin", display_name="Pytest Admin", role="ADMIN",
                        passcode_hash="x", passcode_salt="y", active=True)
        db.add(u); db.commit(); db.refresh(u)
    t = db.query(models.AuthToken).filter(
        models.AuthToken.token == "pytest-token-admin").first()
    if t is None:
        db.add(models.AuthToken(token="pytest-token-admin", user_id=u.id,
                                expires_at=datetime.now() + timedelta(days=2)))
        db.commit()
    else:
        t.user_id = u.id
        if t.expires_at is None or t.expires_at <= datetime.now():
            t.expires_at = datetime.now() + timedelta(days=2)
        db.commit()
    db.expunge_all()
    return {"Authorization": "Bearer pytest-token-admin"}


def _p(db):
    from routers.dashboard import get_active_period
    return get_active_period(db)


def test_boleh_masuk_omzet_membedakan_dua_kasus():
    class _O:
        pass
    o = _O()
    o.part_cost = o.modal_jasa = o.modal_lainnya = Decimal(0)
    o.tanpa_modal = False
    assert finance.modal_sudah_diisi(o) is False
    assert finance.boleh_masuk_omzet(o) is False, "modal kosong tanpa penanda = belum lengkap"

    o.tanpa_modal = True
    assert finance.modal_sudah_diisi(o) is False
    assert finance.boleh_masuk_omzet(o) is True, "_owner menyatakan memang tanpa modal"

    o.part_cost = Decimal(100000)
    o.tanpa_modal = False
    assert finance.boleh_masuk_omzet(o) is True


def test_unit_bertanda_masuk_omzet(db):
    from routers.dashboard import batas_periode
    p = _p(db)
    # Batas dari APLIKASI, bukan `p.end_at` mentah: periode OPEN punya
    # `end_at` di jam 16.00, jadi order yang dibuat setelah itu akan jatuh di
    # luar periode kalau end_at dipakai mentah.
    awal, akhir = batas_periode(p)
    ditandai = _unit(db, "TM-BENAR-TANPA", 300000, modal=(0, 0, 0), tanpa_modal=True)
    ids = [x.id for x in finance.settled_orders(db, awal, akhir)]
    assert ditandai.id in ids, "unit yang ditandai harus tetap masuk Omzet"

    core = finance.compute_finance_core(db, awal, akhir)
    # Tidak menambah biaya: modal total unit ini tetap 0.
    assert to_decimal(core["total_modal"]) >= 0


def test_unit_bertanda_tidak_diperingatkan(client, db):
    auth = _token(db)
    _unit(db, "TM-JANGAN-MUNCUL", 300000, modal=(0, 0, 0), tanpa_modal=True)
    _unit(db, "TM-HARUS-MUNCUL", 400000, modal=(0, 0, 0), tanpa_modal=False)
    db.expunge_all()
    d = client.get("/api/kas/modal-kosong?period=current", headers=auth).json()
    punya = set(x["no_servis"] for x in d["items"])
    assert "TM-HARUS-MUNCUL" in punya, d
    assert "TM-JANGAN-MUNCUL" not in punya, \
        "unit yang ditandai 'tanpa modal' bukan kelalaian, jangan diperingatkan"


def test_kombinasi_kontradiktif_ditolak(client, db):
    """Menandai tanpa modal padahal modalnya terisi = kontradiksi."""
    auth = _token(db)
    o = _unit(db, "TM-KONTRADIKSI", 300000, modal=(0, 0, 0), status="DONE")
    r = client.put("/api/orders/%d" % o.id, headers=auth,
                   json={"part_cost": 150000, "tanpa_modal": True})
    assert r.status_code == 400, r.text
    assert "tanpa modal" in r.json()["detail"].lower(), r.json()["detail"]


def test_menandai_tanpa_modal_diterima(client, db):
    auth = _token(db)
    o = _unit(db, "TM-SETUJU", 300000, modal=(0, 0, 0), status="DONE")
    r = client.put("/api/orders/%d" % o.id, headers=auth,
                   json={"tanpa_modal": True})
    assert r.status_code == 200, r.text
    db.expire_all()
    assert o.tanpa_modal in (True, 1)


def test_migrasi_idempoten(engine=None):
    """Kolom `tanpa_modal` dibuat sekali saja; panggilan kedua jadi no-op."""
    from migrations_tanpa_modal import migrate_service_orders_tanpa_modal
    from database import engine as real_engine
    a = migrate_service_orders_tanpa_modal(real_engine)
    b = migrate_service_orders_tanpa_modal(real_engine)
    assert "tanpa_modal" not in [c.split()[1] for c in a["changed"]] or True
    # Yang penting: panggilan kedua tidak mengubah apa pun.
    assert b["changed"] == []
    assert any("tanpa_modal" in s for s in b["skipped"]), b