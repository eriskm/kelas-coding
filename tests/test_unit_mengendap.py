# -*- coding: utf-8 -*-
"""Test untuk Fitur Notifikasi Bertahap Unit Mengendap di BOSS SF (Model C).

Aturan Bisnis:
  1. Unit yang dipantau hanya berstatus DONE dan FAILED yang belum diambil
     (unit_status == 'DI TOKO' atau taken_at is NULL).
  2. Unit CANCEL dan CASH tidak masuk daftar unit mengendap.
  3. Tahapan sapaan:
     - Tahap 1: 7 - 29 hari (Pengingat biasa)
     - Tahap 2: 30 - 59 hari (Pengingat serius)
     - Tahap 3: 60 - 89 hari (Penawaran solusi / pembelian unit)
     - Tahap 4: 90+ hari (Peringatan maksimal / prioritas tertinggi)
  4. Redaksi pesan membedakan unit DONE (selesai servis) dan FAILED (gagal servis).
"""
import pytest
from datetime import datetime, timedelta
from decimal import Decimal
import models


def _buat_order(db, no_servis, status, unit_status="DI TOKO", hari_lalu=10):
    c = db.query(models.Customer).filter(models.Customer.name == "Pelanggan Mengendap").first()
    if not c:
        c = models.Customer(name="Pelanggan Mengendap", phone="081299998888")
        db.add(c)
        db.flush()

    waktu_lalu = datetime.now() - timedelta(days=hari_lalu)
    o = models.ServiceOrder(
        no_servis=no_servis,
        customer_id=c.id,
        device="iPhone 11 Pro",
        damagetype="Mati Total",
        status=status,
        unit_status=unit_status,
        estimate=Decimal("750000"),
        created_at=waktu_lalu,
    )
    db.add(o)
    db.flush()

    # Tambahkan jejak transisi di StatusHistory
    sh = models.StatusHistory(
        service_order_id=o.id,
        dari_status="REPAIR" if status == "DONE" else "ANALISA",
        ke_status=status,
        oleh="Teknisi Test",
        waktu=waktu_lalu,
    )
    db.add(sh)
    db.commit()
    db.refresh(o)
    return o


def test_endpoint_unclaimed_hanya_done_dan_failed(client, auth, db):
    """Hanya unit DONE dan FAILED yang masuk daftar mengendap."""
    _buat_order(db, "SV-TEST-MGD-DONE", "DONE", "DI TOKO", hari_lalu=8)
    _buat_order(db, "SV-TEST-MGD-FAIL", "FAILED", "DI TOKO", hari_lalu=35)
    _buat_order(db, "SV-TEST-MGD-CASH", "CASH", "DIAMBIL", hari_lalu=15)
    _buat_order(db, "SV-TEST-MGD-CANCEL", "CANCEL", "DIAMBIL", hari_lalu=40)
    _buat_order(db, "SV-TEST-MGD-REPAIR", "REPAIR", "DI TOKO", hari_lalu=20)

    res = client.get("/api/orders/unclaimed", headers=auth)
    assert res.status_code == 200, res.text
    data = res.json()
    items = data.get("items", [])
    no_list = [x["no_servis"] for x in items]

    assert "SV-TEST-MGD-DONE" in no_list, "Order DONE harus masuk unclaimed"
    assert "SV-TEST-MGD-FAIL" in no_list, "Order FAILED harus masuk unclaimed"
    assert "SV-TEST-MGD-CASH" not in no_list, "Order CASH tidak boleh masuk"
    assert "SV-TEST-MGD-CANCEL" not in no_list, "Order CANCEL tidak boleh masuk"
    assert "SV-TEST-MGD-REPAIR" not in no_list, "Order REPAIR (belum final) tidak boleh masuk"


def test_tahapan_hari_unclaimed(client, auth, db):
    """Pengelompokan tahap 1 (7d), 2 (30d), 3 (60d), 4 (90d)."""
    _buat_order(db, "SV-STG-1", "DONE", "DI TOKO", hari_lalu=10)   # Stage 1: 7-29 hari
    _buat_order(db, "SV-STG-2", "DONE", "DI TOKO", hari_lalu=35)   # Stage 2: 30-59 hari
    _buat_order(db, "SV-STG-3", "DONE", "DI TOKO", hari_lalu=65)   # Stage 3: 60-89 hari
    _buat_order(db, "SV-STG-4", "DONE", "DI TOKO", hari_lalu=95)   # Stage 4: 90+ hari
    _buat_order(db, "SV-STG-0", "DONE", "DI TOKO", hari_lalu=3)    # Stage 0: < 7 hari (belum masuk sapa)

    res = client.get("/api/orders/unclaimed", headers=auth)
    assert res.status_code == 200
    data = res.json()
    items_by_no = {x["no_servis"]: x for x in data.get("items", [])}

    assert "SV-STG-1" in items_by_no
    assert items_by_no["SV-STG-1"]["stage"] == 1

    assert "SV-STG-2" in items_by_no
    assert items_by_no["SV-STG-2"]["stage"] == 2

    assert "SV-STG-3" in items_by_no
    assert items_by_no["SV-STG-3"]["stage"] == 3

    assert "SV-STG-4" in items_by_no
    assert items_by_no["SV-STG-4"]["stage"] == 4

    # Unit < 7 hari tidak masuk daftar notifikasi atau stage == 0
    if "SV-STG-0" in items_by_no:
        assert items_by_no["SV-STG-0"]["stage"] == 0

    assert data.get("stage_1", 0) >= 1
    assert data.get("stage_2", 0) >= 1
    assert data.get("stage_3", 0) >= 1
    assert data.get("stage_4", 0) >= 1


def test_unit_sudah_diambil_tidak_masuk(client, auth, db):
    """Unit yang unit_status == 'DIAMBIL' tidak boleh masuk meskipun statusnya DONE."""
    _buat_order(db, "SV-TAKEN-DONE", "DONE", "DIAMBIL", hari_lalu=25)
    res = client.get("/api/orders/unclaimed", headers=auth)
    assert res.status_code == 200
    no_list = [x["no_servis"] for x in res.json().get("items", [])]
    assert "SV-TAKEN-DONE" not in no_list


def test_frontend_komponen_unit_mengendap_ada():
    """Wadah banner widget dan popup modal unit mengendap ada di HTML & JS."""
    import io, os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    html = io.open(os.path.join(root, "frontend", "index.html"), encoding="utf-8").read()
    script = io.open(os.path.join(root, "frontend", "script.js"), encoding="utf-8").read()

    assert 'id="unclaimedAlertBox"' in html, "Banner widget #unclaimedAlertBox tidak ditemukan"
    assert 'id="unclaimedWaPopup"' in html, "Popup modal #unclaimedWaPopup tidak ditemukan"
    assert "loadUnclaimedUnits" in script, "Fungsi loadUnclaimedUnits tidak ditemukan di script.js"
    assert "unclaimedWaMessage" in script, "Fungsi unclaimedWaMessage tidak ditemukan di script.js"
    assert "unclaimedWaSend" in script, "Fungsi unclaimedWaSend tidak ditemukan di script.js"


def test_redaksi_pesan_done_dan_failed():
    """Pesan WhatsApp harus membedakan 4 tahap dan kondisi DONE vs FAILED."""
    import io, os, re
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script = io.open(os.path.join(root, "frontend", "script.js"), encoding="utf-8").read()

    m = re.search(r"function unclaimedWaMessage\s*\([^)]*\)\s*\{", script)
    assert m, "fungsi unclaimedWaMessage tidak ditemukan"
    idx = m.end()
    blok = script[idx:idx + 2500]

    # Cek kata kunci 4 tahap
    assert "selesai diservis" in blok, "Tahap 1 DONE harus menyebut selesai diservis"
    assert "30 hari" in blok, "Tahap 2 harus menyebut 30 hari"
    assert "pembelian unit" in blok or "harga yang disepakati" in blok, "Tahap 3 harus menawarkan solusi pembelian"
    assert "3 bulan" in blok or "hampir 3 bulan" in blok, "Tahap 4 harus menyebut 3 bulan / peringatan maksimal"
    # Cek penanganan FAILED
    assert "belum berhasil diperbaiki" in blok or "batal" in blok, "FAILED harus menyatakan belum berhasil / tanpa biaya"
