# -*- coding: utf-8 -*-
"""Test isolasi data garansi historis (GR-*) dan transaksi lampau dari buku Mutasi Kas.

Sesuai aturan bisnis:
- Data transaksi garansi historis (GR-*) adalah arsip data lama untuk klaim garansi servis.
- Transaksi historis lampau (sebelum periode aktif dimulai) dan DP yang sudah selesai/batal
  TIDAK BOLEH mengotori buku Mutasi Kas, saldo awal, maupun saldo berjalan kas toko aktif.
"""
from datetime import datetime
from decimal import Decimal
import pytest

from models import Customer, Payment, ServiceOrder
from routers.kas import period_rows


def test_transaksi_garansi_historis_tidak_mengotori_mutasi_kas(db):
    """Pastikan transaksi dengan awalan GR-* tidak masuk ke mutasi kas dan tidak menambah saldo kas."""
    start = datetime(2026, 11, 6, 0, 0, 0)
    end = datetime(2026, 11, 6, 23, 59, 59)

    rows_awal, opening_awal = period_rows(db, start, end, with_opening=True)

    cust = Customer(name="Customer Garansi", phone="081299990001")
    db.add(cust)
    db.flush()

    tgl_lampau = datetime(2026, 8, 1, 10, 0, 0)
    order_gr = ServiceOrder(
        no_servis="GR-20260801-0999",
        customer_id=cust.id,
        device="Infinix Hot 30",
        status="CASH",
        unit_status="DIAMBIL",
        estimate=Decimal("300000.00"),
        final_price=Decimal("300000.00"),
        payment=Decimal("300000.00"),
        tanpa_modal=True,
        created_at=tgl_lampau,
        lunas_at=tgl_lampau,
    )
    db.add(order_gr)
    db.flush()

    pay_gr = Payment(
        service_order_id=order_gr.id,
        kind="PELUNASAN",
        amount=Decimal("300000.00"),
        method="CASH",
        note=None,
        created_at=tgl_lampau,
    )
    db.add(pay_gr)
    db.flush()

    order_sv = ServiceOrder(
        no_servis="SV-20261106-9999",
        customer_id=cust.id,
        device="Redmi Note 10",
        status="CASH",
        unit_status="DIAMBIL",
        estimate=Decimal("150000.00"),
        final_price=Decimal("150000.00"),
        payment=Decimal("150000.00"),
        tanpa_modal=True,
        created_at=start,
        lunas_at=start,
    )
    db.add(order_sv)
    db.flush()

    pay_sv = Payment(
        service_order_id=order_sv.id,
        kind="PELUNASAN",
        amount=Decimal("150000.00"),
        method="CASH",
        note="Pelunasan Kasir",
        created_at=start,
    )
    db.add(pay_sv)
    db.flush()

    rows, opening = period_rows(db, start, end, with_opening=True)

    assert opening == opening_awal, f"Opening balance bertambah dari {opening_awal} menjadi {opening} karena GR-*"
    no_servis_list = [str(r.get("ket") or "") for r in rows]
    assert not any("GR-20260801-0999" in s for s in no_servis_list), "Order GR-* tidak boleh ada di mutasi kas"
    assert any("SV-20261106-9999" in s for s in no_servis_list), "Order SV-* harus tercatat di mutasi kas"


def test_dp_order_selesai_atau_cancel_tidak_mengotori_mutasi_kas(db):
    """DP dari unit yang sudah CANCEL / DIAMBIL tidak boleh masuk ke mutasi kas periode aktif."""
    start = datetime(2026, 11, 6, 0, 0, 0)
    end = datetime(2026, 11, 6, 23, 59, 59)

    rows_awal, opening_awal = period_rows(db, start, end, with_opening=True)

    cust = Customer(name="Customer Cancel DP", phone="081299990002")
    db.add(cust)
    db.flush()

    tgl_lampau = datetime(2026, 7, 17, 10, 0, 0)
    order_cancel = ServiceOrder(
        no_servis="SV-20260717-0999",
        customer_id=cust.id,
        device="Infinix Hot 40",
        status="CANCEL",
        unit_status="DIAMBIL",
        estimate=Decimal("500000.00"),
        final_price=Decimal("500000.00"),
        payment=Decimal("500000.00"),
        created_at=tgl_lampau,
    )
    db.add(order_cancel)
    db.flush()

    pay_dp_cancel = Payment(
        service_order_id=order_cancel.id,
        kind="DP",
        amount=Decimal("500000.00"),
        method="CASH",
        created_at=tgl_lampau,
    )
    db.add(pay_dp_cancel)
    db.flush()

    rows, opening = period_rows(db, start, end, with_opening=True)
    assert opening == opening_awal, "DP unit CANCEL/DIAMBIL tidak boleh menambah opening balance"
