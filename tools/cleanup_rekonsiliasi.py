# -*- coding: utf-8 -*-
"""Hapus data rekonsiliasi Tutup Kas (snapshot KasPeriod)."""
import os
import sys

APP = r"D:\PRAKTEK MJPRO"
sys.path.insert(0, os.path.join(APP, "backend"))
os.environ["DATABASE_URL"] = "sqlite:///%s" % os.path.join(APP, "servisku.db")

from database import SessionLocal  # noqa: E402
import models  # noqa: E402
import json

s = SessionLocal()
try:
    # Hapus snapshot rekonsiliasi dari KasPeriod OPEN
    periods = s.query(models.KasPeriod).all()
    for p in periods:
        if p.snapshot:
            snap = json.loads(p.snapshot)
            # Reset rekonsiliasi fields
            if "rekonsiliasi" in snap:
                snap["rekonsiliasi"] = {
                    "selisih": None,
                    "penyesuaian": False,
                    "entry_id": None,
                    "catatan": "cash_counted = hasil hitung fisik; tidak menyuntik opening."
                }
            if "penyelesaian" in snap:
                snap["penyelesaian"]["laci_setelah_penyelesaian"] = "0.00"
            p.snapshot = json.dumps(snap)
            print("Reset snapshot periode #%d" % p.id)
    s.commit()
    print("Rekonsiliasi data dihapus dari snapshot.")
finally:
    s.close()