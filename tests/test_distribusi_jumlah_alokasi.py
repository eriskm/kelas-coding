# -*- coding: utf-8 -*-
"""Jumlah alokasi distribution per periode (untuk catatan di panel Alokasi Profit).

Distribution bisa bertambah lebih dari sekali dalam satu periode kas karena
TOP-UP: begitu laba bersih naik lagi, selisihnya ikut dialokasikan. Kalau user
melihat angka alokasi melompat tanpa penjelasan, itu membingungkan -- jadi UI
menampilkan berapa kali sudah dialokasikan.

Angkanya dihitung dari entri kas cash-out milik Distribution itu, bukan kolom
khusus, sehingga:
  - tidak butuh migrasi schema,
  - tetap benar untuk baris distribution yang dibuat SEBELUM fitur top-up ada.
"""
import pytest

import cash
import distribution as dist
from money import to_decimal


def test_jumlah_alokasi_satu_saat_baru_terbentuk(db):
    from datetime import datetime
    from models import Distribution, KasEntry, KasPeriod
    # SQLite memakai ULANG rowid setelah DELETE, jadi Distribution baru bisa mewarisi
    # id lama -- dan entri kas distribution milik baris lama itu ikut terhitung.
    # Bersihkan keduanya lebih dulu.
    db.query(Distribution).delete(synchronize_session=False)
    db.query(KasPeriod).delete(synchronize_session=False)
    db.query(KasEntry).filter(KasEntry.sumber.in_(
        [cash.SUMBER_CASH_OUT, cash.SUMBER_DISTRIBUSI_ASET])).delete(
        synchronize_session=False)
    db.commit()
    db.expunge_all()

    p = KasPeriod(start_at=datetime(2026, 4, 1, 16), end_at=datetime(2026, 4, 2, 16),
                  status="CLOSED", created_at=datetime(2026, 4, 1, 8))
    db.add(p); db.commit(); db.refresh(p)
    pid = p.id
    cash.catat_injeksi(db, cash.LAYER_LACI, to_decimal("10000000"), "Uji hitung", actor="pytest")
    db.commit()

    key = p.start_at.date().isoformat()
    dist.pastikan_otomatis(db, key, "45000", cto_tercapai=True,
                          kas_period_id=pid, oleh="pytest")
    db.commit()
    row = dist.sudah_ada(db, key, kas_period_id=pid)
    assert dist.jumlah_alokasi(db, row) == 1, "Baru pertama kali -> 1"


def test_jumlah_alokasi_naik_setiap_topup(db):
    from datetime import datetime
    from models import Distribution, KasEntry, KasPeriod
    # SQLite memakai ULANG rowid setelah DELETE, jadi Distribution baru bisa mewarisi
    # id lama -- dan entri kas distribution milik baris lama itu ikut terhitung.
    # Bersihkan keduanya lebih dulu.
    db.query(Distribution).delete(synchronize_session=False)
    db.query(KasPeriod).delete(synchronize_session=False)
    db.query(KasEntry).filter(KasEntry.sumber.in_(
        [cash.SUMBER_CASH_OUT, cash.SUMBER_DISTRIBUSI_ASET])).delete(
        synchronize_session=False)
    db.commit()
    db.expunge_all()

    p = KasPeriod(start_at=datetime(2026, 4, 3, 16), end_at=datetime(2026, 4, 4, 16),
                  status="CLOSED", created_at=datetime(2026, 4, 3, 8))
    db.add(p); db.commit(); db.refresh(p)
    pid = p.id
    cash.catat_injeksi(db, cash.LAYER_LACI, to_decimal("10000000"), "Uji hitung", actor="pytest")
    db.commit()

    key = p.start_at.date().isoformat()
    for laba in ("45000", "170000", "200000"):
        dist.pastikan_otomatis(db, key, laba, cto_tercapai=True, kas_period_id=pid, oleh="pytest")
        db.commit()
    row = dist.sudah_ada(db, key, kas_period_id=pid)
    assert row.laba_bersih == to_decimal("200000")
    # Tiga kali pemicu (awal + 2 top-up) -> tiga entri cash-out.
    assert dist.jumlah_alokasi(db, row) == 3


def test_jumlah_alokasi_nol_bila_belum_ada_distribution(db):
    assert dist.jumlah_alokasi(db, None) == 0


def test_endpoint_overview_menyertakan_jumlah_alokasi(client, db, auth):
    r = client.get("/api/overview", headers=auth)
    assert r.status_code == 200, r.text
    fin = r.json()["finance"]
    # Kunci harus ada supaya UI tidak menampilkan "NaN kali".
    assert "distribusi_jumlah_alokasi" in fin
    assert int(fin["distribusi_jumlah_alokasi"]) >= 0