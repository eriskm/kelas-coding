# -*- coding: utf-8 -*-
"""P2-15 — regression baseline Owner Cash Model v4.

Cakupan: identitas Master Kas = Laci + Aset, transfer yang menjaga Master Kas,
injection yang memilih posisi, rekonsiliasi tanpa suntik opening, alokasi 30%
yang bukan uang baru, dan visibility posisi per role.
"""
from datetime import datetime, timedelta

import pytest

import cash
import distribution as dist
from money import quantize, to_decimal


def _aktif(db):
    from models import KasPeriod
    now = datetime.now()
    start = now.replace(hour=16, minute=0, second=0, microsecond=0)
    if now < start:
        start -= timedelta(days=1)
    end = start + timedelta(days=1)
    p = db.query(KasPeriod).filter(KasPeriod.status == "OPEN").first()
    if p is None:
        p = KasPeriod(start_at=start, end_at=end, status="OPEN")
        db.add(p)
        db.commit()
        db.refresh(p)
    else:
        p.start_at, p.end_at = start, end
        p.created_at = now - timedelta(minutes=10)
        p.status = "OPEN"
        db.commit()
    return p


def _token(db, username, role):
    import models
    u = db.query(models.User).filter(models.User.username == username).first()
    if u is None:
        u = models.User(username=username, display_name=username, role=role,
                        passcode_hash="x", passcode_salt="y", active=True)
        db.add(u)
        db.commit()
        db.refresh(u)
    tok = "pytest-token-%s" % username
    if db.query(models.AuthToken).filter(models.AuthToken.token == tok).first() is None:
        db.add(models.AuthToken(token=tok, user_id=u.id,
                                expires_at=datetime.now() + timedelta(days=2)))
        db.commit()
    return {"Authorization": "Bearer %s" % tok}


def test_master_kas_adalah_penjumlahan_dua_posisi(db):
    cash.catat_injeksi(db, cash.LAYER_LACI, to_decimal("300000"), "pytest laci", actor="pytest")
    cash.catat_injeksi(db, cash.LAYER_ASET, to_decimal("200000"), "pytest aset", actor="pytest")
    db.commit()
    laci, aset = cash.saldo_laci(db), cash.saldo_kas_aset(db)
    assert cash.master_kas(db) == laci + aset


def test_transfer_tidak_mengubah_master_kas(db):
    cash.catat_injeksi(db, cash.LAYER_LACI, to_decimal("500000"), "pytest laci", actor="pytest")
    db.commit()
    sebelum = cash.master_kas(db)
    cash.transfer(db, to_decimal("150000"), cash.LAYER_LACI, cash.LAYER_ASET,
                  "pytest transfer", actor="pytest")
    db.commit()
    assert cash.saldo_laci(db) + cash.saldo_kas_aset(db) == sebelum
    assert cash.master_kas(db) == sebelum


def test_transfer_melebihi_saldo_posisi_ditolak(db):
    cash.catat_injeksi(db, cash.LAYER_LACI, to_decimal("10000"), "pytest laci", actor="pytest")
    db.commit()
    with pytest.raises(cash.CashError):
        cash.transfer(db, to_decimal("999999999"), cash.LAYER_LACI, cash.LAYER_ASET,
                      "pytest transfer kurang", actor="pytest")
        db.commit()


def test_injeksi_memilih_posisi(db):
    laci0, aset0 = cash.saldo_laci(db), cash.saldo_kas_aset(db)
    cash.catat_injeksi(db, cash.LAYER_ASET, to_decimal("75000"), "pytest ke aset", actor="pytest")
    cash.catat_injeksi(db, cash.LAYER_LACI, to_decimal("25000"), "pytest ke laci", actor="pytest")
    db.commit()
    assert cash.saldo_laci(db) == laci0 + to_decimal("25000")
    assert cash.saldo_kas_aset(db) == aset0 + to_decimal("75000")


def test_alokasi_30_dipindahkan_ke_kas_aset(db):
    """OD-LOCK-11.5: 70% keluar saat terbentuk, 30% menunggu Tutup Kas.

    WAKTU 30% Hak Kas Aset DIPISAH dari 70%:
      - saat distribusi terbentuk -> HANYA 70% keluar dari Laci;
      - 30% Hak Kas Aset MASIH DI LACI;
      - baru saat Tutup Kas (`pindahkan_hak_kas_aset`) 30% pindah ke Saldo Aset.
    """
    import distribution as dist_mod
    key = "PY-ALOKASI-V4"
    aset_awal = cash.saldo_kas_aset(db)
    laci_awal = cash.saldo_laci(db)
    master_awal = cash.master_kas(db)

    hasil = dist_mod.terapkan(db, key, "1000000", oleh="pytest")
    db.commit()
    assert hasil["created"] is True

    al = hasil["alokasi"]
    # 30% BELUM pindah: Saldo Aset masih sama seperti sebelumnya.
    assert cash.saldo_kas_aset(db) == aset_awal, \
        "30% Hak Kas Aset tidak boleh pindah sebelum Tutup Kas"
    # Semua 100% masih posisi di Laci - baru 70% yang keluar permanen.
    assert cash.saldo_laci(db) == laci_awal - to_decimal(al["cash_out"]), \
        "hanya 70% yang boleh keluar saat distribusi terbentuk"
    # Master Kas turun 70%; 30% belum digeser ke posisi lain.
    assert cash.master_kas(db) == master_awal - to_decimal(al["cash_out"])

    # --- Tutup Kas memindahkan 30% --------------------------------------
    row = hasil["distribution"]
    assert row.laci_adjust_entry_id is None, \
        "laci_adjust_entry_id harus kosong sebelum Tutup Kas"
    pgl = dist_mod.pindahkan_hak_kas_aset(db, row, oleh="pytest")
    db.commit()
    assert pgl["created"] is True
    assert pgl["nominal"] == to_decimal(al["kas_aset"])
    assert cash.saldo_kas_aset(db) == aset_awal + to_decimal(al["kas_aset"])
    # Transfer hanya pindah posisi: Master Kas TIDAK berubah lagi.
    assert cash.master_kas(db) == master_awal - to_decimal(al["cash_out"])
    assert row.laci_adjust_entry_id is not None

    # Idempoten: Tutup Kas kedua tidak menggeser uang dua kali.
    lagi2 = dist_mod.pindahkan_hak_kas_aset(db, row, oleh="pytest")
    db.commit()
    assert lagi2["created"] is False
    assert lagi2["sisa"] == to_decimal(0)
    assert cash.saldo_kas_aset(db) == aset_awal + to_decimal(al["kas_aset"])
    assert cash.master_kas(db) == master_awal - to_decimal(al["cash_out"])

    # Idempoten: membentuk ulang distribution tidak menggerakkan uang lagi.
    lagi = dist_mod.terapkan(db, key, "1000000", oleh="pytest")
    db.commit()
    assert lagi["created"] is False
    assert cash.master_kas(db) == master_awal - to_decimal(al["cash_out"])


def test_rekonsiliasi_jadi_penyesuaian_bukan_opening(db):
    opening_awal = cash.opening_layer(db, cash.LAYER_LACI)
    sistem = cash.saldo_laci(db)
    fisik = cash.saldo_laci(db) + to_decimal("7777")
    out = cash.rekonsiliasi_laci(db, fisik, actor="pytest")
    db.commit()
    assert out["penyesuaian"] is not None
    assert cash.opening_layer(db, cash.LAYER_LACI) == opening_awal
    assert cash.saldo_laci(db) == fisik
    assert cash.saldo_laci(db) != sistem


def test_kasir_tidak_melihat_saldo_aset(client, db):
    h = _token(db, "pytest_kasir", "KASIR")
    r = client.get("/api/kas/saldo", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "laci" in body
    assert "aset" not in body and "master_kas" not in body
    assert client.get("/api/kas/aset/riwayat", headers=h).status_code == 403


def test_pengelola_melihat_laci_aset_dan_master(client, db):
    h = _token(db, "pytest_pengelola", "PENGELOLA")
    r = client.get("/api/kas/saldo", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    # Bandingkan pada presisi uang (2 desimal). Nilai JSON.float, jadi penjumlahan
    # di sisi Python bisa meleset di digit ke-15; yang diuji IDENTITAS Master Kas.
    assert (quantize(to_decimal(body["master_kas"]))
            == quantize(to_decimal(body["laci"])) + quantize(to_decimal(body["aset"]))), \
        "Master Kas harus = Laci + Aset: %s vs %s + %s" % (
            body["master_kas"], body["laci"], body["aset"])
    assert client.get("/api/kas/aset/riwayat", headers=h).status_code == 200


def test_injection_tanpa_posisi_valid_ditolak(client, db, auth):
    bad = client.post("/api/kas/aset/masuk", headers=auth,
                      json={"keterangan": "pytest posisi ngawur", "nominal": 1000,
                            "posisi": "KANTOR"})
    kosong = client.post("/api/kas/aset/masuk", headers=auth,
                         json={"keterangan": "pytest posisi kosong", "nominal": 1000})
    assert bad.status_code in (400, 422)
    assert kosong.status_code in (400, 422)


def test_transfer_endpoint_menjaga_master_kas(client, db, auth):
    laci0, aset0, master0 = (cash.saldo_laci(db), cash.saldo_kas_aset(db),
                             cash.master_kas(db))
    cash.catat_injeksi(db, cash.LAYER_LACI, to_decimal("900000"), "pytest dana transfer",
                       actor="pytest")
    db.commit()
    master1 = cash.master_kas(db)
    r = client.post("/api/kas/aset/transfer", headers=auth,
                    json={"dari": "LACI", "ke": "KAS_ASET", "nominal": 120000,
                          "keterangan": "pytest endpoint transfer",
                          "ref_type": "transfer", "ref_id": "PY-TR-1"})
    assert r.status_code == 200, r.text
    assert cash.master_kas(db) == master1
    assert cash.saldo_laci(db) > laci0
    assert cash.saldo_kas_aset(db) > aset0
    assert master0 <= master1