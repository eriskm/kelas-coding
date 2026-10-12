# -*- coding: utf-8 -*-
"""Laporan Tutup Kas yang terkirim lewat notifikasi harus angkanya BENAR.

Bug yang ditemukan: `closing.tutup_periode` menulis data notifikasi dengan kunci
`"omzet"`, sedangkan `notifications.format_pesan` membacanya dengan kunci
`"omset"`. Akibatnya baris "Omzet:" di laporan Tutup Kas selalu keluar Rp 0
padahal snapshot periode menyimpan angka yang benar (Rp 2.800.000 pada UAT).

Test ini mengunci: setiap angka yang ditulis `closing` harus benar-benar muncul
di pesan notifikasi -- jadi salah nama kunci tidak bisa lolos diam-diam lagi.
"""
from datetime import datetime
from decimal import Decimal

import pytest

import notifications as notif_mod
from money import to_decimal
from routers.dashboard import compute_finance as CF


def _notif_terakhir(db, event):
    from models import Notification
    return (db.query(Notification).filter(Notification.event == event)
            .order_by(Notification.id.desc()).first())


def test_tutup_kas_mengirim_notifikasi_dengan_angka_benar(client, db):
    import models
    db.query(models.KasPeriod).delete(synchronize_session=False)
    db.query(models.Notification).delete(synchronize_session=False)
    db.commit()

    import closing
    p = models.KasPeriod(start_at=datetime(2026, 5, 1, 16), end_at=datetime(2026, 5, 2, 16),
                         status="OPEN", created_at=datetime(2026, 5, 1, 8))
    db.add(p); db.commit(); db.refresh(p)
    # Periode masih OPEN -> batas atasnya datetime.max (lihat batas_periode).
    fin = CF(db, p.start_at, datetime.max, lihat_kas_besar=True)

    out = closing.tutup_periode(db, p, counted=to_decimal("0"), oleh="pytest",
                                compute_finance=CF)
    db.commit()

    row = _notif_terakhir(db, notif_mod.EVENT_LAPORAN_TUTUP_KAS)
    assert row is not None, "Tutup Kas harus mengirim laporan Tutup Kas"
    pesan = row.pesan or ""

    # Angka yang harus benar-benar muncul di pesan -- inilah yang dulu gagal.
    assert ("Omzet: Rp %s" % _rp(fin["omset"])) in pesan, \
        "Omzet di laporan Tutup Kas harus sama dengan omset periode, bukan 0"
    assert ("Beban: Rp %s" % _rp(fin["total_beban"])) in pesan
    assert ("Laba Bersih: Rp %s" % _rp(fin["laba_bersih"])) in pesan
    assert out["snapshot"]["finance"]["omset"] == fin["omset"]

    row2 = _notif_terakhir(db, notif_mod.EVENT_LAPORAN_BUKA_KAS)
    assert row2 is not None, "Tutup Kas harus mengirim laporan Buka Kas"


def _rp(v):
    """Format sama dengan `notifications._rupiah`."""
    n = int(to_decimal(v))
    return "{:,}".format(n).replace(",", ".")


def test_notifikasi_anti_duplikat_dalam_jendela(db):
    """Kirim event yang sama dua kali dalam jendela -> hanya tercatat satu baris."""
    from models import Notification
    db.query(Notification).delete(synchronize_session=False)
    db.commit()
    now = datetime(2026, 6, 1, 10, 0)
    a = notif_mod.kirim(db, notif_mod.EVENT_UNIT_BARU, ref_type="service_order",
                        ref_code=999, data={"no": "X"}, now=now)
    db.commit()
    b = notif_mod.kirim(db, notif_mod.EVENT_UNIT_BARU, ref_type="service_order",
                        ref_code=999, data={"no": "X"},
                        now=datetime(2026, 6, 1, 10, 5))
    db.commit()
    assert a["status"] == notif_mod.STATUS_DIANTREKAN
    assert b["status"] == notif_mod.STATUS_SKIPPED_DUPLIKAT
    assert db.query(Notification).filter(
        Notification.event == notif_mod.EVENT_UNIT_BARU,
        Notification.ref_code == "999").count() == 1