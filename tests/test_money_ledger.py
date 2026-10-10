# -*- coding: utf-8 -*-
"""P2-14 (ID-13) — regression baseline: presisi uang & Payment Ledger (Q10/Q3/Q17)."""
from datetime import date, datetime, timedelta

from money import quantize, to_decimal
from statusflow import kewajiban, lock_lunas_moment, payment_summary


def test_monetary_arithmetic_tidak_ada_floating_error():
    assert to_decimal("0.1") + to_decimal("0.2") == to_decimal("0.3")
    assert to_decimal("1000") * to_decimal("0.30") == to_decimal("300.00")
    assert quantize(to_decimal("1.005")) == to_decimal("1.01")


def test_lunas_hanya_dari_payment_ledger(db):
    import models
    o = cust = db.query(models.Customer).filter(models.Customer.name == "Pytest Customer").first()
    o = models.ServiceOrder(no_servis="PY-LUNAS", customer_id=cust.id, device="PY", status="PERBAIKAN",
                            service_date=date.today(), final_price=to_decimal("1000000"),
                            estimate=to_decimal("1000000"))
    for f in ("part_cost", "modal_jasa", "modal_lainnya", "payment"):
        setattr(o, f, to_decimal("0"))
    db.add(o)
    db.commit()
    db.refresh(o)

    assert kewajiban(o) == to_decimal("1000000")
    # tanpa payment -> belum lunas
    assert payment_summary(o, [])["payment_status"] == "BELUM LUNAS"
    # DP sebagian saja belum LUNAS (harus ada pelunasan sisa)
    db.add(models.Payment(service_order_id=o.id, kind="DP",
                          amount=to_decimal("400000"), method="CASH", note="dp"))
    db.commit()
    pays = db.query(models.Payment).filter(models.Payment.service_order_id == o.id).all()
    assert payment_summary(o, pays)["payment_status"] == "BELUM LUNAS"
    # pelunasan -> LUNAS
    db.add(models.Payment(service_order_id=o.id, kind="PELUNASAN",
                          amount=to_decimal("600000"), method="CASH", note="lunas"))
    db.commit()
    pays = db.query(models.Payment).filter(models.Payment.service_order_id == o.id).all()
    assert payment_summary(o, pays)["payment_status"] == "LUNAS"
    lock_lunas_moment(o, datetime.now())


def test_endpoint_payment_menolak_setelah_lunas(client, auth, db):
    import models
    o = cust = db.query(models.Customer).filter(models.Customer.name == "Pytest Customer").first()
    o = models.ServiceOrder(no_servis="PY-LUNAS2", customer_id=cust.id, device="PY", status="SELESAI",
                            service_date=date.today(), final_price=to_decimal("500000"),
                            estimate=to_decimal("500000"))
    for f in ("part_cost", "modal_jasa", "modal_lainnya", "payment"):
        setattr(o, f, to_decimal("0"))
    db.add(o)
    db.commit()
    db.refresh(o)
    db.add(models.Payment(service_order_id=o.id, kind="PELUNASAN",
                          amount=to_decimal("500000"), method="CASH", note="lunas"))
    db.commit()

    r = client.post("/api/payments", headers=auth, json={
        "service_order_id": o.id, "kind": "PELUNASAN", "amount": 1000, "method": "CASH"})
    assert r.status_code == 400, r.text
    assert "LUNAS" in (r.json().get("detail") or "")


def test_tidak_ada_kolom_float_pada_tabel_monetary(db):
    from models import MONEY
    assert MONEY.precision == 18 and MONEY.scale == 2