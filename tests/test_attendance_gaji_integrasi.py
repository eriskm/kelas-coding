# -*- coding: utf-8 -*-
"""Test integrasi Kelola Akun (User.gaji_harian) -> Absensi -> Beban Gaji Toko.

Sesuai arahan Owner:
1. Tambah karyawan cukup tambah akun di Kelola Akun beserta Gaji Harian.
2. Kehadiran karyawan per periode menentukan Beban Gaji toko.
3. Jika karyawan tidak masuk (Libur/Izin/Alpha), gajinya disable (Rp 0),
   sehingga beban toko hari itu berkurang dan laci tidak mengeluarkan uang fiktif.
"""
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from models import KasPeriod, User, UserAttendance, ExpensePeriod
from money import ZERO, to_decimal
from finance import (
    freeze_expenses_for_period,
    sync_open_period_salary_expense,
    beban_frozen,
    period_key,
)


def test_user_gaji_harian_and_attendance_toggle(client):
    from database import SessionLocal

    db = SessionLocal()
    try:
        now = datetime.now()
        start = now.replace(hour=16, minute=0, second=0, microsecond=0)
        if now < start:
            start -= timedelta(days=1)
        end = start + timedelta(days=1)

        # 1. Pastikan ada periode kas OPEN
        p = db.query(KasPeriod).filter(KasPeriod.status == "OPEN").first()
        if not p:
            p = KasPeriod(start_at=start, end_at=end, status="OPEN")
            db.add(p)
            db.commit()
            db.refresh(p)

        # 2. Buat 2 user baru dengan gaji harian
        u_kasir = db.query(User).filter(User.username == "test_kasir_abs").first()
        if not u_kasir:
            u_kasir = User(
                username="test_kasir_abs",
                display_name="Kasir Test",
                role="Kasir",
                passcode_hash="fakehash",
                passcode_salt="fakesalt",
                active=1,
                gaji_harian=to_decimal(150000),
            )
            db.add(u_kasir)

        u_cs = db.query(User).filter(User.username == "test_cs_abs").first()
        if not u_cs:
            u_cs = User(
                username="test_cs_abs",
                display_name="CS Test",
                role="Kasir",
                passcode_hash="fakehash",
                passcode_salt="fakesalt",
                active=1,
                gaji_harian=to_decimal(200000),
            )
            db.add(u_cs)

        db.commit()
        db.refresh(u_kasir)
        db.refresh(u_cs)

        assert u_kasir.gaji_harian == Decimal("150000.00")
        assert u_cs.gaji_harian == Decimal("200000.00")

        # 3. Buat absensi awal (keduanya hadir)
        db.query(UserAttendance).filter(UserAttendance.kas_period_id == p.id).delete()
        att1 = UserAttendance(
            kas_period_id=p.id,
            user_id=u_kasir.id,
            hadir=True,
            gaji_nominal=u_kasir.gaji_harian,
            keterangan="Hadir",
        )
        att2 = UserAttendance(
            kas_period_id=p.id,
            user_id=u_cs.id,
            hadir=True,
            gaji_nominal=u_cs.gaji_harian,
            keterangan="Hadir",
        )
        db.add_all([att1, att2])
        db.commit()

        # 4. Sinkronkan beban gaji periode open
        res_sync = sync_open_period_salary_expense(db, p.id)
        assert res_sync.get("gaji_rows") >= 2

        # Cek beban gaji total saat keduanya hadir
        key = period_key(db, p.start_at, p.end_at)
        gaji_rows = (
            db.query(ExpensePeriod)
            .filter(ExpensePeriod.periode == key, ExpensePeriod.kategori == "Gaji")
            .all()
        )
        total_gaji_hadir = sum((r.nilai for r in gaji_rows), ZERO)
        # Setidaknya 150.000 + 200.000 = 350.000
        assert total_gaji_hadir >= Decimal("350000.00")

        # 5. Karyawan CS TIDAK MASUK (Libur/Absen)
        att2.hadir = False
        att2.gaji_nominal = ZERO
        att2.keterangan = "Tidak Masuk / Izin"
        db.commit()

        # Sinkronkan kembali
        sync_open_period_salary_expense(db, p.id)

        # Beban gaji harus berkurang sebesar 200.000
        gaji_rows_after = (
            db.query(ExpensePeriod)
            .filter(ExpensePeriod.periode == key, ExpensePeriod.kategori == "Gaji")
            .all()
        )
        total_gaji_after = sum((r.nilai for r in gaji_rows_after), ZERO)
        assert total_gaji_after == total_gaji_hadir - Decimal("200000.00")

        # Verifikasi beban_frozen membaca angka yang baru
        beban = beban_frozen(db, p.start_at, p.end_at, commit=False)
        assert beban["gaji"] == total_gaji_after

    finally:
        try:
            db.query(UserAttendance).filter(UserAttendance.user_id.in_([u_kasir.id, u_cs.id])).delete(synchronize_session=False)
            db.query(ExpensePeriod).filter(ExpensePeriod.user_id.in_([u_kasir.id, u_cs.id])).delete(synchronize_session=False)
            db.query(User).filter(User.id.in_([u_kasir.id, u_cs.id])).delete(synchronize_session=False)
            db.commit()
        except Exception:
            pass
        db.close()



def test_attendance_api_endpoints(client, db):
    headers = {"Authorization": "Bearer pytest-token-admin"}
    
    # Test GET /api/attendance/today
    res = client.get("/api/attendance/today", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert "items" in data
    assert "total_karyawan" in data
    assert "total_beban_gaji" in data

    if data["items"]:
        first_user = data["items"][0]
        uid = first_user["user_id"]
        
        # Test toggle to False
        res_toggle = client.post(
            "/api/attendance/toggle",
            json={"user_id": uid, "hadir": False, "keterangan": "Libur Toko"},
            headers=headers
        )
        assert res_toggle.status_code == 200
        toggled_data = res_toggle.json()
        target_item = next(it for it in toggled_data["items"] if it["user_id"] == uid)
        assert target_item["hadir"] is False
        assert Decimal(str(target_item["gaji_nominal"])) == 0
        assert target_item["keterangan"] == "Libur Toko"

        # Test toggle back to True
        res_back = client.post(
            "/api/attendance/toggle",
            json={"user_id": uid, "hadir": True},
            headers=headers
        )
        assert res_back.status_code == 200
        back_data = res_back.json()
        target_back = next(it for it in back_data["items"] if it["user_id"] == uid)
        assert target_back["hadir"] is True
        assert target_back["keterangan"] == "Hadir"
