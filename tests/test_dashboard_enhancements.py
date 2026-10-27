"""Tests untuk penyempurnaan UI Dashboard BOSS SF:
- Filter rentang waktu statistik status (all, 7d, 30d, period)
- Integrasi pipeline status dan smart recommendations
- Hub tugas operasional terpadu (garansi + unit mengendap)
- Data real teknisi untuk status bar
"""
from datetime import datetime, timedelta
from decimal import Decimal
import pytest
import models as m


def test_statistics_status_with_range_filters(client, auth, db):
    """Pastikan /api/statistics/status memfilter hitungan per status sesuai range_type."""
    # Buat customer dummy
    cust = m.Customer(name="Tester Range", phone="08123456789")
    db.add(cust)
    db.commit()

    # Buat order hari ini
    o_today = m.ServiceOrder(
        no_servis="SRV-TODAY", customer_id=cust.id, device="iPhone 11",
        status="WAIT PART", estimate=Decimal("500000"),
        created_at=datetime.now()
    )
    # Buat order 15 hari lalu
    o_15d = m.ServiceOrder(
        no_servis="SRV-15D", customer_id=cust.id, device="iPhone X",
        status="WAIT PART", estimate=Decimal("300000"),
        created_at=datetime.now() - timedelta(days=15)
    )
    # Buat order 45 hari lalu
    o_45d = m.ServiceOrder(
        no_servis="SRV-45D", customer_id=cust.id, device="iPhone 8",
        status="WAIT PART", estimate=Decimal("200000"),
        created_at=datetime.now() - timedelta(days=45)
    )
    db.add_all([o_today, o_15d, o_45d])
    db.commit()

    # 1. Default (all) -> minimal 3
    res_all = client.get("/api/statistics/status", headers=auth)
    assert res_all.status_code == 200
    wp_all = next(x["value"] for x in res_all.json()["by_status"] if x["name"] == "WAIT PART")
    assert wp_all >= 3

    # 2. 7 Hari -> hanya o_today yang masuk (dari 3 order baru tadi)
    res_7d = client.get("/api/statistics/status?range_type=7d", headers=auth)
    assert res_7d.status_code == 200
    wp_7d = next(x["value"] for x in res_7d.json()["by_status"] if x["name"] == "WAIT PART")
    assert wp_7d < wp_all
    assert wp_7d >= 1

    # 3. 30 Hari -> o_today dan o_15d masuk, o_45d tidak
    res_30d = client.get("/api/statistics/status?range_type=30d", headers=auth)
    assert res_30d.status_code == 200
    wp_30d = next(x["value"] for x in res_30d.json()["by_status"] if x["name"] == "WAIT PART")
    assert wp_30d >= wp_7d
    assert wp_30d <= wp_all


def test_unclaimed_orders_accessible_for_dashboard_hub(client, auth):
    """Pastikan endpoint /api/orders/unclaimed dapat diakses untuk data hub tindakan dashboard."""
    res = client.get("/api/orders/unclaimed", headers=auth)
    assert res.status_code == 200
    data = res.json()
    assert "total" in data
    assert "stage_1" in data
    assert "stage_2" in data
    assert "stage_3" in data
    assert "stage_4" in data


def test_technicians_accessible_for_status_bar(client, auth):
    """Pastikan endpoint /api/orders/technicians merespons untuk data real teknisi di status bar."""
    res = client.get("/api/orders/technicians", headers=auth)
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)


def test_header_notification_hub_and_no_weather():
    """Pastikan widget cuaca dummy dihapus dan notifikasi hub terpasang di header."""
    with open("frontend/index.html", "r", encoding="utf-8") as f:
        html = f.read()
    assert "32°C" not in html
    assert "fa-cloud-sun" not in html
    assert "headerNotifBtn" in html
    assert "headerNotifPop" in html
    assert "headerNotifBadge" in html
    assert "headerNotifSummaryBadge" in html
    assert "headerNotifList" in html

