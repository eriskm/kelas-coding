# -*- coding: utf-8 -*-
"""Aturan periode kas: periode berjalan DARI DIBUKA sampai DITUTUP.

Bug yang dikunci di sini (terbukti 2026-10-10): `end_at` diisi sebagai
placeholder "16:00 berikutnya". Kalau periode tidak segera ditutup, `end_at`
menjadi basi dan SEMUA transaksi sesudahnya jatuh di luar jendela
[start, end) — sehingga lenyap dari Omzet, Modal, Beban, Conditions Kas, dan
Buku Kas tanpa error sama sekali. Diuji: order CASH Rp250.000 hilang dari
seluruh laporan keuangan.

Aturan Owner: jam 16:00 bukan pemotong periode, hanya patokan pengingat untuk
segera menutup kas.
"""
from datetime import datetime, timedelta

from money import to_decimal


def _buat_periode(db, start, end=None, status="OPEN"):
    import models
    p = models.KasPeriod(start_at=start, end_at=end or start + timedelta(days=1),
                         status=status, created_at=start)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def test_periode_open_berlaku_sampai_now(client, db):
    """Periode OPEN yang end_at-nya sudah basi tetap mencakup transaksi terbaru."""
    import models
    import routers.dashboard as dash
    now = datetime.now()
    # Periodenya dibuat 3 hari lalu dan TIDAK ditutup -> end_at sudah lewat.
    tua = now - timedelta(days=3)
    p = _buat_periode(db, tua)
    assert p.end_at < now, "Syarat: end_at harus sudah basi"

    # dp_factory: satu order CASH+ lunas yang lunas_at = sekarang (di luar end_at).
    import routers.kas as kasmod
    o = _order_cash(db, "PY-PERIODE-BASI", now)

    start, end = dash.batas_periode(p)
    assert end == datetime.max, "Periode OPEN tidak boleh punya batas atas"
    assert start <= o.lunas_at < end

    rows = kasmod.period_rows(db, start, end)
    assert rows, "Transaksi setelah end_at baseline harus tetap masuk Buku Kas"

    fin = dash.compute_finance(db, start, end, lihat_kas_besar=True)
    assert to_decimal(fin["omset"]) >= to_decimal(500000), \
        "Omzet transaksi terbaru harus ikut dihitung"


def test_periode_closed_memakai_batas_asli(client, db):
    """Periode CLOSED memakai end_at apa adanya (arsip, tidak melebar)."""
    import routers.dashboard as dash
    mulai = datetime.now() - timedelta(days=2)
    selesai = datetime.now() - timedelta(days=1)
    p = _buat_periode(db, mulai, selesai, status="CLOSED")
    start, end = dash.batas_periode(p)
    assert start == mulai
    assert end == selesai, "Periode CLOSED tidak boleh diperluas"


def test_overdue_terlapor_di_overview(client, db):
    """Overview memberi tahu kalau periode aktif sudah lewat jam 16:00."""
    import routers.dashboard as dash
    from database import SessionLocal
    s = SessionLocal()
    try:
        _buat_periode(s, datetime.now() - timedelta(days=3))   # OPEN & basi
        r = client.get("/api/overview", headers=_token(db, "pytest_admin", "ADMIN"))
        assert r.status_code == 200, r.text
        per = r.json()["period"]
        assert per["lewat_jam_16"] is True, "Harus terlapor perlu segera tutup kas"
        assert per["berlaku_sampai"] == "ditutup"
        star = {x["key"]: x for x in r.json()["star_cards"]}
        assert "segera tutup kas" in star["omset"]["sub"]
    finally:
        s.close()


def test_tutup_kas_mengisi_end_at_dengan_waktu_asli(client, db):
    """Saat ditutup, end_at = waktu penutupan sebenarnya (bukan placeholder)."""
    import models
    from database import SessionLocal
    p = _buat_periode(db, datetime.now() - timedelta(days=2))   # OPEN & basi
    pid = p.id
    r = client.post("/api/kas/close", headers=_token(db, "pytest_admin", "ADMIN"),
                    json={"kas_period_id": pid})
    assert r.status_code == 200, r.text
    s = SessionLocal()
    try:
        _closed = s.query(models.KasPeriod).filter(
            models.KasPeriod.id == pid).first()
        assert _closed.status == "CLOSED"
        assert _closed.end_at is not None
        assert _closed.closed_at is not None
        # end_at == waktu penutupan (bukan 16:00 placeholder yang bisa basi).
        assert abs((_closed.end_at - _closed.closed_at).total_seconds()) < 2
    finally:
        s.close()


def _order_cash(db, no, momen):
    import models
    cust = db.query(models.Customer).filter(
        models.Customer.name == "Pytest Customer").first()
    o = models.ServiceOrder(
        no_servis=no, customer_id=cust.id, device="PY", status="CASH",
        service_date=momen.date(), final_price=to_decimal(500000),
        estimate=to_decimal(500000), repair_plan="x", technician="Budi",
        warranty_months=1, created_at=momen, lunas_at=momen,
        lunas_date=momen.date(), part_cost=to_decimal(100000),
        modal_jasa=to_decimal(50000), modal_lainnya=to_decimal(0),
    )
    db.add(o)
    db.commit()
    db.refresh(o)
    db.add(models.Payment(service_order_id=o.id, kind="PELUNASAN",
                          amount=to_decimal(500000), created_at=momen))
    db.commit()
    return o


def _token(db, username, role):
    import models
    u = db.query(models.User).filter(models.User.username == username).first()
    if u is None:
        u = models.User(username=username, display_name=username, role=role,
                        passcode_hash="x", passcode_salt="y", active=True)
        db.add(u)
        db.commit()
        db.refresh(u)
    tok = "pytest-token-" + username
    if db.query(models.AuthToken).filter(models.AuthToken.token == tok).first() is None:
        db.add(models.AuthToken(token=tok, user_id=u.id,
                               expires_at=datetime.now() + timedelta(days=2)))
        db.commit()
    return {"Authorization": "Bearer " + tok}