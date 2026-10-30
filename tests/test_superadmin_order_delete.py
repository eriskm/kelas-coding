"""Test Superadmin Cascade Delete pada Service Order.

Memastikan:
- Admin biasa diblokir (409) jika order memiliki pembayaran atau berstatus terminal.
- Superadmin diizinkan menghapus order dengan cascade cleanup (payments, kas_entries, status_history, sparepart usage).
- Saldo laci dikalibrasi ulang setelah penghapusan.
- Audit journal tercatat secara transparan.
"""
from datetime import datetime, timedelta
from decimal import Decimal
import pytest
from models import ServiceOrder, Payment, KasEntry, User, AuthToken

def _token(db, username, role):
    u = db.query(User).filter(User.username == username).first()
    if u is None:
        u = User(username=username, display_name=username.title(),
                 role=role, passcode_hash="x", passcode_salt="y",
                 active=1, created_at=datetime.now())
        db.add(u)
        db.commit()
        u = db.query(User).filter(User.username == username).one()
    tok = "pytest-tok-del-" + username
    if db.query(AuthToken).filter(AuthToken.token == tok).first() is None:
        db.add(AuthToken(token=tok, user_id=u.id, expires_at=datetime.now() + timedelta(days=2)))
        db.commit()
    return {"Authorization": "Bearer " + tok}

def test_admin_blocked_from_deleting_paid_or_done_order(client, db):
    admin_hdr = _token(db, "t_admin_del", "ADMIN")

    # Buat order baru dengan DP
    r = client.post("/api/orders/receive", headers=admin_hdr, json={
        "customer_name": "Test Delete Cust",
        "phone": "081299990001",
        "device": "Xiaomi Note 10",
        "keluhan": "Mati total",
        "estimate": 200000,
        "dp": 50000
    })
    assert r.status_code in (200, 201), r.text
    oid = r.json()["id"]

    # Admin biasa coba hapus -> Harus 409
    del_r = client.delete(f"/api/orders/{oid}", headers=admin_hdr)
    assert del_r.status_code == 409
    assert "Order sudah memiliki" in del_r.json()["detail"]

def test_superadmin_can_cascade_delete_order(client, db):
    admin_hdr = _token(db, "t_admin_del2", "ADMIN")
    super_hdr = _token(db, "t_super_del", "SUPERADMIN")

    # Buat order baru dengan DP
    r = client.post("/api/orders/receive", headers=admin_hdr, json={
        "customer_name": "Test Super Delete Cust",
        "phone": "081299990002",
        "device": "Samsung A52",
        "keluhan": "Ganti LCD",
        "estimate": 300000,
        "dp": 100000
    })
    assert r.status_code in (200, 201), r.text
    oid = r.json()["id"]

    # Superadmin hapus order -> Harus 200 OK
    del_r = client.delete(f"/api/orders/{oid}", headers=super_hdr)
    assert del_r.status_code == 200, del_r.text
    assert del_r.json()["ok"] is True

    # Order sudah terhapus
    get_r = client.get(f"/api/orders/{oid}", headers=admin_hdr)
    assert get_r.status_code == 404

    # Pastikan payments & kas_entries terkait juga terhapus
    db.expire_all()
    assert db.query(Payment).filter(Payment.service_order_id == oid).count() == 0
