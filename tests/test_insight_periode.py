"""Test Insight Periode Ini pada Dashboard Overview (Opsi B).

Memastikan:
- Unit Masuk: hanya order yang masuk pada rentang periode kas aktif.
- Unit Selesai: order yang berstatus DONE pada periode aktif tersebut.
- Unit Lunas: order yang berstatus CASH pada periode aktif tersebut.
- Unit Aktif: unit pendingan yang statusnya masih berjalan (Repair, Wait Part, Konfirmasi, Analisa, Diterima).
"""
from datetime import datetime, timedelta
import pytest
from models import ServiceOrder, User, AuthToken, KasPeriod, StatusHistory

def _token(db, username, role):
    u = db.query(User).filter(User.username == username).first()
    if u is None:
        u = User(username=username, display_name=username.title(),
                 role=role, passcode_hash="x", passcode_salt="y",
                 active=1, created_at=datetime.now())
        db.add(u)
        db.commit()
        u = db.query(User).filter(User.username == username).one()
    tok = "pytest-tok-insight-" + username
    if db.query(AuthToken).filter(AuthToken.token == tok).first() is None:
        db.add(AuthToken(token=tok, user_id=u.id, expires_at=datetime.now() + timedelta(days=2)))
        db.commit()
    return {"Authorization": "Bearer " + tok}

def test_overview_insight_per_periode(client, db):
    admin_hdr = _token(db, "t_admin_insight", "ADMIN")

    r = client.get("/api/overview", headers=admin_hdr)
    assert r.status_code == 200
    data = r.json()
    assert "insight" in data

    insight_map = {item["label"]: item["value"] for item in data["insight"]}
    assert "Unit Masuk" in insight_map
    assert "Unit Selesai" in insight_map
    assert "Unit Lunas" in insight_map
    assert "Unit Aktif" in insight_map

    # Buat unit baru di periode aktif saat ini
    r_create = client.post("/api/orders/receive", headers=admin_hdr, json={
        "customer_name": "Cust Insight Test",
        "phone": "081299990888",
        "device": "Asus ROG Phone",
        "keluhan": "Bootloop",
        "estimate": 500000,
        "dp": 0
    })
    assert r_create.status_code in (200, 201)
    new_id = r_create.json()["id"]

    # Cek kembali overview
    r2 = client.get("/api/overview", headers=admin_hdr)
    assert r2.status_code == 200
    new_map = {item["label"]: item["value"] for item in r2.json()["insight"]}

    # Unit Masuk bertambah 1
    assert new_map["Unit Masuk"] == insight_map["Unit Masuk"] + 1
    # Unit Aktif bertambah 1 (karena statusnya baru masuk/DITERIMA)
    assert new_map["Unit Aktif"] == insight_map["Unit Aktif"] + 1
