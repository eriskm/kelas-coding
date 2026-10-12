# -*- coding: utf-8 -*-
"""Badge jumlah antrean notifikasi (icon lonceng di halaman Keuangan).

`GET /api/notifications` sebelumnya hanya mengirim daftar yang SUDAH dipotong
`limit`. Kalau badge diambil dari daftar itu, angkanya salah begitu log lewat 25
baris -- icon akan menampilkan jumlah yang lebih kecil dari kenyataan, dan
user akan mengira tidak ada notifikasi baru padahal ada.

Jadi `n_diantrekan` dihitung terpisah di SELURUH tabel.
"""
from datetime import datetime

import notifications as notif_mod


def test_daftar_dibatasi_tetapi_badge_menghitung_seluruh_antrean(client, db, auth):
    from models import Notification
    db.query(Notification).delete(synchronize_session=False)
    db.commit()
    for i in range(1, 31):                       # 30 baris, lebih dari limit
        db.add(Notification(event=notif_mod.EVENT_UNIT_BARU,
                            ref_type="service_order", ref_code=str(i),
                            dedup_key="k%d" % i, provider="TELEGRAM",
                            tujuan="", pesan="p%d" % i,
                            status=notif_mod.STATUS_DIANTREKAN,
                            created_at=datetime(2026, 6, 1, 10, i % 60)))
    db.commit()

    r = client.get("/api/notifications?limit=10", headers=auth)
    assert r.status_code == 200, r.text
    body = r.json()

    # Daftar tetap dipotong 10 (itu yang ditampilkan di popover)...
    assert len(body["items"]) == 10
    # ...tapi badge menghitung SELURUH antrean, bukan 10.
    assert body["n_diantrekan"] == 30


def test_badge_hanya_menghitung_yang_belum_terkirim(client, db, auth):
    from models import Notification
    db.query(Notification).delete(synchronize_session=False)
    db.commit()
    campur = [notif_mod.STATUS_DIANTREKAN, notif_mod.STATUS_DIANTREKAN,
              notif_mod.STATUS_TERKIRIM, notif_mod.STATUS_GAGAL]
    for i, st in enumerate(campur, start=1):
        db.add(Notification(event=notif_mod.EVENT_KAS_MASUK,
                            ref_type="service_order", ref_code=str(i),
                            dedup_key="m%d" % i, provider="TELEGRAM",
                            tujuan="", pesan="p", status=st,
                            created_at=datetime(2026, 6, 2, 10, i)))
    db.commit()

    body = client.get("/api/notifications?limit=10", headers=auth).json()
    assert body["n_diantrekan"] == 2, "Hanya DIANTREKAN yang dihitung"


def test_badge_nol_bila_tidak_ada_antrean(client, db, auth):
    from models import Notification
    db.query(Notification).delete(synchronize_session=False)
    db.commit()
    db.add(Notification(event=notif_mod.EVENT_WA_SELESAI, ref_type="service_order",
                        ref_code="1", dedup_key="w1", provider="TELEGRAM",
                        tujuan="", pesan="p", status=notif_mod.STATUS_TERKIRIM,
                        created_at=datetime(2026, 6, 3, 10)))
    db.commit()
    body = client.get("/api/notifications?limit=10", headers=auth).json()
    assert body["n_diantrekan"] == 0
    # UI menyembunyikan badge saat 0 (sudah ditangani di frontend: class `hidden`).