# -*- coding: utf-8 -*-
"""Aturan Owner tentang Modal dan Omzet.

Empat aturan yang ditegaskan Owner:
  1. DONE  -> Perbaikan/Tindakan WAJIB + Harga Final WAJIB.
  2. CASH  -> Perbaikan/Tindakan WAJIB; Modal Part & Jasa BOLEH 0.
  3. Unit CASH yang Modalnya belum diisi BELUM masuk Omzet/Transaksi.
  4. Tutup Kas memunculkan peringatan keras kalau ada transaksi tanpa Modal.

Yang paling berdampak adalah (3): sebelumnya unit CASH modal-0 ikut dihitung
sebagai Omzet, padahal tidak ada biaya sama sekali yang tercatat -- seluruh
Harga Final jadi dianggap laba. Omzet meleset, Laba Kotor naik, CTO bisa
tercapai lebih awal, dan Distribution bisa keluar dari uang yang sebenarnya
bukan keuntungan.
"""
import pytest

import finance


def _unit(db, no, harga, modal=(0, 0, 0), status="CASH", repair_plan="x",
          technician="B", final_price=None, lunas=True):
    import models
    from datetime import date
    from decimal import Decimal
    from money import to_decimal
    cust = db.query(models.Customer).filter(
        models.Customer.name == "Pytest Customer").first()
    o = models.ServiceOrder(
        no_servis=no, customer_id=cust.id, device="PY", status=status,
        service_date=date.today(), created_at=__import__("datetime").datetime.now(),
        taken_at=__import__("datetime").datetime.now(),
        repair_plan=repair_plan, technician=technician, warranty_months=1,
        estimate=to_decimal(harga),
        final_price=to_decimal(harga) if final_price is None else to_decimal(final_price),
        payment=to_decimal("0"))
    o.part_cost, o.modal_jasa, o.modal_lainnya = [to_decimal(x) for x in modal]
    db.add(o)
    db.flush()
    if lunas and status == "CASH":
        # ATURAN OWNER: Omzet hanya dari transaksi LUNAS. Tanpa baris pelunasan,
        # unit tidak masuk cohort Omzet sama sekali -- jadi test yang menghitung
        # dampak ke Omzet WAJIB menulis PELUNASAN lewat helper ini.
        db.add(models.Payment(service_order_id=o.id, kind="PELUNASAN",
                              amount=o.final_price, method="CASH", note="lunas"))
        db.flush()
    db.commit()
    db.refresh(o)
    return o


def _token(db):
    import models
    from datetime import datetime, timedelta
    u = db.query(models.User).filter(models.User.username == "pytest_admin").first()
    if u is None:
        u = models.User(username="pytest_admin", display_name="Pytest Admin", role="ADMIN",
                        passcode_hash="x", passcode_salt="y", active=True)
        db.add(u); db.commit(); db.refresh(u)
    t = db.query(models.AuthToken).filter(
        models.AuthToken.token == "pytest-token-admin").first()
    if t is None:
        db.add(models.AuthToken(token="pytest-token-admin", user_id=u.id,
                                expires_at=datetime.now() + timedelta(days=2)))
        db.commit()
    db.expunge_all()
    return {"Authorization": "Bearer pytest-token-admin"}


# ── (1) DONE wajib Harga Final ────────────────────────────────────────────────
def test_done_menolak_harga_final_kosong(client, db):
    auth = _token(db)
    o = _unit(db, "AT-DONE-HARGA0", 400000, modal=(100000, 20000, 0),
              status="REPAIR", final_price=0)
    r = client.put("/api/orders/%d" % o.id, headers=auth, json={"status": "DONE"})
    assert r.status_code == 400, r.text
    assert "Harga Final" in r.json()["detail"], r.json()["detail"]


def test_done_menolak_tindakan_kosong(client, db):
    auth = _token(db)
    o = _unit(db, "AT-DONE-TINDAKAN", 400000, modal=(100000, 20000, 0),
              status="REPAIR", repair_plan="")
    r = client.put("/api/orders/%d" % o.id, headers=auth, json={"status": "DONE"})
    assert r.status_code == 400
    assert "Perbaikan / Tindakan Perbaikan" in r.json()["detail"]


def test_done_lolos_kalau_semua_lengkap(client, db):
    auth = _token(db)
    o = _unit(db, "AT-DONE-OK", 400000, modal=(100000, 20000, 0), status="REPAIR")
    r = client.put("/api/orders/%d" % o.id, headers=auth, json={"status": "DONE"})
    assert r.status_code == 200, r.text


# ── (2) CASH tetap boleh dengan Modal 0 ───────────────────────────────────────
def test_cash_tetap_boleh_dengan_modal_nol(client, db):
    auth = _token(db)
    o = _unit(db, "AT-CASH-MODAL0", 400000, modal=(0, 0, 0), status="DONE")
    r = client.put("/api/orders/%d" % o.id, headers=auth, json={"status": "CASH"})
    assert r.status_code == 200, r.text


# ── (3) Modal kosong = belum masuk Omzet ─────────────────────────────────────
def test_modal_sudah_diisi_mendeteksi():
    from money import to_decimal
    from decimal import Decimal

    class _O:
        pass
    o = _O()
    o.part_cost = o.modal_jasa = o.modal_lainnya = Decimal(0)
    assert finance.modal_sudah_diisi(o) is False
    o.part_cost = Decimal(1)
    assert finance.modal_sudah_diisi(o) is True
    o.part_cost = Decimal(0); o.modal_jasa = Decimal(50000)
    assert finance.modal_sudah_diisi(o) is True
    o.modal_jasa = Decimal(0); o.modal_lainnya = Decimal(25000)
    assert finance.modal_sudah_diisi(o) is True
    o.modal_lainnya = Decimal(0)
    assert finance.modal_sudah_diisi(o) is False


def test_unit_cash_modal_nol_tidak_masuk_kohort(db):
    """Nilai mutlak tidak bisa dibandingkan (sandbox bersama) -> pakai delta."""
    from money import to_decimal
    from routers.dashboard import batas_periode
    p = _periode_aktif(db)
    # PENTING: pakai batas dari APLIKASI, bukan `p.end_at` mentah. Untuk periode
    # yang masih OPEN, `batas_periode()` mengembalikan `datetime.max` -- kalau
    # pakai end_at mentah (jam 16.00), setiap order yang dibuat lewat jam 16.00
    # akan berada di LUAR periode dan test ini ikut gagal.
    awal, akhir = batas_periode(p)
    isi = _unit(db, "AT-OMZET-ISI", 400000, modal=(200000, 50000, 0))
    sebelum = to_decimal(finance.compute_finance_core(db, awal, akhir)["omset"])
    kosong = _unit(db, "AT-OMZET-KOSONG", 500000, modal=(0, 0, 0))
    sesudah = to_decimal(finance.compute_finance_core(db, awal, akhir)["omset"])
    ids = [x.id for x in finance.settled_orders(db, awal, akhir)]
    assert kosong.id not in ids
    assert isi.id in ids
    assert sesudah == sebelum, "Omset harus tidak berubah: %s -> %s" % (sebelum, sesudah)


# ── (4) Peringatan keras ──────────────────────────────────────────────────────
def test_peringatan_menyebut_ARTI_baru_bukan_lagi_sah(client, db):
    """Keterangan endpoint harus sesuai aturan terbaru: modal 0 = belum lengkap."""
    auth = _token(db)
    d = client.get("/api/kas/modal-kosong?period=current", headers=auth).json()
    ket = d["keterangan"].lower()
    # Tidak boleh lagi berbunyi "modal 0 itu sah" sebagai alasan utama,
    # karena aturan Owner sekarang: modal kosong berarti belum masuk Omzet.
    assert "sah" not in ket, d["keterangan"]


def _periode_aktif(db):
    from routers.dashboard import get_active_period
    return get_active_period(db)