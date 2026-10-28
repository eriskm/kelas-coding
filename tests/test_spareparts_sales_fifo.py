"""Tests untuk fitur Sparepart Batch FIFO dan Kasir Penjualan Langsung:
- Pengadaan Batch baru (Supplier, modal beda, qty)
- Penjualan langsung kasir dengan pemotongan stok FIFO bertingkat
- Validasi stok tidak mencukupi
- Integrasi omzet dan modal penjualan part ke dalam financial core
"""
from datetime import datetime, date, timedelta
from decimal import Decimal
import pytest
import models as m
from finance import compute_finance_core


def test_sparepart_batch_fifo_sales(client, auth, db):
    """Pastikan penjualan sparepart memprioritaskan batch tertua (FIFO)."""
    # 1. Buat sparepart master
    sp = m.Sparepart(
        kategori="LCD", merek="Apple", jenis="LCD iPhone 11 Ori",
        device="iPhone 11", qty=0, harga_beli=Decimal("120000"),
        harga_jual=Decimal("140000"), tanggal=date.today()
    )
    db.add(sp)
    db.commit()

    # 2. Tambah Batch 1 (Lama): 2 pcs @ modal 120.000, jual 140.000
    res_b1 = client.post(
        f"/api/spareparts/{sp.id}/batches",
        headers=auth,
        json={
            "supplier": "Supplier A",
            "harga_beli": 120000,
            "harga_jual": 140000,
            "qty_masuk": 2,
            "tanggal_masuk": (date.today() - timedelta(days=5)).isoformat()
        }
    )
    assert res_b1.status_code == 201
    b1_data = res_b1.json()
    assert b1_data["qty_sisa"] == 2

    # 3. Tambah Batch 2 (Baru): 48 pcs @ modal 123.000, jual 143.000
    res_b2 = client.post(
        f"/api/spareparts/{sp.id}/batches",
        headers=auth,
        json={
            "supplier": "Supplier B",
            "harga_beli": 123000,
            "harga_jual": 143000,
            "qty_masuk": 48,
            "tanggal_masuk": date.today().isoformat()
        }
    )
    assert res_b2.status_code == 201
    b2_data = res_b2.json()
    assert b2_data["qty_sisa"] == 48

    # Cek total stok master
    db.refresh(sp)
    assert sp.qty == 50

    # 4. Lakukan penjualan 3 pcs (2 pcs dari Batch 1 @ 140rb + 1 pcs dari Batch 2 @ 143rb)
    sale_payload = {
        "customer_name": "Pak Hendra",
        "customer_phone": "0812345678",
        "payment_method": "CASH",
        "items": [
            {"sparepart_id": sp.id, "qty": 3}
        ]
    }
    res_sale = client.post("/api/spareparts/sales", headers=auth, json=sale_payload)
    assert res_sale.status_code == 201
    sale_data = res_sale.json()

    # Omzet = (2 * 140.000) + (1 * 143.000) = 280.000 + 143.000 = 423.000
    assert float(sale_data["total_omzet"]) == 423000.0
    # Modal = (2 * 120.000) + (1 * 123.000) = 240.000 + 123.000 = 363.000
    assert float(sale_data["total_modal"]) == 363000.0
    # Laba = 423.000 - 363.000 = 60.000
    assert float(sale_data["laba"]) == 60000.0

    # Pastikan rincian item terdiri dari 2 pecahan batch
    assert len(sale_data["items"]) == 2
    it1 = next(x for x in sale_data["items"] if x["batch_id"] == b1_data["id"])
    assert it1["qty"] == 2
    assert float(it1["harga_jual"]) == 140000.0

    it2 = next(x for x in sale_data["items"] if x["batch_id"] == b2_data["id"])
    assert it2["qty"] == 1
    assert float(it2["harga_jual"]) == 143000.0

    # Sisa stok master = 50 - 3 = 47
    db.refresh(sp)
    assert sp.qty == 47

    # Batch 1 sekarang harus habis (qty_sisa = 0, status = DEPLETED)
    b1_db = db.query(m.SparepartBatch).filter(m.SparepartBatch.id == b1_data["id"]).first()
    assert b1_db.qty_sisa == 0
    assert b1_db.status == "DEPLETED"

    # Batch 2 sisa 47
    b2_db = db.query(m.SparepartBatch).filter(m.SparepartBatch.id == b2_data["id"]).first()
    assert b2_db.qty_sisa == 47


def test_part_sale_insufficient_stock(client, auth, db):
    """Pastikan transaksi ditolak bila stok tidak mencukupi."""
    sp = m.Sparepart(
        kategori="Baterai", merek="Xiaomi", jenis="Baterai BN53",
        qty=1, harga_beli=Decimal("50000"), harga_jual=Decimal("80000")
    )
    db.add(sp)
    db.commit()

    res = client.post(
        "/api/spareparts/sales",
        headers=auth,
        json={
            "customer_name": "Umum",
            "items": [{"sparepart_id": sp.id, "qty": 5}]
        }
    )
    assert res.status_code == 400
    assert "tidak mencukupi" in res.json()["detail"].lower()


def test_part_sales_included_in_finance_core(client, auth, db):
    """Pastikan omzet dan modal part penjualan langsung masuk ke financial core periode."""
    sp = m.Sparepart(
        kategori="Aksesoris", merek="Robot", jenis="Charger 20W Fast",
        qty=10, harga_beli=Decimal("40000"), harga_jual=Decimal("75000")
    )
    db.add(sp)
    db.commit()

    # Beli 2 charger: Omzet 150.000, Modal 80.000, Laba 70.000
    res = client.post(
        "/api/spareparts/sales",
        headers=auth,
        json={
            "customer_name": "Pak Joko",
            "items": [{"sparepart_id": sp.id, "qty": 2}]
        }
    )
    assert res.status_code == 201

    # Uji compute_finance_core
    now = datetime.now()
    start = now - timedelta(hours=1)
    end = now + timedelta(hours=1)

    fin = compute_finance_core(db, start, end)
    assert fin["omset_part"] >= Decimal("150000")
    assert fin["modal_part_sales"] >= Decimal("80000")
    assert fin["omset"] >= fin["omset_part"]
    assert fin["total_modal"] >= fin["modal_part_sales"]
