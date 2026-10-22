# -*- coding: utf-8 -*-
"""Integritas ledger kas: `saldo_setelah` dan proteksi hapus entri.

Dua hal yang dikunci di sini.

(1) RANTAI `saldo_setelah` HARUS sama dengan running sum sebenarnya.

    `saldo_setelah` adalah saldo berjalan yang disimpan saat entri dibuat.
    Ia bisa basi kalau ada entri yang dihapus setelahnya, atau kalau entri
    dibuat di tengah satu request sehingga urutannya tidak sama dengan
    urutan waktu. Yang dipakai untuk menghitung uang (`cash.saldo_layer`)
    selalu dihitung ulang dari `nominal`, jadi yang basi cuma tampilan --
    tapi tampilan yang melompat membuat seolah-olah uang hilang.

    Bukti produksi (2026-10-19): 8 entri lama periode 2026-10-15 menyimpan
    angka 500.000 lebih rendah dari running sum, karena entri DP dibuat
    saat server jalan dengan kode setengah jadi.

(2) ENDPOINT HAPUS ENTRI KAS tidak boleh jadi pintu kehilangan uang.

    `DELETE /api/kas/entries/{id}` dulu bisa menghapus entri APAPUN dari
    periode yang sudah ditutup, tanpa jurnal dan tanpa jejak. Menghapus
    entri modal berarti Laci bertambah diam-diam tanpa ada transaksi yang
    tercatat, dan `distributions.laci_adjust_entry_id` bisa jadi menunjuk
    ke entri yang sudah tidak ada.
"""
from datetime import datetime, timedelta
from decimal import Decimal

import pytest


# ─────────────────────────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────────────────────────

def _auth(db):
    import models
    u = db.query(models.User).filter(
        models.User.username == "pytest_admin").first()
    if u is None:
        u = models.User(username="pytest_admin", display_name="Pytest Admin",
                        role="ADMIN", passcode_hash="x", passcode_salt="y",
                        active=True)
        db.add(u); db.commit(); db.refresh(u)
    t = db.query(models.AuthToken).filter(
        models.AuthToken.token == "pytest-token-admin").first()
    if t is None:
        db.add(models.AuthToken(token="pytest-token-admin", user_id=u.id,
                                expires_at=datetime.now() + timedelta(days=2)))
        db.commit()
    db.expunge_all()
    return {"Authorization": "Bearer pytest-token-admin"}


def _entri(db, jenis="Masuk", nominal=100000, sumber="MANUAL", kategori=None,
           keterangan="uji"):
    """Buat entri kas (baris ledger) untuk diuji."""
    import models
    kat = kategori or ("Uji" if sumber == "MANUAL" else sumber)
    row = models.KasEntry(
        jenis=jenis, kategori=kat, keterangan=keterangan,
        nominal=Decimal(nominal), layer="LACI",
        saldo_setelah=Decimal(0), sumber=sumber)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _running_sum(db, layer="LACI"):
    """Running sum SEBENARNYA (tanpa ikut `saldo_setelah`)."""
    import models
    tot = Decimal(0)
    for e in db.query(models.KasEntry).filter(
            models.KasEntry.layer == layer).all():
        n = Decimal(str(e.nominal or 0))
        tot += n if (e.jenis or "").lower() == "masuk" else -n
    return tot


def _rantai_basi(db, layer="LACI"):
    """List (id, stored, expected) untuk baris non-SaldoAwal yang tidak cocok.

    Expected dihitung dari `saldo_layer` (SSOT uang) dikurangi akumulasi baris
    SETELAH baris itu. Rumusnya independen dari loop `recompute_saldo_setelah`
    -- jadi kalau keduanya sepakat, itu bukan tautologi.

        saldo_layer = opening + sum(non_SaldoAwal)
        expected_i  = saldo_layer - sum(non_SaldoAwal setelah i)
                    = opening + sum(non_SaldoAwal sampai i)
    """
    import cash as cash_mod
    rows = cash_mod.rows_layer(db, layer)
    urut = sorted(rows, key=lambda r: (cash_mod._moment(r) or datetime.min,
                                       r.id or 0))
    non_sa = [r for r in urut
              if (r.kategori or "").strip() != cash_mod.SALDO_AWAL_KATEGORI]
    total = cash_mod.saldo_layer(db, layer)

    tails = [Decimal(0)] * len(non_sa)
    acc = Decimal(0)
    for i in range(len(non_sa) - 1, -1, -1):
        tails[i] = acc
        r = non_sa[i]
        n = Decimal(str(r.nominal or 0))
        acc += n if (r.jenis or "").lower() == "masuk" else -n

    salah = []
    for i, r in enumerate(non_sa):
        expected = Decimal(total) - tails[i]
        stored = Decimal(str(r.saldo_setelah or 0))
        if stored != expected:
            salah.append((r.id, stored, expected))
    return salah


# ─────────────────────────────────────────────────────────────────
# 1. Rantai saldo_setelah
# ─────────────────────────────────────────────────────────────────

def test_recompute_menyamakan_rantai(client, db):
    """Setelah `recompute_saldo_setelah`, tidak ada baris yang tidak cocok."""
    import cash as cash_mod
    _auth(db)
    _entri(db, "Masuk", 300000, keterangan="uji-1")
    _entri(db, "Keluar", 120000, keterangan="uji-2")
    _entri(db, "Masuk", 50000, keterangan="uji-3")

    # sengaja bikin basi: ketik angka yang salah pada satu baris
    import models
    baris = db.query(models.KasEntry).filter(
        models.KasEntry.keterangan == "uji-2").first()
    baris.saldo_setelah = Decimal(1)
    db.commit()
    db.expunge_all()
    assert _rantai_basi(db), "syarat: harus ada baris yang tidak cocok"
    # SALDO itu sendiri tidak boleh berubah - yang dibetulkan hanya saldonya.
    sebelum = _running_sum(db)

    diubah = cash_mod.recompute_saldo_setelah(db)
    db.commit()
    db.expunge_all()

    assert diubah >= 1, "recompute harus melaporkan baris yang diperbaiki"
    assert _rantai_basi(db) == [], \
        "semua baris harus punya saldo_setelah yang sama dengan running sum"
    assert _running_sum(db) == sebelum, "running sum tidak boleh berubah"


def test_recompute_idempoten(client, db):
    """Jalankan dua kali: kedua call tidak boleh mengubah apa pun."""
    import cash as cash_mod
    _auth(db)
    _entri(db, "Masuk", 250000, keterangan="uji-idem")
    _entri(db, "Keluar", 75000, keterangan="uji-idem-2")
    cash_mod.recompute_saldo_setelah(db)
    db.commit()
    db.expunge_all()

    kedua = cash_mod.recompute_saldo_setelah(db)
    db.commit()
    db.expunge_all()
    assert kedua == 0, "panggil kedua harus tidak mengubah apa pun"
    assert _rantai_basi(db) == []


def test_recompute_tidak_mengubah_nominal(client, db):
    """Recompute hanya menyentuh `saldo_setelah`; nominal & jenis utuh."""
    import cash as cash_mod
    import models
    _auth(db)
    e = _entri(db, "Masuk", 175000, keterangan="uji-utuh")
    eid, enom, ejenis = e.id, e.nominal, e.jenis
    cash_mod.recompute_saldo_setelah(db)
    db.commit()
    db.expunge_all()
    e2 = db.query(models.KasEntry).get(eid)
    assert e2.nominal == enom, "nominal tidak boleh berubah"
    assert e2.jenis == ejenis, "jenis tidak boleh berubah"


def test_migrasi_saldo_setelah_ada_dan_idempoten(client, db):
    """Migrasi startup harus ada dan aman dipanggil berulang."""
    from migrations_saldo_setelah import migrate_saldo_setelah
    from database import engine
    a = migrate_saldo_setelah(engine)
    b = migrate_saldo_setelah(engine)
    assert "changed" in a and "skipped" in a
    assert b["skipped"], "panggilan kedua harus melompat (sudah cocok)"


# ─────────────────────────────────────────────────────────────────
# 2. Hapus entri kas
# ─────────────────────────────────────────────────────────────────

def test_entri_sistem_tidak_bisa_dihapus(client, db):
    """Entri modal/beban/distribusi = bukti perpindahan uang."""
    auth = _auth(db)
    e = _entri(db, "Keluar", 450000, sumber="MODAL", kategori="Pembelian Modal",
               keterangan="Modal Part unit uji")
    r = client.delete("/api/kas/entries/%d" % e.id, headers=auth)
    assert r.status_code == 400, r.text
    assert "sistem" in r.text.lower(), r.text

    import models
    db.expunge_all()
    assert db.query(models.KasEntry).get(e.id) is not None, \
        "entri sistem tidak boleh hilang"


def test_entri_manual_bisa_dihapus(client, db):
    """Entri MANUAL milik user tetap boleh dihapus (perilaku lama)."""
    auth = _auth(db)
    e = _entri(db, "Masuk", 25000, sumber="MANUAL", keterangan="catatan manual")
    r = client.delete("/api/kas/entries/%d" % e.id, headers=auth)
    assert r.status_code == 200, r.text

    import models
    db.expunge_all()
    assert db.query(models.KasEntry).get(e.id) is None, "entri manual harus hilang"


def test_hapus_entri_mencatat_jurnal(client, db):
    """Penghapusan harus ada jejaknya di jurnal (append-only)."""
    auth = _auth(db)
    import journal
    import models
    e = _entri(db, "Masuk", 25000, sumber="MANUAL", keterangan="catatan manual")
    before = db.query(models.JournalEntry).filter(
        models.JournalEntry.event == "ENTRI_KAS_DIHAPUS").count()
    r = client.delete("/api/kas/entries/%d" % e.id, headers=auth)
    assert r.status_code == 200, r.text
    db.expunge_all()
    after = db.query(models.JournalEntry).filter(
        models.JournalEntry.event == "ENTRI_KAS_DIHAPUS").count()
    assert after == before + 1, "penghapusan harus tercatat di jurnal"


def test_hapus_entri_memperbarui_rantai_saldo(client, db):
    """Setelah menghapus entri, rantai saldo_setelah harus tetap benar."""
    auth = _auth(db)
    e1 = _entri(db, "Masuk", 400000, keterangan="uji-rantai-1")
    e2 = _entri(db, "Keluar", 150000, keterangan="uji-rantai-2")
    e3 = _entri(db, "Masuk", 90000, keterangan="uji-rantai-3")
    eid2 = e2.id

    import cash as cash_mod
    cash_mod.recompute_saldo_setelah(db)
    db.commit()
    db.expunge_all()
    assert _rantai_basi(db) == []

    r = client.delete("/api/kas/entries/%d" % eid2, headers=auth)
    assert r.status_code == 200, r.text
    db.expunge_all()

    assert _rantai_basi(db) == [], \
        "rantai saldo_setelah harus dihitung ulang setelah penghapusan"


def test_entri_periode_tertutup_tidak_bisa_dihapus(client, db):
    """Periode tertutup = final (OD-LOCK-11)."""
    auth = _auth(db)
    import models
    from routers.dashboard import batas_periode
    lama = datetime.now() - timedelta(days=3)
    p = models.KasPeriod(status="CLOSED", start_at=lama, end_at=lama + timedelta(days=1),
                         closed_at=lama, closed_by="uji", created_at=lama)
    db.add(p)
    db.commit()
    db.refresh(p)
    pid = p.id
    db.expunge_all()
    p2 = db.query(models.KasPeriod).get(pid)
    start, end = batas_periode(p2)
    e = _entri(db, "Masuk", 75000, sumber="MANUAL", keterangan="uji-tertutup")
    eid = e.id
    # paksa momentenya ke dalam periode tertutup
    row = db.query(models.KasEntry).get(eid)
    row.created_at = start + timedelta(hours=1)
    db.commit()
    db.expunge_all()

    r = client.delete("/api/kas/entries/%d" % eid, headers=auth)
    assert r.status_code == 400, r.text
    assert "ditutup" in r.text.lower() or "final" in r.text.lower(), r.text

    db.expunge_all()
    assert db.query(models.KasEntry).get(eid) is not None, \
        "entri periode tertutup tidak boleh hilang"