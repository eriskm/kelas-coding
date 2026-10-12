# -*- coding: utf-8 -*-
"""Top-up Distribusi Laba (keputusan Owner).

Sebelum ada fitur ini, `pastikan_otomatis` berhenti begitu Distribution di
periode itu terbentuk. Akibatnya CTO yang sudah tercapai lalu ditransaksi
lagi TIDAK menambah alokasi -- laba baru diam-diam ngumpet di Laci.

Sekarang laba yang naik dialokasikan ulang sebesar SELISIHNYA dengan rasio
yang sama (10/30/30/30). Yang diuji di sini:

  1. top-up menambah alokasi, bukan membuat Distribution kedua;
  2. idempoten: tanpa laba baru tidak terjadi apa-apa;
  3. laba turun TIDAK mengurangi alokasi yang sudah terjadi;
  4. Laci tidak cukup -> ditunda, TIDAK keluar sebagian;
  5. CTO tidak tercapai -> tidak ada top-up.
"""
from datetime import datetime

from money import to_decimal

import cash
import distribution as dist


def _set_laci(db, target):
    """Setel Saldo Laci ke angka PASTI.

    Sandbox dipakai bersama test lain yang semuanya mengisi Laci, jadi saldo
    absolut tidak pernah bisa diasumsikan. Selisihnya ditutup dengan satu entri
    'Pengaturan Uji' (bukan CASH_OUT) supaya tidak ikut terhitung sebagai
    cash-out distribusi.
    """
    target = to_decimal(target)
    cur = cash.saldo_laci(db)
    if target > cur:
        cash.catat_injeksi(db, cash.LAYER_LACI, target - cur, "Pengaturan Uji", actor="pytest")
    elif target < cur:
        cash.catat_mutasi(db, cash.LAYER_LACI, "Keluar", "Pengaturan Uji",
                          "Pengaturan Uji", cur - target,
                          sumber=cash.SUMBER_PENYESUAIAN,
                          check_saldo=False, oleh="pytest")
    db.commit()
    assert cash.saldo_laci(db) == target


def _siapkan(db, IMAL="10000000"):
    """Kas Period BARU + Saldo Laci disetel ke angka pasti.

    Dua hal yang SENGAJA dilakukan supaya test ini tidak mengganggu test lain:

    1. Periode dibuat berstatus `CLOSED` dan bertanggal lampau (Juli 2026).
       `get_active_period()` mengambil periode OPEN dengan id tertinggi -- kalau
       periode test ini OPEN, ia akan jadi "periode aktif" dan memicu top-up
       saat order test lain di-CASH, sehingga saldo Laci mereka bergeser.
    2. Tidak menghapus Distribution/KasEntry milik test lain. Sandbox dipakai
       bersama dan test lain mengukur delta saldo, jadi menghapus entri kas di
       sini membuat mereka asserting angka yang salah. Baris Distribution yang
       tertinggal tidak mengganggu karena `sudah_ada` dicocokkan lewat
       `kas_period_id` milik periode baru ini.
    """
    from models import Distribution, KasPeriod
    p = KasPeriod(start_at=datetime(2026, 7, 5, 16), end_at=datetime(2026, 7, 6, 16),
                  status="CLOSED", created_at=datetime(2026, 7, 5, 8))
    db.add(p); db.commit(); db.refresh(p)
    # SQLite MEMAKAI ULANG rowid setelah `DELETE FROM kas_periods`, jadi id periode
    # baru ini bisa sama dengan id periode lama yang Distribution-nya masih tertinggal.
    # Kalau dibiarkan, `sudah_ada()` akan menemukan distribution milik periode LAIN
    # dan top-up tidak pernah terjadi. Bersihkan baris dengan id yang sama.
    db.query(Distribution).filter(
        Distribution.kas_period_id == p.id).delete(synchronize_session=False)
    db.commit()
    pid = p.id
    db.expunge_all()   # melepas instance; diambil ulang supaya tidak detached
    p = db.query(KasPeriod).filter(KasPeriod.id == pid).one()
    _set_laci(db, IMAL)
    return p, p.start_at.date().isoformat()


def _jumlah_baris(db, pid):
    from models import Distribution
    return db.query(Distribution).filter(
        Distribution.kas_period_id == pid).count()


def _id_entri(db):
    from models import KasEntry
    return db.query(KasEntry.id).order_by(KasEntry.id.desc()).first()[0] or 0


def _panggil(db, key, pid, laba, cto=True):
    return dist.pastikan_otomatis(db, key, laba, cto_tercapai=cto,
                                  kas_period_id=pid, oleh="pytest")


def test_1_topup_menambah_alokasi_bukan_baris_baru(db):
    """CTO sudah tercapai, lalu ada transaksi baru -> selisihnya ikut dibagi."""
    from models import Distribution, KasEntry
    p, key = _siapkan(db)

    id_entri_awal = _id_entri(db)

    a = _panggil(db, key, p.id, "45000", cto=True)
    db.commit()
    assert a["dibentuk"] is True and a.get("topup") is not True
    assert a["distribution"].laba_bersih == to_decimal("45000")
    assert a["distribution"].bonus_karyawan == to_decimal("4500")
    assert a["distribution"].cash_out == to_decimal("31500")
    assert a["distribution"].hak_kas_aset == to_decimal("13500")

    # Transaksi baru: laba bersih naik ke 170.000 (selisih 125.000)
    id_entri_awal = _id_entri(db)
    b = _panggil(db, key, p.id, "170000", cto=True)
    db.commit()
    assert b["dibentuk"] is True and b.get("topup") is True

    # TETAP SATU baris Distribution -- akumulatornya yang dinaikkan.
    assert _jumlah_baris(db, p.id) == 1
    row = b["distribution"]
    assert row.laba_bersih == to_decimal("170000")
    # 10/30/30/30 dari total 170.000
    assert row.bonus_karyawan == to_decimal("17000")
    assert row.pengelola == to_decimal("51000")
    assert row.investor == to_decimal("51000")
    assert row.hak_kas_aset == to_decimal("51000")
    assert row.cash_out == to_decimal("119000")

    # Uang benar-benar bergerak untuk porsi TAMBAHAN saja:
    #   70% x 125.000 = 87.500 keluar Laci, 30% x 125.000 = 37.500 -> Aset
    assert b["cash_out"] == to_decimal("119000")   # akumulator
    assert b["alokasi_topup"]["cash_out"] == to_decimal("87500")
    assert b["alokasi_topup"]["kas_aset"] == to_decimal("37500")
    assert b["trigger"] == "CTO tercapai (top-up laba baru)"

    # Saldo Aset WAJIB naik sebesar porsi top-up. Ini yang paling mudah
    # terlewat: `cash.transfer` punya guard idempoten pada
    # (layer, sumber, ref_type, ref_id), dan transfer kedua untuk Distribution
    # yang sama punya ref_id yang sama -- sehingga tanpa `idempoten=False`
    # porsinya tidak pernah benar-benar berpindah ke Saldo Aset.
    dari_aset = cash.saldo_kas_aset(db) - to_decimal("37500")
    assert dari_aset >= 0
    n_transfer_baru = db.query(KasEntry).filter(
        KasEntry.id > id_entri_awal,
        KasEntry.sumber == cash.SUMBER_DISTRIBUSI_ASET).count()
    assert n_transfer_baru == 2, "Top-up harus menambah satu pasangan transfer baru"


def test_2_tanpa_laba_baru_tidak_terjadi_apa_apa(db):
    """Menjalankan gatekeeper berulang dengan laba sama -> 0 efek samping."""
    from models import KasEntry
    p, key = _siapkan(db)
    _panggil(db, key, p.id, "45000", cto=True)
    db.commit()
    id_awal = db.query(KasEntry.id).order_by(KasEntry.id.desc()).first()[0] or 0
    snap = cash.master_kas(db)

    for _ in range(3):
        r = _panggil(db, key, p.id, "45000", cto=True)
        db.commit()
        assert r["dibentuk"] is False
        assert r.get("topup") is not True
        assert r["alasan"] == "Sudah pernah terbentuk di periode ini"

    assert cash.master_kas(db) == snap
    assert db.query(KasEntry).filter(KasEntry.id > id_awal).count() == 0


def test_3_laba_turun_tidak_mengurangi_alokasi(db):
    """Koreksi modal/beban membuat laba turun -> Distribution lama utuh."""
    from models import Distribution, KasEntry
    p, key = _siapkan(db)
    _panggil(db, key, p.id, "45000", cto=True)
    db.commit()
    uang_diterima = cash.saldo_laci(db)

    r = _panggil(db, key, p.id, "10000", cto=True)
    db.commit()

    assert r["dibentuk"] is False and r.get("topup") is not True
    assert _jumlah_baris(db, p.id) == 1
    assert r["distribution"].laba_bersih == to_decimal("45000")
    # Tidak ada uang yang FLOW BALIK.
    assert cash.saldo_laci(db) == uang_diterima


def test_4_laci_kurang_ditunda_bukan_keluar_sebagian(db):
    """All-or-nothing: Laci kurang untuk SELURUH porsi -> tidak ada yang bergerak."""
    from models import Distribution, KasEntry
    # Modal awal pas untuk distribusi pertama saja.
    p, key = _siapkan(db, IMAL="45000")
    _panggil(db, key, p.id, "45000", cto=True)
    db.commit()
    row = dist.sudah_ada(db, key, p.id)
    assert cash.saldo_laci(db) == to_decimal("0")
    id_awal = db.query(KasEntry.id).order_by(KasEntry.id.desc()).first()[0] or 0

    # Laba naik lagi tapi Laci sudah kosong -> harus ditunda.
    r = _panggil(db, key, p.id, "170000", cto=True)
    db.commit()

    assert r["dibentuk"] is False and r.get("topup") is not True
    assert dist.ALASAN_KAS_KURANG in r["alasan"]
    # Tidak ada Distribution kedua, tidak ada entri parsial, tidak ada Laci minus.
    assert _jumlah_baris(db, p.id) == 1
    assert db.query(KasEntry).filter(KasEntry.id > id_awal).count() == 0
    assert cash.saldo_laci(db) == to_decimal("0")
    assert row.laba_bersih == to_decimal("45000")

    # Begitu uangnya cukup, top-up langsung tertangkap.
    _set_laci(db, "200000")
    db.commit()
    r2 = _panggil(db, key, p.id, "170000", cto=True)
    db.commit()
    assert r2["dibentuk"] is True and r2.get("topup") is True
    assert r2["distribution"].laba_bersih == to_decimal("170000")


def test_5_cto_tidak_tercapai_tidak_ada_topup(db):
    """CTO hilang lagi (beban baru) -> tidak ada distribusi, baik awal maupun top-up."""
    from models import Distribution, KasEntry
    p, key = _siapkan(db)

    belum = _panggil(db, key, p.id, "45000", cto=False)
    db.commit()
    assert belum["dibentuk"] is False
    assert belum["alasan"] == dist.ALASAN_BELUM_SIAP
    assert _jumlah_baris(db, p.id) == 0

    # CTO tercapai -> baris pertama terbentuk.
    _panggil(db, key, p.id, "45000", cto=True)
    db.commit()
    # Beban baru >>= laba, CTO jatuh lagi, laba naik -> TIDAK boleh top-up.
    r = _panggil(db, key, p.id, "170000", cto=False)
    db.commit()
    assert r["dibentuk"] is False and r.get("topup") is not True
    assert _jumlah_baris(db, p.id) == 1
    assert r["distribution"].laba_bersih == to_decimal("45000")