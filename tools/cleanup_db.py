# -*- coding: utf-8 -*-
"""Bersihkan DB untuk test dari nol:
- Hapus semua periode CLOSED (arsip Tutup Kas)
- Hapus semua WarrantyClaim
- Hapus Customer yang tidak dipakai order di halaman Transaksi (status bukan CASH/CANCEL)
- Hapus Payment, KasEntry, Distribution, ExpensePeriod, ExpenseDebt, Refund, StatusHistory yg terkait
- Sisakan: 1 periode OPEN, ServiceOrder status DITERIMA/ANALISA/KONFIRMASI/WAIT PART/REPAIR/DONE, Customer & Payment yg terkait
"""
import os
import sys
import shutil
from datetime import datetime
from decimal import Decimal

APP = r"D:\PRAKTEK MJPRO"
sys.path.insert(0, os.path.join(APP, "backend"))
os.environ["DATABASE_URL"] = "sqlite:///%s" % os.path.join(APP, "servisku.db")

from database import SessionLocal  # noqa: E402
import models  # noqa: E402

# Backup dulu
BAK = os.path.join(APP, "servisku.db.bak_before_clean_%s" % datetime.now().strftime("%Y%m%d_%H%M%S"))
shutil.copy2(os.path.join(APP, "servisku.db"), BAK)
print("Backup:", BAK)

s = SessionLocal()
try:
    # 1. Hapus periode CLOSED (arsip Tutup Kas) - sisakan OPEN terakhir
    open_periods = s.query(models.KasPeriod).filter(models.KasPeriod.status == "OPEN").all()
    if len(open_periods) > 1:
        # Kalau >1 OPEN, tutup yang lama, sisakan yang paling baru
        for p in open_periods[:-1]:
            p.status = "CLOSED"
            p.closed_at = datetime.now()
            p.closed_by = "cleanup"
    closed = s.query(models.KasPeriod).filter(models.KasPeriod.status == "CLOSED").all()
    for p in closed:
        # Hapus snapshot & data terkait
        s.query(models.Distribution).filter(models.Distribution.kas_period_id == p.id).delete(synchronize_session=False)
        s.query(models.ExpensePeriod).filter(models.ExpensePeriod.periode.like("kas_period:%d" % p.id)).delete(synchronize_session=False)
        s.query(models.ExpensePeriod).filter(models.ExpensePeriod.periode == p.start_at.strftime("%Y-%m-%d")).delete(synchronize_session=False)
        s.query(models.KasEntry).filter(models.KasEntry.ref_type == "periode", models.KasEntry.ref_id == p.id).delete(synchronize_session=False)
        s.delete(p)
        print("  Hapus periode CLOSED #%d" % p.id)

    # 2. Hapus semua WarrantyClaim
    s.query(models.WarrantyClaim).delete(synchronize_session=False)
    print("  Hapus semua WarrantyClaim")

    # 3. Hapus Refund
    s.query(models.Refund).delete(synchronize_session=False)
    print("  Hapus semua Refund")

    # 4. Hapus ExpenseDebt (hutang beban)
    s.query(models.ExpenseDebtEntry).delete(synchronize_session=False)
    s.query(models.ExpenseDebtPeriod).delete(synchronize_session=False)
    print("  Hapus ExpenseDebt")

    # 5. Identifikasi ServiceOrder yang DI SIMPAN (status berjalan di halaman Transaksi)
    keep_status = ("DITERIMA", "ANALISA", "KONFIRMASI", "WAIT PART", "REPAIR", "DONE")
    keep_orders = s.query(models.ServiceOrder.id).filter(
        models.ServiceOrder.status.in_(keep_status)
    ).all()
    keep_ids = {r[0] for r in keep_orders}
    print("  ServiceOrder disimpan (%s): %s" % (len(keep_ids), sorted(keep_ids)))

    # 6. Hapus ServiceOrder yang TIDAK di keep (CASH, CANCEL, FAILED)
    s.query(models.Payment).filter(
        ~models.Payment.service_order_id.in_(keep_ids)
    ).delete(synchronize_session=False)
    s.query(models.StatusHistory).filter(
        ~models.StatusHistory.service_order_id.in_(keep_ids)
    ).delete(synchronize_session=False)
    s.query(models.ServiceOrderPart).filter(
        ~models.ServiceOrderPart.service_order_id.in_(keep_ids)
    ).delete(synchronize_session=False)
    deleted_orders = s.query(models.ServiceOrder).filter(
        ~models.ServiceOrder.id.in_(keep_ids)
    ).delete(synchronize_session=False)
    print("  Hapus ServiceOrder arsip: %d" % deleted_orders)

    # 7. Hapus Customer yang tidak punya order tersisa
    used_cust = s.query(models.ServiceOrder.customer_id).filter(
        models.ServiceOrder.id.in_(keep_ids)
    ).distinct().all()
    used_cust_ids = {r[0] for r in used_cust}
    all_cust = s.query(models.Customer.id).all()
    for (cid,) in all_cust:
        if cid not in used_cust_ids:
            s.delete(s.query(models.Customer).get(cid))
    print("  Hapus Customer tidak terpakai, sisa: %d" % len(used_cust_ids))

    # 8. Hapus KasEntry yang bukan SALDO AWAL dan bukan terkait order tersisa
    # (Payment & Beban akan dihapus via ref_id filter di atas, tapi manual entries bisa ada)
    s.query(models.KasEntry).filter(
        models.KasEntry.kategori != "Saldo Awal",
        models.KasEntry.sumber.in_(["MODAL", "BEBAN", "CASH_OUT", "DISTRIBUSI_ASET", "TRANSFER", "INJEKSI", "REKONSILIASI", "PENYESUAIAN", "HUTANG_BEBAN", "REFUND_DP", "FAILED_CANCEL", "REFUND_GARANSI"]),
    ).delete(synchronize_session=False)
    print("  Hapus KasEntry sistem (bukan manual)")

    # 9. Hapus Distribution lama
    s.query(models.Distribution).delete(synchronize_session=False)
    print("  Hapus Distribution")

    # 10. Hapus ExpensePeriod lama
    s.query(models.ExpensePeriod).delete(synchronize_session=False)
    print("  Hapus ExpensePeriod")

    # 11. Hapus IdempotencyKey lama
    s.query(models.IdempotencyRecord).delete(synchronize_session=False)
    print("  Hapus IdempotencyRecord")

    # 12. Hapus JournalEntry lama (keep recent maybe, tapi hapus semua)
    s.query(models.JournalEntry).delete(synchronize_session=False)
    print("  Hapus JournalEntry")

    # 13. Hapus Notification lama
    s.query(models.Notification).delete(synchronize_session=False)
    print("  Hapus Notification")

    # 13. Hapus StockMove lama
    s.query(models.StockMove).delete(synchronize_session=False)
    print("  Hapus StockMove")

    s.commit()
    print("\n=== CLEANUP SELESAI ===")
    print("Sisa data:")
    print("  KasPeriod OPEN: %d" % s.query(models.KasPeriod).filter(models.KasPeriod.status == "OPEN").count())
    print("  ServiceOrder: %d" % s.query(models.ServiceOrder).count())
    print("  Customer: %d" % s.query(models.Customer).count())
    print("  Payment: %d" % s.query(models.Payment).count())
    print("  KasEntry: %d" % s.query(models.KasEntry).count())
    print("  Expense: %d" % s.query(models.Expense).count())
    print("  ExpensePeriod: %d" % s.query(models.ExpensePeriod).count())

finally:
    s.close()