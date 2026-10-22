# -*- coding: utf-8 -*-
"""P2-14 (ID-13) — regression baseline: Kas terpisah, Distribusi & Tutup Kas."""
from datetime import date, datetime, timedelta

import cash
import distribution as dist
from money import to_decimal
from statusflow import lock_lunas_moment


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


def test_laci_dan_kas_aset_terpisah(db):
    import models
    sal_awal = (cash.saldo_laci(db), cash.saldo_kas_aset(db))
    cash.catat_mutasi(db, cash.LAYER_KAS_ASET, "Masuk", "Kas Aset", "PY injeksi", to_decimal("100000"))
    db.commit()
    assert cash.saldo_kas_aset(db) == sal_awal[1] + to_decimal("100000")
    assert cash.saldo_laci(db) == sal_awal[0]
    ring = cash.ringkasan_saldo(db)
    assert "total" not in ring and set(ring["layer"]) == {"LACI", "KAS_ASET"}


def test_precheck_kas_aset_menolak_kurang(db):
    cash.catat_mutasi(db, cash.LAYER_KAS_ASET, "Masuk", "Kas Aset", "PY modal", to_decimal("10000"))
    db.commit()
    cukup, saldo, kurang = cash.cukup_kas_aset(db, to_decimal("999999999"))
    assert cukup is False and kurang > 0


def test_distribusi_10_30_30_30_total_100():
    hit = dist.hitung("1000000")
    assert hit["karyawan"] == to_decimal("100000")
    assert hit["pengelola"] == to_decimal("300000")
    assert hit["investor"] == to_decimal("300000")
    assert hit["kas_aset"] == to_decimal("300000")
    assert hit["cash_out"] == to_decimal("700000")
    assert hit["total"] == to_decimal("1000000")
    assert dist.hitung("0")["eligible"] is False


def test_distribusi_idempotent_per_periode(db):
    key = "PY-PERIODE-TEST"
    cash.catat_injeksi(db, cash.LAYER_LACI, to_decimal("700000"), "pytest injeksi distribusi", actor="pytest")
    first = dist.terapkan(db, key, "1000000", oleh="pytest")
    db.commit()
    second = dist.terapkan(db, key, "1000000", oleh="pytest")
    db.commit()
    assert first["created"] is True
    assert second["created"] is False


def test_tutup_kas_409_pada_eksekusi_kedua(client, auth, db):
    p = _aktif(db)
    r1 = client.post("/api/kas/close", headers=auth,
                     json={"cash_counted": 0, "kas_period_id": p.id})
    assert r1.status_code in (200, 400), r1.text
    if r1.status_code == 200:
        r2 = client.post("/api/kas/close", headers=auth,
                         json={"cash_counted": 0, "kas_period_id": p.id})
        assert r2.status_code == 409, r2.text