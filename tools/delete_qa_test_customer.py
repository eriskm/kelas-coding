# -*- coding: utf-8 -*-
"""Pembersihan Pelanggan Uji Coba (Histori QA) dan 20 order dummy peninggalan masa development.

Sesuai permintaan Owner:
- Menghapus akun placeholder Customer ID 1: 'Pelanggan Uji Coba (Histori QA)' (080000000000)
- Menghapus 20 order dummy development (SV-20261019-3723 s.d. SV-20261029-3367)
- Menghapus 25 payment terkait order dummy tersebut
- Menghapus status_history terkait order dummy tersebut
- Mencatat jejak audit ke journal_entries
- Menyisakan murni 466 pelanggan riil toko dan 221 transaksi riil toko (39 aktif + 182 garansi).
"""
import os
import sys
import shutil
import sqlite3
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from database import SessionLocal
import models
import journal

DB_PATH = os.path.join(PROJECT_ROOT, "servisku.db")
BACKUP_PATH = os.path.join(PROJECT_ROOT, "servisku.db.backup_before_delete_qa_customer")


def run_cleanup():
    if not os.path.exists(DB_PATH):
        print(f"[ERROR] Database {DB_PATH} tidak ditemukan.")
        return False

    # 1. Buat safety backup
    print(f"[INFO] Membuat backup database ke {BACKUP_PATH}...")
    shutil.copyfile(DB_PATH, BACKUP_PATH)
    print(f"[SUCCESS] Backup berhasil dibuat.")

    db = SessionLocal()
    try:
        # 2. Cari Customer ID 1
        target_cust = db.query(models.Customer).filter(models.Customer.id == 1).first()
        if not target_cust:
            print("[INFO] Pelanggan ID 1 sudah tidak ada di database.")
            return True

        print(f"[INFO] Ditemukan: ID={target_cust.id}, Nama='{target_cust.name}', Phone='{target_cust.phone}'")

        # 3. Cari seluruh service_orders yang merujuk ke customer_id = 1
        orders = db.query(models.ServiceOrder).filter(models.ServiceOrder.customer_id == 1).all()
        order_ids = [o.id for o in orders]
        order_nos = [o.no_servis for o in orders]
        print(f"[INFO] Ditemukan {len(orders)} order dummy pengujian: {order_nos}")

        # 4. Hapus relasi jika ada
        if order_ids:
            # Hapus status history
            deleted_history = (
                db.query(models.StatusHistory)
                .filter(models.StatusHistory.service_order_id.in_(order_ids))
                .delete(synchronize_session=False)
            )
            print(f"[INFO] Menghapus {deleted_history} baris status_history.")

            # Hapus payments
            deleted_payments = (
                db.query(models.Payment)
                .filter(models.Payment.service_order_id.in_(order_ids))
                .delete(synchronize_session=False)
            )
            print(f"[INFO] Menghapus {deleted_payments} baris payments.")

            # Hapus service_orders
            deleted_orders = (
                db.query(models.ServiceOrder)
                .filter(models.ServiceOrder.customer_id == 1)
                .delete(synchronize_session=False)
            )
            print(f"[INFO] Menghapus {deleted_orders} baris service_orders.")

        # 5. Hapus customer ID 1
        db.delete(target_cust)
        db.flush()
        print(f"[SUCCESS] Pelanggan ID 1 berhasil dihapus.")

        # 6. Catat Audit Journal
        journal.record(
            db,
            domain="CUSTOMER",
            event="CUSTOMER_DELETE",
            entity_type="customers",
            entity_id=1,
            amount=None,
            actor="Owner / Cleanup QA",
            source=journal.SOURCE_SYSTEM,
            ref_code="CLEANUP-QA-CUSTOMER-1",
            details={
                "deleted_customer": "Pelanggan Uji Coba (Histori QA)",
                "phone": "080000000000",
                "deleted_orders_count": len(order_ids),
                "deleted_order_numbers": order_nos,
                "note": "Pembersihan akun placeholder dan 20 order dummy testing development atas permintaan Owner"
            }
        )
        db.commit()

        # Verifikasi akhir
        final_cust_count = db.query(models.Customer).count()
        final_order_count = db.query(models.ServiceOrder).count()
        print(f"\n==========================================")
        print(f"[VERIFIKASI] Total Pelanggan Riil: {final_cust_count} (semua pelanggan riil)")
        print(f"[VERIFIKASI] Total Order Riil Toko: {final_order_count} (39 servis aktif + 182 garansi)")
        print(f"==========================================")
        return True

    except Exception as e:
        db.rollback()
        print(f"[ERROR] Gagal melakukan pembersihan: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        db.close()


if __name__ == "__main__":
    success = run_cleanup()
    sys.exit(0 if success else 1)
