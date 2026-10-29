"""Tests untuk Mekanisme Setor Modal Part (Revolving Fund & Valuasi Stok):
1. Transaksi Penjualan Part (POS Kasir) otomatis mencatat:
   - Kas Masuk ke Laci (Omzet Penjualan Part)
   - Kas Keluar dari Laci (Modal Part disetor ke pos pengadaan sparepart sesuai OD-LOCK-01)
   - Saldo Laci bertambah bersih sebesar laba transaksi (total_omzet - total_modal)
2. Idempotensi ledger: mutasi tidak tercatat ganda bila diulang
3. Endpoint `/api/spareparts/revolving-fund/summary` menghitung agregat modal disetor,
   total belanja batch, valuasi stok fisik aktif di rak, dan sisa dana berputar.
4. Proteksi RBAC: hanya role dengan REPORT_SPAREPART yang boleh melihat ringkasan keuangan part.
"""
from datetime import datetime, date, timedelta
from decimal import Decimal
import pytest
import models as m
from cash import saldo_laci, catat_part_sale, LAYER_LACI, SUMBER_PART_SALE, SUMBER_MODAL
from routers.kas import period_rows


def test_part_sale_automatic_cash_ledger(client, auth, db):
    """Pastikan transaksi POS kasir mencatat mutasi Masuk (omzet) dan Keluar (modal part)."""
    saldo_awal = saldo_laci(db)

    # Buat sparepart master dan batch
    sp = m.Sparepart(
        kategori="Konektor", merek="Universal", jenis="Konektor Type-C Board",
        qty=0, harga_beli=Decimal("25000"), harga_jual=Decimal("50000"), tanggal=date.today()
    )
    db.add(sp)
    db.commit()

    # Tambah batch stok: 5 pcs @ modal 25.000, jual 50.000
    res_b = client.post(
        f"/api/spareparts/{sp.id}/batches",
        headers=auth,
        json={
            "supplier": "Supplier Jaya",
            "harga_beli": 25000,
            "harga_jual": 50000,
            "qty_masuk": 5,
            "tanggal_masuk": date.today().isoformat()
        }
    )
    assert res_b.status_code == 201

    # Kasir menjual 2 pcs: Omzet 100.000, Modal 50.000, Laba 50.000
    res_sale = client.post(
        "/api/spareparts/sales",
        headers=auth,
        json={
            "customer_name": "Customer Counter",
            "items": [{"sparepart_id": sp.id, "qty": 2}]
        }
    )
    assert res_sale.status_code == 201
    sale_data = res_sale.json()
    sale_id = sale_data["id"]

    # Periksa entri kas laci untuk penjualan ini
    entries = (
        db.query(m.KasEntry)
        .filter(m.KasEntry.layer == LAYER_LACI)
        .filter(m.KasEntry.ref_type.in_(["part_sale", "part_sale_modal"]))
        .filter(m.KasEntry.ref_id == sale_id)
        .all()
    )
    assert len(entries) == 2, "Harus ada 2 entri kas untuk penjualan part: omzet (Masuk) dan modal (Keluar)"

    entry_masuk = next(e for e in entries if (e.jenis or "").capitalize() == "Masuk")
    assert entry_masuk.sumber == SUMBER_PART_SALE
    assert float(entry_masuk.nominal) == 100000.0

    entry_keluar = next(e for e in entries if (e.jenis or "").capitalize() == "Keluar")
    assert entry_keluar.sumber == SUMBER_MODAL
    assert entry_keluar.ref_type == "part_sale_modal"
    assert float(entry_keluar.nominal) == 50000.0

    # Periksa Saldo Laci bertambah bersih sebesar laba (Rp 50.000)
    saldo_akhir = saldo_laci(db)
    assert saldo_akhir == saldo_awal + Decimal("50000.00")

    # Uji Idempotensi: panggil ulang catat_part_sale tidak boleh menambah entri
    sale_obj = db.query(m.PartSale).filter(m.PartSale.id == sale_id).first()
    replay_res = catat_part_sale(db, sale_obj, actor="test")
    assert replay_res == [], "Replay harus idempoten dan tidak menghasilkan mutasi baru"
    assert saldo_laci(db) == saldo_akhir


def test_revolving_fund_summary_endpoint(client, auth, db):
    """Pastikan endpoint summary revolving fund mengembalikan angka yang akurat dan dilindungi RBAC."""
    # 1. Akses dengan Admin (wewenang REPORT_SPAREPART)
    res = client.get("/api/spareparts/revolving-fund/summary", headers=auth)
    assert res.status_code == 200
    data = res.json()

    assert "modal_disetor_servis" in data
    assert "modal_disetor_penjualan" in data
    assert "total_modal_disetor" in data
    assert "total_belanja_pengadaan" in data
    assert "valuasi_stok_aktif" in data
    assert "sisa_dana_kas_part" in data

    # Nilai total modal disetor harus = modal servis + modal penjualan
    assert abs(data["total_modal_disetor"] - (data["modal_disetor_servis"] + data["modal_disetor_penjualan"])) < 0.01

    # 2. Akses tanpa wewenang (Teknisi) harus ditolak 403
    tek_user = m.User(
        username="teknisi_uji_rf",
        display_name="Teknisi Uji",
        role="TEKNISI",
        passcode_hash="x",
        passcode_salt="y",
        active=True
    )
    db.add(tek_user)
    db.commit()

    import secrets
    tek_token = "tok_tek_rf_" + secrets.token_hex(8)
    db.add(m.AuthToken(token=tek_token, user_id=tek_user.id, created_at=datetime.now(),
                       expires_at=datetime.now() + timedelta(days=1)))
    db.commit()

    res_tek = client.get(
        "/api/spareparts/revolving-fund/summary",
        headers={"Authorization": f"Bearer {tek_token}"}
    )
    assert res_tek.status_code == 403, "Teknisi tidak boleh mengakses laporan keuangan sparepart"


def test_period_rows_mutasi_kas_termasuk_penjualan_part(client, auth, db):
    """Pastikan baris penjualan part dan modalnya muncul di Mutasi Kas harian."""
    sp = m.Sparepart(
        kategori="Lainnya", jenis="Lem T7000 Hitam",
        qty=5, harga_beli=Decimal("15000"), harga_jual=Decimal("30000")
    )
    db.add(sp)
    db.commit()

    res_sale = client.post(
        "/api/spareparts/sales",
        headers=auth,
        json={
            "customer_name": "Toko Sebelah",
            "items": [{"sparepart_id": sp.id, "qty": 1}]
        }
    )
    assert res_sale.status_code == 201

    now = datetime.now()
    start = now - timedelta(hours=2)
    end = now + timedelta(hours=2)

    rows = period_rows(db, start, end)
    sale_in_rows = [r for r in rows if "Lem T7000" in (r.get("ket") or "") or "Penjualan Part" in (r.get("ket") or "")]
    assert len(sale_in_rows) >= 1, "Penjualan part harus tercantum dalam baris mutasi kas"
