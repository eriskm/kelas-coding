# -*- coding: utf-8 -*-
"""P2-15 B-1 & B-2 — regression test.

B-1: Tutup Kas kedua pada TANGGAL KALENDER YANG SAMA harus berhasil
     (bukan 500, bukan dianggap replay periode pertama, tanpa double cash-out).
B-2: `snapshot.selisih` harus memakai basis LEDGER Laci (counted vs Saldo Laci)
     — sama dengan selisih yang dicatat sebagai penyesuaian, bukan `fin["saldo"]`.
"""
from datetime import datetime, timedelta

import pytest

import cash
import closing
import distribution as dist
from money import to_decimal
from routers.dashboard import compute_finance as _cf


def _kunci(tanggal):
    return tanggal.date().isoformat()


def test_b1_distribusi_unik_per_kas_period(db):
    """B-1a: dua Kas Period pada tanggal sama -> dua Distribution, tanpa bentrok."""
    from models import Distribution, KasPeriod
    db.query(Distribution).delete()
    db.query(KasPeriod).delete()
    db.commit()

    hari = datetime(2026, 10, 6)
    p1 = KasPeriod(start_at=datetime(2026, 10, 5, 16), end_at=hari, status="CLOSED")
    db.add(p1); db.commit(); db.refresh(p1)
    p2 = KasPeriod(start_at=datetime(2026, 10, 6, 17, 15), end_at=datetime(2026, 10, 7, 16),
                   status="OPEN")
    db.add(p2); db.commit(); db.refresh(p2)

    key = _kunci(hari)
    d1 = dist.terapkan(db, key, "1000000", kas_period_id=p1.id, oleh="pytest")
    db.commit()
    d2 = dist.terapkan(db, key, "500000", kas_period_id=p2.id, oleh="pytest")
    db.commit()

    assert d1["created"] is True and d1["distribution"] is not None
    assert d2["created"] is True and d2["distribution"] is not None
    # keduanya baris BERBEDA
    assert d1["distribution"].id != d2["distribution"].id
    assert d1["distribution"].kas_period_id == p1.id
    assert d2["distribution"].kas_period_id == p2.id
    # label tampilan tetap tanggal murni (UI tidak berubah)
    assert d2["periode"] == key
    assert d2["periode_key"] == "%s#%s" % (key, p2.id)


def test_b1_replay_kas_period_yang_sama_tidak_menggandakan(db):
    """B-1b: Kas Period yang sama diproses dua kali -> idempoten, 1 baris, 1 cash-out."""
    import models
    from models import Distribution, KasEntry, KasPeriod
    db.query(Distribution).delete()
    db.query(KasPeriod).delete()
    # Rowid distributions dipakai ulang, jadi ref_id=1 yang dipakai sekarang bisa
    # menabrak entri kas dari test sebelumnya. Guard idempoten
    # `cash.mutasi_tersimpan` akan salah menyimpulkan "sudah pernah" kalau sisa
    # entri itu tidak dibersihkan — jadi bersihkan dulu, seperti periode baru.
    db.query(KasEntry).filter(
        KasEntry.sumber.in_([cash.SUMBER_CASH_OUT, cash.SUMBER_DISTRIBUSI_ASET])
    ).delete(synchronize_session=False)
    db.commit()
    # Buang instance lama dari identity map — SQLite memakai ulang rowid, jadi
    # Distribution baru bisa "mewarisi" nilai kolom dari object yang dihapus.
    db.expunge_all()

    p = KasPeriod(start_at=datetime(2026, 10, 5, 16), end_at=datetime(2026, 10, 6, 16),
                  status="OPEN", created_at=datetime(2026, 10, 5, 8))
    db.add(p); db.commit(); db.refresh(p)
    key = _kunci(p.start_at)
    # `db.query(Distribution).delete()` di atas membuat SQLite memakai ulang rowid,
    # jadi ref_id Distribution yang baru bisa sama dengan distribution test lain.
    # Karena itu hanya entri kas yang dibuat SESUDAH titik ini yang dihitung.
    maks_id_awal = db.query(KasEntry.id).order_by(KasEntry.id.desc()).first()[0] or 0

    a = dist.terapkan(db, key, "1000000", kas_period_id=p.id, oleh="pytest")
    db.commit()
    co1 = closing.catat_cash_out(db, a["distribution"], oleh="pytest")
    db.commit()
    b = dist.terapkan(db, key, "1000000", kas_period_id=p.id, oleh="pytest")
    db.commit()
    co2 = closing.catat_cash_out(db, b["distribution"], oleh="pytest")
    db.commit()

    assert a["created"] is True
    assert b["created"] is False and b["distribution"].id == a["distribution"].id
    assert db.query(Distribution).count() == 1
    # Uang distributions sekarang bergerak SAAT BARISNYA TERBENTUK (keputusan
    # Owner), jadi `closing.catat_cash_out` yang dipanggil setelahnya sudah
    # tidak punya kerjaan — persis yang diuji di sini: replay tidak menggandakan.
    assert co1["created"] is False
    assert co2["created"] is False
    assert co1["nominal"] == co2["nominal"]
    assert closing._entry_id(co2["entry"]) == closing._entry_id(co1["entry"])
    # Cash-out tercatat tepat satu kali untuk periode ini.
    assert db.query(KasEntry).filter(
        KasEntry.id > maks_id_awal,
        KasEntry.layer == cash.LAYER_LACI,
        KasEntry.sumber == cash.SUMBER_CASH_OUT).count() == 1
    # Dan Hak Kas Aset juga tercatat tepat satu kali (Keluar Laci + Masuk Aset).
    assert db.query(KasEntry).filter(
        KasEntry.id > maks_id_awal,
        KasEntry.sumber == cash.SUMBER_DISTRIBUSI_ASET).count() == 2


def test_b1_entry_id_aman_untuk_dict_dan_orm(db):
    """B-1c: inti crash HTTP 500 — `entry` bisa dict atau objek ORM."""
    from models import KasEntry
    row = KasEntry(jenis="Masuk", kategori="Uji", keterangan="Uji B-1",
                   nominal=to_decimal("1000"), layer=cash.LAYER_LACI,
                   saldo_setelah=to_decimal("1000"))
    db.add(row); db.commit(); db.refresh(row)
    assert closing._entry_id({"id": 99}) == 99
    assert closing._entry_id(row) == row.id
    assert closing._entry_id(None) is None


def _isolated_db():
    """Session ke SQLite BARU yang kosong.

    Dipakai karena Tutup Kas sekarang menyelesaikan kewajiban periode: Beban
    periode dibayar dari Laci SEBELUM Declare dibandingkan. Di sandbox bersama
    ada beban recurring dari test lain, jadi `counted` yang dihitung test ini
    akan dibandingkan dengan saldo yang sudah berkurang oleh beban itu -- dan
    test gagal bukan karena salahnya basis rekonsiliasi yang sedang diuji.
    """
    import os
    import tempfile
    from database import Base
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    folder = tempfile.mkdtemp(prefix="p215_iso_")
    eng = create_engine("sqlite:///%s" % os.path.join(folder, "iso.db"))
    Base.metadata.create_all(bind=eng)
    return sessionmaker(bind=eng)()


def test_b2_selisih_snapshot_pakai_basis_ledger(db):
    """B-2: snapshot.selisih == selisih rekonsiliasi ledger, bukan `fin['saldo']`.

    Dijalankan di DB terisolasi: Tutup Kas menyelesaikan kewajiban periode lebih
    dulu (bayar Beban, catat modal terlewat, jalankan distribusi), dan itu akan
    mengubah Saldo Laci sebelum Declare dibandingkan. Yang diuji di sini adalah
    BASIS rekonsiliasi (ledger vs akrual), jadi perlu kondisi tanpa beban lain.
    """
    from models import KasPeriod
    s = _isolated_db()
    cash.catat_injeksi(s, cash.LAYER_LACI, to_decimal("1000000"), "UAT B-2", actor="pytest")
    s.commit()

    p = KasPeriod(start_at=datetime(2026, 10, 5, 16), end_at=datetime(2026, 10, 6, 16),
                  status="OPEN", created_at=datetime(2026, 10, 5, 8))
    s.add(p); s.commit(); s.refresh(p)

    counted = cash.saldo_laci(s) - to_decimal("12345")
    out = closing.tutup_periode(s, p, counted=counted, oleh="pytest", compute_finance=_cf)
    s.commit()

    snap = out["snapshot"]
    # snapshot.selisih == rekonsiliasi.selisih (keduanya basis LEDGER LACI)
    assert str(snap["selisih"]) == out["rekonsiliasi"]["selisih"]
    # Declare fisik = saldo Laci - 12.345  =>  selisih harus -12.345 (kurang)
    assert float(snap["selisih"]) == -12345.0
    # SALDO LACI benar-benar diselaraskan ke Declare fisik
    assert cash.saldo_laci(s) == counted
    # penanda basis supaya tidak ambigu bagi pembaca snapshot/UI
    assert snap["selisih_basis"] == "LEDGER LACI (counted vs Saldo Laci)"
    # Tanpa beban, tidak ada yang dibayar dan Laci tetap 1.000.000 - 12.345.
    assert to_decimal(snap["penyelesaian"]["beban_dibayar_dari_laci"]) == to_decimal("0")
    s.close()


def test_b2_tidak_mengubah_financial_ssot(db):
    """B-2: fix TIDAK boleh mengubah Financial SSOT (v4 #9).

    DB terisolasi karena Tutup Cas kini menyelesaikan kewajiban periode lebih dulu
    (bayar Beban, catat modal terlewat). Kalau ada beban recurring milik test
    lain, Declare yang dihitung SEBELUM tutup akan dibandingkan dengan saldo
    yang sudah berkurang -- dan test ini akan salah menangkap penyesuaian yang
    sebenarnya konsekuensi penyelesaian periode, bukan Declare yang salah.
    """
    from models import KasPeriod
    s = _isolated_db()
    cash.catat_injeksi(s, cash.LAYER_LACI, to_decimal("500000"), "UAT B-2b", actor="pytest")
    s.commit()

    p = KasPeriod(start_at=datetime(2026, 10, 5, 16), end_at=datetime(2026, 10, 6, 16),
                  status="OPEN", created_at=datetime(2026, 10, 5, 8))
    s.add(p); s.commit(); s.refresh(p)

    master_before = cash.master_kas(s)
    opening_before = cash.opening_layer(s, cash.LAYER_LACI)
    out = closing.tutup_periode(s, p, counted=cash.saldo_laci(s), oleh="pytest",
                                compute_finance=_cf)
    s.commit()

    # snapshot.finance tetap memakai Financial SSOT (tidak diubah fix B-2)
    assert "finance" in out["snapshot"]
    assert out["snapshot"]["finance"].get("laba_bersih") is not None
    # Declare pas -> tidak ada penyesuaian
    assert out["rekonsiliasi"]["penyesuaian"] is False
    # opening Laci TIDAK disuntik oleh Declare fisik (v4 #7)
    assert float(out["saldo"]["kas_perputaran_laci_awal"]) == float(opening_before)
    assert cash.opening_layer(s, cash.LAYER_LACI) == opening_before
    assert cash.master_kas(s) >= master_before
    s.close()
