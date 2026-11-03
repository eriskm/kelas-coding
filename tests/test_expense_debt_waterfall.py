# -*- coding: utf-8 -*-
"""Test pengaman untuk Waterfall Hutang Beban & Pelunasan Kas Aset Fleksibel.

Sesuai persetujuan Owner:
1. Prioritas Waterfall: Laba Kotor menutup Gaji Karyawan (CTS) 100% lebih dulu,
   sisa Laba Kotor baru menutup Beban Operasional (CTO).
2. Detail Beban: Rincian per karyawan (Karyawan 1, Karyawan 2) dan Operasional Toko.
3. Pelunasan Kas Aset Fleksibel: Bisa dibayar seadanya Kas Aset (sebagian) atau penuh.
4. Hak Akses: Hanya akun Owner (Admin / Pengelola) dan Developer (Superadmin).
   Kasir dan Teknisi tidak memiliki wewenang.
"""
from datetime import datetime, timedelta
from decimal import Decimal
import pytest
from sqlalchemy.orm import Session

from money import to_decimal, quantize, ZERO
import models as m
import cash as cash_mod
import expense_debt as debt_mod
import authority as auth


def _setup_periode_dengan_beban(db: Session, omzet_val, modal_val, kas_aset_val=0):
    """Setup periode kas dengan beban gaji dan operasional seperti contoh real toko."""
    mulai = datetime(2026, 11, 1, 9, 0, 0)
    selesai = mulai + timedelta(days=1)
    
    # 1. Kas Period (Gunakan periode OPEN aktif yang ada agar tidak mendobel periode terbuka)
    kp = db.query(m.KasPeriod).filter(m.KasPeriod.status == "OPEN").order_by(m.KasPeriod.id.desc()).first()
    if not kp:
        kp = m.KasPeriod(start_at=mulai, end_at=selesai, status="OPEN")
        db.add(kp)
        db.flush()
    else:
        kp.start_at = mulai
        kp.end_at = selesai
        db.flush()
    
    p_key = f"kas_period:{kp.id}"
    db.query(m.ExpensePeriod).filter(m.ExpensePeriod.periode == p_key).delete()
    db.query(m.ExpenseDebtEntry).delete()
    db.query(m.ExpenseDebtPeriod).delete()
    db.flush()
    
    # 2. Users (Karyawan)
    u_dana = db.query(m.User).filter_by(username="dana_test").first()
    if not u_dana:
        u_dana = m.User(username="dana_test", display_name="Ahmad Dana", role="Admin", passcode_hash="x", passcode_salt="s")
        db.add(u_dana)
        db.flush()
        
    u_reza = db.query(m.User).filter_by(username="reza_test").first()
    if not u_reza:
        u_reza = m.User(username="reza_test", display_name="Muhammad Reza", role="Kasir", passcode_hash="x", passcode_salt="s")
        db.add(u_reza)
        db.flush()
        
    # 3. Expense Periods (Frozen expenses)
    # Total Gaji = 400.000 (Dana 200rb, Reza 200rb)
    # Total Ops = 205.000 (Sewa 170rb, Pulsa 5rb, Listrik 14rb, Internet 16rb)
    # Total Beban = 605.000
    p_key = f"kas_period:{kp.id}"
    beban_data = [
        ("Gaji", "Gaji: Ahmad Dana", 200000, u_dana.id),
        ("Gaji", "Gaji: Muhammad Reza", 200000, u_reza.id),
        ("Operasional", "Sewa Tempat", 170000, None),
        ("Operasional", "Listrik", 14000, None),
        ("Operasional", "Internet", 16000, None),
        ("Operasional", "Pulsa", 5000, None),
    ]
    for kat, nama, nil, uid in beban_data:
        ep = m.ExpensePeriod(
            periode=p_key,
            kategori=kat,
            nama_beban=nama,
            nilai=to_decimal(nil),
            user_id=uid
        )
        db.add(ep)
    db.flush()

    # 4. Transaksi Servis (Omzet & Modal) jika ada
    if omzet_val > 0:
        cust = m.Customer(name="Pelanggan Test", phone="08123456789")
        db.add(cust)
        db.flush()
        
        so = m.ServiceOrder(
            no_servis="SO-TEST-1",
            customer_id=cust.id,
            device="Smartphone Test",
            status="CASH",
            unit_status="DIAMBIL",
            service_date=mulai.date(),
            taken_at=mulai,
            final_price=to_decimal(omzet_val),
            estimate=to_decimal(omzet_val),
            part_cost=to_decimal(modal_val),
            modal_jasa=ZERO,
            modal_lainnya=ZERO,
            technician="Dana",
            repair_plan="Service Test",
            created_at=mulai
        )
        db.add(so)
        db.flush()
        pay = m.Payment(
            service_order_id=so.id,
            kind="PELUNASAN",
            amount=to_decimal(omzet_val),
            created_at=mulai
        )
        db.add(pay)
        db.flush()

    # 5. Kas Aset jika ada
    if kas_aset_val > 0:
        cash_mod.catat_mutasi(
            db,
            layer=cash_mod.LAYER_KAS_ASET,
            jenis="Masuk",
            kategori="Suntik Modal",
            keterangan="Suntikan Kas Aset Test",
            nominal=to_decimal(kas_aset_val),
            tanggal=mulai.date()
        )
        db.flush()

    return {"kp": kp, "p_key": p_key, "u_dana": u_dana, "u_reza": u_reza}


def test_breakdown_waterfall_cts_tercapai_cto_minus(db):
    """Skenario Kasus User:
    Total Gaji = 400.000, Total Ops = 205.000, Total Beban = 605.000.
    Laba Kotor = 505.000 (Omzet 751.250 - Modal 246.250).
    Waterfall:
    - Gaji tercover 100% -> Hutang Gaji = 0 (Dana Rp 0, Reza Rp 0 / LUNAS)
    - Operasional tercover 105.000 -> Hutang Operasional = 100.000
    - Total Hutang Beban Toko = 100.000 (Hanya berhutang ke Operasional).
    """
    ctx = _setup_periode_dengan_beban(db, omzet_val=751250, modal_val=246250)
    
    bd = debt_mod.hitung_breakdown_hutang(db, kas_period_id=ctx["kp"].id)
    
    assert bd["total_gaji"] == Decimal("400000")
    assert bd["total_ops"] == Decimal("205000")
    assert bd["total_beban"] == Decimal("605000")
    assert bd["laba_kotor"] == Decimal("505000")
    
    # Hak Keringat Karyawan (CTS): Bebas Hutang (Lunas)
    assert bd["hutang_gaji"] == Decimal("0")
    for g in bd["gaji_items"]:
        assert g["hutang"] == Decimal("0")
        assert g["terbayar"] == g["nilai"]
        assert g["status"] == "LUNAS"
        
    # Beban Operasional (CTO): Minus 100.000
    assert bd["hutang_ops"] == Decimal("100000")
    assert bd["total_hutang"] == Decimal("100000")


def test_breakdown_waterfall_cts_belum_tercapai(db):
    """Skenario ketika Laba Kotor sangat kecil (250.000):
    Waterfall:
    - Gaji 400.000 tercover 250.000 -> Hutang Gaji = 150.000 (dibagi prorata ke Ahmad Dana & Reza)
    - Operasional 205.000 tidak tercover sama sekali (0) -> Hutang Ops = 205.000
    - Total Hutang Beban = 355.000.
    """
    ctx = _setup_periode_dengan_beban(db, omzet_val=496250, modal_val=246250)
    
    bd = debt_mod.hitung_breakdown_hutang(db, kas_period_id=ctx["kp"].id)
    
    assert bd["laba_kotor"] == Decimal("250000")
    assert bd["gaji_tercover"] == Decimal("250000")
    assert bd["hutang_gaji"] == Decimal("150000")
    assert bd["hutang_ops"] == Decimal("205000")
    assert bd["total_hutang"] == Decimal("355000")
    
    # Cek rincian gaji karyawan
    for g in bd["gaji_items"]:
        assert g["terbayar"] == Decimal("125000")  # Porsi 50% dari 250rb
        assert g["hutang"] == Decimal("75000")
        assert g["status"] in ("SEBAGIAN", "TERTUNGGAK")


def test_pelunasan_fleksibel_sebagian_dari_kas_aset(db):
    """Pengujian pelunasan nominal fleksibel (bayar seadanya kas aset):
    Hutang Beban total 100.000 (Operasional).
    Kas Aset memiliki saldo 60.000.
    Owner membayar seadanya: nominal 60.000.
    - Pelunasan berhasil
    - Kas Aset berkurang 60.000 (sisa 0)
    - Sisa Hutang berkurang dari 100.000 menjadi 40.000.
    """
    ctx = _setup_periode_dengan_beban(db, omzet_val=751250, modal_val=246250, kas_aset_val=60000)
    
    # Catat hutang manual 100.000 sesuai defisit
    debt_mod.catat_hutang_manual(
        db,
        periode_key=ctx["p_key"],
        nominal=Decimal("100000"),
        kas_period_id=ctx["kp"].id,
        oleh="Ahmad Dana"
    )
    
    assert debt_mod.saldo_hutang(db) == Decimal("100000")
    aset_awal = cash_mod.saldo_kas_aset(db)
    
    # Pelunasan fleksibel nominal 60.000 (seadanya kas aset)
    res = debt_mod.lunas_hutang(
        db,
        nominal=Decimal("60000"),
        periode=ctx["p_key"],
        oleh="Ahmad Dana"
    )
    
    # Verifikasi hasil
    assert res["saldo_hutang"] == Decimal("40000")
    assert debt_mod.saldo_hutang(db) == Decimal("40000")
    # v4 #8: Kewajiban berkurang secara riil, saldo posisi Kas Aset tidak berubah otomatis
    assert cash_mod.saldo_kas_aset(db) == aset_awal


def test_pelunasan_melebihi_saldo_kas_aset_ditolak(db):
    """Validasi: Jika nominal yang diinput melebihi saldo Kas Aset yang tersedia, wajib tolak."""
    ctx = _setup_periode_dengan_beban(db, omzet_val=751250, modal_val=246250)
    
    debt_mod.catat_hutang_manual(
        db,
        periode_key=ctx["p_key"],
        nominal=Decimal("100000000"),
        kas_period_id=ctx["kp"].id,
        oleh="Ahmad Dana"
    )
    
    aset_tersedia = cash_mod.saldo_kas_aset(db)
    nominal_lebih = aset_tersedia + Decimal("500000")
    with pytest.raises(debt_mod.DebtError, match="Saldo Kas Aset tidak cukup"):
        debt_mod.lunas_hutang(db, nominal=nominal_lebih, periode=ctx["p_key"])


def test_pelunasan_melebihi_saldo_hutang_ditolak(db):
    """Validasi: Jika nominal melebihi sisa hutang, wajib tolak."""
    ctx = _setup_periode_dengan_beban(db, omzet_val=751250, modal_val=246250, kas_aset_val=200000)
    
    debt_mod.catat_hutang_manual(
        db,
        periode_key=ctx["p_key"],
        nominal=Decimal("100000"),
        kas_period_id=ctx["kp"].id,
        oleh="Ahmad Dana"
    )
    
    with pytest.raises(debt_mod.DebtError, match="melebihi sisa Hutang Beban"):
        debt_mod.lunas_hutang(db, nominal=Decimal("150000"), periode=ctx["p_key"])


def test_hak_akses_hanya_owner_dan_developer():
    """Wewenang EXPENSE_DEBT_WRITE hanya dimiliki Owner (Admin / Pengelola) dan Developer (Superadmin).
    Kasir, Teknisi, dan role lain ditolak.
    """
    class MockUser:
        def __init__(self, role):
            self.role = role

    u_dev = MockUser("SUPERADMIN")
    u_admin = MockUser("ADMIN")
    u_pengelola = MockUser("PENGELOLA")
    u_kasir = MockUser("KASIR")
    u_teknisi = MockUser("TEKNISI")
    u_investor = MockUser("INVESTOR")

    # Developer & Owner (Admin) HARUS BISA
    assert auth.can(u_dev, auth.Action.EXPENSE_DEBT_WRITE) is True
    assert auth.can(u_admin, auth.Action.EXPENSE_DEBT_WRITE) is True

    # Karyawan lain (Kasir, Teknisi) dan Role Monitoring Read-Only (Pengelola, Investor) HARUS DITOLAK
    assert auth.can(u_kasir, auth.Action.EXPENSE_DEBT_WRITE) is False
    assert auth.can(u_teknisi, auth.Action.EXPENSE_DEBT_WRITE) is False
    assert auth.can(u_pengelola, auth.Action.EXPENSE_DEBT_WRITE) is False
    assert auth.can(u_investor, auth.Action.EXPENSE_DEBT_WRITE) is False


def test_api_endpoints_waterfall_dan_lunas_fleksibel(client, db):
    """Test integrasi HTTP API:
    - GET /api/beban-hutang mengembalikan objek 'breakdown'
    - GET /api/beban-hutang/breakdown mengembalikan status 200
    - POST /api/beban-hutang/lunas menerima body JSON {'nominal': ...}
    - Role Kasir ditolak 403 saat memanggil POST /api/beban-hutang/lunas
    """
    ctx = _setup_periode_dengan_beban(db, omzet_val=751250, modal_val=246250, kas_aset_val=100000)
    debt_mod.catat_hutang_manual(
        db,
        periode_key=ctx["p_key"],
        nominal=Decimal("100000"),
        kas_period_id=ctx["kp"].id,
        oleh="Ahmad Dana"
    )
    db.commit()

    # 1. Login sebagai Admin (Owner)
    from routers.auth import create_token
    token_admin = create_token(db, ctx["u_dana"])
    headers_admin = {"Authorization": f"Bearer {token_admin}"}

    # 2. GET /api/beban-hutang
    r = client.get("/api/beban-hutang", headers=headers_admin)
    assert r.status_code == 200
    data = r.json()
    assert "breakdown" in data
    assert data["breakdown"]["total_gaji"] == 400000
    assert data["breakdown"]["total_ops"] == 205000

    # 3. GET /api/beban-hutang/breakdown
    r_bd = client.get("/api/beban-hutang/breakdown", headers=headers_admin)
    assert r_bd.status_code == 200
    bd_data = r_bd.json()
    assert bd_data["hutang_gaji"] == 0
    assert bd_data["hutang_ops"] == 100000

    # 4. Login sebagai Kasir (Karyawan tanpa hak)
    token_kasir = create_token(db, ctx["u_reza"])
    headers_kasir = {"Authorization": f"Bearer {token_kasir}"}

    # Kasir mencoba melunasi -> DITOLAK 403
    r_fail = client.post("/api/beban-hutang/lunas", json={"nominal": 50000}, headers=headers_kasir)
    assert r_fail.status_code == 403

    # 5. Admin (Owner) melunasi secara fleksibel (50.000)
    aset_terekam = cash_mod.saldo_kas_aset(db)
    r_lunas = client.post("/api/beban-hutang/lunas", json={"nominal": 50000}, headers=headers_admin)
    assert r_lunas.status_code == 200
    lunas_data = r_lunas.json()
    assert Decimal(str(lunas_data["saldo_hutang"])) == Decimal("50000")
    assert Decimal(str(lunas_data["saldo_kas_aset"])) == aset_terekam

