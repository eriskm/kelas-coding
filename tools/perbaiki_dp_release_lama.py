# -*- coding: utf-8 -*-
"""Perbaikan data: Entri kas `DP_RELEASE` sisa implementasi lama.

MASALAH
-------
Pada versi awal, DP tidak langsung masuk Laci saat diterima. Ia ditahan lalu
dilepaskan sebagai entri `DP_RELEASE` saat order di-CASH. Model itu sudah
dibuang: sekarang DP langsung jadi baris Masuk dengan sumber `PAYMENT` begitu
diterima (lihat `cash.catat_penerimaan`).

_baris `DP_RELEASE` yang terlanjur tertulis TIDAK ikut terhapus -- dan lebih
jburuk, `DP_RELEASE` tidak ada di `cash.SUMBER_BARIS_KAS`, jadi baris itu
tidak pernah tampil di Mutasi Kas. Akibatnya Mutasi Kas arsip periode tidak
cocok dengan saldo yang tercatat di snapshot, dan selisihnya tidak bisa
ditelusuri.

Akibatnya pada order #2 (SV-20261011-1873, DP Rp 500.000):
  - payment id=1 (DP)   -> TIDAK punya entri kas sama sekali
  - payment id=2 (pelunasan Rp 1.000.000) -> entri PAYMENT normal
  - jadi DP-nya masuk lewat DP_RELEASE, bukan PAYMENT

APA YANG DIPERBAIKI
-------------------
Baris `DP_RELEASE` diubah IN PLACE menjadi `PAYMENT` yang menunjuk payment DP
aslinya. Sengaja in-place, bukan hapus+tambah, supaya:
  - `id` tetap -> urutan ledger dan `saldo_setelah` baris berikutnya tidak
    bergeser sama sekali;
  - `created_at` tetap -> atribusi periode tidak berubah;
  - saldo Laci secara matematis MUSTAHL sama (jenis, layer, dan nominal tidak
    disentuh). Skrip ini memverifikasi itu sebelum commit.

IDEMPOTEN: kalau tidak ada baris `DP_RELEASE`, skrip keluar dengan "tidak ada
yang perlu diperbaiki" dan tidak menulis apa pun.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))

from money import ZERO, to_decimal  # noqa: E402
from models import JournalEntry, KasEntry, Payment  # noqa: E402
from database import SessionLocal  # noqa: E402

#: Keterangan harus sama polanya dengan `cash.catat_penerimaan` supaya Mutasi
#: Kas menampilkan kalimat yang konsisten dengan baris pembayaran lain.
KETERANGAN_TPL = "Penerimaan pembayaran %s unit #%s (%s)"


def _pilih_payment(db, entri):
    """Payment DP yang jadi asal-usul entri DP_RELEASE ini.

    `DP_RELEASE` lama menunjuk `ref_id = <payment id>` dari baris PELUNASAN yang
    dibuat bersamaan di event CASH. Payment DP-nya dicari dari order yang sama:
    baris DP yang created_at-nya paling dekat dengan entri.
    """
    ref = db.query(Payment).filter(Payment.id == entri.ref_id).first()
    if ref is not None:
        order_id = ref.service_order_id
        buscar_kind = "DP"
    else:
        order_id = entri.ref_id
        buscar_kind = "DP"
    dp = (db.query(Payment)
          .filter(Payment.service_order_id == order_id,
                  Payment.kind == buscar_kind)
          .order_by(Payment.id.desc()).first())
    return ref, dp


def perbaiki(db, log=print):
    masuk = (db.query(KasEntry)
             .filter(KasEntry.sumber == "DP_RELEASE").all())
    if not masuk:
        log("Tidak ada baris DP_RELEASE. Tidak ada yang perlu diperbaiki.")
        return {"diperbaiki": 0}

    n = 0
    for e in masuk:
        ref_pelunasan, dp = _pilih_payment(db, e)
        if dp is None:
            log("  kas#%s: payment DP tidak ditemukan -- dilewati." % e.id)
            continue
        if to_decimal(dp.amount) != to_decimal(e.nominal):
            log("  kas#%s: nominal DP %s != entri %s -- dilewati agar tidak"
                " mengubah saldo." % (e.id, dp.amount, e.nominal))
            continue
        saldo_sebelum = saldo_laci_hitung(db)
        lama = (e.sumber, e.ref_type, e.ref_id, e.kategori)

        e.sumber = "PAYMENT"
        e.kategori = "Penerimaan Pembayaran"
        e.ref_type = "payment"
        e.ref_id = dp.id
        e.keterangan = KETERANGAN_TPL % (dp.kind, dp.service_order_id, "CASH")
        db.flush()

        # Journal-nya juga harus ikut, kalau tidak detailnya menunjuk entri yang
        # sudah tidak ada lagi sumbernya.
        for j in (db.query(JournalEntry)
                  .filter(JournalEntry.entity_type == "kas_entry",
                          JournalEntry.entity_id == e.id).all()):
            j.ref_type = "payment"
            j.ref_code = str(dp.id)
            j.source = "PAYMENT"
            if j.details is not None:
                try:
                    d = dict(j.details)
                except (TypeError, ValueError):
                    d = {}
                d["sumber_awal"] = "DP_RELEASE"
                d["event"] = "PENERIMAAN"
                j.details = d
        db.flush()

        saldo_sesudah = saldo_laci_hitung(db)
        if saldo_sebelum != saldo_sesudah:
            db.rollback()
            log("  kas#%s: saldo berubah %s -> %s. Dibatalkan."
                % (e.id, saldo_sebelum, saldo_sesudah))
            raise SystemExit(1)
        log("  kas#%s: %s -> PAYMENT (payment id=%s, %s). Saldo tetap %s."
            % (e.id, "/".join(str(x) for x in lama), dp.id, dp.amount, saldo_sesudah))
        n += 1
    return {"diperbaiki": n}


def saldo_laci_hitung(db):
    """Saldo Laci yang dihitung ulang dari ledger (bukan kolom saldo_setelah)."""
    total = ZERO
    for r in db.query(KasEntry).filter(KasEntry.layer == "LACI").all():
        n = to_decimal(r.nominal)
        total += n if (r.jenis or "").lower() == "masuk" else -n
    return total


def main():
    db = SessionLocal()
    try:
        sebelum = saldo_laci_hitung(db)
        print("Saldo Laci sebelum : %s" % sebelum)
        res = perbaiki(db)
        db.commit()
        sesudah = saldo_laci_hitung(db)
        print("Saldo Laci sesudah : %s" % sesudah)
        print("Baris diperbaiki   : %d" % res["diperbaiki"])
        if sebelum != sesudah:
            print("GAGAL: saldo berubah!")
            raise SystemExit(1)
        print("OK: saldo tidak berubah.")
    finally:
        db.close()


if __name__ == "__main__":
    main()