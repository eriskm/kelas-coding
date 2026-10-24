# -*- coding: utf-8 -*-
"""Test endpoint precheck garansi dan integrasi query parameter.

Memastikan precheck refund garansi dapat dipanggil via:
  GET /api/refunds/precheck/garansi/{warranty_claim_id}?nominal=...
dan mengembalikan data validasi kecukupan Saldo Kas Aset.
"""
from datetime import date, datetime
from decimal import Decimal
import pytest
from fastapi.testclient import TestClient

from database import Base
import models as m
from main import app
from dependencies import get_db_session
from routers.auth import get_authenticated_user
import cash


@pytest.fixture()
def client_and_db(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=eng)
    TestingSessionLocal = sessionmaker(bind=eng)
    session = TestingSessionLocal()

    # Buat user admin
    admin = m.User(username="admin_toko", display_name="Admin Toko", role="ADMIN", passcode_hash="x", passcode_salt="y", active=1)
    session.add(admin)

    # Buat pelanggan
    cust = m.Customer(name="Budi Pelanggan", phone="0812345678")
    session.add(cust)
    session.commit()

    # Buat order servis & claim garansi
    order = m.ServiceOrder(
        no_servis="SV-TEST-001", customer_id=cust.id, device="Infinix Hot 10",
        status="CASH", warranty_months=1, service_date=date.today(),
        created_at=datetime.now()
    )
    session.add(order)
    session.commit()

    claim = m.WarrantyClaim(
        claim_no="CLM-TEST-001", service_order_id=order.id, customer_id=cust.id,
        claim_date=date.today(), complaint="Layar bergaris", customer_cost=Decimal("50000"),
        created_at=datetime.now()
    )
    session.add(claim)
    session.commit()

    def override_db():
        try:
            yield session
        finally:
            pass

    def override_auth():
        return admin

    app.dependency_overrides[get_db_session] = override_db
    app.dependency_overrides[get_authenticated_user] = override_auth

    client = TestClient(app)
    try:
        yield client, session, claim
    finally:
        app.dependency_overrides.clear()
        session.close()
        eng.dispose()


def test_precheck_garansi_url_query_param(client_and_db):
    client, session, claim = client_and_db

    # 1. Saldo Kas Aset masih Rp 0 -> diminta Rp 100.000 -> cukup = False
    resp = client.get(f"/api/refunds/precheck/garansi/{claim.id}?nominal=100000")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["claim_found"] is True
    assert data["diminta"] == 100000.0
    assert data["saldo_kas_aset"] == 0.0
    assert data["cukup"] is False

    # 2. Tambah kas aset Rp 150.000 -> diminta Rp 100.000 -> cukup = True
    cash.catat_mutasi(session, cash.LAYER_KAS_ASET, "Masuk", "Kas Aset", "Setoran Kas Aset", Decimal("150000"))
    session.commit()

    resp2 = client.get(f"/api/refunds/precheck/garansi/{claim.id}?nominal=100000")
    assert resp2.status_code == 200, resp2.text
    data2 = resp2.json()
    assert data2["saldo_kas_aset"] == 150000.0
    assert data2["cukup"] is True
