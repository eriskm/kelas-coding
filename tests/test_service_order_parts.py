"""Tests untuk integrasi pemakaian sparepart pada modul servis (Teknisi & Admin):
- Penambahan sparepart dari stok fisik toko ke nota servis
- Pemotongan stok FIFO bertingkat dari SparepartBatch
- Akumulasi otomatis nilai part_cost pada ServiceOrder (multi-part support)
- Proteksi wewenang: Teknisi dilarang melihat modal beli (dimask jadi 0)
- Opsi penambahan part luar/kanibal (wajib wewenang Admin)
- Pembatalan part (restock fisik kembali ke rak & batch asal + kurangi part_cost)
- Larangan modifikasi part pada unit berstatus CASH
- Jurnal audit pergerakan stok (StockMove) tercatat untuk Admin Sparepart
"""
from datetime import date, datetime, timedelta
from decimal import Decimal
import pytest
import models as m


def _seed_teknisi(db, username="tek_part_test"):
    u = db.query(m.User).filter(m.User.username == username).first()
    if not u:
        u = m.User(username=username, display_name="Teknisi Test",
                   role="TEKNISI", passcode_hash="x", passcode_salt="y", active=1)
        db.add(u)
        db.commit()
        db.refresh(u)
    else:
        u.active = 1
        u.role = "TEKNISI"
        db.commit()

    token_str = f"pytest-tok-{username}"
    tok = db.query(m.AuthToken).filter(m.AuthToken.token == token_str).first()
    if not tok:
        tok = m.AuthToken(token=token_str, user_id=u.id,
                          expires_at=datetime.now() + timedelta(days=2))
        db.add(tok)
        db.commit()
    else:
        tok.user_id = u.id
        tok.expires_at = datetime.now() + timedelta(days=2)
        db.commit()
    return {"Authorization": f"Bearer {token_str}"}


def test_service_order_parts_fifo_integration(client, auth, db):
    """Test alur lengkap: Pasang part -> FIFO deplesi -> part_cost otomatis -> Batal pasang."""
    # 1. Buat ServiceOrder baru
    cust = db.query(m.Customer).first()
    order = m.ServiceOrder(
        no_servis="SV-TEST-PART-01",
        customer_id=cust.id,
        device="Oppo Reno 5 4G",
        status="REPAIR",
        technician="Pytest Teknisi",
        final_price=Decimal("350000"),
        part_cost=Decimal("0"),
        service_date=date.today()
    )
    db.add(order)
    db.commit()
    db.refresh(order)

    # 2. Buat master sparepart LCD dengan 2 batch FIFO
    sp = m.Sparepart(
        kategori="LCD", merek="OG SUPER", jenis="LCD OPPO RENO 5 4G OG SUPER",
        device="Oppo Reno 5", qty=5, harga_beli=Decimal("130000"),
        harga_jual=Decimal("200000"), tanggal=date.today()
    )
    db.add(sp)
    db.commit()
    db.refresh(sp)

    # Batch 1 (lama): 2 pcs @ 130.000
    b1 = m.SparepartBatch(
        sparepart_id=sp.id, supplier="Supplier Lama",
        harga_beli=Decimal("130000"), harga_jual=Decimal("200000"),
        qty_masuk=2, qty_sisa=2, tanggal_masuk=date.today() - timedelta(days=3),
        status="ACTIVE"
    )
    # Batch 2 (baru): 3 pcs @ 135.000
    b2 = m.SparepartBatch(
        sparepart_id=sp.id, supplier="Supplier Baru",
        harga_beli=Decimal("135000"), harga_jual=Decimal("205000"),
        qty_masuk=3, qty_sisa=3, tanggal_masuk=date.today(),
        status="ACTIVE"
    )
    db.add_all([b1, b2])
    db.commit()

    # 3. Teknisi pasang part pertama (1 unit)
    tek_auth = _seed_teknisi(db, "tek_part_1")
    res1 = client.post(
        f"/api/orders/{order.id}/parts",
        headers=tek_auth,
        json={"sparepart_id": sp.id, "qty": 1}
    )
    assert res1.status_code == 201
    data1 = res1.json()
    assert data1["success"] is True
    # Teknisi dilarang melihat modal_beli (harus 0)
    assert data1["modal_beli"] == 0
    assert data1["order_part_cost"] == 0

    # Verifikasi di database:
    db.refresh(order)
    db.refresh(sp)
    db.refresh(b1)
    db.refresh(b2)
    # Master stok berkurang jadi 4
    assert sp.qty == 4
    # Batch 1 berkurang dari 2 jadi 1 (FIFO)
    assert b1.qty_sisa == 1
    # Modal part otomatis terakumulasi di order (130.000)
    assert order.part_cost == Decimal("130000")

    # 4. Teknisi pasang part kedua: Baterai (multi-part support)
    sp_bat = m.Sparepart(
        kategori="Baterai", merek="Original", jenis="Baterai Oppo Reno 5 BLP803",
        qty=10, harga_beli=Decimal("80000"), harga_jual=Decimal("150000"),
        tanggal=date.today()
    )
    db.add(sp_bat)
    db.commit()
    db.refresh(sp_bat)

    res2 = client.post(
        f"/api/orders/{order.id}/parts",
        headers=tek_auth,
        json={"sparepart_id": sp_bat.id, "qty": 1}
    )
    assert res2.status_code == 201

    db.refresh(order)
    db.refresh(sp_bat)
    assert sp_bat.qty == 9
    # Total part_cost otomatis 130.000 (LCD) + 80.000 (Baterai) = 210.000
    assert order.part_cost == Decimal("210000")

    # 5. List parts: Teknisi melihat part tapi modal 0; Admin melihat rincian modal asli
    res_list_tek = client.get(f"/api/orders/{order.id}/parts", headers=tek_auth)
    assert res_list_tek.status_code == 200
    items_tek = res_list_tek.json()["items"]
    assert len(items_tek) == 2
    for it in items_tek:
        assert it["modal_beli"] == 0

    res_list_adm = client.get(f"/api/orders/{order.id}/parts", headers=auth)
    assert res_list_adm.status_code == 200
    body_adm = res_list_adm.json()
    assert body_adm["part_cost"] == 210000.0
    items_adm = body_adm["items"]
    assert len(items_adm) == 2
    # Item pertama modal 130.000, item kedua modal 80.000
    modals = sorted([it["modal_beli"] for it in items_adm])
    assert modals == [80000.0, 130000.0]

    # 6. Lepas/Batal part pertama (LCD)
    part_lcd_item = [it for it in items_adm if it["sparepart_id"] == sp.id][0]
    res_del = client.delete(
        f"/api/orders/{order.id}/parts/{part_lcd_item['id']}?alasan=Tes+batal",
        headers=tek_auth
    )
    assert res_del.status_code == 200

    # Verifikasi pengembalian stok fisik & batch
    db.refresh(order)
    db.refresh(sp)
    db.refresh(b1)
    # Master stok kembali jadi 5
    assert sp.qty == 5
    # Batch 1 kembali jadi 2
    assert b1.qty_sisa == 2
    # part_cost berkurang kembali hanya tersisa Baterai (80.000)
    assert order.part_cost == Decimal("80000")

    # 7. Verifikasi log mutasi Admin Sparepart (/api/inventory/moves)
    res_moves = client.get("/api/inventory/moves?limit=10", headers=auth)
    assert res_moves.status_code == 200
    moves = res_moves.json()["items"]
    aksi_list = [m["aksi"] for m in moves]
    assert "PAKAI" in aksi_list
    assert "BATAL" in aksi_list


def test_service_order_part_external_and_cash_locked(client, auth, db):
    """Test opsi part luar (khusus Admin) dan proteksi transaksi CASH."""
    cust = db.query(m.Customer).first()
    order = m.ServiceOrder(
        no_servis="SV-TEST-PART-EXT",
        customer_id=cust.id,
        device="Samsung A50",
        status="REPAIR",
        technician="Pytest Teknisi",
        final_price=Decimal("400000"),
        part_cost=Decimal("0"),
        service_date=date.today()
    )
    db.add(order)
    db.commit()
    db.refresh(order)

    # 1. Teknisi mencoba tambah part luar -> harus DITOLAK (403 / ORDER_UPDATE_MODAL required)
    tek_auth = _seed_teknisi(db, "tek_part_ext")
    res_tek = client.post(
        f"/api/orders/{order.id}/parts",
        headers=tek_auth,
        json={
            "is_external": True,
            "part_name": "Konektor Cas Kanibal Toko Sebelah",
            "modal_beli": 35000,
            "qty": 1
        }
    )
    assert res_tek.status_code == 403

    # 2. Admin menambahkan part luar -> SUKSES
    res_adm = client.post(
        f"/api/orders/{order.id}/parts",
        headers=auth,
        json={
            "is_external": True,
            "part_name": "Konektor Cas Kanibal Toko Sebelah",
            "modal_beli": 35000,
            "qty": 1
        }
    )
    assert res_adm.status_code == 201
    db.refresh(order)
    assert order.part_cost == Decimal("35000")

    # 3. Unit ditransisikan ke CASH -> part tidak boleh ditambah atau dibatalkan lagi
    order.status = "CASH"
    db.commit()

    # Coba tambah part baru saat CASH -> 400
    res_add_cash = client.post(
        f"/api/orders/{order.id}/parts",
        headers=auth,
        json={"is_external": True, "part_name": "Tambahan", "modal_beli": 10000}
    )
    assert res_add_cash.status_code == 400
    assert "CASH" in res_add_cash.json()["detail"]

    # Coba hapus part saat CASH -> 400
    part_id = res_adm.json()["part_id"]
    res_del_cash = client.delete(
        f"/api/orders/{order.id}/parts/{part_id}",
        headers=auth
    )
    assert res_del_cash.status_code == 400
    assert "CASH" in res_del_cash.json()["detail"]
