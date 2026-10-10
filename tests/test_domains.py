# -*- coding: utf-8 -*-
"""P2-14 (ID-13) — regression baseline: Warranty, Refund, Hutang Beban, Inventory,
Notification, dan idempotency key (P2-14)."""
from datetime import date, datetime, timedelta

import cash
import expense_debt as debt
import inventory as inv
import notifications as notif
import refunds as ref
from money import to_decimal


def _unit(db, no, harga=500000, warranty=3, lunas=True):
    import models
    cust = db.query(models.Customer).filter(models.Customer.name == "Pytest Customer").first()
    o = models.ServiceOrder(no_servis=no, customer_id=cust.id, device="PY", status="SELESAI",
                            service_date=date.today(), final_price=to_decimal(harga),
                            estimate=to_decimal(harga), warranty_months=warranty)
    for f in ("part_cost", "modal_jasa", "modal_lainnya", "payment"):
        setattr(o, f, to_decimal("0"))
    db.add(o)
    db.commit()
    db.refresh(o)
    if lunas:
        db.add(models.Payment(service_order_id=o.id, kind="PELUNASAN",
                              amount=to_decimal(harga), method="CASH", note="lunas"))
        db.commit()
        from statusflow import lock_lunas_moment
        lock_lunas_moment(o, datetime.now())
    return o


def test_warranty_record_hanya_dari_unit_lunas_dan_bergaransi(client, auth, db):
    import models
    o_ok = _unit(db, "PY-WAR-OK")
    o_noga = _unit(db, "PY-WAR-NOGA", warranty=0)
    o_belum = _unit(db, "PY-WAR-BELUM", lunas=False)

    r_ok = client.post("/api/claims/receive", headers=auth,
                       json={"service_order_id": o_ok.id, "complaint": "layar mati"})
    assert r_ok.status_code == 201, r_ok.text
    assert db.query(models.WarrantyClaim).filter(
        models.WarrantyClaim.service_order_id == o_ok.id).count() == 1

    for o in (o_noga, o_belum):
        r = client.post("/api/claims/receive", headers=auth,
                        json={"service_order_id": o.id, "complaint": "ditolak"})
        assert r.status_code == 409, r.text
        assert db.query(models.WarrantyClaim).filter(
            models.WarrantyClaim.service_order_id == o.id).count() == 0


def test_refund_3_jenis_sumber_dana_beda(client, auth, db):
    import models
    cash.catat_mutasi(db, cash.LAYER_KAS_ASET, "Masuk", "Kas Aset", "PY modal", to_decimal("1000000"))
    cash.catat_mutasi(db, cash.LAYER_LACI, "Masuk", "Saldo Awal", "PY modal laci", to_decimal("1000000"))
    db.commit()

    o_dp = _unit(db, "PY-REF-DP", 300000)
    db.add(models.Payment(service_order_id=o_dp.id, kind="DP",
                          amount=to_decimal("300000"), method="CASH", note="dp"))
    db.commit()
    r_dp = client.post("/api/refunds/dp", headers=auth,
                       json={"service_order_id": o_dp.id, "nominal": 300000})
    assert r_dp.status_code == 200, r_dp.text
    assert r_dp.json()["refund"]["sumber_dana"] == "LACI"

    claim = models.WarrantyClaim(claim_no="PY-CLM-1", service_order_id=_unit(db, "PY-REF-WAR").id,
                                 customer_id=1, claim_date=date.today(),
                                 warranty_status="VALID", decision="DITERIMA",
                                 claim_status="DITERIMA", customer_cost=to_decimal("450000"),
                                 internal_cost=to_decimal("0"))
    db.add(claim)
    db.commit()
    r_gar = client.post("/api/refunds/garansi", headers=auth,
                        json={"warranty_claim_id": claim.id, "nominal": 450000})
    assert r_gar.status_code == 200, r_gar.text
    assert r_gar.json()["refund"]["sumber_dana"] == "KAS_ASET"

    r_fc = client.post("/api/refunds/failed-cancel", headers=auth,
                       json={"service_order_id": _unit(db, "PY-REF-FC", 250000).id,
                             "nominal": 100000})
    assert r_fc.status_code == 200, r_fc.text
    assert r_fc.json()["refund"]["sumber_dana"] == "LACI"


def test_hutang_beban_tidak_muncul_di_buku_kas(db):
    import models
    from routers.kas import period_rows
    cash.catat_mutasi(db, cash.LAYER_KAS_ASET, "Masuk", "Kas Aset", "PY modal", to_decimal("1000"))
    db.commit()
    rows = period_rows(db, datetime.min, datetime.max)
    kategori = {r["kategori"] for r in rows}
    assert not any("Defisit Beban" in (k or "") or "Hutang Beban" in (k or "") for k in kategori)
    # dan saldo Laci tidak pernah menyentuh hutang
    assert cash.saldo_layer(db, cash.LAYER_LACI) == cash.saldo_laci(db)


def test_inventory_decrement_dan_pembatalan_idempoten(db):
    import models
    part = models.Sparepart(kategori="LCD", merek="PY", jenis="PY-LCD", device="PY",
                            qty=5, harga_beli=to_decimal("100000"),
                            harga_jual=to_decimal("150000"), tanggal=date.today())
    unit = _unit(db, "PY-INV-1", 500000)
    db.add_all([part])
    db.commit()
    db.refresh(part)

    # pakai melebihi stok -> StockConflict
    try:
        inv.catat_pakai(db, part.id, 99, unit.id)
        raise AssertionError("harusnya StockConflict")
    except inv.StockConflict:
        db.rollback()

    pakai = inv.catat_pakai(db, part.id, 3, unit.id)
    db.commit()
    assert pakai["qty_sesudah"] == 2
    batal1 = inv.batalkan_pakai(db, pakai["usage"].id)
    db.commit()
    assert batal1["idempotent"] is False and batal1["qty_sesudah"] == 5
    batal2 = inv.batalkan_pakai(db, pakai["usage"].id)
    db.commit()
    assert batal2["idempotent"] is True
    assert db.get(models.Sparepart, part.id).qty == 5


def test_notifikasi_anti_duplikat(db):
    n1 = notif.kirim(db, notif.EVENT_UNIT_BARU, "service_order", 424242,
                     data={"no_servis": "PY"}, actor="pytest")
    db.commit()
    n2 = notif.kirim(db, notif.EVENT_UNIT_BARU, "service_order", 424242,
                     data={"no_servis": "PY"}, actor="pytest")
    db.commit()
    assert n1["status"] == notif.STATUS_DIANTREKAN
    assert n2["status"] == notif.STATUS_SKIPPED_DUPLIKAT


def test_idempotency_key_mencegah_retry_ganda(client, auth, db):
    import models
    o = _unit(db, "PY-IDEM", 500000, lunas=False)
    payload = {"service_order_id": o.id, "kind": "PELUNASAN",
               "amount": 500000, "method": "CASH"}
    hdr = dict(auth)
    hdr["Idempotency-Key"] = "pytest-idem-1"
    r1 = client.post("/api/payments", headers=hdr, json=payload)
    assert r1.status_code == 201, r1.text
    n1 = db.query(models.Payment).filter(models.Payment.service_order_id == o.id).count()
    # retry dengan key sama -> tidak menambah payment
    r2 = client.post("/api/payments", headers=hdr, json=payload)
    n2 = db.query(models.Payment).filter(models.Payment.service_order_id == o.id).count()
    assert n2 == n1, (r2.status_code, r2.text)
    # key sama dengan request berbeda -> 409
    hdr2 = dict(auth)
    hdr2["Idempotency-Key"] = "pytest-idem-1"
    r3 = client.post("/api/payments", headers=hdr2,
                     json=dict(payload, amount=123000))
    assert r3.status_code == 409, r3.text