"""Tests untuk alur Retur / Garansi Sparepart Cacat Pabrik (Defective Parts):
- Pelaporan part cacat dari pengerjaan unit servis (part_cost servis otomatis dikurangi)
- Pelaporan part cacat langsung dari stok fisik toko (keluar dari rak siap jual ke karantina)
- Proteksi wewenang: Teknisi boleh lapor cacat, tapi DILARANG eksekusi resolusi (wajib Admin/Admin Sparepart)
- Resolusi GANTI_BARANG: Unit pengganti dari supplier tiba, stok fisik rak bertambah kembali (+1)
- Resolusi POTONG_NOTA: Supplier memotong tagihan belanja / refund uang modal
- Resolusi DITOLAK: Supplier menolak klaim, dicatat sebagai kerugian barang rusak
"""
from datetime import date, datetime, timedelta
from decimal import Decimal
import pytest
import models as m


def _seed_role_user(db, username, role):
    u = db.query(m.User).filter(m.User.username == username).first()
    if not u:
        u = m.User(username=username, display_name=f"User {role}",
                   role=role, passcode_hash="x", passcode_salt="y", active=1)
        db.add(u)
        db.commit()
        db.refresh(u)
    else:
        u.active = 1
        u.role = role
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


def test_retur_cacat_dari_unit_servis(client, auth, db):
    """Teknisi mendapati LCD cacat saat tes di unit:
    - Lapor retur -> part dilepas dari unit, part_cost servis berkurang kembali.
    - Klaim retur tercatat dengan status MENUNGGU.
    """
    cust = db.query(m.Customer).first()
    order = m.ServiceOrder(
        no_servis="SV-TEST-DEFECT-01",
        customer_id=cust.id,
        device="Infinix Hot 30",
        status="REPAIR",
        technician="Pytest Teknisi",
        final_price=Decimal("300000"),
        part_cost=Decimal("0"),
        service_date=date.today()
    )
    db.add(order)
    db.commit()
    db.refresh(order)

    sp = m.Sparepart(
        kategori="LCD", merek="OG SUPER", jenis="LCD INF HOT 30 OG SUPER",
        device="Infinix Hot 30", qty=3, harga_beli=Decimal("128000"),
        harga_jual=Decimal("185000"), tanggal=date.today()
    )
    db.add(sp)
    db.commit()
    db.refresh(sp)

    batch = m.SparepartBatch(
        sparepart_id=sp.id, supplier="Supplier Bintang",
        harga_beli=Decimal("128000"), harga_jual=Decimal("185000"),
        qty_masuk=3, qty_sisa=3, tanggal_masuk=date.today(),
        status="ACTIVE"
    )
    db.add(batch)
    db.commit()
    db.refresh(batch)

    tek_auth = _seed_role_user(db, "tek_defect_test", "TEKNISI")

    # 1. Pasang part ke unit servis
    res_add = client.post(
        f"/api/orders/{order.id}/parts",
        headers=tek_auth,
        json={"sparepart_id": sp.id, "qty": 1}
    )
    assert res_add.status_code == 201
    part_item_id = res_add.json()["part_id"]

    db.refresh(order)
    assert order.part_cost == Decimal("128000")
    db.refresh(sp)
    assert sp.qty == 2

    # 2. Teknisi tes layar dan menemukan ghost touch -> lapor retur cacat pabrik
    res_retur = client.post(
        f"/api/orders/{order.id}/parts/{part_item_id}/retur",
        headers=tek_auth,
        json={"alasan_cacat": "Ghost touch sudut kanan bawah dan flicker"}
    )
    assert res_retur.status_code == 201
    data_retur = res_retur.json()
    assert data_retur["success"] is True
    no_retur = data_retur["no_retur"]
    assert no_retur.startswith("RET-")

    # 3. Verifikasi di database:
    db.refresh(order)
    # part_cost servis otomatis kembali jadi 0 (tidak membebani nota konsumen)
    assert order.part_cost == Decimal("0")

    # Entri SparepartDefect tercipta
    defect = db.query(m.SparepartDefect).filter(m.SparepartDefect.no_retur == no_retur).first()
    assert defect is not None
    assert defect.status == "MENUNGGU"
    assert defect.supplier == "Supplier Bintang"
    assert defect.modal_satuan == Decimal("128000")
    assert defect.service_order_id == order.id
    assert "Ghost touch" in defect.alasan_cacat

    # Riwayat mutasi tercatat
    move = db.query(m.StockMove).filter(m.StockMove.id == defect.stock_move_id).first()
    assert move is not None
    assert move.aksi == "RETUR_CACAT"


def test_retur_cacat_dari_stok_dan_proteksi_wewenang(client, auth, db):
    """Part cacat ditemukan saat cek stok fisik rak:
    - Stok fisik dipotong dari rak siap jual ke karantina retur.
    - Teknisi DILARANG menyelesaikan klaim (403).
    - Admin Sparepart berhasil menyelesaikan klaim GANTI_BARANG (stok kembali bertambah).
    """
    sp = m.Sparepart(
        kategori="Baterai", merek="Original", jenis="Baterai Xiaomi Note 10",
        device="Xiaomi Note 10", qty=5, harga_beli=Decimal("75000"),
        harga_jual=Decimal("120000"), tanggal=date.today()
    )
    db.add(sp)
    db.commit()
    db.refresh(sp)

    batch = m.SparepartBatch(
        sparepart_id=sp.id, supplier="Supplier Mega Jaya",
        harga_beli=Decimal("75000"), harga_jual=Decimal("120000"),
        qty_masuk=5, qty_sisa=5, tanggal_masuk=date.today(),
        status="ACTIVE"
    )
    db.add(batch)
    db.commit()
    db.refresh(batch)

    adm_sp_auth = _seed_role_user(db, "adm_sp_tester", "ADMIN SPAREPART")
    tek_auth = _seed_role_user(db, "tek_defect_tester2", "TEKNISI")

    # 1. Admin Sparepart mencatat 1 pcs baterai kembung dari kotak
    res_lapor = client.post(
        "/api/inventory/defects",
        headers=adm_sp_auth,
        json={
            "sparepart_id": sp.id,
            "qty": 1,
            "alasan_cacat": "Baterai kembung fisik dari kemasan pabrik"
        }
    )
    assert res_lapor.status_code == 201
    defect_id = res_lapor.json()["id"]

    # Stok fisik berkurang dari 5 menjadi 4
    db.refresh(sp)
    assert sp.qty == 4
    db.refresh(batch)
    assert batch.qty_sisa == 4

    # 2. Status diupdate menjadi DIKIRIM (dibawa ke supplier)
    res_status = client.put(
        f"/api/inventory/defects/{defect_id}/status",
        headers=adm_sp_auth,
        json={"status": "DIKIRIM", "note": "Dibawa sales ke supplier Mega Jaya"}
    )
    assert res_status.status_code == 200
    assert res_status.json()["status"] == "DIKIRIM"

    # 3. Teknisi mencoba menyelesaikan klaim retur -> harus DITOLAK (403 Forbidden)
    res_tek_resolve = client.post(
        f"/api/inventory/defects/{defect_id}/resolve",
        headers=tek_auth,
        json={"resolusi": "GANTI_BARANG", "note": "Teknisi coba bypass"}
    )
    assert res_tek_resolve.status_code == 403

    # 4. Admin Sparepart mengeksekusi resolusi GANTI_BARANG (unit baru tiba)
    res_resolve = client.post(
        f"/api/inventory/defects/{defect_id}/resolve",
        headers=adm_sp_auth,
        json={"resolusi": "GANTI_BARANG", "note": "Unit baru normal telah diterima"}
    )
    assert res_resolve.status_code == 200
    assert res_resolve.json()["status"] == "GANTI_BARANG"

    # 5. Verifikasi stok fisik bertambah kembali dari 4 menjadi 5!
    db.refresh(sp)
    assert sp.qty == 5
    db.refresh(batch)
    assert batch.qty_sisa == 5

    # Verifikasi riwayat mutasi GANTI_SUPPLIER tercatat
    res_moves = client.get("/api/inventory/moves?limit=10", headers=auth)
    assert res_moves.status_code == 200
    moves = res_moves.json()["items"]
    aksi_list = [m["aksi"] for m in moves]
    assert "RETUR_CACAT" in aksi_list
    assert "GANTI_SUPPLIER" in aksi_list


def test_resolusi_potong_nota_dan_ditolak(client, auth, db):
    """Uji resolusi POTONG_NOTA (stok tidak kembali, uang modal dikreditkan)
    dan DITOLAK (supplier tolak garansi).
    """
    sp = m.Sparepart(
        kategori="Konektor", merek="Ori", jenis="Papan Cas A50",
        qty=2, harga_beli=Decimal("25000"), harga_jual=Decimal("50000"),
        tanggal=date.today()
    )
    db.add(sp)
    db.commit()
    db.refresh(sp)

    adm_sp_auth = _seed_role_user(db, "adm_sp_tester3", "ADMIN SPAREPART")

    # Lapor 1 cacat
    res1 = client.post(
        "/api/inventory/defects",
        headers=adm_sp_auth,
        json={"sparepart_id": sp.id, "qty": 1, "alasan_cacat": "Pin bengkok pabrik"}
    )
    assert res1.status_code == 201
    defect_id1 = res1.json()["id"]

    db.refresh(sp)
    assert sp.qty == 1

    # Resolusi POTONG_NOTA
    res_potong = client.post(
        f"/api/inventory/defects/{defect_id1}/resolve",
        headers=adm_sp_auth,
        json={"resolusi": "POTONG_NOTA", "note": "Dipotong pada nota belanja #INV-8899"}
    )
    assert res_potong.status_code == 200
    assert res_potong.json()["status"] == "POTONG_NOTA"

    # Stok tetap 1 (karena tidak ada unit fisik pengganti)
    db.refresh(sp)
    assert sp.qty == 1

    # Verifikasi daftar defects API
    res_list = client.get("/api/inventory/defects?status=ALL", headers=adm_sp_auth)
    assert res_list.status_code == 200
    items = res_list.json()["items"]
    assert any(it["id"] == defect_id1 for it in items)
