# -*- coding: utf-8 -*-
"""Regression: migrasi data legacy TIDAK boleh menulis Payment Ledger berulang.

Bug yang dikunci di sini (terbukti 2026-10-08):
`_migrate_status_data()` di `backend/main.py` berjalan SETIAP startup. Untuk
order berstatus CASH ia menulis satu baris `PELUNASAN` tanpa guard sama sekali,
sehingga tiap restart menambah baris lagi. Karena `statusflow.payment_summary`
menjumlahkan SEMUA baris `payments`, dan `routers/kas.period_rows` juga
menalkannya penuh, duplikat langsung menjadi arus kas fiktif.

Yang diuji:
1. Menjalankan migrasi dua kali berturut-turut = jumlah baris Payment tetap.
2. Order CASH yang sudah punya ledger (dari event CASH) tidak digandakan.
3. Order CASH legacy tanpa ledger tetap dapat backfill satu kali saja.
4. Replay event CASH tidak menambah baris Payment baru.
"""
from datetime import datetime, timedelta
from decimal import Decimal

from money import to_decimal


def _cash_order(db, no, harga):
    import models
    cust = db.query(models.Customer).filter(
        models.Customer.name == "Pytest Customer").first()
    o = models.ServiceOrder(
        no_servis=no, customer_id=cust.id, device="PY", brand="PY", model="M1",
        status="CASH", service_date=datetime.now().date(),
        final_price=to_decimal(harga), estimate=to_decimal(harga),
        repair_plan="Ganti LCD", technician="Budi", warranty_months=1,
        part_cost=to_decimal(100000), modal_jasa=to_decimal(50000),
        modal_lainnya=to_decimal(0), payment=to_decimal(0),
        created_at=datetime.now(),
    )
    db.add(o)
    db.commit()
    db.refresh(o)
    return o


def _n_payment(db, order_id):
    import models
    return db.query(models.Payment).filter(
        models.Payment.service_order_id == order_id).count()


def test_migrasi_legacy_cash_idempoten(client, db):
    """Jalankan _migrate_status_data() berulang -> Payment Ledger tidak bertambah."""
    import models
    import main

    # (1) order CASH yang SUDAH punya ledger (mis. dari event CASH)
    o1 = _cash_order(db, "PY-IDEM-ADA", 500000)
    db.add(models.Payment(service_order_id=o1.id, kind="PELUNASAN",
                          amount=to_decimal(500000), created_at=datetime.now()))
    db.commit()
    n1_awal = _n_payment(db, o1.id)
    assert n1_awal == 1

    # (2) order CASH legacy: belum ada baris Payment sama sekali
    o2 = _cash_order(db, "PY-IDEM-BARU", 750000)
    n2_awal = _n_payment(db, o2.id)
    assert n2_awal == 0, "order legacy harus mulai tanpa ledger"

    # Jalankan migrasi 3x berturut-turut (setiap startup aplikasi)
    for _ in range(3):
        main._migrate_status_data()

    db.expire_all()
    assert _n_payment(db, o1.id) == n1_awal, \
        "order yang sudah punya ledger TIDAK boleh digandakan migrasi"
    assert _n_payment(db, o2.id) == 1, \
        "order legacy hanya boleh di-backfill SATU KALI"

    # Nominal pun harus pas: tidak boleh melebihi kewajiban
    pays = db.query(models.Payment).filter(
        models.Payment.service_order_id == o2.id).all()
    total = sum(to_decimal(p.amount) for p in pays)
    assert total == to_decimal(750000), "backfill tidak boleh melebihi kewajiban"


def test_replay_cash_tidak_tambah_payment(client, db, auth):
    """Replay event CASH (koreksi dengan catatan) tidak boleh menambah baris."""
    import models
    o = _cash_order(db, "PY-IDEM-REPLAY", 600000)
    db.add(models.Payment(service_order_id=o.id, kind="PELUNASAN",
                          amount=to_decimal(600000), created_at=datetime.now()))
    db.commit()
    n_awal = _n_payment(db, o.id)

    # CASH -> CASH butuh catatan (status terminal)
    r = client.put("/api/orders/%d" % o.id, headers=auth,
                   json={"status": "CASH", "status_note": "koreksi admin"})
    assert r.status_code == 200, r.text
    db.expire_all()

    n_akhir = _n_payment(db, o.id)
    assert n_akhir == n_awal, \
        "Replay CASH tidak boleh membuat PELUNASAN tambahan (sisa sudah 0)"
    pays = db.query(models.Payment).filter(
        models.Payment.service_order_id == o.id).all()
    total = sum(to_decimal(p.amount) for p in pays)
    assert total == to_decimal(600000), "total bayar harus tetap = kewajiban"